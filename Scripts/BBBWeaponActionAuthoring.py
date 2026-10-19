import argparse
import json
from pathlib import Path

import numpy as np

from BBBGripAuthoring import arm_pose, matrix_quaternion, matrix_values, quaternion_angle_degrees, runtime_geometry, synchronize_hand_helpers
from BBBGripPoseFitting import SurfacePose, rotation_matrix, transform_matrix
from BBBWeaponActionPolicy import validate_action_phase_window, validate_finger_pose_windows


CHANGED_BONES = ('clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l', 'ik_hand_l', 'ik_hand_r', 'ik_hand_gun')


def smooth(value):
    """/** @param value 归一化阶段 @return 两端速度和加速度归零的权重 */"""
    value = np.clip(value, 0, 1)
    return value * value * value * (10 - 15 * value + 6 * value * value)


def blend_rotation(first, second, weight):
    """/** @param first 起始旋转 @param second 目标旋转 @param weight 阶段权重 @return 最短弧旋转 */"""
    first = np.asarray(matrix_quaternion(first))
    second = np.asarray(matrix_quaternion(second))
    dot = first @ second
    if dot < 0:
        second = -second
        dot = -dot
    if dot > .9995:
        quaternion = first * (1 - weight) + second * weight
        return rotation_matrix(quaternion / np.linalg.norm(quaternion))
    angle = np.arccos(np.clip(dot, -1, 1))
    quaternion = (np.sin((1 - weight) * angle) * first + np.sin(weight * angle) * second) / np.sin(angle)
    return rotation_matrix(quaternion)


def pose_matrix(value):
    """/** @param value 原生姿态报告中的组件变换 @return 仿射矩阵 */"""
    translation = [value['translation'][axis] for axis in ('x', 'y', 'z')]
    scale = [value['scale'][axis] for axis in ('x', 'y', 'z')]
    return transform_matrix(translation + value['quaternion'] + scale)


def record(matrix):
    """/** @param matrix 无剪切姿态 @return 原生写轨道所需显式变换 */"""
    values = matrix_values(matrix)
    return {'position': values[:3], 'rotation': values[3:7], 'scale': values[7:]}


def phase_weight(frame, phases):
    """/** @param frame 实际动作帧 @param phases 进入 满权 结束满权 退出帧 @return 显式阶段的平滑权重 */"""
    first, full, leave, end = phases
    if not first < full <= leave < end:
        raise ValueError('动作修正阶段必须按时间顺序明确')
    return float(smooth((frame - first) / (full - first)) * (1 - smooth((frame - leave) / (end - leave))))


def contact_translation_weight(frame, correction):
    """/** @param frame 实际动作帧 @param correction 单一平移及明确接触窗口 @return 接触窗口并集权重 取匣空程不累加位移 */"""
    if ('phase_frames' in correction) == ('phase_windows' in correction):
        raise ValueError('机构平移必须明确单窗口或多窗口之一')
    windows = correction.get('phase_windows')
    if 'phase_frames' in correction:
        windows = [correction['phase_frames']]
    if not isinstance(windows, list) or not windows:
        raise ValueError('机构接触窗口必须为非空数组')
    previous_end = -1
    weights = []
    for phases in windows:
        if not isinstance(phases, list) or len(phases) != 4 or any(type(value) not in (int, float) or not np.isfinite(value) or value < 0 for value in phases):
            raise ValueError('机构接触窗口必须为四个有限非负帧号')
        if phases[0] < previous_end:
            raise ValueError('机构接触窗口必须有序且不能重叠')
        weights.append(phase_weight(frame, phases))
        previous_end = phases[-1]
    return max(weights)


def rigid_attachment_matrix(values):
    """/** @param values 明确厘米位置 单位四元数及单位缩放 @return 经严格校验的刚体矩阵 */"""
    values = np.asarray(values, dtype=float)
    if values.shape != (10,) or not np.all(np.isfinite(values)) or not np.allclose(values[7:], 1, atol=1e-6, rtol=0) or abs(np.linalg.norm(values[3:7]) - 1) > .0001:
        raise ValueError('附件与机构变换必须为有限单位四元数和单位缩放刚体')
    return transform_matrix(values)


