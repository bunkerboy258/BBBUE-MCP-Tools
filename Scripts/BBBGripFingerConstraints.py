import numpy as np

from BBBGripPoseFitting import nearest_triangles


def _segments(first_start, first_end, second_start, second_end):
    """/** @param first_start 第一线段起点 @param first_end 第一线段终点 @param second_start 第二线段起点数组 @param second_end 第二线段终点数组 @return 精确线段距离数组 */"""
    u = first_end - first_start
    v = second_end - second_start
    w = first_start - second_start
    a = float(u @ u)
    b = v @ u
    c = w @ u
    e = np.einsum('ij,ij->i', v, v)
    f = np.einsum('ij,ij->i', v, w)
    denominator = a * e - b * b
    s = np.zeros(len(v))
    valid = denominator > 1e-16
    s[valid] = np.clip((b[valid] * f[valid] - c[valid] * e[valid]) / denominator[valid], 0, 1)
    t = np.clip((b * s + f) / np.maximum(e, 1e-20), 0, 1)
    s = np.clip((b * t - c) / max(a, 1e-20), 0, 1)
    t = np.clip((b * s + f) / np.maximum(e, 1e-20), 0, 1)
    return np.linalg.norm(w + s[:, None] * u - t[:, None] * v, axis=1)


def triangle_pair_metrics(first, second, tolerance_cm=1e-7):
    """/** @param first 第一组非退化三角面 @param second 第二组非退化三角面 @param tolerance_cm 相交容差 @return 面片相交数及包含边边距离的最近间隙 */"""
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    for triangles in (first, second):
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles) or not np.all(np.isfinite(triangles)):
            raise ValueError('指面检查需要非空有限三角面')
        if np.any(np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1) < 1e-10):
            raise ValueError('指面检查拒绝退化三角面')
    if not np.isfinite(tolerance_cm) or tolerance_cm < 0:
        raise ValueError('指面相交容差无效')

    minimum = min(float(nearest_triangles(first.reshape(-1, 3), second)[1].min()),
                  float(nearest_triangles(second.reshape(-1, 3), first)[1].min()))
    second_edges = np.roll(second, -1, axis=1) - second
    second_normal = np.cross(second_edges[:, 0], second_edges[:, 1])
    count = 0
    pairs = []
    for first_index, triangle in enumerate(first):
        edges = np.roll(triangle, -1, axis=0) - triangle
        normal = np.cross(edges[0], edges[1])
        candidates = np.all(second.max(axis=1) >= triangle.min(axis=0) - tolerance_cm, axis=1)
        candidates &= np.all(second.min(axis=1) <= triangle.max(axis=0) + tolerance_cm, axis=1)
        indices = np.flatnonzero(candidates)
        if len(indices):
            other = second[indices]
            other_edges = second_edges[indices]
            normals = second_normal[indices]
            axes = [np.broadcast_to(normal, (len(indices), 3)), normals]
            for edge in edges:
                axes.append(np.broadcast_to(np.cross(normal, edge), (len(indices), 3)))
                axes.append(np.cross(normals, edge))
                for slot in range(3):
                    axes.append(np.cross(edge, other_edges[:, slot]))
            for slot in range(3):
                axes.append(np.cross(normals, other_edges[:, slot]))
            overlaps = np.ones(len(indices), dtype=bool)
            for axis in axes:
                lengths = np.linalg.norm(axis, axis=1)
                active = lengths > 1e-12
                unit = axis / np.maximum(lengths[:, None], 1e-20)
                one = np.einsum('vj,nj->nv', triangle, unit)
                two = np.einsum('nvj,nj->nv', other, unit)
                separated = (one.max(axis=1) < two.min(axis=1) - tolerance_cm) | (two.max(axis=1) < one.min(axis=1) - tolerance_cm)
                overlaps &= ~(active & separated)
            count += int(overlaps.sum())
            pairs.extend([[first_index, int(indices[index])] for index in np.flatnonzero(overlaps)[:max(0, 16 - len(pairs))]])
        for first_edge in range(3):
            for second_edge in range(3):
                distances = _segments(triangle[first_edge], triangle[(first_edge + 1) % 3],
                                      second[:, second_edge], second[:, (second_edge + 1) % 3])
                minimum = min(minimum, float(distances.min()))
    if count:
        minimum = 0.0
    return {'intersectionPairCount': count, 'minimumSurfaceGapCm': minimum,
            'intersectionPairs': pairs,
            'firstTriangleCount': len(first), 'secondTriangleCount': len(second),
            'method': 'triangle_sat_coplanar_axes_and_exact_segment_distance'}


