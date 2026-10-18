"""离线手指接触拟合 使用实际线性蒙皮与明确的武器接触区域"""

import argparse
import json
from pathlib import Path

import numpy as np

from BBBGripSolidAudit import WeldedSolidSurface


def rotation_matrix(quaternion):
    """/** @param quaternion XYZW四元数 @return 列向量旋转矩阵 */"""
    quaternion = np.asarray(quaternion, dtype=float)
    if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)) or np.linalg.norm(quaternion) < 1e-12:
        raise ValueError('旋转需要四个有限数且长度非零')
    x, y, z, w = quaternion / np.linalg.norm(quaternion)
    return np.array([[1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
                     [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
                     [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)]])


def transform_matrix(values):
    """/** @param values 位置四元数缩放十项 @return 列向量仿射矩阵 */"""
    values = np.asarray(values, dtype=float)
    if values.shape != (10,) or not np.all(np.isfinite(values)) or np.any(np.abs(values[7:10]) < 1e-12):
        raise ValueError('变换需要十个有限数且缩放非零')
    matrix = np.eye(4)
    matrix[:3, :3] = rotation_matrix(values[3:7]) @ np.diag(values[7:10])
    matrix[:3, 3] = values[:3]
    return matrix


def quaternion_multiply(a, b):
    """/** @param a 左四元数 @param b 右四元数 @return 归一化乘积 */"""
    av, bv = np.asarray(a[:3]), np.asarray(b[:3])
    result = np.r_[a[3]*bv + b[3]*av + np.cross(av, bv), a[3]*b[3] - av@bv]
    return result / np.linalg.norm(result)


def _triangle_data(triangles):
    a = triangles[:, 0]
    ab = triangles[:, 1] - a
    ac = triangles[:, 2] - a
    normals = np.cross(ab, ac)
    norms = np.linalg.norm(normals, axis=1)
    valid = norms > 1e-9
    a, ab, ac, normals, norms = a[valid], ab[valid], ac[valid], normals[valid], norms[valid]
    if not len(a):
        raise ValueError('接触区域没有有效三角面')
    normals /= norms[:, None]
    d00, d01, d11 = np.sum(ab*ab, axis=1), np.sum(ab*ac, axis=1), np.sum(ac*ac, axis=1)
    return a, ab, ac, normals, d00, d01, d11


def _nearest_triangles_block(points, prepared):
    a, ab, ac, normals, d00, d01, d11 = prepared
    delta = points[:, None, :] - a
    distance = np.sum(delta*normals, axis=2)
    projected = points[:, None, :] - distance[:, :, None]*normals
    relative = projected - a
    d20, d21 = np.sum(relative*ab, axis=2), np.sum(relative*ac, axis=2)
    denominator = np.maximum(d00*d11 - d01*d01, 1e-20)
    v = (d11*d20 - d01*d21) / denominator
    w = (d00*d21 - d01*d20) / denominator
    inside = (v >= 0) & (w >= 0) & (v+w <= 1)
    best = projected.copy()
    best_squared = np.where(inside, distance*distance, np.inf)
    for start, edge in ((a, ab), (a, ac), (a+ab, ac-ab)):
        fraction = np.clip(np.sum((points[:, None, :]-start)*edge, axis=2) /
                           np.maximum(np.sum(edge*edge, axis=1), 1e-20), 0, 1)
        candidate = start + fraction[:, :, None]*edge
        squared = np.sum((points[:, None, :]-candidate)**2, axis=2)
        use = squared < best_squared
        best[use] = candidate[use]
        best_squared[use] = squared[use]
    chosen = np.argmin(best_squared, axis=1)
    rows = np.arange(len(points))
    closest = best[rows, chosen]
    return closest, np.sqrt(best_squared[rows, chosen]), np.sum((points-closest)*normals[chosen], axis=1)


def nearest_triangles(points, triangles):
    """/** @param points 同一空间有限点 @param triangles 实际面片区域 @return 分块精确最近点 距离和局部法向间隙 不判定实体穿透 */"""
    return TriangleQuery(triangles).nearest(points)


class TriangleQuery:
    """/** 缓存明确面片的边向量与单位法向 供同一组拟合重复查询 */"""

    def __init__(self, triangles):
        """/** @param triangles 有限实际面片区域 @return 可重复使用的固定区域查询 */"""
        triangles = np.asarray(triangles, dtype=float)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles) or not np.all(np.isfinite(triangles)):
            raise ValueError('接触区域必须为非空有限三角面数组')
        self.prepared = _triangle_data(triangles)

    def nearest(self, points):
        """/** @param points 同一空间有限点 @return 最近点 无符号距离和原始法向间隙 */"""
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
            raise ValueError('查询点必须为有限的三维点数组')
        if not len(points):
            return np.empty((0, 3)), np.empty(0), np.empty(0)
        blocks = [_nearest_triangles_block(points[start:start+64], self.prepared) for start in range(0, len(points), 64)]
        return tuple(np.concatenate([block[index] for block in blocks], axis=0) for index in range(3))