def explicit_rigid_contact(target, gun, frame, contacts):
    """/** @param target 原左腕目标 @param gun 本帧实际枪体 @param frame 实际帧 @param contacts 枪空间刚体接触修正及阶段 @return 保留空程的明确机构接触目标 */"""
    output = target.copy()
    if not isinstance(contacts, list):
        raise ValueError('机构刚体接触必须为显式数组')
    previous_end = -1
    for contact in contacts:
        if not isinstance(contact, dict):
            raise ValueError('机构刚体接触条目必须为对象')
        phases = contact.get('phase_frames')
        weight = contact_translation_weight(frame, {'phase_frames': phases})
        if phases[0] < previous_end:
            raise ValueError('机构刚体接触窗口必须有序且不重叠')
        previous_end = phases[-1]
        delta = rigid_attachment_matrix(contact.get('delta_weapon'))
        if weight == 0:
            continue
        desired = gun @ delta @ np.linalg.inv(gun) @ target
        output[:3, 3] = target[:3, 3] * (1 - weight) + desired[:3, 3] * weight
        output[:3, :3] = blend_rotation(target[:3, :3], desired[:3, :3], weight)
    return output


def bounded_action_phase_weight(frame, window, frame_count=None):
    """/** @param frame 实际帧 @param window 明确阶段及可选边界保持 @param frame_count 真实帧数 @return 严格范围内的五次平滑权重 仅显式允许前后各一帧 */"""
    phases = validate_action_phase_window(window, frame_count)
    return phase_weight(frame, phases)


def compensate_hand_attachment_grip(target, frame, changes, frame_count=None):
    """/** @param target 原左腕组件目标 @param frame 实际动作帧 @param changes 原附件局部变换与新握持及阶段 @return 保持附件世界轨迹的刚体腕反补偿 */"""
    output = target.copy()
    if not isinstance(changes, list):
        raise ValueError('独立附件握持反补偿必须为显式数组')
    previous_end = -1
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError('独立附件握持反补偿条目必须为对象')
        if change.get('bone') != 'hand_l':
            raise ValueError('当前附件握持反补偿只处理左手实际动作目标')
        original = rigid_attachment_matrix(change.get('reference_attachment_local'))
        current = rigid_attachment_matrix(change.get('attachment_local'))
        phases = change.get('phase_frames')
        weight = bounded_action_phase_weight(frame, change, frame_count)
        if phases[0] < previous_end:
            raise ValueError('独立附件握持反补偿窗口必须有序且不重叠')
        previous_end = phases[-1]
        if weight == 0:
            continue
        desired = target @ original @ np.linalg.inv(current)
        output[:3, 3] = target[:3, 3] * (1 - weight) + desired[:3, 3] * weight
        output[:3, :3] = blend_rotation(target[:3, :3], desired[:3, :3], weight)
    return output


def apply_finger_curls(surface, local, corrections, weight):
    """/** @param surface 实际骨架 @param local 当前局部姿态 @param corrections 明确掌空间弯曲平面和关节角 @param weight 阶段权重 @return 只追加指定关节卷曲 不搜索参数 */"""
    output = local.copy()
    if not np.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError('动作指骨阶段权重必须有限且位于零至一')
    for correction in corrections:
        hand = correction['hand']
        if hand not in ('hand_l', 'hand_r') or hand not in surface.names:
            raise ValueError('动作指骨必须指定实际左右手骨')
        axis = np.asarray(correction['axis_in_hand'], dtype=float)
        if axis.shape != (3,) or not np.all(np.isfinite(axis)) or np.linalg.norm(axis) < 1e-8:
            raise ValueError('必须明确实际手掌空间的连续卷曲平面')
        axis /= np.linalg.norm(axis)
        for name, degrees in correction['angles_degrees'].items():
            if name not in surface.names or not name.endswith(hand[-2:]) or not name.startswith(('thumb_', 'index_', 'middle_', 'ring_', 'pinky_')):
                raise ValueError('动作指骨修正范围无效: ' + name)
            if not np.isfinite(degrees) or abs(degrees) > 90:
                raise ValueError('动作指骨追加角必须有限且不超过九十度')
            if weight == 0:
                continue
            components = surface.components(output)
            world_axis = components[surface.names[hand], :3, :3] @ axis
            world_axis /= np.linalg.norm(world_axis)
            angle = np.deg2rad(degrees * weight)
            delta = rotation_matrix(np.r_[world_axis * np.sin(angle / 2), np.cos(angle / 2)])
            index = surface.names[name]
            parent = surface.bones[index]['parent']
            desired = delta @ components[index, :3, :3]
            output[index, :3, :3] = np.linalg.solve(components[parent, :3, :3], desired)
    return output


