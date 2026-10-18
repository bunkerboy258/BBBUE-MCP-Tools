import argparse
import json
from pathlib import Path

import numpy as np

from BBBGripAuthoring import arm_pose, matrix_quaternion, matrix_values, quaternion_angle_degrees, runtime_geometry, synchronize_hand_helpers
from BBBGripPoseFitting import SurfacePose, rotation_matrix, transform_matrix


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


def contact_target(old_weapon, new_weapon, wrist):
    """/** @param old_weapon 原挂接组件变换 @param new_weapon 新挂接组件变换 @param wrist 原腕姿态 @return 保持武器局部接触的腕姿态 */"""
    return new_weapon @ np.linalg.inv(old_weapon) @ wrist


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
            right = components[surface.names['hand_r']]
            wrist = components[surface.names['hand_l']].copy()
            old_weapon = right @ transform_matrix(context['attachment_socket']['local']) @ original_attachment
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
            if action['kind'] in ('reload', 'melee'):
                weight = max(weight, 1 - smooth(frame / max(1, action['release_frame'])))
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
                target[:3, 3] += new_weapon[:3, :3] @ delta * phase_weight(frame, correction['phase_frames'])
            adjusted, angle = clavicle_adjustment(surface, local, target)
            poses.append({'local': local, 'target': target, 'hold': hold, 'weight': float(weight), 'angle': angle})
        tracks = {name: [] for name in CHANGED_BONES}
        for correction in action.get('finger_curls', []):
            for name in correction['angles_degrees']:
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
            if action.get('finger_curls'):
                output = apply_finger_curls(surface, output, action['finger_curls'], phase_weight(frame, action['finger_phase_frames']))
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
        report = {'asset': action['asset'], 'kind': action['kind'], 'frames': actual['keys']}
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
                pairs.append(('hold', after['hand_r'] @ relative, after['hand_l']))
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
