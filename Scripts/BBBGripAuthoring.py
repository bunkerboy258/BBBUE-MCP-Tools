import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from BBBGripFingerConstraints import neighbor_audit
from BBBGripPoseFitting import SurfacePose, TriangleQuery, contact_error, fit_pose, quaternion_multiply, region_triangles, rotation_matrix, transform_matrix
from BBBGripSolidAudit import WeldedSolidSurface


def matrix_quaternion(matrix):
    """/** @param matrix 纯旋转矩阵 @return 最短符号归一化XYZW四元数 */"""
    m = np.asarray(matrix, dtype=float)
    eigen = np.array([[m[0, 0] - m[1, 1] - m[2, 2], m[0, 1] + m[1, 0], m[0, 2] + m[2, 0], m[2, 1] - m[1, 2]],
                      [m[0, 1] + m[1, 0], m[1, 1] - m[0, 0] - m[2, 2], m[1, 2] + m[2, 1], m[0, 2] - m[2, 0]],
                      [m[0, 2] + m[2, 0], m[1, 2] + m[2, 1], m[2, 2] - m[0, 0] - m[1, 1], m[1, 0] - m[0, 1]],
                      [m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1], m.trace()]]) / 3
    values, vectors = np.linalg.eigh(eigen)
    result = vectors[:, np.argmax(values)]
    if result[3] < 0:
        result = -result
    return result.tolist()


def matrix_values(matrix):
    """/** @param matrix 无剪切仿射矩阵 @return 平移四元数缩放十项 */"""
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    rotation = matrix[:3, :3] / scale
    if np.any(scale < 1e-10) or np.max(np.abs(rotation.T @ rotation - np.eye(3))) > 1e-5 or np.linalg.det(rotation) < 0:
        raise ValueError('握姿流程拒绝剪切或镜像骨骼变换')
    return matrix[:3, 3].tolist() + matrix_quaternion(rotation) + scale.tolist()