def contact_error(distances, normal_gaps, target_gap, surface_normal_sign):
    """/** @param distances 无符号三角面距离 @param normal_gaps 原始绕序法向间隙 @param target_gap 正外侧目标间隙 @param surface_normal_sign 明确外法向符号 @return 有向法向误差与切向残差之和 */"""
    if type(surface_normal_sign) not in (int, float) or surface_normal_sign not in (-1, 1):
        raise ValueError('接触面外法向符号必须明确为一或负一')
    tangential_squared = np.maximum(0, np.asarray(distances)**2-np.asarray(normal_gaps)**2)
    normal_error = surface_normal_sign*np.asarray(normal_gaps)-target_gap
    return normal_error**2+tangential_squared


class SurfacePose:
    """实际绑定顶点与明确局部姿势的离线蒙皮"""

    def __init__(self, data):
        self.data = data
        self.bones = data['bones']
        self.names = {bone['name'].lower(): i for i, bone in enumerate(self.bones)}
        if not self.bones or len(self.names) != len(self.bones):
            raise ValueError('骨架为空或含重复骨名')
        if any(not isinstance(bone['parent'], int) or bone['parent'] < -1 or bone['parent'] >= index for index, bone in enumerate(self.bones)):
            raise ValueError('骨架父子顺序无效')
        self.locals = np.array([transform_matrix(bone['local']) for bone in self.bones])
        self.ids = {vertex['id']: i for i, vertex in enumerate(data['vertices'])}
        if not self.ids or len(self.ids) != len(data['vertices']):
            raise ValueError('网格顶点为空或含重复编号')
        self.bind = np.array([vertex['bindPosition'] + [1] for vertex in data['vertices']])
        self.initial = np.array([vertex['position'] for vertex in data['vertices']])
        self.weights = []
        for vertex_index, vertex in enumerate(data['vertices']):
            for bone, weight in vertex['weights']:
                self.weights.append((vertex_index, bone, weight))
        self.weights = np.asarray(self.weights)
        if self.weights.ndim != 2 or self.weights.shape[1] != 3 or not np.all(np.isfinite(self.weights)):
            raise ValueError('网格缺少有限蒙皮权重')
        self.vertex_indices = self.weights[:, 0].astype(int)
        self.bone_indices = self.weights[:, 1].astype(int)
        self.influence_weights = self.weights[:, 2]
        if np.any(self.weights[:, 1] != self.bone_indices) or np.any(self.bone_indices < 0) or np.any(self.bone_indices >= len(self.bones)) or np.any(self.influence_weights <= 0):
            raise ValueError('蒙皮骨骼索引或权重无效')
        sums = np.bincount(self.vertex_indices, weights=self.influence_weights, minlength=len(self.ids))
        if np.any(np.abs(sums-1) > 3/65535):
            raise ValueError('顶点蒙皮权重未归一化')
        if not np.all(np.isfinite(self.bind)) or not np.all(np.isfinite(self.initial)):
            raise ValueError('网格坐标包含非有限数')
        reference = self.components(np.array([transform_matrix(bone['referenceLocal']) for bone in self.bones]))
        self.inverse_bind = np.linalg.inv(reference)
        for i, bone in enumerate(self.bones):
            if 'inverseBindMatrix' in bone:
                self.inverse_bind[i] = np.asarray(bone['inverseBindMatrix']).reshape(4, 4).T
        if not np.all(np.isfinite(self.inverse_bind)):
            raise ValueError('逆绑定矩阵包含非有限数')
        self.local_points = np.einsum('nij,nj->ni', self.inverse_bind[self.bone_indices],
                                      self.bind[self.vertex_indices])
        self.row_skin_cache = {}
        self.influence_starts = np.searchsorted(self.vertex_indices, np.arange(len(self.initial)), side='left')
        self.influence_ends = np.searchsorted(self.vertex_indices, np.arange(len(self.initial)), side='right')

    def components(self, local):
        """/** @param local 父空间矩阵 @return 组件空间矩阵 */"""
        result = local.copy()
        for i, bone in enumerate(self.bones):
            if bone['parent'] >= 0:
                result[i] = result[bone['parent']] @ local[i]
        return result

    def skin(self, rotations=None, rows=None):
        """/** @param rotations 明确局部四元数覆盖 @param rows 可选顶点行 @return 实际蒙皮顶点 */"""
        local = self.locals.copy()
        for name, quaternion in (rotations or {}).items():
            index = self.names[name.lower()]
            local[index, :3, :3] = rotation_matrix(quaternion) @ np.diag(self.bones[index]['local'][7:10])
        components = self.components(local)
        if rows is not None:
            key = tuple(int(index) for index in rows)
            if any(index < 0 or index >= len(self.initial) for index in key):
                raise ValueError('指定蒙皮顶点行越界')
            if key not in self.row_skin_cache:
                indices = []
                targets = []
                for target, row in enumerate(key):
                    influence = list(range(self.influence_starts[row], self.influence_ends[row]))
                    indices.extend(influence)
                    targets.extend([target]*len(influence))
                self.row_skin_cache[key] = np.asarray(indices, dtype=int), np.asarray(targets, dtype=int)
            indices, targets = self.row_skin_cache[key]
            influences = np.einsum('nij,nj->ni', components[self.bone_indices[indices]], self.local_points[indices])[:, :3]
            result = np.zeros((len(key), 3))
            np.add.at(result, targets, influences*self.influence_weights[indices, None])
            return result
        influences = np.einsum('nij,nj->ni', components[self.bone_indices], self.local_points)[:, :3]
        result = np.zeros_like(self.initial)
        np.add.at(result, self.vertex_indices, influences*self.influence_weights[:, None])
        return result


