"""将人工小数帧握持修正连续化并生成审核动画"""
import hashlib
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _key, _mesh_binding, _pose, _read_transform
from BBBManualActionAuthoring import _source, _save, _digest, _evaluate_control_curves


def _channels(sequence, mesh):
    """
    /**
     * @param sequence	明确制作序列
     * @param mesh	角色网格
     * @return	唯一Rig的原生控制通道
     */
    """
    tracks = _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1 or len(tracks[0].get_sections()) != 1:
        raise RuntimeError('MANUAL_BAKE_SINGLE_RIG_REQUIRED')
    return {str(channel.channel_name): channel for channel in tracks[0].get_sections()[0].get_all_channels()}


def _solver(asset):
    """
    /**
     * @param asset	已保存制作Rig
     * @return	独立求值实例
     */
    """
    instance = asset.create_control_rig()
    instance.request_init()
    if not instance.execute_event('Forwards Solve'):
        raise RuntimeError('MANUAL_BAKE_RIG_INIT')
    return instance


def _sample(sequence, channels, instance, time):
    """
    /**
     * @param sequence	通道所属序列
     * @param channels	控制通道
     * @param instance	独立Rig
     * @param time	秒数
     * @return	完成前向求解的层级
     */
    """
    hierarchy = instance.get_hierarchy()
    _evaluate_control_curves(sequence, channels, hierarchy, time)
    if not instance.execute_event('Forwards Solve'):
        raise RuntimeError('MANUAL_BAKE_RIG_SOLVE')
    return hierarchy


def _delta_at(anchors, frame):
    """
    /**
     * @param anchors	人工修正及起止零修正
     * @param frame	显示帧时间
     * @return	零端点速度的连续修正 不产生插值过冲
     */
    """
    for first, second in zip(anchors, anchors[1:]):
        if first['frame'] <= frame <= second['frame']:
            alpha = (frame - first['frame']) / (second['frame'] - first['frame'])
            alpha = alpha * alpha * (3.0 - 2.0 * alpha)
            return first['delta'].lerp(second['delta'], alpha)
    raise RuntimeError('MANUAL_BAKE_ANCHOR_RANGE')


def _corrected(base, channels, instance, time, display_fps, anchors, control):
    """
    /**
     * @param base	只在瞬态中移除小数帧窄峰的基线
     * @param channels	瞬态基线通道
     * @param instance	独立求解器
     * @param time	秒数
     * @param display_fps	原序列显示帧率
     * @param anchors	人工修正控制点
     * @param control	左手控制器
     * @return	按右手空间追加人工修正后的姿势
     */
    """
    hierarchy = _sample(base, channels, instance, time)
    right = hierarchy.get_global_transform(_key('hand_r'))
    relative = hierarchy.get_global_transform(_key(control, 'CONTROL')).make_relative(right)
    delta = _delta_at(anchors, time * display_fps)
    relative.translation = relative.translation + delta.translation
    relative.rotation = delta.rotation * relative.rotation
    target = unreal.MathLibrary.compose_transforms(relative, right)
    hierarchy.set_global_transform(_key(control, 'CONTROL'), target)
    if not instance.execute_event('Forwards Solve'):
        raise RuntimeError('MANUAL_BAKE_CORRECTED_SOLVE')
    return hierarchy


