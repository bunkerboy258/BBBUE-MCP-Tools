import hashlib
import json
import math
import uuid

import unreal

from BBBAssetWritePolicy import require_asset_write


def action_inputs(definition, sequence, action):
    """/** @param definition 武器配置 @param sequence 审核序列 @param action 动作名称 @return 正式蒙太奇 骨轨目标和角色网格 */"""
    from BBBControlRigAuthoringToolset import _weapon_review_bindings

    fields = {'equip': 'character_equip_montage', 'reload': 'character_reload_montage',
              'reload_start': 'character_reload_start_montage', 'reload_end': 'character_reload_end_montage'}
    if action not in fields:
        raise RuntimeError('审核入口仅接收有正式角色蒙太奇的明确动作')
    montage = definition.get_editor_property(fields[action])
    if not isinstance(montage, unreal.AnimMontage):
        raise RuntimeError('武器未配置这个角色动作 ' + action)
    tracks = [slot.get_editor_property('anim_track') for slot in montage.get_editor_property('slot_anim_tracks')
              if str(slot.get_editor_property('slot_name')) == 'UpperBody']
    segments = tracks[0].get_editor_property('anim_segments') if len(tracks) == 1 else []
    animation = segments[0].get_editor_property('anim_reference') if len(segments) == 1 else None
    root = definition.get_path_name().rsplit('/', 1)[0]
    if not isinstance(animation, unreal.AnimSequence) or not animation.get_path_name().startswith(root + '/Animation/'):
        raise RuntimeError('角色动作须有唯一且属于本型号的 UpperBody 骨轨目标')
    proxies, weapon = _weapon_review_bindings(sequence, definition.get_editor_property('equipment_mesh'))
    if len(proxies) != 1:
        raise RuntimeError('动作校正须有唯一的角色 Rig 轨道')
    mesh = proxies[0].proxy.get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset()
    return montage, animation, mesh, proxies[0], weapon