def region_triangles(surface, bounds, matrix, triangle_ids=None, exclude_triangle_ids=()):
    """/** @param surface 武器几何 @param bounds 可选明确组件空间盒 @param matrix 武器到角色矩阵 @param triangle_ids 明确接触面 @param exclude_triangle_ids 排除面 @return 角色空间实际接触面 */"""
    vertices = {v['id']: np.array(v['position']) for v in surface['vertices']}
    triangles = np.array([[vertices[i] for i in triangle['vertices']] for triangle in surface['triangles']])
    known = {triangle['id'] for triangle in surface['triangles']}
    allowed = known
    if triangle_ids is not None:
        if not set(triangle_ids) <= known:
            raise ValueError('武器接触区域包含不存在的面片编号')
        allowed = set(triangle_ids)
    if not set(exclude_triangle_ids) <= known:
        raise ValueError('武器排除区域包含不存在的面片编号')
    allowed -= set(exclude_triangle_ids)
    mask = np.array([triangle['id'] in allowed for triangle in surface['triangles']])
    centers = triangles.mean(axis=1)
    if bounds is not None:
        bounds = np.asarray(bounds, dtype=float)
        if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)) or np.any(bounds[0] > bounds[1]):
            raise ValueError('武器接触包围盒无效')
        mask &= np.all((centers >= bounds[0]) & (centers <= bounds[1]), axis=1)
    selected = triangles[mask]
    if len(selected) == 0:
        raise ValueError('指定武器区域没有三角面')
    return selected @ matrix[:3, :3].T + matrix[:3, 3]