def apply_finger_pose_windows(surface, local, frame, windows):
    """/** @param surface 实际骨架 @param local 当前局部姿态 @param frame 源帧 @param windows 已校验完整指姿窗口 @return 仅混入明确指骨局部旋转 保留位置缩放和其它骨 */"""
    output = local.copy()
    for window in windows:
        weight = phase_weight(frame, window['phase_frames'])
        if weight == 0:
            continue
        for name, quaternion in window['local_rotations'].items():
            index = surface.names[name]
            scale = np.linalg.norm(output[index, :3, :3], axis=0)
            if np.any(scale < 1e-12):
                raise ValueError('固定手指姿态不能修改零缩放骨')
            original = output[index, :3, :3] / scale[None, :]
            output[index, :3, :3] = blend_rotation(original, rotation_matrix(quaternion), weight) @ np.diag(scale)
    return output


def contact_target(old_weapon, new_weapon, wrist):
    """/** @param old_weapon 原挂接组件变换 @param new_weapon 新挂接组件变换 @param wrist 原腕姿态 @return 保持武器局部接触的腕姿态 */"""
    return new_weapon @ np.linalg.inv(old_weapon) @ wrist


def runtime_right_hand(surface, components, local, quaternion):
    """/** @param surface 实际骨架 @param components 动作原生组件姿态 @param local 动作原生局部姿态 @param quaternion 正式父骨空间腕增量 @return 不改动作源的实际右腕组件姿态 */"""
    index = surface.names['hand_r']
    parent = surface.bones[index]['parent']
    wrist = local[index].copy()
    wrist[:3, :3] = rotation_matrix(quaternion) @ wrist[:3, :3]
    if parent < 0:
        return wrist
    return components[parent] @ wrist


def clavicle_adjustment(surface, local, target, minimum_angle=0):
    """/** @param surface 实际骨架 @param local 当前局部姿态 @param target 腕目标 @param minimum_angle 平滑包络下界 @return 不拉伸的锁骨修正姿态及角度 */"""
    components = surface.components(local)
    indices = [surface.names[name] for name in ('clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l')]
    clavicle, upper, lower, hand = indices
    origin = components[clavicle, :3, 3]
    shoulder = components[upper, :3, 3]
    reach = np.linalg.norm(components[lower, :3, 3] - shoulder)
    reach += np.linalg.norm(components[hand, :3, 3] - components[lower, :3, 3]) - .5
    if np.linalg.norm(target[:3, 3] - shoulder) <= reach and minimum_angle == 0:
        return local.copy(), 0.
    offset = shoulder - origin
    direction = target[:3, 3] - origin
    axis = np.cross(offset, direction)
    if np.linalg.norm(axis) < 1e-8:
        raise ValueError('锁骨修正方向退化')
    axis /= np.linalg.norm(axis)
    high = min(np.arccos(np.clip(offset @ direction / np.linalg.norm(offset) / np.linalg.norm(direction), -1, 1)), np.deg2rad(35))
    low = 0.
    for iteration in range(30):
        angle = (low + high) / 2
        rotation = rotation_matrix(np.r_[axis * np.sin(angle / 2), np.cos(angle / 2)])
        location = origin + rotation @ offset
        if np.linalg.norm(target[:3, 3] - location) > reach:
            low = angle
        if np.linalg.norm(target[:3, 3] - location) <= reach:
            high = angle
    angle = max(high, np.deg2rad(minimum_angle))
    rotation = rotation_matrix(np.r_[axis * np.sin(angle / 2), np.cos(angle / 2)])
    desired = components[clavicle].copy()
    desired[:3, :3] = rotation @ desired[:3, :3]
    result = local.copy()
    result[clavicle] = np.linalg.inv(components[surface.bones[clavicle]['parent']]) @ desired
    return result, float(np.rad2deg(angle))