def finger_triangles(surface, points, names, minimum_weight):
    """/** @param surface 明确蒙皮表面 @param points 当前完整顶点 @param names 指节骨骼 @param minimum_weight 指节合计权重 @return 全部顶点均属于指定指节区域的面片 */"""
    if not names or len(set(names)) != len(names) or any(name.lower() not in surface.names for name in names):
        raise ValueError('指面区域需要明确且唯一的骨骼')
    if not np.isfinite(minimum_weight) or not 0 < minimum_weight <= 1:
        raise ValueError('指面选取权重无效')
    selected = {surface.names[name.lower()] for name in names}
    rows = {index for index, vertex in enumerate(surface.data['vertices'])
            if sum(weight for bone, weight in vertex['weights'] if bone in selected) >= minimum_weight}
    triangles = []
    identifiers = []
    for triangle in surface.data['triangles']:
        indices = [surface.ids[identifier] for identifier in triangle['vertices']]
        if all(index in rows for index in indices):
            value = points[indices]
            if np.linalg.norm(np.cross(value[1] - value[0], value[2] - value[0])) > 1e-10:
                triangles.append(value)
                identifiers.append(triangle['id'])
    if not triangles:
        raise ValueError('指定指面区域没有完整非退化面片: ' + ','.join(names))
    return np.asarray(triangles), identifiers


def neighbor_audit(surface, rotations, constraints):
    """/** @param surface 明确蒙皮表面 @param rotations 局部四元数覆盖 @param constraints 明确相邻手指约束 @return 关节间距与实际指面相交验收 */"""
    from BBBGripPoseFitting import rotation_matrix

    points = surface.skin(rotations)
    local = surface.locals.copy()
    for name, quaternion in rotations.items():
        index = surface.names[name.lower()]
        local[index, :3, :3] = rotation_matrix(quaternion) @ np.diag(surface.bones[index]['local'][7:10])
    components = surface.components(local)
    reports = []
    used = set()
    for request in constraints:
        name = request['name']
        if not name or name in used:
            raise ValueError('相邻手指检查名称必须唯一')
        used.add(name)
        weight = request.get('minimum_weight', .35)
        first, first_ids = finger_triangles(surface, points, request['first_bones'], weight)
        second, second_ids = finger_triangles(surface, points, request['second_bones'], weight)
        if set(request['first_bones']) & set(request['second_bones']):
            raise ValueError('相邻指面不能包含同一骨骼')
        metrics = triangle_pair_metrics(first, second)
        gap_range = request['surface_gap_cm']
        if len(gap_range) != 2 or not all(np.isfinite(gap_range)) or not 0 <= gap_range[0] <= gap_range[1]:
            raise ValueError('指面间隙约束无效')
        passed = gap_range[0] <= metrics['minimumSurfaceGapCm'] <= gap_range[1] and metrics['intersectionPairCount'] == 0
        joints = []
        for pair in request['joint_pairs']:
            limits = pair['distance_cm']
            if len(limits) != 2 or not all(np.isfinite(limits)) or not 0 <= limits[0] <= limits[1]:
                raise ValueError('指节间距约束无效')
            a = surface.names[pair['first'].lower()]
            b = surface.names[pair['second'].lower()]
            distance = float(np.linalg.norm(components[a, :3, 3] - components[b, :3, 3]))
            valid = limits[0] <= distance <= limits[1]
            passed &= valid
            joints.append({'first': pair['first'], 'second': pair['second'], 'distanceCm': distance,
                           'allowedCm': limits, 'passed': bool(valid)})
        reports.append({'name': name, **metrics, 'jointPairs': joints, 'passed': bool(passed),
                        'intersectionTriangleIds': [[first_ids[a], second_ids[b]] for a, b in metrics['intersectionPairs']],
                        'firstTriangleIds': first_ids, 'secondTriangleIds': second_ids})
    return reports