def _layers(rig_track):
    """/** @param rig_track 角色控制器轨道 @return 原始段与人工可编辑叠加段 */"""
    sections = [section for section in rig_track.get_sections() if section.is_active()]
    additive = [section for section in sections if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(sections) != 2 or len(additive) != 1:
        raise RuntimeError('校正需要一个原始段和一个可编辑叠加段')
    return next(section for section in sections if section != additive[0]), additive[0]


def _samples(section, names, rate, frames):
    """/** @param section 动画段 @param names 读取通道 @param rate 显示帧率 @param frames 显示帧 @return 连续逐帧通道值 */"""
    channels = {str(channel.channel_name): channel for channel in section.get_all_channels()}
    result = []
    for name in names:
        channel = channels[name]
        if not channel.get_keys() and channel.has_default():
            result.append([channel.get_default()] * len(frames))
            continue
        bounds = channel.compute_effective_range()
        bounds.set_start_seconds(frames[0] * rate.denominator / rate.numerator)
        bounds.set_end_seconds((frames[-1] + 1) * rate.denominator / rate.numerator)
        values = list(channel.evaluate_keys(bounds, rate))
        if len(values) < len(frames):
            raise RuntimeError('接触校正通道采样不足 ' + name)
        result.append(values[:len(frames)])
    return list(zip(*result))


def fit(definition, sequence, animation, mesh, rig_proxy, weapon, contacts, dry_run):
    """/** @param definition 武器配置 @param sequence 审核序列 @param animation 正式动画 @param mesh 角色网格 @param rig_proxy 角色控制器 @param weapon 预览枪 @param contacts 接触窗口 @param dry_run 只观察 @return 校正证据 */"""
    from BBBControlRigAuthoringToolset import _attachment_defaults, _key, _pose
    from BBBHandRetargetBatchToolset import _contact_ranges, _contact_weight, _validate_contact_reach
    from BBBManualActionNative import _channel_digest, _copy_sequence, _export

    editor = unreal.LevelSequenceEditorBlueprintLibrary
    if not dry_run and editor.get_current_level_sequence() != sequence:
        raise RuntimeError('先打开待校正的审核序列')
    grip = definition.get_editor_property('character_grip_pose')
    if not isinstance(grip, unreal.AnimSequence):
        raise RuntimeError('先应用目标武器的未开火握姿')
    _, defaults = _attachment_defaults(weapon, definition.get_editor_property('spawn_offset'))
    rate = sequence.get_display_rate()
    if sequence.get_playback_start() != 0:
        raise RuntimeError('审核动作必须从零帧开始')
    count = min(sequence.get_playback_end(), math.floor(animation.get_play_length() * rate.numerator / rate.denominator + 0.0001) + 1)
    if contacts:
        _contact_ranges({'contacts': contacts}, count)
    elif not dry_run:
        raise RuntimeError('须先明确枪体接触区间')
    names = ['hand_l_ik_ctrl.' + part + '.' + axis for part in ('Location', 'Rotation') for axis in 'XYZ']
    scope = unreal.new_object(unreal.LevelSequence, name='BBBActionReview_' + uuid.uuid4().hex)
    if not dry_run:
        editor.force_update()
    signature = _channel_digest(sequence, relative_paths=True) if not dry_run else None
    try:
        before = _export(sequence, animation, mesh, scope, 'Before', require_source_tracks=False)
        grip_pose = _pose(grip, mesh, 0.0)
        bone = lambda pose, name: unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)
        relative = bone(grip_pose, 'hand_l').make_relative(bone(grip_pose, 'hand_r'))
        frames = list(range(count))
        if not dry_run:
            base, edit = _layers(rig_proxy.track)
            offset = rig_proxy.control_rig.get_hierarchy().get_global_control_offset_transform(_key('hand_l_ik_ctrl', 'CONTROL'), True)
            base_samples = _samples(base, names, rate, frames)
            edits = _samples(edit, names, rate, frames)
        plan = {}
        errors = []
        for frame in frames:
            pose = _pose(before, mesh, min(before.get_play_length(), frame * rate.denominator / rate.numerator))
            left = bone(pose, 'hand_l')
            target = relative * bone(pose, 'hand_r')
            errors.append(round((left.translation - target.translation).length(), 3))
            if dry_run or not any(row['start_frame'] <= frame <= row['end_frame'] for row in contacts):
                continue
            weight = _contact_weight(frame, contacts, 1.0)
            if weight <= 0.00001:
                plan[frame] = (edits[frame], left)
                continue
            desired = left.lerp(target, weight)
            arm = {name: bone(pose, name) for name in ('upperarm_l', 'lowerarm_l', 'hand_l')}
            _validate_contact_reach(arm, desired)
            local = desired.make_relative(offset)
            angles = local.rotation.rotator()
            values = list(local.translation.to_tuple()) + [angles.roll, angles.pitch, angles.yaw]
            for index in range(3, 6):
                current = base_samples[frame][index] + edits[frame][index]
                values[index] += 360.0 * round((current - values[index]) / 360.0)
            plan[frame] = ([value - base_samples[frame][i] for i, value in enumerate(values)], desired)
        report = {'source_signature': signature, 'before_error_cm': errors, 'frames': count,
                  'contact_frames': list(plan), 'dry_run': dry_run}
        if dry_run:
            return report

        def write(target, edit_section, transform_defaults):
            target.modify()
            edit_section.modify()
            channels = {str(channel.channel_name): channel for channel in edit_section.get_all_channels()}
            for channel, value in transform_defaults:
                channel.set_default(value)
            for i, name in enumerate(names):
                for frame, (values, _) in plan.items():
                    channels[name].add_key(unreal.FrameNumber(value=frame), values[i], 0.0,
                                           unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)

        candidate = _copy_sequence(sequence, scope, 'Candidate')
        _export(candidate, animation, mesh, scope, 'Initialize', False, require_source_tracks=False)
        from BBBControlRigAuthoringToolset import _weapon_review_bindings
        tested_rig, tested_weapon = _weapon_review_bindings(candidate, definition.get_editor_property('equipment_mesh'))
        _, tested_edit = _layers(tested_rig[0].track)
        _, candidate_defaults = _attachment_defaults(tested_weapon, definition.get_editor_property('spawn_offset'))
        write(candidate, tested_edit, candidate_defaults)
        after = _export(candidate, animation, mesh, scope, 'After', require_source_tracks=False)
        maximum = 0.0
        max_rotation = 0.0
        for frame in frames:
            time = min(after.get_play_length(), frame * rate.denominator / rate.numerator)
            actual = bone(_pose(after, mesh, time), 'hand_l')
            expected = plan[frame][1] if frame in plan else bone(_pose(before, mesh, time), 'hand_l')
            maximum = max(maximum, (actual.translation - expected.translation).length())
            dot = abs(sum(x * y for x, y in zip(actual.rotation.to_tuple(), expected.rotation.to_tuple())))
            max_rotation = max(max_rotation, math.degrees(2 * math.acos(min(1.0, dot))))
        if maximum > 0.8 or max_rotation > 5.0:
            raise RuntimeError(f'校正候选未通过 姿势误差 {maximum:.3f} cm / {max_rotation:.2f} deg')
        require_asset_write([sequence])
        if _channel_digest(sequence, relative_paths=True) != signature:
            raise RuntimeError('审核序列在采样期间发生修改')
        with unreal.ScopedEditorTransaction('校正武器动作目标握点'):
            write(sequence, edit, defaults)
        editor.force_update()
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('校正序列保存失败')
        report.update({'saved': True, 'maximum_error_cm': maximum, 'maximum_rotation_error_deg': max_rotation})
        return report
    finally:
        unreal.purge_object_references(scope, True)


def apply(sequence, animation, mesh, next_sequence):
    """/** @param sequence 已审核序列 @param animation 正式动作 @param mesh 角色网格 @param next_sequence 已准备的下一份 @return 保存和交接结果 */"""
    from BBBControlRigAuthoringToolset import _bake_existing_animation
    from BBBManualActionAuthoring import _digest
    from BBBManualActionNative import _channel_digest

    library = unreal.EditorAssetLibrary
    editor = unreal.LevelSequenceEditorBlueprintLibrary
    editor.force_update()
    tag = 'BBBWeaponActionApplied'
    signature = _channel_digest(sequence, relative_paths=True)
    fingerprint = hashlib.sha256((signature + _digest(animation)).encode()).hexdigest()
    result = {'already_applied': library.get_metadata_tag(sequence, tag) == fingerprint}
    if not result['already_applied']:
        if editor.get_current_level_sequence() != sequence:
            raise RuntimeError('当前打开的序列与待应用序列不一致')
        require_asset_write([sequence, animation])
        result['bake'] = json.loads(_bake_existing_animation(sequence, animation, mesh))
        library.set_metadata_tag(sequence, tag, hashlib.sha256((signature + _digest(animation)).encode()).hexdigest())
        if not library.save_loaded_asset(sequence, False):
            raise RuntimeError('正式动画已保存 审核交接状态保存失败')
    if next_sequence:
        if not editor.open_level_sequence(next_sequence) or editor.get_current_level_sequence() != next_sequence:
            raise RuntimeError('正式动画已保存 下一份打开失败')
        editor.set_current_time(0)
        result['next'] = next_sequence.get_path_name()
    return result