def entry_hold_weight(action, frame):
    """/** @param action 实际分段动作与明确起始释放帧 @param frame 实际帧 @return 从已保存静态握持淡出的权重 */"""
    if 'entry_hold_release_frame' not in action and action['kind'] not in ('reload', 'melee'):
        return 0.
    release = action.get('entry_hold_release_frame', action.get('release_frame'))
    if type(release) not in (int, float) or not np.isfinite(release) or release <= 0:
        raise ValueError('动作起始握持释放帧必须为正有限数值')
    return float(1 - smooth(frame / release))


def explicit_forearm_roll(surface, local, frame, windows):
    """/** @param surface 实际左臂骨架 @param local 双骨求解后的局部姿态 @param frame 实际帧 @param windows 明确轴向角与阶段 @return 保持腕组件目标的前臂旋转与皮肤扭转分配 */"""
    if not isinstance(windows, list) or not windows:
        raise ValueError('前臂轴向旋转必须为非空显式窗口数组')
    lower = surface.names['lowerarm_l']
    hand = surface.names['hand_l']
    twist = surface.names['lowerarm_twist_01_l']
    if surface.bones[hand]['parent'] != lower or surface.bones[twist]['parent'] != lower:
        raise ValueError('前臂旋转需要腕与扭转骨直接从属于实际左前臂')
    previous_end = -1
    output = local.copy()
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError('前臂旋转窗口必须为对象')
        angle = window.get('angle_degrees')
        fraction = window.get('twist_fraction', .5)
        if type(angle) not in (int, float) or not np.isfinite(angle) or abs(angle) > 90:
            raise ValueError('前臂轴向旋转角必须有限且不超过九十度')
        if type(fraction) not in (int, float) or not np.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('前臂皮肤扭转比例必须有限且位于零至一')
        phases = window.get('phase_frames')
        weight = contact_translation_weight(frame, {'phase_frames': phases})
        if phases[0] < previous_end:
            raise ValueError('前臂旋转窗口必须有序且不重叠')
        previous_end = phases[-1]
        if weight == 0 or angle == 0:
            continue
        before = surface.components(output)
        axis = before[hand, :3, 3] - before[lower, :3, 3]
        length = np.linalg.norm(axis)
        if length < 1e-8:
            raise ValueError('实际前臂轴长度退化')
        axis /= length
        radians = np.radians(angle * weight)
        delta = rotation_matrix(np.r_[axis * np.sin(radians / 2), np.cos(radians / 2)])
        desired_lower = before[lower].copy()
        desired_lower[:3, :3] = delta @ desired_lower[:3, :3]
        parent = surface.bones[lower]['parent']
        output[lower] = np.linalg.inv(before[parent]) @ desired_lower
        after_lower = surface.components(output)
        output[hand] = np.linalg.inv(after_lower[lower]) @ before[hand]
        twist_radians = radians * fraction
        twist_delta = rotation_matrix(np.r_[axis * np.sin(twist_radians / 2), np.cos(twist_radians / 2)])
        desired_twist = before[twist].copy()
        desired_twist[:3, :3] = twist_delta @ desired_twist[:3, :3]
        output[twist, :3, :3] = np.linalg.solve(after_lower[lower, :3, :3], desired_twist[:3, :3])
    return output


