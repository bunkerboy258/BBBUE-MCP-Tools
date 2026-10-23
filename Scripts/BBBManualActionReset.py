import math
import hashlib
import json
import uuid

import unreal

from BBBAssetWritePolicy import require_asset_write


def neutral_value(name, absolute):
    """/** @param name\t通道名 @param absolute\t是否绝对层 @return\t绝对缩放一及原生叠加零增量 */"""
    return 1.0 if absolute and '.Scale.' in name else 0.0


def nonfinger_digest(sequence):
    """/** @param sequence\t制作序列 @return\t手指之外的全部通道摘要 */"""
    rows = []
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                for channel in section.get_all_channels():
                    name = str(channel.channel_name)
                    if name.startswith('fk_'):
                        continue
                    keys = [(key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).frame_number.value,
                             key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).sub_frame, str(key.get_value()))
                            for key in channel.get_keys()]
                    default = str(channel.get_default()) if hasattr(channel, 'has_default') and channel.has_default() else None
                    rows.append([binding.get_id().export_text(), str(track.get_class().get_name()), name, default, keys])
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def restore_entire_fingers(path, data, write_paths):
    """/** @param path\t制作源 @param data\t原指骨动画输入 @param write_paths\t唯一序列 @return\t整段原指骨恢复及非指骨保持证明 */"""
    import BBBManualActionNative as native
    from BBBControlRigAuthoringToolset import _asset, _pose
    from BBBManualActionAuthoring import _save

    if set(write_paths) != {data['sequence']} or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('RESTORE_ENTIRE_FINGERS_SCOPE')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    reference = _asset(data['restore_action_fingers_request'].get('animation', data['finger_animation']), unreal.AnimSequence)
    rate = sequence.get_display_rate()
    fps = 120.0
    count = round(reference.get_play_length() * fps) + 1
    fingers = [f'{finger}_{joint:02}_{side}' for side in ('l', 'r')
               for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)]
    rows = {bone: [] for bone in fingers}
    for frame in range(count):
        pose = _pose(reference, mesh, frame / fps)
        for bone in fingers:
            transform = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
            rotation = transform.rotation.rotator()
            values = list(transform.translation.to_tuple()) + [rotation.roll, rotation.pitch, rotation.yaw] + list(transform.scale3d.to_tuple())
            if rows[bone]:
                for axis in range(3, 6):
                    values[axis] += 360 * round((rows[bone][-1][axis] - values[axis]) / 360)
            rows[bone].append(values)
    suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
    def write(target):
        binding = native._mesh_binding(target, mesh)
        sections = [section for track in binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack) for section in track.get_sections()]
        if len(sections) != 2:
            raise RuntimeError('RESTORE_ENTIRE_FINGERS_TWO_SECTIONS')
        for section in sections:
            absolute = section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE
            for channel in section.get_all_channels():
                name = str(channel.channel_name)
                if not name.startswith('fk_'):
                    continue
                control, suffix = name.split('.', 1)
                bone = control.removeprefix('fk_')
                if bone not in rows or suffix not in suffixes:
                    raise RuntimeError('RESTORE_ENTIRE_FINGERS_CONTROL: ' + name)
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
                channel.set_default(neutral_value(name, absolute))
                if not absolute:
                    continue
                for frame, values in enumerate(rows[bone]):
                    display_frame = frame / fps * rate.numerator / rate.denominator
                    channel.add_key(unreal.FrameNumber(value=math.floor(display_frame)), values[suffixes.index(suffix)],
                                    display_frame-math.floor(display_frame), unreal.MovieSceneTimeUnit.DISPLAY_RATE,
                                    unreal.MovieSceneKeyInterpolation.LINEAR)
    protected = nonfinger_digest(sequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBRestoreEntireFingers_' + uuid.uuid4().hex)
    try:
        copied = native._copy_sequence(sequence, scope, 'Candidate')
        native._export(copied, reference, mesh, scope, 'Initialize', False)
        write(copied)
        if nonfinger_digest(copied) != protected:
            raise RuntimeError('RESTORE_ENTIRE_FINGERS_NONFINGER_CHANGED')
        baked = native._export(copied, reference, mesh, scope, 'Restored')
        sample_rate = baked.data_model_interface.get_frame_rate()
        sample_fps = sample_rate.numerator / sample_rate.denominator
        maximum_position = 0.0
        maximum_rotation = 0.0
        for sample in range(baked.data_model_interface.get_number_of_keys()):
            time = sample / sample_fps
            expected = _pose(reference, mesh, time)
            actual = _pose(baked, mesh, time)
            for bone in fingers:
                a = unreal.AnimPoseExtensions.get_bone_pose(expected, bone, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(actual, bone, unreal.AnimPoseSpaces.LOCAL)
                maximum_position = max(maximum_position, (a.translation-b.translation).length())
                dot = abs(sum(x*y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple())))
                maximum_rotation = max(maximum_rotation, math.degrees(2 * math.acos(min(1.0, dot))))
        if maximum_position > 0.01 or maximum_rotation > 0.1:
            raise RuntimeError('RESTORE_ENTIRE_FINGERS_OUTPUT: ' + str((maximum_position, maximum_rotation)))
        require_asset_write([sequence])
        write(sequence)
        if nonfinger_digest(sequence) != protected:
            raise RuntimeError('RESTORE_ENTIRE_FINGERS_NONFINGER_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('RESTORE_ENTIRE_FINGERS_SAVE')
        result = {'sequence': data['sequence'], 'reference': reference.get_path_name(), 'finger_bones': len(fingers),
                  'checked_samples': baked.data_model_interface.get_number_of_keys(), 'position_error_cm': maximum_position,
                  'rotation_error_degrees': maximum_rotation, 'nonfinger_channels_preserved': True, 'additive_finger_keys': 0}
        data.pop('restore_action_fingers_request')
        data['finger_restore'] = result
        data['runtime_applied'] = False
        _save(path, data)
        editors = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
        editors.close_all_editors_for_asset(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        native.repair_timeline_range(sequence)
        return result
    finally:
        unreal.purge_object_references(scope, True)


def restore_fingers(path, data, write_paths):
    """/** @param path\t制作源 @param data\t明确撤销的手指修正帧 @param write_paths\t唯一序列 @return\t原基础手指恢复及手部IK保持证明 */"""
    import BBBManualActionNative as native
    from BBBControlRigAuthoringToolset import _asset, _pose
    from BBBManualActionAuthoring import _save

    if data['restore_action_fingers_request'].get('entire_clip'):
        return restore_entire_fingers(path, data, write_paths)
    if set(write_paths) != {data['sequence']} or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('RESTORE_ACTION_FINGERS_SCOPE')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    request = data['restore_action_fingers_request']
    reference = _asset(request.get('animation', data['finger_animation']), unreal.AnimSequence)
    frames = request['frames']
    rate = sequence.get_display_rate()
    def layer(target):
        sections = [section for track in native._mesh_binding(target, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
                    for section in track.get_sections() if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(sections) != 1:
            raise RuntimeError('RESTORE_ACTION_FINGERS_SINGLE_OFFSET')
        return sections[0]
    from BBBControlRigAuthoringToolset import _key
    hierarchy = _asset(data['rig'], unreal.ControlRigBlueprint).hierarchy
    absolute = [section for track in native._mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
                for section in track.get_sections() if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE][0]
    bases = {str(channel.channel_name): channel for channel in absolute.get_all_channels()}
    plans = {}
    for frame in frames:
        pose = _pose(reference, mesh, frame * rate.denominator / rate.numerator)
        for side in ('l', 'r'):
            for finger in ('thumb', 'index', 'middle', 'ring', 'pinky'):
                for joint in (1, 2, 3):
                    bone = f'{finger}_{joint:02}_{side}'
                    key = _key('fk_' + bone, 'CONTROL')
                    parent = hierarchy.get_parents(key)[0]
                    offset = hierarchy.get_global_control_offset_transform(key, True).make_relative(hierarchy.get_global_transform(parent, True))
                    local = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
                    angles = (offset.rotation.inversed() * local.rotation).normalized().rotator()
                    for axis, desired in zip(('X', 'Y', 'Z'), (angles.roll, angles.pitch, angles.yaw)):
                        name = 'fk_' + bone + '.Rotation.' + axis
                        channel = bases[name]
                        exact = [k for k in channel.get_keys() if abs(k.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).frame_number.value + k.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).sub_frame - frame) < 0.000001]
                        base_value = float(channel.get_default()) if not channel.get_keys() else None
                        if exact:
                            base_value = float(exact[0].get_value())
                        if base_value is None:
                            bounds = channel.compute_effective_range()
                            bounds.set_start_seconds(frame * rate.denominator / rate.numerator)
                            bounds.set_end_seconds((frame + 1) * rate.denominator / rate.numerator)
                            base_value = float(channel.evaluate_keys(bounds, rate)[0])
                        plans[(name, frame)] = desired - base_value
    def write(target):
        section = layer(target)
        section.set_is_locked(False)
        for channel in section.get_all_channels():
            name = str(channel.channel_name)
            if not name.startswith('fk_') or '.Rotation.' not in name:
                continue
            for frame in frames:
                channel.add_key(unreal.FrameNumber(value=frame), plans[(name, frame)], 0.0,
                                unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.AUTO)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBRestoreActionFingers_' + uuid.uuid4().hex)
    try:
        candidate = native._copy_sequence(sequence, scope, 'Candidate')
        native._export(candidate, source, mesh, scope, 'Initialize', False)
        write(candidate)
        animation = native._export(candidate, source, mesh, scope, 'Restored')
        maximum_angle = 0.0
        for frame in frames:
            time = frame * rate.denominator / rate.numerator
            expected = _pose(reference, mesh, time * data['source_time_scale'])
            actual = _pose(animation, mesh, time)
            for side in ('l', 'r'):
                for finger in ('thumb', 'index', 'middle', 'ring', 'pinky'):
                    for joint in (1, 2, 3):
                        bone = f'{finger}_{joint:02}_{side}'
                        a = unreal.AnimPoseExtensions.get_bone_pose(expected, bone, unreal.AnimPoseSpaces.LOCAL)
                        b = unreal.AnimPoseExtensions.get_bone_pose(actual, bone, unreal.AnimPoseSpaces.LOCAL)
                        dot = abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple())))
                        angle = math.degrees(2 * math.acos(min(1.0, dot)))
                        maximum_angle = max(maximum_angle, angle)
                        if angle > 0.1:
                            raise RuntimeError('RESTORE_ACTION_FINGERS_POSE: ' + bone)
        require_asset_write([sequence])
        write(sequence)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('RESTORE_ACTION_FINGERS_SAVE')
        data.pop('restore_action_fingers_request')
        data.get('grip_endpoints', {})['finger_sides'] = []
        data['runtime_applied'] = False
        _save(path, data)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        native.repair_timeline_range(sequence)
        return {'sequence': data['sequence'], 'fingers_restored_to_base': True, 'frames': frames,
                'rotation_error_degrees': maximum_angle, 'hand_ik_and_attachment_tracks_untouched': True}
    finally:
        unreal.purge_object_references(scope, True)