def canonical_digest(value):
    """/** @param value 明确制作数据 @return 不受字典顺序影响的内容摘要 */"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def quaternion_angle_degrees(first, second):
    """/** @param first 第一XYZW四元数 @param second 第二XYZW四元数 @return 忽略符号和浮点长度误差的最短角度差 */"""
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    for value in (first, second):
        if value.shape != (4,) or not np.all(np.isfinite(value)) or np.linalg.norm(value) < 1e-12:
            raise ValueError('旋转角度比较需要两个非零有限XYZW四元数')
    dot = abs(float(first @ second / (np.linalg.norm(first) * np.linalg.norm(second))))
    return float(np.degrees(2 * np.arccos(np.clip(dot, 0, 1))))


def bounded_search(initial, limits, steps, evaluate, maximum_passes=12):
    """/** @param initial 初始参数 @param limits 每轴明确范围 @param steps 搜索步长 @param evaluate 确定性代价函数 @param maximum_passes 每级最大轮数 @return 有界最优参数与代价 */"""
    values = np.asarray(initial, dtype=float)
    limits = np.asarray(limits, dtype=float)
    if limits.shape != values.shape + (2,) or not np.all(np.isfinite(limits)) or np.any(limits[..., 0] > values) or np.any(limits[..., 1] < values):
        raise ValueError('搜索范围必须包含初始参数')
    if not steps or any(not np.isfinite(step) or step <= 0 for step in steps):
        raise ValueError('搜索步长必须为正有限数')
    score = evaluate(values)
    for step in steps:
        for iteration in range(maximum_passes):
            changed = False
            for index in np.ndindex(values.shape):
                best = score
                selected = values
                for sign in (-1, 1):
                    candidate = values.copy()
                    candidate[index] += sign * step
                    if not limits[index + (0,)] <= candidate[index] <= limits[index + (1,)]:
                        continue
                    cost = evaluate(candidate)
                    if not np.isfinite(cost):
                        raise ValueError('拟合代价不是有限数')
                    if cost < best - 1e-14:
                        best = cost
                        selected = candidate
                if best < score - 1e-14:
                    values = selected
                    score = best
                    changed = True
            if not changed:
                break
    return values, float(score)


def _swing(first, second):
    """/** @param first 原向量 @param second 目标向量 @return 保持最短弧的旋转矩阵 */"""
    first = first / np.linalg.norm(first)
    second = second / np.linalg.norm(second)
    dot = np.clip(first @ second, -1, 1)
    if dot > 1 - 1e-12:
        return np.eye(3)
    axis = np.cross(first, second)
    if dot < -1 + 1e-10:
        seed = np.eye(3)[np.argmin(np.abs(first))]
        axis = np.cross(first, seed)
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    skew = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + skew + skew @ skew / (1 + dot)


def arm_pose(surface, target, seed_rotations, upper='upperarm_l', lower='lowerarm_l', hand='hand_l'):
    """/** @param surface 基准蒙皮 @param target 组件空间腕目标 @param seed_rotations 明确局部种子 @param upper 上臂骨 @param lower 前臂骨 @param hand 腕骨 @return 保留全部骨长和缩放的局部矩阵 */"""
    local = surface.locals.copy()
    for name, quaternion in seed_rotations.items():
        index = surface.names[name.lower()]
        local[index, :3, :3] = rotation_matrix(quaternion) @ np.diag(surface.bones[index]['local'][7:10])
    indices = [surface.names[name] for name in (upper, lower, hand)]
    if surface.bones[indices[1]]['parent'] != indices[0] or surface.bones[indices[2]]['parent'] != indices[1]:
        raise ValueError('握姿腕部求解要求直接相连的上臂前臂和腕骨')
    components = surface.components(local)
    shoulder, elbow, wrist = [components[index, :3, 3].copy() for index in indices]
    a = np.linalg.norm(elbow - shoulder)
    b = np.linalg.norm(wrist - elbow)
    direction = target[:3, 3] - shoulder
    distance = np.linalg.norm(direction)
    if distance < abs(a - b) + 1e-5 or distance > a + b - 1e-5:
        raise ValueError('左腕目标超出真实骨长可达范围 禁止拉伸或静默截断')
    direction /= distance
    reference_normal = np.cross(elbow - shoulder, wrist - elbow)
    bend = np.cross(direction, reference_normal)
    if np.linalg.norm(bend) < 1e-6:
        raise ValueError('左臂初始弯曲平面退化 需要明确参考姿势')
    bend /= np.linalg.norm(bend)
    cosine = np.clip((a * a + distance * distance - b * b) / (2 * a * distance), -1, 1)
    desired_elbow = shoulder + a * (cosine * direction + np.sqrt(max(0, 1 - cosine * cosine)) * bend)
    upper_index, lower_index, hand_index = indices
    desired = components[upper_index].copy()
    desired[:3, :3] = _swing(elbow - shoulder, desired_elbow - shoulder) @ desired[:3, :3]
    parent = surface.bones[upper_index]['parent']
    local[upper_index, :3, :3] = (np.linalg.inv(components[parent]) @ desired)[:3, :3]
    components = surface.components(local)
    desired = components[lower_index].copy()
    desired[:3, :3] = _swing(components[hand_index, :3, 3] - components[lower_index, :3, 3], target[:3, 3] - desired_elbow) @ desired[:3, :3]
    local[lower_index, :3, :3] = (np.linalg.inv(components[upper_index]) @ desired)[:3, :3]
    components = surface.components(local)
    local[hand_index, :3, :3] = (np.linalg.inv(components[lower_index]) @ target)[:3, :3]
    components = surface.components(local)
    if np.linalg.norm(components[hand_index, :3, 3] - target[:3, 3]) > .0001:
        raise ValueError('解析左臂求解回读没有到达目标')
    return local


def runtime_geometry(surface, weapon, context, calibration):
    """/** @param surface 角色姿势 @param weapon 武器参考采样 @param context 实际插槽父骨与局部变换 @param calibration 校准偏移 @return 武器矩阵及与运行时顺序一致的左腕目标 */"""
    components = surface.components(surface.locals)
    right = components[surface.names['hand_r']]
    attachment = context['attachment_socket']
    if attachment['parent'] != 'hand_r':
        raise ValueError('当前正式握姿流程要求挂接插槽父骨为hand_r')
    socket = transform_matrix(attachment['local'])
    weapon_matrix = right @ socket @ transform_matrix(calibration['spawn_offset'])
    left_socket = context['left_socket']
    weapon_bones = {bone['name']: transform_matrix(bone['component']) for bone in weapon['bones']}
    if left_socket['parent'] not in weapon_bones:
        raise ValueError('左手插槽父骨不在武器实际骨架中')
    socket_component = weapon_bones[left_socket['parent']] @ transform_matrix(left_socket['local'])
    socket_in_right = np.linalg.inv(right) @ weapon_matrix @ socket_component
    target = socket_in_right.copy()
    target[:3, 3] += np.asarray(calibration['left_ik_offset'])
    target[:3, :3] = target[:3, :3] @ rotation_matrix(calibration['left_ik_rotation'])
    return weapon_matrix, right @ target


def _repose(surface, local):
    """/** @param surface 原始蒙皮 @param local 完整新局部姿势 @return 保留实际逆绑定矩阵的新采样 */"""
    result = copy.deepcopy(surface.data)
    rotations = {bone['name']: matrix_values(local[index])[3:7] for index, bone in enumerate(surface.bones)}
    points = surface.skin(rotations)
    components = surface.components(local)
    for index, bone in enumerate(result['bones']):
        bone['local'] = matrix_values(local[index])
        bone['component'] = matrix_values(components[index])
    for index, vertex in enumerate(result['vertices']):
        vertex['position'] = points[index].tolist()
    return result


def calibrate(character, weapon, context, recipe):
    """/** @param character 角色基准 @param weapon 武器参考 @param context 运行时插槽关系 @param recipe 明确制作配置 @return 掌面校准结果和完整左臂姿势 */"""
    surface = SurfacePose(character)
    baseline_error = float(np.linalg.norm(surface.skin() - surface.initial, axis=1).max())
    if baseline_error > .002:
        raise ValueError('原生采样与离线蒙皮基线不一致')
    config = copy.deepcopy(recipe['calibration'])
    seed = recipe['pose']['local_rotations']
    transform_matrix(config['spawn_offset'])
    rotation_matrix(config['left_ik_rotation'])
    adjustments = {}
    if config['mode'] == 'fit':
        for side in ('right', 'left'):
            request = config[side + '_palm']
            ids = request['vertex_ids']
            if not ids or len(set(ids)) != len(ids) or not set(ids) <= surface.ids.keys() or request['surface_normal_sign'] not in (-1, 1):
                raise ValueError('掌面校准需要明确顶点和表面方向')
            rows = [surface.ids[identifier] for identifier in ids]
            original = copy.deepcopy(config)
            weapon_matrix, target = runtime_geometry(surface, weapon, context, original)
            translation_basis = transform_matrix(original['spawn_offset'])[:3, :3]
            right = surface.components(surface.locals)[surface.names['hand_r']]
            offset_basis = np.linalg.inv(right[:3, :3]) @ weapon_matrix[:3, :3]

            def moved(parameters):
                current = copy.deepcopy(original)
                if side == 'right':
                    current['spawn_offset'][:3] = (np.asarray(original['spawn_offset'][:3]) + translation_basis @ parameters).tolist()
                if side == 'left':
                    current['left_ik_offset'] = (np.asarray(original['left_ik_offset']) + offset_basis @ parameters).tolist()
                return current

            def evaluate(parameters):
                current = moved(parameters)
                matrix, wrist_target = runtime_geometry(surface, weapon, context, current)
                local = arm_pose(surface, wrist_target, seed)
                posed = SurfacePose(_repose(surface, local))
                triangles = region_triangles(weapon, request.get('weapon_bounds'), matrix, request.get('weapon_triangle_ids'))
                query = TriangleQuery(triangles)
                _, distances, gaps = query.nearest(posed.initial[rows])
                errors = contact_error(distances, gaps, request['target_gap_cm'], request['surface_normal_sign'])
                deficits = np.maximum(0, request.get('clearance_cm', .02) - request['surface_normal_sign'] * gaps)
                return float(errors.mean() + 20 * deficits.max() ** 2 + .001 * (parameters @ parameters))

            limits = request['translation_limits_weapon_cm']
            delta, score = bounded_search(np.zeros(3), limits, config['steps_cm'], evaluate)
            config = moved(delta)
            adjustments[side] = {'translationWeaponCm': delta.tolist(), 'cost': score}
    if config['mode'] not in ('fixed', 'fit'):
        raise ValueError('掌面校准模式必须为fixed或fit')
    matrix, target = runtime_geometry(surface, weapon, context, config)
    local = arm_pose(surface, target, seed)
    return {'spawn_offset': config['spawn_offset'], 'left_ik_offset': config['left_ik_offset'],
            'left_ik_rotation': config['left_ik_rotation'], 'adjustments': adjustments}, local, matrix, target, baseline_error


def _refine_neighbors(surface, weapon, matrix, rotations, recipe):
    """/** @param surface 已校准角色 @param weapon 武器采样 @param matrix 武器矩阵 @param rotations 当前姿势 @param recipe 制作约束 @return 保持接触与清除代价的有界指间距修正 */"""
    config = recipe.get('neighbor_refinement')
    if not config:
        return rotations
    names = config['bones']
    starting = {name: rotations.get(name, surface.bones[surface.names[name]]['local'][3:7]) for name in names}
    prepared = []
    for contact in recipe['fitting']['contacts']:
        rows = [surface.ids[identifier] for identifier in contact['vertex_ids']]
        triangles = region_triangles(weapon, contact.get('weapon_bounds'), matrix, contact.get('weapon_triangle_ids'))
        clearance = None
        if contact.get('clearance_vertex_ids'):
            clearance_mesh = region_triangles(weapon, None, matrix, contact['clearance_weapon_triangle_ids'])
            clearance = TriangleQuery(clearance_mesh)
        prepared.append((rows, TriangleQuery(triangles), contact, clearance))

    def overrides(parameters):
        result = dict(rotations)
        for index, name in enumerate(names):
            quaternion = starting[name]
            for axis in range(3):
                half = np.deg2rad(parameters[index, axis]) / 2
                delta = np.zeros(4)
                delta[axis] = np.sin(half)
                delta[3] = np.cos(half)
                quaternion = quaternion_multiply(quaternion, delta)
            result[name] = list(quaternion)
        return result

    def evaluate(parameters):
        current = overrides(parameters)
        points = surface.skin(current)
        cost = float(.00005 * np.sum(parameters ** 2))
        for rows, query, contact, clearance_query in prepared:
            _, distances, gaps = query.nearest(points[rows])
            cost += float(contact_error(distances, gaps, contact['target_gap_cm'], contact['surface_normal_sign']).mean())
            ids = contact.get('clearance_vertex_ids', [])
            if ids:
                _, _, all_gaps = clearance_query.nearest(points[[surface.ids[identifier] for identifier in ids]])
                deficits = np.maximum(0, contact.get('clearance_cm', .03) - contact['surface_normal_sign'] * all_gaps)
                cost += float(30 * (np.mean(deficits ** 2) + np.max(deficits ** 2)))
        local = surface.locals.copy()
        for name, quaternion in current.items():
            index = surface.names[name]
            local[index, :3, :3] = rotation_matrix(quaternion) @ np.diag(surface.bones[index]['local'][7:10])
        components = surface.components(local)
        for constraint in recipe['neighbors']:
            for pair in constraint['joint_pairs']:
                a = components[surface.names[pair['first']], :3, 3]
                b = components[surface.names[pair['second']], :3, 3]
                distance = np.linalg.norm(a - b)
                lower, upper = pair['distance_cm']
                cost += 40 * float(max(0, lower - distance, distance - upper) ** 2)
        return cost

    values, cost = bounded_search(np.zeros((len(names), 3)), config['limits_degrees'], config['steps_degrees'], evaluate)
    return overrides(values)


def geometry_audit(character, weapon, matrix, rotations, recipe):
    """/** @param character 校准后角色 @param weapon 武器采样 @param matrix 完整挂接矩阵 @param rotations 当前指骨覆盖 @param recipe 验收范围 @return 接触闭合组件和指间距的独立结果 */"""
    surface = SurfacePose(character)
    skinning_error = float(np.linalg.norm(surface.skin() - surface.initial, axis=1).max())
    if skinning_error > .002:
        raise ValueError('正式姿势的离线蒙皮与原生回读不一致')
    points = surface.skin(rotations)
    selected = [index for index, vertex in enumerate(character['vertices']) if vertex.get('selected', True)]
    triangles = region_triangles(weapon, None, matrix)
    solid = WeldedSolidSurface(triangles).audit(points[selected], [character['vertices'][index]['id'] for index in selected])
    contacts = []
    for request in recipe['fitting']['contacts']:
        target = region_triangles(weapon, request.get('weapon_bounds'), matrix, request.get('weapon_triangle_ids'))
        rows = [surface.ids[identifier] for identifier in request['vertex_ids']]
        _, distances, gaps = TriangleQuery(target).nearest(points[rows])
        bone_indices = {surface.names[name] for name in request['bones']}
        finger_rows = [index for index, vertex in enumerate(character['vertices'])
                       if sum(weight for bone, weight in vertex['weights'] if bone in bone_indices) >= .35]
        _, finger_distances, unused = TriangleQuery(target).nearest(points[finger_rows])
        contacts.append({'name': request['name'], 'meanDistanceCm': float(distances.mean()),
                         'minimumFingerDistanceCm': float(finger_distances.min()),
                         'nearContactVertexCount': int((finger_distances <= recipe['checks']['contact_patch_distance_cm']).sum()),
                         'minimumOutwardNormalGapCm': float((gaps * request['surface_normal_sign']).min()),
                         'selectionReviewed': request.get('selection_reviewed') is True})
    neighbors = neighbor_audit(surface, rotations, recipe['neighbors'])
    failures = []
    if solid['insideDepthMaximumCm'] > recipe['checks']['maximum_inside_depth_cm']:
        failures.append('weapon_internal_depth')
    for contact in contacts:
        request = next(item for item in recipe['fitting']['contacts'] if item['name'] == contact['name'])
        minimum = request.get('minimum_contact_patch_vertices', recipe['checks']['minimum_contact_patch_vertices'])
        if contact['nearContactVertexCount'] < minimum:
            failures.append('contact_patch:' + contact['name'])
    failures.extend('neighbor:' + item['name'] for item in neighbors if not item['passed'])
    return {'contacts': contacts, 'closedComponents': solid, 'neighbors': neighbors,
            'passed': not failures, 'failures': failures,
            'baselineSkinningErrorCm': skinning_error,
            'contactSelectionReviewRequired': any(not item['selectionReviewed'] for item in contacts),
            'wholeWeaponSolidPenetrationProven': False, 'jointConstraintsAreAnatomicalProof': False}


def solve(request):
    """/** @param request 明确采样上下文与制作配置 @return 完整静态姿势和独立验收结果 */"""
    recipe = request['recipe']
    character = request['character']
    weapon = request['weapon']
    calibration, local, matrix, target, baseline_error = calibrate(character, weapon, request['context'], recipe)
    posed = _repose(SurfacePose(character), local)
    surface = SurfacePose(posed)
    rotations = dict(recipe['pose']['local_rotations'])
    fitting = None
    if recipe['pose']['mode'] == 'fit':
        config = copy.deepcopy(recipe['fitting'])
        right = surface.components(surface.locals)[surface.names['hand_r']]
        config['attachment'] = matrix_values(np.linalg.inv(right) @ matrix)
        fitting = fit_pose(posed, weapon, config)
        rotations.update(fitting['localRotations'])
        rotations = _refine_neighbors(surface, weapon, matrix, rotations, recipe)
    if recipe['pose']['mode'] not in ('fixed', 'fit'):
        raise ValueError('手指制作模式必须为fixed或fit')
    for name, quaternion in rotations.items():
        index = surface.names[name]
        local[index, :3, :3] = rotation_matrix(quaternion) @ np.diag(surface.bones[index]['local'][7:10])
    components = surface.components(local)
    for helper, hand in (('ik_hand_l', 'hand_l'), ('ik_hand_r', 'hand_r'), ('ik_hand_gun', 'hand_r')):
        index = surface.names[helper]
        parent = surface.bones[index]['parent']
        desired = components[surface.names[hand]]
        local[index] = np.linalg.inv(components[parent]) @ desired
        components = surface.components(local)
    audit = geometry_audit(posed, weapon, matrix, rotations, recipe)
    locals_output = {bone['name']: matrix_values(local[index]) for index, bone in enumerate(surface.bones)}
    components_output = {bone['name']: matrix_values(components[index]) for index, bone in enumerate(surface.bones)}
    return {'calibration': calibration, 'local_pose': locals_output, 'component_pose': components_output,
            'finger_rotations': rotations, 'baselineSkinningErrorCm': baseline_error,
            'leftWristTargetErrorCm': float(np.linalg.norm(components[surface.names['hand_l'], :3, 3] - target[:3, 3])),
            'geometry': audit, 'passed': audit['passed'], 'runtimeAcceptance': 'pending'}


def audit(request):
    """/** @param request 当前正式动画的实际采样与配置 @return 不写资产的最终姿势数值验收 */"""
    recipe = request['recipe']
    character = request['character']
    surface = SurfacePose(character)
    calibration = recipe['solution']['calibration']
    matrix, target = runtime_geometry(surface, request['weapon'], request['context'], calibration)
    geometry = geometry_audit(character, request['weapon'], matrix, {}, recipe)
    expected = recipe['solution']['local_pose']
    maximum_position = 0.0
    maximum_rotation = 0.0
    maximum_scale = 0.0
    static_motion = 0.0
    control_position = 0.0
    control_rotation = 0.0
    for sample in request['samples']:
        posed = SurfacePose(sample)
        static_motion = max(static_motion, float(np.linalg.norm(posed.initial - surface.initial, axis=1).max()))
        for bone in posed.bones:
            actual = bone['local']
            desired = expected[bone['name']]
            maximum_position = max(maximum_position, float(np.linalg.norm(np.asarray(actual[:3]) - desired[:3])))
            maximum_rotation = max(maximum_rotation, quaternion_angle_degrees(actual[3:7], desired[3:7]))
            maximum_scale = max(maximum_scale, float(np.max(np.abs(np.asarray(actual[7:10]) - desired[7:10]))))
    wrist = transform_matrix(next(bone for bone in character['bones'] if bone['name'] == 'hand_l')['component'])
    wrist_error = float(np.linalg.norm(wrist[:3, 3] - target[:3, 3]))
    checks = recipe['checks']
    controls = request['control_keys']
    for key in controls:
        desired = recipe['solution']['component_pose'][key['control'].removeprefix('pose_')]
        actual = key['value']
        offset = request['control_offsets'][key['control']]
        offset_matrix = transform_matrix(offset['position'] + offset['rotation'] + offset['scale'])
        actual_matrix = transform_matrix(actual['position'] + actual['rotation'] + actual['scale'])
        actual = matrix_values(offset_matrix @ actual_matrix)
        control_position = max(control_position, float(np.linalg.norm(np.asarray(actual[:3]) - desired[:3])))
        control_rotation = max(control_rotation, quaternion_angle_degrees(actual[3:7], desired[3:7]))
    passed = geometry['passed'] and maximum_position <= checks['maximum_pose_position_error_cm']
    passed &= maximum_rotation <= checks['maximum_pose_rotation_error_degrees'] and maximum_scale <= .0001
    passed &= static_motion <= checks['maximum_static_motion_cm'] and wrist_error <= checks['maximum_wrist_error_cm']
    passed &= len(controls) == 2 * len(expected) and control_position <= checks['maximum_pose_position_error_cm'] and control_rotation <= checks['maximum_pose_rotation_error_degrees']
    actual_definition = request['definition_calibration']
    definition_errors = {}
    for field in ('spawn_offset', 'left_ik_offset'):
        definition_errors[field] = float(np.max(np.abs(np.asarray(actual_definition[field]) - calibration[field])))
    definition_errors['leftRotationDegrees'] = quaternion_angle_degrees(actual_definition['left_ik_rotation'], calibration['left_ik_rotation'])
    definition_matches = definition_errors['spawn_offset'] <= .0001 and definition_errors['left_ik_offset'] <= .0001 and definition_errors['leftRotationDegrees'] <= .02
    if request.get('require_definition_match', True):
        passed &= definition_matches
    return {'passed': bool(passed), 'geometry': geometry, 'maximumPosePositionErrorCm': maximum_position,
            'maximumPoseRotationErrorDegrees': maximum_rotation, 'maximumPoseScaleError': maximum_scale,
            'staticMaximumVertexMotionCm': static_motion, 'leftWristTargetErrorCm': wrist_error,
            'definitionMatchesSolution': bool(definition_matches), 'definitionErrors': definition_errors,
            'maximumControlPositionErrorCm': control_position, 'maximumControlRotationErrorDegrees': control_rotation,
            'runtimeAcceptance': 'pending'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('output')
    arguments = parser.parse_args()
    request = json.loads(Path(arguments.request).read_text(encoding='utf-8'))
    actions = {'solve': solve, 'audit': audit}
    result = actions[request['action']](request)
    destination = Path(arguments.output)
    with destination.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, allow_nan=False)
    print(json.dumps({'passed': result['passed']}, ensure_ascii=False))