def bake_review(recipe_path, write_paths):
    """
    /**
     * @param recipe_path	正式人工制作源及明确重烘焙设置
     * @param write_paths	唯一审核动画
     * @return	保留人工控制点的连续修正成品及原生校验 不写运行引用
     */
    """
    from BBBAnimationTrajectoryTools import _track_metadata
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('MANUAL_BAKE_PIE_FORBIDDEN')
    path, data = _source(recipe_path)
    settings = data['continuous_review']
    destination = settings['animation']
    if set(write_paths) != {destination} or destination.rsplit('/', 1)[0] != data['weapon_root'] + '/Animation/Sequence':
        raise RuntimeError('MANUAL_BAKE_WRITE_SCOPE')
    source = _asset(data['animation'], unreal.AnimSequence)
    if _digest(source) != data['source_track_digest']:
        raise RuntimeError('MANUAL_BAKE_SOURCE_CHANGED')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    output = _asset(destination, unreal.AnimSequence)
    require_asset_write([output])
    metadata = _track_metadata(output)
    rate = sequence.get_display_rate()
    display_fps = rate.numerator / rate.denominator
    duration = source.get_play_length()
    control = settings['control']
    if control != 'hand_l_ik_ctrl' or settings['bake_fps'] != 120:
        raise RuntimeError('MANUAL_BAKE_EXPLICIT_SETTINGS')
    original = _channels(sequence, mesh)
    suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
    frames = set()
    for name, channel in original.items():
        for key in channel.get_keys():
            stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            frame = stamp.frame_number.value + stamp.sub_frame
            if abs(frame - round(frame)) > 0.0001:
                if not name.startswith(control + '.'):
                    raise RuntimeError('MANUAL_BAKE_OTHER_SUBFRAME_CONTROL: ' + name)
                frames.add(round(frame, 5))
    frames = sorted(frames)
    if not 2 <= len(frames) <= 32 or settings['entry_frame'] != 0 or abs(settings['exit_frame'] - duration * display_fps) > 0.001:
        raise RuntimeError('MANUAL_BAKE_ANCHORS_AND_BOUNDARIES')
    if frames[0] <= settings['entry_frame'] or frames[-1] >= settings['exit_frame']:
        raise RuntimeError('MANUAL_BAKE_ANCHOR_ORDER')
    scope = unreal.new_object(unreal.LevelSequence, name='BBBContinuousManual_' + uuid.uuid4().hex)
    try:
        base = unreal.SystemLibrary.duplicate_object(sequence, scope, 'Base')
        if base.get_outermost().get_path_name() != '/Engine/Transient':
            raise RuntimeError('MANUAL_BAKE_TRANSIENT_BASE_ONLY')
        temporary_animation = unreal.SystemLibrary.duplicate_object(source, scope, 'Evaluation')
        options = unreal.AnimSeqExportOption()
        options.export_transforms = True
        options.export_morph_targets = False
        options.export_attribute_curves = False
        options.export_material_curves = False
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not unreal.SequencerTools.export_anim_sequence(world, base, temporary_animation, options, _mesh_binding(base, mesh), False):
            raise RuntimeError('MANUAL_BAKE_TRANSIENT_BASE_EVALUATION')
        base_channels = _channels(base, mesh)
        desired_instance = _solver(asset)
        base_instance = _solver(asset)
        for suffix in suffixes:
            if control + '.' + suffix not in base_channels:
                raise RuntimeError('MANUAL_BAKE_BASE_CHANNEL_NAMES: ' + str(list(base_channels)[:16]))
            channel = base_channels[control + '.' + suffix]
            for key in list(channel.get_keys()):
                stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                frame = stamp.frame_number.value + stamp.sub_frame
                if abs(frame - round(frame)) > 0.0001:
                    channel.remove_key(key)
        anchors = [{'frame': settings['entry_frame'], 'delta': unreal.Transform()}]
        targets = []
        for frame in frames:
            time = frame / display_fps
            desired_hierarchy = _sample(sequence, original, desired_instance, time)
            right = desired_hierarchy.get_global_transform(_key('hand_r'))
            desired = desired_hierarchy.get_global_transform(_key(control, 'CONTROL')).make_relative(right)
            targets.append(desired_hierarchy.get_global_transform(_key('hand_l')))
            base_hierarchy = _sample(base, base_channels, base_instance, time)
            neutral = base_hierarchy.get_global_transform(_key(control, 'CONTROL')).make_relative(base_hierarchy.get_global_transform(_key('hand_r')))
            delta = unreal.Transform(location=desired.translation - neutral.translation)
            delta.rotation = desired.rotation * neutral.rotation.inversed()
            anchors.append({'frame': frame, 'delta': delta})
        anchors.append({'frame': settings['exit_frame'], 'delta': unreal.Transform()})
        count = round(duration * settings['bake_fps']) + 1
        if count < 2 or count > 1200:
            raise RuntimeError('MANUAL_BAKE_SAMPLE_COUNT')
        names = [str(bone.name) for bone in base_instance.get_hierarchy().get_bones()]
        prepared = {name: [] for name in names}
        expected = []
        for index in range(count):
            time = min(duration, index / settings['bake_fps'])
            hierarchy = _corrected(base, base_channels, base_instance, time, display_fps, anchors, control)
            expected.append({name: hierarchy.get_global_transform(_key(name)) for name in names})
            for name in names:
                prepared[name].append(hierarchy.get_local_transform(_key(name)))
        controller = output.controller
        controller.open_bracket('重烘焙连续人工左手修正', False)
        try:
            controller.remove_all_bone_tracks(False)
            controller.set_frame_rate(unreal.FrameRate(numerator=settings['bake_fps'], denominator=1), False)
            controller.set_number_of_frames(unreal.FrameNumber(value=count - 1), False)
            for name, values in prepared.items():
                if not controller.add_bone_track(name, False) or not controller.set_bone_track_keys(name, [value.translation for value in values], [value.rotation for value in values], [value.scale3d for value in values], False):
                    raise RuntimeError('MANUAL_BAKE_BONE_WRITE: ' + name)
        finally:
            controller.close_bracket(False)
        if unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(source, output) < 0:
            raise RuntimeError('MANUAL_BAKE_CURVES')
        after = _track_metadata(output)
        if {key: value for key, value in after.items() if key not in ('frames', 'rate')} != {key: value for key, value in metadata.items() if key not in ('frames', 'rate')}:
            raise RuntimeError('MANUAL_BAKE_METADATA_CHANGED')
        maximum = 0.0
        options = unreal.AnimPoseEvaluationOptions()
        options.optional_skeletal_mesh = mesh
        options.should_retarget = False
        options.evaluation_type = unreal.AnimDataEvalType.RAW
        for index, bones in enumerate(expected):
            pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(output, min(duration, index / settings['bake_fps']), options)
            for name, value in bones.items():
                actual = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)
                distance = (actual.translation - value.translation).length()
                maximum = max(maximum, distance)
                if distance > 0.02:
                    raise RuntimeError('MANUAL_BAKE_NATIVE_READBACK: %s index=%d cm=%f actual=%s expected=%s' % (name, index, distance, actual.export_text(), value.export_text()))
        errors = []
        for frame, target in zip(frames, targets):
            pose = _pose(output, mesh, frame / display_fps)
            actual = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_l', unreal.AnimPoseSpaces.WORLD)
            error = (actual.translation - target.translation).length()
            raw = unreal.AnimPoseExtensions.get_anim_pose_at_time(output, frame / display_fps, options)
            raw_hand = unreal.AnimPoseExtensions.get_bone_pose(raw, 'hand_l', unreal.AnimPoseSpaces.WORLD)
            errors.append({'frame': frame, 'left_hand_error_cm': error, 'raw_hand_error_cm': (raw_hand.translation - target.translation).length()})
        if any(row['left_hand_error_cm'] > settings['max_anchor_error_cm'] for row in errors):
            raise RuntimeError('MANUAL_BAKE_ANCHOR_ERROR: ' + str(errors))
        if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('MANUAL_BAKE_SAVE')
        result = {'animation': destination, 'sample_keys': count, 'fps': settings['bake_fps'], 'seconds': output.get_play_length(),
                  'anchor_errors': errors, 'native_sample_error_cm': maximum, 'sequenceModified': False, 'runtimeReferenceChanged': False,
                  'anchors': [{'frame': row['frame'], 'delta_right_hand_space': _read_transform(row['delta'])} for row in anchors],
                  'visualAcceptance': 'pending'}
        data['review_bake']['continuous_result'] = result
        asset_file = Path(unreal.Paths.project_content_dir()) / (destination.removeprefix('/Game/') + '.uasset')
        data['review_bake']['animation_sha256'] = hashlib.sha256(asset_file.read_bytes()).hexdigest()
        data['review_bake']['sample_keys'] = count
        _save(path, data)
        return result
    finally:
        base_channels = None
        base = None
        unreal.purge_object_references(scope, True)