def reset(path, data, write_paths):
    """/** @param path\t动作制作源 @param data\t当前制作参数 @param write_paths\t唯一序列 @return\t公共动作还原及附件保持证据 */"""
    import BBBManualActionNative as native
    from BBBControlRigAuthoringToolset import _asset, _pose, _key
    from BBBManualActionAuthoring import _save

    if set(write_paths) != {data['sequence']} or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('ACTION_RESET_SCOPE_OR_PIE')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    reference = _asset(data['animation'], unreal.AnimSequence)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    rate = sequence.get_display_rate()
    count = source.data_model_interface.get_number_of_keys()
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    names = {str(name).casefold(): str(name) for name in unreal.AnimPoseExtensions.get_bone_names(_pose(reference, mesh, 0))}
    mapping = {kind + '_' + side + suffix: bone + '_' + side for side in ('l', 'r')
               for kind, suffix, bone in [('clavicle', '_ctrl', 'clavicle'), ('hand', '_ik_ctrl', 'hand'), ('elbow', '_pv_ctrl', 'lowerarm')]}
    def sections(target):
        binding = native._mesh_binding(target, mesh)
        values = [section for track in binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
                  for section in track.get_sections()]
        base = [section for section in values if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE]
        edit = [section for section in values if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(base) != 1 or len(edit) != 1:
            raise RuntimeError('ACTION_RESET_SINGLE_BASE_OFFSET')
        return base[0], edit[0]
    base, edit = sections(sequence)
    controls = {str(channel.channel_name).split('.')[0] for channel in base.get_all_channels()}
    values = {control: [] for control in controls}
    for frame in range(count):
        pose = _pose(reference, mesh, frame * rate.denominator / rate.numerator * data['source_time_scale'])
        finger_pose = _pose(source, mesh, frame * rate.denominator / rate.numerator)
        for control in controls:
            name = mapping.get(control, control.removeprefix('source_').removeprefix('fk_'))
            bone = names.get(name.casefold())
            if bone is None:
                raise RuntimeError('ACTION_RESET_UNKNOWN_CONTROL: ' + control)
            space = unreal.AnimPoseSpaces.LOCAL if control.startswith('fk_') else unreal.AnimPoseSpaces.WORLD
            transform = unreal.AnimPoseExtensions.get_bone_pose(finger_pose if control.startswith('fk_') else pose, bone, space)
            if not control.startswith('fk_'):
                offset = asset.hierarchy.get_global_control_offset_transform(_key(control, 'CONTROL'), True)
                transform = transform.make_relative(offset)
            rotation = transform.rotation.rotator()
            numbers = list(transform.translation.to_tuple()) + [rotation.roll, rotation.pitch, rotation.yaw] + list(transform.scale3d.to_tuple())
            if values[control]:
                for axis in range(3, 6):
                    numbers[axis] += 360 * round((values[control][-1][axis] - numbers[axis]) / 360)
            values[control].append(numbers)
    suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
    def write(target):
        absolute, offset = sections(target)
        for section in (absolute, offset):
            section.set_is_locked(False)
            for channel in section.get_all_channels():
                name = str(channel.channel_name)
                if '.' not in name:
                    continue
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
                channel.set_default(neutral_value(name, section == absolute))
                if section == absolute:
                    control, suffix = name.split('.', 1)
                    if suffix not in suffixes:
                        raise RuntimeError('ACTION_RESET_CHANNEL: ' + name)
                    index = suffixes.index(suffix)
                    for frame, numbers in enumerate(values[control]):
                        channel.add_key(unreal.FrameNumber(value=frame), numbers[index], 0.0,
                                        unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)
        absolute.set_is_locked(True)
    preserved = native._channel_digest(sequence, [base, edit])
    scope = unreal.new_object(unreal.LevelSequence, name='BBBResetAction_' + uuid.uuid4().hex)
    try:
        candidate = native._copy_sequence(sequence, scope, 'Candidate')
        native._export(candidate, source, mesh, scope, 'Initialize', False)
        write(candidate)
        baked = native._export(candidate, source, mesh, scope, 'Base')
        maximum = 0.0
        for frame in range(count):
            time = frame * rate.denominator / rate.numerator
            expected = _pose(reference, mesh, time * data['source_time_scale'])
            actual = _pose(baked, mesh, time)
            finger_pose = _pose(source, mesh, time)
            for bone in names.values():
                if bone.casefold().startswith('ik_hand_'):
                    continue
                finger = bone.casefold().startswith(('thumb_', 'index_', 'middle_', 'ring_', 'pinky_'))
                space = unreal.AnimPoseSpaces.LOCAL if finger else unreal.AnimPoseSpaces.WORLD
                a = unreal.AnimPoseExtensions.get_bone_pose(finger_pose if finger else expected, bone, space)
                b = unreal.AnimPoseExtensions.get_bone_pose(actual, bone, space)
                error = (a.translation - b.translation).length()
                maximum = max(maximum, error)
                dot = abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple())))
                if error > 0.05 or dot < 0.99999:
                    raise RuntimeError('ACTION_RESET_BASE_POSE: ' + bone + ' frame=' + str(frame) + ' cm=' + str(error) + ' expected=' + str(a.translation.to_tuple()) + ' actual=' + str(b.translation.to_tuple()))
        require_asset_write([sequence])
        write(sequence)
        if native._channel_digest(sequence, list(sections(sequence))) != preserved:
            raise RuntimeError('ACTION_RESET_ATTACHMENTS_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('ACTION_RESET_SAVE')
        for field in ('reset_base_request', 'grip_endpoints', 'left_smoothing', 'key_smoothing', 'preserve_authored_end', 'bake_result'):
            data.pop(field, None)
        data['runtime_applied'] = False
        result = {'sequence': data['sequence'], 'base': data['animation'], 'base_pose_error_cm': maximum,
                  'manual_offset_keys_cleared': True, 'attachments_preserved': True, 'runtimeModified': False}
        data['base_reset'] = result
        _save(path, data)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        native.repair_timeline_range(sequence)
        return result
    finally:
        unreal.purge_object_references(scope, True)