def explicit_wrist_component_path(targets, keys):
    """/** @param targets 原始逐帧组件腕目标 @param keys 人工明确帧与刚体目标 @return 首尾连续的五次平滑短路径 不搜索接触或改变右臂 */"""
    if not isinstance(keys, list) or len(keys) < 2:
        raise ValueError('左腕短路径必须有至少两个明确关键帧')
    parsed = []
    previous = -1
    for key in keys:
        if not isinstance(key, dict) or type(key.get('frame')) != int or not previous < key['frame'] < len(targets):
            raise ValueError('左腕短路径关键帧必须为范围内严格递增整数')
        matrix = rigid_attachment_matrix(key.get('transform'))
        parsed.append((key['frame'], matrix))
        previous = key['frame']
    for frame, matrix in (parsed[0], parsed[-1]):
        if np.linalg.norm(matrix[:3, 3] - targets[frame][:3, 3]) > .001 or quaternion_angle_degrees(matrix_quaternion(matrix[:3, :3]), matrix_quaternion(targets[frame][:3, :3])) > .02:
            raise ValueError('左腕短路径首尾必须匹配原目标 避免切入或退出突变')
    output = [matrix.copy() for matrix in targets]
    for (first, a), (end, b) in zip(parsed, parsed[1:]):
        for frame in range(first, end + 1):
            weight = float(smooth((frame - first) / (end - first)))
            output[frame][:3, 3] = a[:3, 3] * (1 - weight) + b[:3, 3] * weight
            output[frame][:3, :3] = blend_rotation(a[:3, :3], b[:3, :3], weight)
    return output


