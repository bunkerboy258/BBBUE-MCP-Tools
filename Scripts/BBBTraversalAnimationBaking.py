import json
import math

import unreal
from BBBAssetWritePolicy import require_asset_write


def _slerp(left, right, alpha):
    """/** @param left 起始旋转 @param right 目标旋转 @param alpha 权重 @return 最短路径归一化旋转 */"""
    a, b = list(left.to_tuple()), list(right.to_tuple())
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b = [-value for value in b]
        dot = -dot
    wa, wb = 1 - alpha, alpha
    if dot < 0.9995:
        angle = math.acos(min(1.0, dot))
        wa = math.sin((1 - alpha) * angle) / math.sin(angle)
        wb = math.sin(alpha * angle) / math.sin(angle)
    values = [wa * x + wb * y for x, y in zip(a, b)]
    norm = math.sqrt(sum(v * v for v in values))
    return unreal.Quat(*[v / norm for v in values])


def _blend(a, b, alpha):
    """/** @param a 首姿态 @param b 末姿态 @param alpha 平滑权重 @return 保持骨长的局部变换 */"""
    value = unreal.Transform(location=a.translation * (1 - alpha) + b.translation * alpha,
                             scale=a.scale3d * (1 - alpha) + b.scale3d * alpha)
    value.rotation = _slerp(a.rotation, b.rotation, alpha)
    return value


def _contact_correction(sequence, source, evaluate, result, start_frame, end_frame, core_start, root_origin, contact_window):
    """/** @param sequence 目标动作 @param source 原片 @param evaluate 原始求值 @param result 烘焙轨道 @param start_frame 起点 @param end_frame 末点 @param core_start 主体起点 @param root_origin 原片原点 @return 不拉伸双臂的接触回读误差 */"""
    contact_begin, contact_end, full_begin, full_end = contact_window
    contacts = {}
    largest_body_offset = 0.0
    for source_frame in range(max(start_frame, contact_begin), min(end_frame, contact_end) + 1):
        weight = min((source_frame - contact_begin) / max(1, full_begin - contact_begin), (contact_end - source_frame) / max(1, contact_end - full_end), 1.0)
        weight = max(0.0, weight)
        weight = weight * weight * (3 - 2 * weight)
        if weight == 0:
            continue
        frame = core_start + source_frame - start_frame
        pose = sequence.get_anim_pose_at_frame(frame, evaluate)
        reference = source.get_anim_pose_at_frame(source_frame, evaluate)
        contacts[frame] = {}
        targets = {}
        body_delta = unreal.Vector(0, 0, 0)
        for side in ('l', 'r'):
            name = 'hand_' + side
            current = pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation
            target = reference.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation - root_origin
            targets[name] = current * (1 - weight) + target * weight
            body_delta += (targets[name] - current) * 0.5
        for attempt in range(8):
            for side in ('l', 'r'):
                upper, lower, hand = [pose.get_bone_pose(name + '_' + side, unreal.AnimPoseSpaces.WORLD)
                    for name in ('upperarm', 'lowerarm', 'hand')]
                reach = (lower.translation - upper.translation).length() + (hand.translation - lower.translation).length() - 0.2
                direction = targets['hand_' + side] - upper.translation - body_delta
                distance = direction.length()
                if distance > reach:
                    body_delta += direction * ((distance - reach) / distance)
        largest_body_offset = max(largest_body_offset, body_delta.length())
        if body_delta.length() > 35.0:
            raise RuntimeError('攀爬身体接触对齐偏移过大')
        root_rotation = pose.get_bone_pose('root', unreal.AnimPoseSpaces.WORLD).rotation
        result['pelvis'][frame].translation += root_rotation.inversed().rotate_vector(body_delta)
        for side in ('l', 'r'):
            upper_name, lower_name, hand_name = ['%s_%s' % (bone, side) for bone in ('upperarm', 'lowerarm', 'hand')]
            upper, lower, hand, clavicle = [pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD)
                for name in (upper_name, lower_name, hand_name, 'clavicle_' + side)]
            for value in (upper, lower, hand, clavicle):
                value.translation += body_delta
            desired = targets[hand_name]
            joint, end = unreal.AnimGraphLibrary.two_bone_ik(upper.translation, lower.translation, hand.translation,
                lower.translation, desired, False, 1.0, 1.0)
            if (end - desired).length() > 0.1:
                raise RuntimeError('原片接触点超出手臂可达范围 不允许拉伸 ' + str(source_frame) + side)
            upper_rotation = unreal.MathLibrary.quat_find_between_vectors(lower.translation - upper.translation, joint - upper.translation) * upper.rotation
            lower_rotation = unreal.MathLibrary.quat_find_between_vectors(hand.translation - lower.translation, end - joint) * lower.rotation
            result[upper_name][frame].rotation = (clavicle.rotation.inversed() * upper_rotation).normalized()
            result[lower_name][frame].rotation = (upper_rotation.inversed() * lower_rotation).normalized()
            result[hand_name][frame].rotation = (lower_rotation.inversed() * hand.rotation).normalized()
            contacts[frame][hand_name] = desired
    sequence.controller.open_bracket('按原片接触轨迹修正攀爬双臂', False)
    try:
        for name in ('pelvis', 'upperarm_l', 'lowerarm_l', 'hand_l', 'upperarm_r', 'lowerarm_r', 'hand_r'):
            values = result[name]
            if not sequence.controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                raise RuntimeError('双臂接触轨道写入失败')
    finally:
        sequence.controller.close_bracket(False)
    maximum = 0.0
    for frame, targets in contacts.items():
        pose = sequence.get_anim_pose_at_frame(frame, evaluate)
        for name, desired in targets.items():
            maximum = max(maximum, (pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation - desired).length())
    if maximum > 0.1:
        raise RuntimeError('双臂接触轨迹回读误差过大 ' + str(maximum))
    return {'frames': len(contacts), 'sourceWindow': [contact_begin, contact_end], 'fullWeightWindow': [full_begin, full_end],
            'maximumBodyOffsetCm': largest_body_offset, 'maximumErrorCm': maximum}