def _contact_rows(surface, request, triangle_set):
    explicit = request.get('vertex_ids')
    excluded = set(request.get('exclude_vertex_ids', []))
    if not excluded <= surface.ids.keys():
        raise ValueError('排除区域包含不存在的手部顶点编号')
    if explicit is not None:
        if len(set(explicit)) != len(explicit) or not set(explicit) <= surface.ids.keys():
            raise ValueError('接触点包含重复或不存在的顶点编号')
        rows = [surface.ids[identifier] for identifier in explicit if identifier not in excluded]
        if not rows:
            raise ValueError('明确接触点被全部排除或为空')
        return np.asarray(rows), 'explicit_vertex_ids'
    if request.get('selection_mode') != 'radial_candidate':
        raise ValueError('正式接触拟合需要明确vertex_ids 自动候选必须显式selection_mode=radial_candidate')
    center = triangle_set.mean(axis=(0, 1))
    rows = []
    for name in request['bones']:
        bone = surface.names[name.lower()]
        candidates = [i for i, vertex in enumerate(surface.data['vertices'])
                      if vertex['id'] not in excluded and vertex.get('selected', True)
                      and any(b == bone and weight >= .35 for b, weight in vertex['weights'])]
        if not candidates:
            raise ValueError('手指骨骼缺少有效表面: '+name)
        points = surface.initial[candidates]
        origin = np.asarray(surface.bones[bone]['component'][:3])
        direction = center-origin
        direction /= max(np.linalg.norm(direction), 1e-10)
        scores = (points-origin) @ direction
        selected = np.argsort(scores)[-max(4, len(candidates)//5):]
        rows.extend(np.asarray(candidates)[selected][::max(1, len(selected)//5)][:6].tolist())
    return np.asarray(sorted(set(rows))), 'radial_candidate_requires_review'


def _full_surface_audit(points, vertex_ids, triangles, threshold):
    _, distances, gaps = nearest_triangles(points, triangles)
    near = distances <= threshold
    negative = near & (gaps < -1e-5)
    closest = np.argsort(distances)[:min(16, len(distances))]
    return {'sampleCount': len(points), 'nearSurfaceThresholdCm': float(threshold),
            'minimumDistanceCm': float(distances.min()), 'nearSurfacePointCount': int(near.sum()),
            'nearSurfaceNegativeLocalNormalCount': int(negative.sum()),
            'nearSurfaceMinimumLocalNormalGapCm': float(gaps[near].min()) if np.any(near) else None,
            'closestVertexIds': [int(vertex_ids[index]) for index in closest],
            'volumePenetrationEvaluated': False, 'normalSignIsVolumeClassification': False,
            'method': 'all_selected_vertices_to_all_weapon_triangles'}


def _clearance_audit(points, query, vertex_ids, normal_sign, clearance_cm):
    _, distances, gaps = query.nearest(points)
    oriented = gaps*normal_sign
    deficits = np.maximum(0, clearance_cm-oriented)
    worst = np.argsort(oriented)[:min(16, len(oriented))]
    return {'sampleCount': len(points), 'clearanceCm': float(clearance_cm),
            'minimumOutwardNormalGapCm': float(oriented.min()),
            'penetratingPointCount': int((oriented < -1e-5).sum()),
            'belowClearancePointCount': int((deficits > 1e-5).sum()),
            'maximumDeficitCm': float(deficits.max()),
            'worstVertexIds': [int(vertex_ids[index]) for index in worst],
            'localNormalAssumption': True}


def fit_pose(character, weapon, configuration):
    """/** @param character 角色采样 @param weapon 武器采样 @param configuration 明确接触区与边界 @return 有界拟合与独立几何回读数据 */"""
    surface = SurfacePose(character)
    baseline_error = float(np.max(np.linalg.norm(surface.skin()-surface.initial, axis=1)))
    if baseline_error > .002:
        raise ValueError('离线蒙皮与引擎回读不符: '+str(baseline_error))
    if not isinstance(configuration.get('contacts'), list) or not configuration['contacts']:
        raise ValueError('拟合需要至少一个明确接触组')
    regularization = configuration.get('regularization', .00008)
    if not np.isfinite(regularization) or regularization < 0:
        raise ValueError('姿势正则权重必须为非负有限数')
    attachment = transform_matrix(configuration['attachment'])
    hand_r = next(b for b in character['bones'] if b['name'].lower() == 'hand_r')
    weapon_matrix = transform_matrix(hand_r['component']) @ attachment
    rotations = {}
    results = []
    prepared = []
    used_bones = set()
    for request in configuration['contacts']:
        name = request['name']
        if request.get('weapon_bounds') is None and request.get('weapon_triangle_ids') is None:
            raise ValueError('拟合需要明确武器接触区域 不能默认吸附全部枪体')
        if not request['bones'] or any(value.lower() not in surface.names for value in request['bones']):
            raise ValueError('接触拟合需要明确有效骨骼')
        if len(set(value.lower() for value in request['bones'])) != len(request['bones']):
            raise ValueError('接触拟合拒绝重复骨骼')
        if used_bones & {value.lower() for value in request['bones']}:
            raise ValueError('不同接触组不能重复拟合同一骨骼 请合并接触点')
        used_bones.update(value.lower() for value in request['bones'])
        triangle_set = region_triangles(weapon, request.get('weapon_bounds'), weapon_matrix,
            request.get('weapon_triangle_ids'), request.get('exclude_weapon_triangle_ids', []))
        bones = [surface.names[value.lower()] for value in request['bones']]
        rows, selection_method = _contact_rows(surface, request, triangle_set)
        starting = {character['bones'][i]['name']: character['bones'][i]['local'][3:7] for i in bones}
        values = np.zeros((len(bones), 3))
        maximum = request.get('maximum_delta_degrees', configuration.get('maximum_delta_degrees', 25))
        if not np.isfinite(maximum) or maximum <= 0 or maximum > 180:
            raise ValueError('关节最大增量必须大于零且不超过一百八十度')
        limits = np.tile(np.asarray([-maximum, maximum], dtype=float), (len(bones), 3, 1))
        for bone_name, ranges in request.get('joint_limits_degrees', {}).items():
            if bone_name.lower() not in [value.lower() for value in request['bones']]:
                raise ValueError('关节约束引用了本组以外的骨骼')
            ranges = np.asarray(ranges, dtype=float)
            if ranges.shape != (3, 2) or not np.all(np.isfinite(ranges)) or np.any(ranges[:, 0] > 0) or np.any(ranges[:, 1] < 0) or np.any(ranges[:, 0] < -maximum) or np.any(ranges[:, 1] > maximum):
                raise ValueError('局部XYZ关节增量约束无效或未包含初始零值')
            limits[[value.lower() for value in request['bones']].index(bone_name.lower())] = ranges
        axes = request.get('axes', [0, 1, 2])
        if not axes or len(set(axes)) != len(axes) or any(type(axis) is not int or axis not in (0, 1, 2) for axis in axes):
            raise ValueError('拟合轴只能为非重复的局部XYZ索引')
        gap = request.get('target_gap_cm', .06)
        if not np.isfinite(gap) or gap < 0:
            raise ValueError('目标接触间隙必须为非负有限数')
        signed_target = request.get('signed_normal_target', True)
        if type(signed_target) is not bool:
            raise ValueError('signed_normal_target必须为布尔值')
        normal_sign = request.get('surface_normal_sign')
        if signed_target and (type(normal_sign) not in (int, float) or normal_sign not in (-1, 1)):
            raise ValueError('正式拟合需要明确surface_normal_sign为一或负一')
        contact_query = TriangleQuery(triangle_set)
        clearance = None
        clearance_ids = request.get('clearance_vertex_ids')
        clearance_triangles = request.get('clearance_weapon_triangle_ids')
        if clearance_ids is not None or clearance_triangles is not None:
            if not clearance_ids or not clearance_triangles or not signed_target:
                raise ValueError('清除约束需要明确顶点 面片和有向表面配置')
            if len(set(clearance_ids)) != len(clearance_ids) or not set(clearance_ids) <= surface.ids.keys():
                raise ValueError('清除点包含重复或不存在的顶点编号')
            clearance_rows = np.asarray([surface.ids[identifier] for identifier in clearance_ids])
            clearance_cm = request.get('clearance_cm', configuration.get('clearance_cm', .03))
            clearance_weight = request.get('clearance_weight', configuration.get('clearance_weight', 20))
            if not np.isfinite(clearance_cm) or clearance_cm < 0:
                raise ValueError('清除间隙必须为非负有限数')
            if not np.isfinite(clearance_weight) or clearance_weight < 10 or clearance_weight > 30:
                raise ValueError('清除惩罚权重必须为十至三十的有限数')
            clearance_mesh = region_triangles(weapon, None, weapon_matrix, clearance_triangles)
            clearance_topology = WeldedSolidSurface(clearance_mesh)
            if clearance_topology.degenerate_count or not clearance_topology.components or any(report['status'] != 'closed_2_manifold' or not report['orientationConsistent'] for report, mesh in clearance_topology.components):
                raise ValueError('清除区域必须包含完整闭合且绕序一致的组件')
            clearance_query = TriangleQuery(clearance_mesh)
            clearance = {'rows': clearance_rows, 'query': clearance_query, 'cm': clearance_cm,
                         'weight': clearance_weight, 'ids': clearance_ids, 'triangles': len(clearance_mesh),
                         'components': len(clearance_topology.components)}
        evaluation_rows = rows
        if clearance is not None:
            evaluation_rows = np.unique(np.r_[rows, clearance['rows']])
            clearance['slots'] = np.searchsorted(evaluation_rows, clearance['rows'])
        contact_slots = np.searchsorted(evaluation_rows, rows)
        if clearance is None:
            contact_slots = np.arange(len(rows))

        def overrides(parameters):
            output = dict(rotations)
            for i, bone in enumerate(bones):
                quaternion = np.array(starting[character['bones'][bone]['name']])
                for axis in range(3):
                    angle = np.deg2rad(parameters[i, axis]) / 2
                    delta = np.zeros(4)
                    delta[axis], delta[3] = np.sin(angle), np.cos(angle)
                    quaternion = quaternion_multiply(quaternion, delta)
                output[character['bones'][bone]['name']] = quaternion.tolist()
            return output

        def evaluate(parameters):
            points = surface.skin(overrides(parameters), evaluation_rows)
            _, distances, normal_gaps = contact_query.nearest(points[contact_slots])
            errors = (distances-gap)**2
            if signed_target:
                errors = contact_error(distances, normal_gaps, gap, normal_sign)
            regularizer = regularization*np.sum(parameters**2)
            clearance_cost = 0.0
            if clearance is not None:
                _, _, clearance_gaps = clearance['query'].nearest(points[clearance['slots']])
                deficits = np.maximum(0, clearance['cm']-normal_sign*clearance_gaps)
                clearance_cost = clearance['weight']*(np.mean(deficits**2)+np.max(deficits**2))
            return float(np.mean(errors)+regularizer+clearance_cost), distances, normal_gaps

        before = evaluate(values)
        before_clearance = None
        if clearance is not None:
            before_clearance = _clearance_audit(surface.skin(overrides(values), clearance['rows']), clearance['query'],
                clearance['ids'], normal_sign, clearance['cm'])
        score = before[0]
        steps = configuration.get('steps_degrees', [8, 3, 1])
        if not steps or any(not np.isfinite(step) or step <= 0 for step in steps):
            raise ValueError('拟合步长必须是正有限数')
        for step in steps:
            for iteration in range(3):
                changed = False
                for i in range(len(bones)):
                    for axis in axes:
                        best, best_values = score, values
                        for sign in (-1, 1):
                            candidate = values.copy()
                            candidate[i, axis] += sign*step
                            if candidate[i, axis] < limits[i, axis, 0] or candidate[i, axis] > limits[i, axis, 1]:
                                continue
                            cost = evaluate(candidate)[0]
                            if cost < best:
                                best, best_values = cost, candidate
                        if best < score:
                            values, score, changed = best_values, best, True
                if not changed:
                    break
        after = evaluate(values)
        rotations = overrides(values)
        results.append({'name': name, 'sampleCount': len(rows),
                        'beforeMeanGapCm': float(np.mean(before[1])), 'afterMeanGapCm': float(np.mean(after[1])),
                        'beforeMaxGapCm': float(max(before[1])), 'afterMaxGapCm': float(max(after[1])),
                        'meanNormalGapCm': float(np.mean(after[2])),
                        'signedNormalTarget': signed_target,
                        'surfaceNormalSign': normal_sign if signed_target else None,
                        'meanOutwardNormalGapCm': float(np.mean(after[2])*normal_sign) if signed_target else None,
                        'maximumDeltaDegrees': float(np.max(np.abs(values))),
                        'selectionMethod': selection_method,
                        'requiresContactSelectionReview': selection_method != 'explicit_vertex_ids' or request.get('selection_reviewed') is not True,
                        'selectionReviewed': selection_method == 'explicit_vertex_ids' and request.get('selection_reviewed') is True,
                        'jointDeltaDegrees': {character['bones'][bone]['name']: values[index].tolist() for index, bone in enumerate(bones)},
                        'normalGapIsNotSolidPenetrationProof': True,
                        'sampleVertexIds': [character['vertices'][i]['id'] for i in rows]})
        if clearance is not None:
            results[-1]['clearanceAudit'] = {'before': before_clearance, 'weight': clearance['weight'],
                'triangleCount': clearance['triangles'], 'closedComponentCount': clearance['components']}
        prepared.append((rows, contact_query, clearance))
    final_points = surface.skin(rotations)
    for result, (rows, contact_query, clearance) in zip(results, prepared):
        _, distances, gaps = contact_query.nearest(final_points[rows])
        result['afterMeanGapCm'] = float(distances.mean())
        result['afterMaxGapCm'] = float(distances.max())
        result['meanNormalGapCm'] = float(gaps.mean())
        result['meanOutwardNormalGapCm'] = float(gaps.mean()*result['surfaceNormalSign']) if result['signedNormalTarget'] else None
        result['minimumOutwardNormalGapCm'] = float((gaps*result['surfaceNormalSign']).min()) if result['signedNormalTarget'] else None
        result['wrongSideContactPointCount'] = int((gaps*result['surfaceNormalSign'] < -1e-5).sum()) if result['signedNormalTarget'] else None
        result['finalStateRecomputed'] = True
        if clearance is not None:
            result['clearanceAudit']['after'] = _clearance_audit(final_points[clearance['rows']], clearance['query'],
                clearance['ids'], result['surfaceNormalSign'], clearance['cm'])
            result['clearanceAudit']['finalStateRecomputed'] = True
        result['jointRotationDeltaDegrees'] = {}
        for name in result['jointDeltaDegrees']:
            original = np.asarray(surface.bones[surface.names[name.lower()]]['local'][3:7], dtype=float)
            original /= np.linalg.norm(original)
            dot = abs(float(original @ np.asarray(rotations[name])))
            result['jointRotationDeltaDegrees'][name] = float(np.degrees(2*np.arccos(np.clip(dot, 0, 1))))
    selected_rows = [index for index, vertex in enumerate(character['vertices']) if vertex.get('selected', True)]
    if not selected_rows:
        raise ValueError('独立全表面检查缺少明确选中顶点')
    all_triangles = region_triangles(weapon, None, weapon_matrix)
    threshold = configuration.get('near_surface_threshold_cm', .25)
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError('近表面审计阈值必须为正有限数')
    selected_ids = [character['vertices'][index]['id'] for index in selected_rows]
    audits = {'before': _full_surface_audit(surface.initial[selected_rows], selected_ids, all_triangles, threshold),
              'after': _full_surface_audit(final_points[selected_rows], selected_ids, all_triangles, threshold)}
    solid = WeldedSolidSurface(all_triangles)
    solid_audits = {'before': solid.audit(surface.initial[selected_rows], selected_ids),
                    'after': solid.audit(final_points[selected_rows], selected_ids)}
    return {'localRotations': rotations, 'contacts': results,
            'baselineSkinningErrorCm': baseline_error,
            'independentFullSurfaceAudit': audits,
            'independentClosedComponentAudit': solid_audits,
            'jointConstraintsAreAnatomicalProof': False,
            'method': 'bounded_offline_surface_contact_fit'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('character')
    parser.add_argument('weapon')
    parser.add_argument('configuration')
    parser.add_argument('output')
    arguments = parser.parse_args()
    output = Path(arguments.output)
    if output.exists():
        raise ValueError('拟合报告拒绝覆盖已有文件')
    result = fit_pose(*[json.loads(Path(path).read_text(encoding='utf-8'))
                        for path in (arguments.character, arguments.weapon, arguments.configuration)])
    output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'localRotations'}, ensure_ascii=False))