def build(request):
    """/** @param request 实际逐帧采样和明确接触阶段 @return 非累积绝对轨道 制作控制器与诊断数据 */"""
    recipe = request['recipe']
    surface = SurfacePose(request['character'])
    context = recipe['solution']['inputs']['context']
    weapon = request['weapon']
    original_attachment = transform_matrix(request['original_calibration']['spawn_offset'])
    current_attachment = transform_matrix(recipe['calibration']['spawn_offset'])
    _, target = runtime_geometry(surface, weapon, context, recipe['calibration'])
    reference = surface.components(surface.locals)
    relative = np.linalg.inv(reference[surface.names['hand_r']]) @ target
    results = []
    sources = {asset['asset']: asset for asset in request['source_poses']['assets']}
    for action in request['actions']:
        source = sources[action['source']]
        frames = source['samples']
        if len(frames) != source['keys'] or [frame['frame'] for frame in frames] != list(range(source['keys'])):
            raise ValueError('必须输入完整逐帧原生采样')
        start, end = action['return_frames']
        if end < start or start < 0 or end >= len(frames):
            raise ValueError('回握阶段超出动作范围')
        poses = []
        for sample in frames:
            frame = sample['frame']
            bones = {name.casefold(): value for name, value in sample['bones'].items()}
            components = np.array([pose_matrix(bones[bone['name'].casefold()]) for bone in surface.bones])
            local = np.array([np.linalg.inv(components[bone['parent']]) @ components[index]
                              if bone['parent'] >= 0 else components[index]
                              for index, bone in enumerate(surface.bones)])
            source_right = components[surface.names['hand_r']]
            right = runtime_right_hand(surface, components, local, recipe['calibration'].get('right_wrist_delta', [0, 0, 0, 1]))
            wrist = components[surface.names['hand_l']].copy()
            old_weapon = source_right @ transform_matrix(context['attachment_socket']['local']) @ original_attachment
            new_weapon = right @ transform_matrix(context['attachment_socket']['local']) @ current_attachment
            transformed = contact_target(old_weapon, new_weapon, wrist)
            mount_weight = 1.
            if action['kind'] == 'equip':
                first, last = action['mount_frames']
                mount_weight = smooth((frame - first) / max(1, last - first))
            if action['kind'] == 'melee':
                mount_weight = 0.
            if action.get('free_hand_frames'):
                leave, free, approach, contact = action['free_hand_frames']
                mount_weight = max(1 - smooth((frame - leave) / max(1, free - leave)),
                                   smooth((frame - approach) / max(1, contact - approach)))
            moved = wrist.copy()
            moved[:3, 3] = wrist[:3, 3] * (1 - mount_weight) + transformed[:3, 3] * mount_weight
            moved[:3, :3] = blend_rotation(wrist[:3, :3], transformed[:3, :3], mount_weight)
            hold = right @ relative
            weight = smooth((frame - start) / max(1, end - start))
            weight = max(weight, entry_hold_weight(action, frame))
            if action['kind'] == 'return':
                weight = 1.
            target = moved.copy()
            target[:3, 3] = moved[:3, 3] * (1 - weight) + hold[:3, 3] * weight
            target[:3, :3] = blend_rotation(moved[:3, :3], hold[:3, :3], weight)
            if action.get('contact_translation'):
                correction = action['contact_translation']
                delta = np.asarray(correction['delta_weapon_cm'], dtype=float)
                if delta.shape != (3,) or not np.all(np.isfinite(delta)):
                    raise ValueError('机构接触平移必须为明确有限厘米三向量')
                target[:3, 3] += new_weapon[:3, :3] @ delta * contact_translation_weight(frame, correction)
            if action.get('contact_transforms'):
                if action.get('contact_translation'):
                    raise ValueError('同一动作必须明确平移接触或完整刚体接触之一')
                target = explicit_rigid_contact(target, new_weapon, frame, action['contact_transforms'])
            if action.get('hand_attachment_grip_changes'):
                target = compensate_hand_attachment_grip(target, frame, action['hand_attachment_grip_changes'], len(frames))
            adjusted, angle = clavicle_adjustment(surface, local, target)
            poses.append({'local': local, 'target': target, 'hold': hold, 'weight': float(weight), 'angle': angle})
        if 'left_wrist_component_keys' in action:
            targets = explicit_wrist_component_path([pose['target'] for pose in poses], action['left_wrist_component_keys'])
            for pose, target in zip(poses, targets):
                pose['target'] = target
                _, pose['angle'] = clavicle_adjustment(surface, pose['local'], target)
        tracks = {name: [] for name in CHANGED_BONES}
        if 'forearm_roll' in action:
            tracks['lowerarm_twist_01_l'] = []
        for correction in action.get('finger_curls', []):
            for name in correction['angles_degrees']:
                tracks[name] = []
        if 'finger_pose_windows' in action:
            for name in sorted(validate_finger_pose_windows(action['finger_pose_windows'], surface.names, len(poses))):
                tracks[name] = []
        finger_return_start = None
        if action.get('finger_return_frames'):
            contact, returned = action['finger_return_frames']
            if not 0 <= contact < returned < len(poses):
                raise ValueError('机构操作后的手指回握阶段无效')
            for name in recipe['solution']['finger_rotations']:
                if name.endswith('_l'):
                    tracks[name] = []
        keys = []
        metrics = []
        for frame, pose in enumerate(poses):
            envelope = max([other['angle'] * smooth((6 - abs(frame - index)) / 6)
                            for index, other in enumerate(poses) if abs(frame - index) <= 6] + [0])
            local, angle = clavicle_adjustment(surface, pose['local'], pose['target'], envelope)
            surface.locals = local
            try:
                output = arm_pose(surface, pose['target'], {})
            except ValueError as error:
                raise ValueError(action['kind'] + ' frame ' + str(frame) + ': ' + str(error)) from error
            if 'forearm_roll' in action:
                output = explicit_forearm_roll(surface, output, frame, action['forearm_roll'])
            if action.get('finger_curls'):
                output = apply_finger_curls(surface, output, action['finger_curls'], phase_weight(frame, action['finger_phase_frames']))
            if 'finger_pose_windows' in action:
                output = apply_finger_pose_windows(surface, output, frame, action['finger_pose_windows'])
            if action.get('finger_return_frames'):
                contact, returned = action['finger_return_frames']
                if frame == contact:
                    finger_return_start = output.copy()
                if frame > contact:
                    weight = float(smooth((frame - contact) / (returned - contact)))
                    for name, quaternion in recipe['solution']['finger_rotations'].items():
                        if name.endswith('_l'):
                            index = surface.names[name]
                            output[index, :3, :3] = blend_rotation(finger_return_start[index, :3, :3], rotation_matrix(quaternion), weight)
            output, components = synchronize_hand_helpers(surface, output)
            for name in tracks:
                tracks[name].append(record(output[surface.names[name]]))
            control_bones = list(surface.names)
            if not action.get('new_sequence', False):
                control_bones = [name for name in surface.names if name in CHANGED_BONES
                                 or name.endswith('_l') and any(name.startswith(prefix + '_')
                                                              for prefix in ('thumb', 'index', 'middle', 'ring', 'pinky', 'upperarm_twist', 'lowerarm_twist'))]
            for name in control_bones:
                keys.append({'frame': frame, 'control': 'source_' + surface.bones[surface.names[name]]['name'],
                             'value': record(components[surface.names[name]])})
            keys.append({'frame': frame, 'control': 'hand_l_ik_ctrl', 'value': record(components[surface.names['hand_l']])})
            keys.append({'frame': frame, 'control': 'elbow_l_pv_ctrl', 'value': record(components[surface.names['lowerarm_l']])})
            metrics.append({'frame': frame, 'holdWeight': pose['weight'], 'clavicleAngleDegrees': angle,
                            'wristTargetErrorCm': float(np.linalg.norm(components[surface.names['hand_l'], :3, 3] - pose['target'][:3, 3])),
                            'holdPositionErrorCm': float(np.linalg.norm(components[surface.names['hand_l'], :3, 3] - pose['hold'][:3, 3]))})
        results.append({**action, 'tracks': tracks, 'keys': keys, 'metrics': metrics})
    return {'schema': 1, 'weapon': recipe['weapon_root'], 'grip_fingerprint': recipe['validation']['fingerprint'],
            'method': 'explicit_absolute_tracks_from_native_source_with_rigid_weapon_contact_transform_and_quintic_returns',
            'original_calibration': request['original_calibration'], 'actions': results,
            'acceptance': {'data': 'pending_native_readback', 'visual': 'pending', 'human_final': 'pending'}}