def bake(source_path, retargeter_path, idle_path, sequence_path, montage_path,
         start_frame, end_frame, enter_seconds, exit_seconds, contact_window=(40, 74, 48, 64)):
    """/** @param source_path 原片 @param retargeter_path 映射 @param idle_path 站姿 @param sequence_path 序列输出 @param montage_path 蒙太奇输出 @param start_frame 起帧 @param end_frame 末帧 @param enter_seconds 进入 @param exit_seconds 退出 @return 保存及轨迹证据 */"""
    assets = unreal.EditorAssetLibrary
    if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
        raise RuntimeError('攀爬制作需要停止 PIE')
    if len({source_path, idle_path, sequence_path, montage_path}) != 4 or any(not path.startswith('/Game/_Project/')
        or any(part in ('', '.', '..') for part in path.split('/')[2:]) for path in (sequence_path, montage_path)):
        raise RuntimeError('需要两个明确的自有资产路径')
    source, idle, retargeter = [unreal.load_asset(p) for p in (source_path, idle_path, retargeter_path)]
    if not isinstance(source, unreal.AnimSequence) or not isinstance(idle, unreal.AnimSequence) or not isinstance(retargeter, unreal.IKRetargeter):
        raise RuntimeError('动作 站姿或重定向器类型无效')
    count = source.data_model_interface.get_number_of_keys()
    if not 0 <= start_frame < end_frame < count or not all(math.isfinite(s) and 0.1 <= s <= 1.0 for s in (enter_seconds, exit_seconds)):
        raise RuntimeError('裁切范围或过渡时间无效')
    control = unreal.IKRetargeterController.get_controller(retargeter)
    src_mesh = control.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
    mesh = control.get_preview_mesh(unreal.RetargetSourceOrTarget.TARGET)
    if src_mesh.get_editor_property('skeleton') != source.get_skeleton() or mesh.get_editor_property('skeleton') != idle.get_skeleton():
        raise RuntimeError('重定向器两端骨架与动作不符')
    roots = [control.get_op_controller(i) for i in range(control.get_num_retarget_ops())
             if control.get_op_controller(i).get_class().get_name() == 'IKRetargetRootMotionController']
    if len(roots) != 1 or roots[0].get_settings().root_height_source != unreal.RootMotionHeightSource.COPY_HEIGHT_FROM_SOURCE:
        raise RuntimeError('攀爬根高度必须来自原片')
    existing = [unreal.load_asset(path) if assets.does_asset_exist(path) else None for path in (sequence_path, montage_path)]
    for item, kind in zip(existing, (unreal.AnimSequence, unreal.AnimMontage)):
        if item and (not isinstance(item, kind) or item.get_skeleton() != idle.get_skeleton()):
            raise RuntimeError('已有输出的类型或骨架不匹配')
        if item and item.get_outermost() in set(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()):
            raise RuntimeError('已有输出有未保存编辑')
    require_asset_write([item for item in existing if item], [path for path, item in zip((sequence_path, montage_path), existing) if not item])
    options = unreal.IKRetargetBatchOperationInputs()
    options.assets_to_retarget = [assets.find_asset_data(source_path)]
    options.source_mesh, options.target_mesh, options.ik_retarget_asset = src_mesh, mesh, retargeter
    options.target_path, options.replace = sequence_path.rsplit('/', 1)
    options.search = source_path.rsplit('/', 1)[-1]
    options.prefix, options.suffix = '', ''
    options.include_referenced_assets = False
    options.overwrite_existing_files = bool(existing[0])
    outputs = unreal.IKRetargetBatchOperation.run_batch_retarget(options)
    if len(outputs) != 1 or str(outputs[0].package_name) != sequence_path:
        raise RuntimeError('重定向输出与目标路径不符')
    sequence = unreal.load_asset(sequence_path)
    if sequence.get_skeleton() != idle.get_skeleton() or sequence.data_model_interface.get_number_of_keys() != count:
        raise RuntimeError('重定向骨架或采样数改变')
    rate = sequence.data_model_interface.get_frame_rate()
    fps = rate.numerator / rate.denominator
    enter, leave, hold = round(enter_seconds * fps), round(exit_seconds * fps), max(1, round(0.1 * fps))
    evaluate = unreal.AnimPoseEvaluationOptions()
    evaluate.evaluation_type = unreal.AnimDataEvalType.RAW
    evaluate.should_retarget = False
    idle_pose = idle.get_anim_pose_at_frame(0, evaluate)
    names = [str(n) for n in sequence.data_model_interface.get_bone_track_names()]
    reader = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms
    original = {name: list(reader(sequence, name)) for name in names}
    source_root = list(reader(source, 'root'))
    if len(source_root) != count:
        raise RuntimeError('原片根轨道采样不完整')
    original['root'] = source_root
    root_start = original['root'][start_frame]
    root_end = original['root'][end_frame]
    result = {}
    for name in names:
        frames = original[name]
        rest = idle_pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL)
        first, last = frames[start_frame], frames[end_frame]
        if name == 'root':
            rest = _blend(first, first, 0.0)
        keys = [_blend(rest, rest, 0.0) for _ in range(hold + 1)]
        for i in range(1, enter + 1):
            t = i / enter
            keys.append(_blend(rest, first, t * t * (3 - 2 * t)))
        keys.extend(_blend(value, value, 0.0) for value in frames[start_frame + 1:end_frame + 1])
        ending = rest
        if name == 'root':
            ending = last
        for i in range(1, leave + 1):
            t = i / leave
            keys.append(_blend(last, ending, t * t * (3 - 2 * t)))
        keys.extend(_blend(ending, ending, 0.0) for _ in range(hold))
        if name == 'root':
            for value in keys:
                value.translation -= root_start.translation
        result[name] = keys
    keys_count = len(result['root'])
    sequence.controller.open_bracket('烘焙攀爬主体与僵尸首尾站姿', False)
    try:
        sequence.controller.remove_all_curves_of_type(unreal.RawCurveTrackTypes.RCT_FLOAT, False)
        sequence.controller.remove_all_curves_of_type(unreal.RawCurveTrackTypes.RCT_TRANSFORM, False)
        sequence.controller.set_number_of_frames(unreal.FrameNumber(keys_count - 1), False)
        for name, keys in result.items():
            if not sequence.controller.set_bone_track_keys(name, [v.translation for v in keys], [v.rotation for v in keys], [v.scale3d for v in keys], False):
                raise RuntimeError('骨轨写入失败 ' + name)
    finally:
        sequence.controller.close_bracket(False)
    unreal.AnimationLibrary.remove_all_animation_notify_tracks(sequence)
    unreal.AnimationLibrary.remove_all_animation_sync_markers(sequence)
    sequence.set_editor_properties({'enable_root_motion': True, 'force_root_lock': True,
                                  'root_motion_root_lock': unreal.RootMotionRootLock.ZERO})
    sequence.set_preview_skeletal_mesh(mesh)
    evaluate.incorporate_root_motion_into_pose = True
    contact = _contact_correction(sequence, source, evaluate, result, start_frame, end_frame,
                                  hold + enter, root_start.translation, contact_window)
    maximum = 0.0
    for name, expected in result.items():
        actual = list(reader(sequence, name))
        if len(actual) != keys_count:
            raise RuntimeError('回读关键帧数量不符 ' + name)
        for a, b in zip(actual, expected):
            maximum = max(maximum, (a.translation - b.translation).length())
            if maximum > 0.001 or abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))) < 0.99999:
                raise RuntimeError('回读姿态不符 ' + name)
    require_asset_write([sequence])
    if not assets.save_loaded_asset(sequence, False):
        raise RuntimeError('攀爬序列保存失败')
    factory = unreal.AnimMontageFactory()
    factory.set_editor_property('source_animation', sequence)
    folder, name = montage_path.rsplit('/', 1)
    montage = existing[1] or unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimMontage, factory)
    if not montage:
        raise RuntimeError('攀爬蒙太奇创建失败')
    slot = list(montage.get_editor_property('slot_anim_tracks'))
    track = slot[0].get_editor_property('anim_track')
    segments = list(track.get_editor_property('anim_segments'))
    if len(segments) != 1:
        raise RuntimeError('攀爬蒙太奇需要唯一完整动作片段')
    segments[0].set_editor_properties({'anim_reference': sequence,
                                      'anim_start_time': 0.0, 'anim_end_time': sequence.get_play_length(),
                                      'anim_play_rate': 1.0})
    track.set_editor_property('anim_segments', segments)
    slot[0].set_editor_property('anim_track', track)
    slot[0].set_editor_property('slot_name', unreal.Name('DefaultSlot'))
    montage.set_editor_property('slot_anim_tracks', slot)
    montage.controller.set_frame_rate(rate)
    montage.controller.set_number_of_frames(unreal.FrameNumber(keys_count - 1))
    for field in ('blend_in', 'blend_out'):
        blend = montage.get_editor_property(field)
        blend.set_editor_property('blend_time', 0.12)
        montage.set_editor_property(field, blend)
    section_times = [0.0, (hold + enter) / fps, (hold + enter + end_frame - start_frame) / fps]
    sections = json.loads(unreal.BBBAssetRepairEditorLibrary.configure_montage_sections(montage, ['Enter', 'Climb', 'Exit'], section_times))
    if not sections.get('success'):
        raise RuntimeError('蒙太奇区段配置失败')
    if not unreal.BBBAssetRepairEditorLibrary.refresh_montage_links(montage) or not assets.save_loaded_asset(montage, False):
        raise RuntimeError('攀爬蒙太奇保存失败')
    montage.set_preview_skeletal_mesh(mesh)
    assets.save_loaded_asset(montage, False)
    evaluate.incorporate_root_motion_into_pose = True
    tracked = ('root', 'pelvis', 'head', 'hand_l', 'hand_r', 'foot_l', 'foot_r', 'ball_l', 'ball_r')
    trajectory = []
    endpoints = {'positionCm': 0.0, 'rotationDegrees': 0.0}
    for frame in range(keys_count):
        pose = sequence.get_anim_pose_at_frame(frame, evaluate)
        trajectory.append({'frame': frame, 'bones': {name: list(pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation.to_tuple()) for name in tracked}})
        if frame in (0, keys_count - 1):
            for name in names:
                if name == 'root':
                    continue
                a = pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL)
                b = idle_pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL)
                endpoints['positionCm'] = max(endpoints['positionCm'], (a.translation - b.translation).length())
                dot = min(1.0, abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))))
                endpoints['rotationDegrees'] = max(endpoints['rotationDegrees'], math.degrees(2 * math.acos(dot)))
    if endpoints['positionCm'] > 0.01 or endpoints['rotationDegrees'] > 0.05:
        raise RuntimeError('首尾站姿回读误差过大 ' + str(endpoints))
    return json.dumps({'source': source_path, 'sequence': sequence_path, 'montage': montage_path,
                       'sourceFrames': [start_frame, end_frame], 'fps': fps, 'keys': keys_count,
                       'length': sequence.get_play_length(), 'climbStart': section_times[1], 'climbEnd': section_times[2],
                       'rootDelta': list((root_end.translation - root_start.translation).to_tuple()),
                       'trackReadbackErrorCm': maximum, 'sections': sections['sections'],
                       'endpointError': endpoints, 'handContact': contact, 'trajectory': trajectory, 'saved': True}, ensure_ascii=False)