def verify(request, result, saved):
    """/** @param request 原始逐帧输入 @param result 已写入的明确制作轨道 @param saved 正式动画独立原生采样 @return 允许差异 IK配对与回握目标的实际误差 */"""
    surface = SurfacePose(request['character'])
    source_assets = {asset['asset']: asset for asset in request['source_poses']['assets']}
    actual_assets = {asset['asset']: asset for asset in saved['assets']}
    recipe = request['recipe']
    reference = surface.components(surface.locals)
    _, target = runtime_geometry(surface, request['weapon'], recipe['solution']['inputs']['context'], recipe['calibration'])
    relative = np.linalg.inv(reference[surface.names['hand_r']]) @ target
    reports = []
    for action in result['actions']:
        source = source_assets[action['source']]
        actual = actual_assets[action['asset']]
        if actual['keys'] != len(actual['samples']) or actual['keys'] != source['keys']:
            raise ValueError('正式回读必须覆盖全部帧')
        report = {'asset': action['asset'], 'kind': action['kind'], 'frames': actual['keys'],
                  'fullhold_with_declared_contact_frames': [], 'fullhold_pure_static_frames': []}
        errors = {name: 0. for name in ('helper_position_cm', 'helper_rotation_degrees', 'other_local_position_cm',
                                      'other_local_rotation_degrees', 'track_position_cm', 'track_rotation_degrees',
                                      'hold_position_cm', 'hold_rotation_degrees')}
        for original_frame, actual_frame, metric in zip(source['samples'], actual['samples'], action['metrics']):
            if original_frame['frame'] != actual_frame['frame'] or original_frame['frame'] != metric['frame']:
                raise ValueError('正式回读帧顺序不一致')
            frame = original_frame['frame']
            before = {name.casefold(): pose_matrix(value) for name, value in original_frame['bones'].items()}
            after = {name.casefold(): pose_matrix(value) for name, value in actual_frame['bones'].items()}
            pairs = []
            for helper, hand in (('ik_hand_gun', 'hand_r'), ('ik_hand_r', 'hand_r'), ('ik_hand_l', 'hand_l')):
                pairs.append(('helper', after[helper], after[hand]))
            for index, bone in enumerate(surface.bones):
                name = bone['name'].casefold()
                parent = surface.bones[bone['parent']]['name'].casefold() if bone['parent'] >= 0 else None
                first = np.linalg.inv(before[parent]) @ before[name] if parent else before[name]
                second = np.linalg.inv(after[parent]) @ after[name] if parent else after[name]
                if name not in action['tracks']:
                    pairs.append(('other_local', first, second))
                if name in action['tracks']:
                    key = action['tracks'][name][frame]
                    expected = transform_matrix(key['position'] + key['rotation'] + key['scale'])
                    pairs.append(('track', expected, second))
            if metric['holdWeight'] >= .999999:
                components = np.array([after[bone['name'].casefold()] for bone in surface.bones])
                local = np.array([np.linalg.inv(components[bone['parent']]) @ components[index]
                                  if bone['parent'] >= 0 else components[index]
                                  for index, bone in enumerate(surface.bones)])
                right = runtime_right_hand(surface, components, local, recipe['calibration'].get('right_wrist_delta', [0, 0, 0, 1]))
                expected_hold = right @ relative
                context = recipe['solution']['inputs']['context']
                gun = right @ transform_matrix(context['attachment_socket']['local']) @ transform_matrix(recipe['calibration']['spawn_offset'])
                if action.get('contact_translation'):
                    correction = action['contact_translation']
                    expected_hold[:3, 3] += gun[:3, :3] @ np.asarray(correction['delta_weapon_cm'], dtype=float) * contact_translation_weight(frame, correction)
                if action.get('contact_transforms'):
                    expected_hold = explicit_rigid_contact(expected_hold, gun, frame, action['contact_transforms'])
                if action.get('hand_attachment_grip_changes'):
                    expected_hold = compensate_hand_attachment_grip(expected_hold, frame, action['hand_attachment_grip_changes'], actual['keys'])
                category = 'fullhold_pure_static_frames' if np.allclose(expected_hold, right @ relative, atol=1e-10, rtol=0) else 'fullhold_with_declared_contact_frames'
                report[category].append(frame)
                pairs.append(('hold', expected_hold, after['hand_l']))
            for prefix, first, second in pairs:
                position = float(np.linalg.norm(first[:3, 3] - second[:3, 3]))
                angle = quaternion_angle_degrees(matrix_quaternion(first[:3, :3]), matrix_quaternion(second[:3, :3]))
                errors[prefix + '_position_cm'] = max(errors[prefix + '_position_cm'], position)
                errors[prefix + '_rotation_degrees'] = max(errors[prefix + '_rotation_degrees'], angle)
        report['errors'] = errors
        report['passed'] = all(value < (.001 if name.endswith('_cm') else .02) for name, value in errors.items())
        reports.append(report)
    return {'passed': all(report['passed'] for report in reports), 'actions': reports}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('output')
    parser.add_argument('--verify')
    arguments = parser.parse_args()
    request = json.loads(Path(arguments.request).read_text(encoding='utf-8-sig'))
    if arguments.verify:
        result = json.loads(Path(arguments.output).read_text(encoding='utf-8-sig'))
        saved = json.loads(Path(arguments.verify).read_text(encoding='utf-8-sig'))
        if isinstance(saved, list):
            saved = saved[0]
        verification = verify(request, result, saved)
        result['verification'] = verification
        result['acceptance']['data'] = 'passed_native_readback' if verification['passed'] else 'failed_native_readback'
        Path(arguments.output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        print(json.dumps(verification))
        raise SystemExit(0 if verification['passed'] else 2)
    result = build(request)
    Path(arguments.output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(json.dumps([{'kind': action['kind'], 'frames': len(action['metrics']),
                       'maxWristErrorCm': max(metric['wristTargetErrorCm'] for metric in action['metrics']),
                       'maxClavicleDegrees': max(metric['clavicleAngleDegrees'] for metric in action['metrics'])}
                      for action in result['actions']]))
