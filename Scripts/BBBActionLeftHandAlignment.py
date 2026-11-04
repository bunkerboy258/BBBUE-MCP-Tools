import gc
import hashlib
import json
import math
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _key
from BBBFingerAnimationTools import _tracks
from BBBRetargetInPlaceBatch import _metadata


def _pose(animation, mesh, seconds):
    """/** @param animation 动画 @param mesh 网格 @param seconds 时间 @return 原始组件姿势 */"""
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = False
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    return unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, seconds, options)


def _components(animation, mesh, seconds):
    """/** @param animation 动画 @param mesh 网格 @param seconds 时间 @return 按骨名索引的组件变换 */"""
    pose = _pose(animation, mesh, seconds)
    return {str(name).casefold(): pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD)
            for name in pose.get_bone_names()}


def _angle(first, second):
    """/** @param first 四元数 @param second 四元数 @return 最短弧角度 */"""
    a = first.to_tuple()
    b = second.to_tuple()
    norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    if not math.isfinite(norm) or norm < 0.000001:
        raise RuntimeError('LEFT_HAND_ALIGNMENT_QUATERNION')
    return math.degrees(2.0 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(a, b))) / norm)))


def _compose(local, parent):
    """/** @param local 局部变换 @param parent 父变换 @return 组件变换 */"""
    value = unreal.Transform(location=parent.transform_location(local.translation), scale=local.scale3d)
    value.rotation = parent.rotation * local.rotation
    return value


def _write(animation, tracks):
    """/** @param animation 候选动画 @param tracks 明确骨轨 @return 写入成功时无返回值 */"""
    controller = animation.controller
    controller.open_bracket('左手握持基准与原手指轨道', False)
    try:
        for name, values in tracks.items():
            if not controller.set_bone_track_keys(name, [v.translation for v in values],
                                                 [v.rotation for v in values], [v.scale3d for v in values], False):
                raise RuntimeError('LEFT_HAND_ALIGNMENT_WRITE: ' + name)
    finally:
        controller.close_bracket(False)


def _authored(job, target, mesh, scope):
    """/** @param job 动作项 @param target 正式动画 @param mesh 网格 @param scope 瞬态归属 @return 未对齐的原生制作求值 */"""
    request = job.get('authoring_input')
    if request is None:
        return target
    from BBBManualActionNative import _copy_sequence, _export
    if request.get('source_recipe'):
        project = Path(unreal.Paths.project_dir()).resolve()
        path = (project / request['source_recipe']).resolve()
        if not path.is_relative_to(project / 'Content/_Project/Characters'):
            raise RuntimeError('LEFT_HAND_ALIGNMENT_AUTHORING_SCOPE')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if data['output_animation'] != job['animation']:
            raise RuntimeError('LEFT_HAND_ALIGNMENT_AUTHORING_OUTPUT')
        from BBBManualActionAuthoring import _digest
        source_animation = _asset(data['animation'], unreal.AnimSequence)
        if _digest(source_animation) != data['source_track_digest']:
            raise RuntimeError('LEFT_HAND_ALIGNMENT_AUTHORING_SOURCE_CHANGED')
        sequence = _asset(data['sequence'], unreal.LevelSequence)
        source = _asset(data['finger_animation'], unreal.AnimSequence)
        return _export(sequence, source, _asset(data['mesh'], unreal.SkeletalMesh), scope, 'Authored')
    sequence = _asset(request['sequence'], unreal.LevelSequence)
    return _export(sequence, target, mesh, scope, 'Authored')


def _request_digest(job, data, reference, curves):
    """/** @param job 动作项 @param data 校准配置 @param reference 握持参考 @param curves 原曲线 @return 当前制作输入指纹 */"""
    from BBBManualActionAuthoring import _digest
    from BBBManualActionNative import _channel_digest
    values = {'reference': _digest(reference), 'reference_space': data['reference_space'],
              'rig': data['left_hand_rig'], 'curves': curves, 'constant': job.get('constant_reference', False)}
    request = job.get('authoring_input')
    if request:
        sequence_path = request.get('sequence')
        if request.get('source_recipe'):
            path = Path(unreal.Paths.project_dir()) / request['source_recipe']
            authored = json.loads(path.read_text(encoding='utf-8-sig'))
            sequence_path = authored['sequence']
            values['finger_input'] = _digest(_asset(authored['finger_animation'], unreal.AnimSequence))
        values['sequence'] = _channel_digest(_asset(sequence_path, unreal.LevelSequence))
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def match_finger_seam(path, data, write_paths):
    """/** @param path 正式制作源 @param data 明确指骨接缝请求 @param write_paths 唯一LS @return 保留其他通道的原生边界关键帧 */"""
    from BBBManualActionNative import _copy_sequence, _export, _mesh_binding
    from BBBManualActionAuthoring import _save
    if set(write_paths) != {data['sequence']} or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('FINGER_SEAM_SCOPE_OR_PIE')
    request = data['restore_action_fingers_request']
    bones = request['bone_names']
    valid = {f'{digit}_{joint:02}_{side}' for digit in ('thumb', 'index', 'middle', 'ring', 'pinky')
             for joint in (1, 2, 3) for side in ('l', 'r')}
    if not bones or len(set(bones)) != len(bones) or set(bones) - valid:
        raise RuntimeError('FINGER_SEAM_EXPLICIT_BONES')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    reference = _asset(request['animation'], unreal.AnimSequence)
    reference_rate = reference.data_model_interface.get_frame_rate()
    reference_frame = request['reference_frame']
    if type(reference_frame) is not int or not 0 <= reference_frame < reference.data_model_interface.get_number_of_keys():
        raise RuntimeError('FINGER_SEAM_REFERENCE_FRAME')
    reference_time = reference_frame * reference_rate.denominator / reference_rate.numerator
    rate = sequence.get_display_rate()
    targets = request['frames']
    anchors = request['preserve_frames']
    if not targets or not anchors or set(targets) & set(anchors) or any(type(f) is not int or not sequence.get_playback_start() <= f < sequence.get_playback_end() for f in targets + anchors):
        raise RuntimeError('FINGER_SEAM_TARGET_AND_ANCHORS')
    sections = [s for t in _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
                for s in t.get_sections()]
    absolute = [s for s in sections if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE]
    additive = [s for s in sections if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(absolute) != 1 or len(additive) != 1:
        raise RuntimeError('FINGER_SEAM_SINGLE_BASE_OFFSET')
    names = {f'fk_{bone}.Rotation.{axis}' for bone in bones for axis in ('X', 'Y', 'Z')}
    bases = {str(c.channel_name): c for c in absolute[0].get_all_channels()}
    offsets = {str(c.channel_name): c for c in additive[0].get_all_channels()}
    if names - bases.keys() or names - offsets.keys():
        raise RuntimeError('FINGER_SEAM_CHANNELS')

    def evaluate(channel, frame):
        """/** @param channel 原生通道 @param frame 显示帧 @return 当前值 */"""
        if not channel.get_keys():
            return float(channel.get_default()) if channel.has_default() else 0.0
        for key in channel.get_keys():
            stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            if abs(stamp.frame_number.value + stamp.sub_frame - frame) < 0.000001:
                return float(key.get_value())
        bounds = channel.compute_effective_range()
        bounds.set_start_seconds(frame * rate.denominator / rate.numerator)
        bounds.set_end_seconds((frame + 1) * rate.denominator / rate.numerator)
        values = channel.evaluate_keys(bounds, sequence.get_tick_resolution())
        if not values:
            raise RuntimeError('FINGER_SEAM_CHANNEL_EVALUATION')
        return float(values[0])

    def protected(target):
        """/** @param target 序列 @return 指定旋转通道以外的完整摘要 */"""
        display_rate = target.get_display_rate()
        tick_rate = target.get_tick_resolution()
        rows = [target.get_playback_start(), target.get_playback_end(),
                display_rate.numerator, display_rate.denominator, tick_rate.numerator, tick_rate.denominator]
        getters = ('get_interpolation_mode', 'get_tangent_mode', 'get_tangent_weight_mode',
                   'get_arrive_tangent', 'get_leave_tangent', 'get_arrive_tangent_weight', 'get_leave_tangent_weight')
        for binding in target.get_bindings():
            rows.append(binding.get_id().export_text())
            for track in binding.get_tracks():
                rows.append(track.get_class().get_name())
                for section in track.get_sections():
                    rows.append([str(section.get_blend_type().blend_type), section.is_locked()])
                    for channel in section.get_all_channels():
                        name = str(channel.channel_name)
                        if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE and name in names:
                            continue
                        keys = []
                        for key in channel.get_keys():
                            time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                            keys.append([time.frame_number.value, time.sub_frame, str(key.get_value()),
                                         [str(getattr(key, getter)()) for getter in getters if hasattr(key, getter)]])
                        default = str(channel.get_default()) if hasattr(channel, 'has_default') and channel.has_default() else None
                        rows.append([name, default, keys])
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    pose = _pose(reference, mesh, reference_time)
    hierarchy = _asset(data['rig'], unreal.ControlRigBlueprint).hierarchy
    plans = {}
    for bone in bones:
        control = _key('fk_' + bone, 'CONTROL')
        parent = hierarchy.get_parents(control)[0]
        offset = hierarchy.get_global_control_offset_transform(control, True).make_relative(hierarchy.get_global_transform(parent, True))
        desired = pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
        angles = (offset.rotation.inversed() * desired.rotation).normalized().rotator()
        for axis, angle in zip(('X', 'Y', 'Z'), (angles.roll, angles.pitch, angles.yaw)):
            name = 'fk_' + bone + '.Rotation.' + axis
            for frame in anchors:
                plans[(name, frame)] = evaluate(offsets[name], frame)
            for frame in targets:
                value = angle - evaluate(bases[name], frame)
                current = evaluate(offsets[name], frame)
                value += 360.0 * round((current - value) / 360.0)
                plans[(name, frame)] = value

    def write(target):
        """/** @param target 明确候选或正式序列 @return 写入所选通道的边界与保护锚点 */"""
        layer = [s for t in _mesh_binding(target, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
                 for s in t.get_sections() if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(layer) != 1:
            raise RuntimeError('FINGER_SEAM_OFFSET_LAYER')
        for channel in layer[0].get_all_channels():
            name = str(channel.channel_name)
            if name not in names:
                continue
            for frame in anchors + targets:
                channel.add_key(unreal.FrameNumber(value=frame), plans[(name, frame)], 0.0,
                                unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.AUTO)

    signature = protected(sequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBFingerSeam_' + uuid.uuid4().hex)
    try:
        before = _export(sequence, source, mesh, scope, 'Before')
        candidate = _copy_sequence(sequence, scope, 'Candidate')
        _export(candidate, source, mesh, scope, 'Initialize', False)
        candidate_signature = protected(candidate)
        write(candidate)
        if protected(candidate) != candidate_signature:
            raise RuntimeError('FINGER_SEAM_UNRELATED_CHANNEL_CHANGED')
        baked = _export(candidate, source, mesh, scope, 'After')
        maximum = 0.0
        for frame in anchors + targets:
            time = frame * rate.denominator / rate.numerator
            expected = pose if frame in targets else _pose(before, mesh, time)
            actual = _pose(baked, mesh, time)
            for bone in bones:
                a = expected.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
                b = actual.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
                maximum = max(maximum, _angle(a.rotation, b.rotation))
                if _angle(a.rotation, b.rotation) > 0.1:
                    raise RuntimeError('FINGER_SEAM_POSE: %s:%d:%.6f' % (bone, frame, _angle(a.rotation, b.rotation)))
        require_asset_write([sequence])
        write(sequence)
        if protected(sequence) != signature:
            raise RuntimeError('FINGER_SEAM_PROTECTED_READBACK')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('FINGER_SEAM_SAVE')
        data.pop('restore_action_fingers_request')
        data['finger_seam'] = {'reference': request['animation'], 'reference_frame': reference_frame,
                               'bones': bones, 'frames': targets, 'preserve_frames': anchors,
                               'maximum_rotation_error_degrees': maximum, 'other_channels_preserved': True}
        _save(path, data)
        return data['finger_seam']
    finally:
        unreal.purge_object_references(scope, True)


def _prepare(animation, job, data, reference, mesh, scope):
    """/** @param animation 正式动画 @param job 动作项 @param data 基准配置 @param reference 唯一握姿 @param mesh 网格 @param scope 瞬态归属 @return 完整验证的候选骨轨与证据 */"""
    from BBBActionRetargetTools import _blend
    from BBBHandRetargetBatchToolset import _LEFT_ARM_BONES, _fit_contact_shoulder, _validate_contact_reach
    from BBBLeftHandMotionCalibration import _sync_left_ik
    if animation.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE:
        raise RuntimeError('LEFT_HAND_ALIGNMENT_ABSOLUTE_ONLY')
    original = _tracks(animation)
    model = animation.data_model_interface
    count = model.get_number_of_keys()
    rate = model.get_frame_rate()
    authored = _authored(job, animation, mesh, scope)
    if abs(authored.get_play_length() - animation.get_play_length()) > 0.00001:
        raise RuntimeError('LEFT_HAND_ALIGNMENT_AUTHORING_LENGTH')
    names = unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)
    curve = next((n for n in names if str(n).casefold() == data['blend_curve'].casefold()), None)
    if not job.get('constant_reference') and curve is None:
        raise RuntimeError('LEFT_HAND_ALIGNMENT_CURVE_REQUIRED')
    weights = [0.0] * count
    if not job.get('constant_reference'):
        weights = [float(unreal.AnimationLibrary.get_float_value_at_time(animation, curve,
                   frame * rate.denominator / rate.numerator)) for frame in range(count)]
    if any(not math.isfinite(value) for value in weights):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_NONFINITE_CURVE')
    weights = [min(1.0, max(0.0, value)) for value in weights]
    grip_pose = _components(reference, mesh, 0.0)
    grip = grip_pose['hand_l'].make_relative(grip_pose['hand_r'])
    allowed = set(_LEFT_ARM_BONES)
    fingers = {name for name in original if name.startswith(('thumb_', 'index_', 'middle_', 'ring_', 'pinky_'))}
    if authored != animation:
        allowed.update(fingers)
    if not set(_LEFT_ARM_BONES).issubset(original):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_ARM_TRACKS_REQUIRED')
    candidate = unreal.SystemLibrary.duplicate_object(animation, scope, 'Candidate')
    seeded = {}
    authored_components = []
    if authored != animation:
        for name in allowed - {'ik_hand_l'}:
            seeded[name] = []
        for frame in range(count):
            pose = _pose(authored, mesh, frame * rate.denominator / rate.numerator)
            authored_components.append({str(n).casefold(): pose.get_bone_pose(n, unreal.AnimPoseSpaces.WORLD)
                                        for n in pose.get_bone_names()})
            for name in seeded:
                value = pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL)
                value.translation = original[name][frame].translation
                value.scale3d = original[name][frame].scale3d
                seeded[name].append(value)
        _write(candidate, seeded)
    blueprint = _asset(data['left_hand_rig'], unreal.ControlRigBlueprint)
    rig = blueprint.create_control_rig()
    rig.request_init()
    if not rig.execute_event('Forwards Solve'):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_RIG_INIT')
    hierarchy = rig.get_hierarchy()
    controls = {str(k.name).casefold(): str(k.name) for k in hierarchy.get_controls()}
    source_controls = {n.removeprefix('source_'): actual for n, actual in controls.items() if n.startswith('source_')}
    if not {'hand_l_ik_ctrl', 'elbow_l_pv_ctrl'}.issubset(controls):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_RIG_CONTROLS')
    prepared = {name: [] for name in _LEFT_ARM_BONES if name != 'ik_hand_l'}
    seeded_tracks = _tracks(candidate)
    expected = []
    shoulder_max = 0.0
    for frame, weight in enumerate(weights):
        seconds = frame * rate.denominator / rate.numerator
        pose = _components(candidate, mesh, seconds)
        if set(pose) - set(source_controls):
            raise RuntimeError('LEFT_HAND_ALIGNMENT_SOURCE_CONTROLS')
        source_pose = authored_components[frame] if authored_components else pose
        current_right = pose['hand_r']
        authored_left = _compose(source_pose['hand_l'].make_relative(source_pose['hand_r']), current_right)
        target = _blend(authored_left, _compose(grip, current_right), 1.0 - weight)
        expected.append(target)
        if weight >= 1.0:
            for name in prepared:
                prepared[name].append(seeded_tracks[name][frame])
            continue
        pole = _compose(source_pose['lowerarm_l'].make_relative(source_pose['hand_r']), current_right)
        shoulder_max = max(shoulder_max, _fit_contact_shoulder(pose, target, hierarchy))
        _validate_contact_reach(pose, target, pole)
        for name, value in pose.items():
            hierarchy.set_global_transform(_key(source_controls[name], 'CONTROL'), value)
        hierarchy.set_global_transform(_key(controls['hand_l_ik_ctrl'], 'CONTROL'), target)
        hierarchy.set_global_transform(_key(controls['elbow_l_pv_ctrl'], 'CONTROL'), pole)
        if not rig.execute_event('Forwards Solve'):
            raise RuntimeError('LEFT_HAND_ALIGNMENT_RIG_SOLVE')
        for name in prepared:
            value = hierarchy.get_local_transform(_key(name))
            value.translation = original[name][frame].translation
            value.scale3d = original[name][frame].scale3d
            prepared[name].append(value)
    _write(candidate, prepared)
    _sync_left_ik(candidate, mesh, count, rate)
    actual = _tracks(candidate)
    if set(actual) != set(original) or _metadata(candidate) != _metadata(animation):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_METADATA_CHANGED')
    if any(actual[name] != values for name, values in original.items() if name not in allowed):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_NON_TARGET_CHANGED')
    position_max = 0.0
    rotation_max = 0.0
    for frame, target in enumerate(expected):
        pose = _components(candidate, mesh, frame * rate.denominator / rate.numerator)
        hand = pose['hand_l']
        position_max = max(position_max, (hand.translation - target.translation).length())
        rotation_max = max(rotation_max, _angle(hand.rotation, target.rotation))
        if (hand.translation - target.translation).length() > 0.05 or _angle(hand.rotation, target.rotation) > 0.1:
            raise RuntimeError('LEFT_HAND_ALIGNMENT_TARGET: %s:%d' % (job['animation'], frame))
        for name in fingers & allowed:
            actual_finger = actual[name][frame]
            source_finger = seeded[name][frame]
            if (actual_finger.translation - source_finger.translation).length() > 0.0001 or _angle(actual_finger.rotation, source_finger.rotation) > 0.001 or (actual_finger.scale3d - source_finger.scale3d).length() > 0.00001:
                raise RuntimeError('LEFT_HAND_ALIGNMENT_FINGER_CHANGED: ' + name)
    return actual, allowed, {'mode': 'left_hand_relative_curve', 'reference': data['reference_animation'],
                           'reference_space': 'hand_r', 'curve': str(curve) if curve else None,
                           'action_weights': weights, 'frames': count, 'maximum_position_cm': position_max,
                           'maximum_rotation_degrees': rotation_max, 'maximum_clavicle_degrees': shoulder_max,
                           'non_target_tracks_preserved': True, 'authored_fingers_preserved': True}


def finalize(recipe_path, write_paths):
    """/** @param recipe_path 正式制作源 @param write_paths 明确成品子集 @return 原位左臂校准及原手指保持证据 */"""
    from BBBActionRetargetTools import _save
    from BBBManualActionAuthoring import _digest
    from BBBAnimationCurveTools import _curve_values
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    if not path.is_relative_to(project / 'Content/_Project/Characters') or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_SCOPE_OR_PIE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBNativeRetargetActions' or data.get('reference_space') != 'hand_r' or not data.get('approval'):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_EXPLICIT_REFERENCE_REQUIRED')
    jobs = [j for j in data['jobs'] if j['animation'] in write_paths]
    if not jobs or len(jobs) != len(set(write_paths)) or {j['animation'] for j in jobs} != set(write_paths):
        raise RuntimeError('LEFT_HAND_ALIGNMENT_WRITE_SCOPE')
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    mesh = _asset(data['target_mesh'], unreal.SkeletalMesh)
    reports = []
    for job in jobs:
        animation = _asset(job['animation'], unreal.AnimSequence)
        metadata = _metadata(animation)
        protected_tracks = _tracks(animation)
        curves = _curve_values(animation)
        before = _digest(animation)
        request_digest = _request_digest(job, data, reference, curves)
        previous = job.get('validation', {})
        if previous.get('mode') == 'left_hand_relative_curve' and previous.get('request_digest') == request_digest:
            if before == job.get('aligned_digest'):
                reports.append(previous)
                continue
            raise RuntimeError('LEFT_HAND_ALIGNMENT_SAVED_TARGET_CHANGED')
        scope = unreal.new_object(unreal.LevelSequence, name='BBBActionLeftHand_' + uuid.uuid4().hex)
        try:
            tracks, allowed, report = _prepare(animation, job, data, reference, mesh, scope)
            if _digest(animation) != before:
                raise RuntimeError('LEFT_HAND_ALIGNMENT_INPUT_CHANGED')
            require_asset_write([animation])
            _write(animation, {name: tracks[name] for name in allowed})
            actual = _tracks(animation)
            if set(actual) != set(tracks) or _metadata(animation) != metadata or _curve_values(animation) != curves:
                raise RuntimeError('LEFT_HAND_ALIGNMENT_READBACK')
            for name, values in actual.items():
                if name not in allowed and values != protected_tracks[name]:
                    raise RuntimeError('LEFT_HAND_ALIGNMENT_PROTECTED_READBACK: ' + name)
                if len(values) != len(tracks[name]):
                    raise RuntimeError('LEFT_HAND_ALIGNMENT_READBACK_COUNT: ' + name)
                for value, expected in zip(values, tracks[name]):
                    if (value.translation - expected.translation).length() > 0.0001 or _angle(value.rotation, expected.rotation) > 0.001 or (value.scale3d - expected.scale3d).length() > 0.00001:
                        raise RuntimeError('LEFT_HAND_ALIGNMENT_TRACK_READBACK: ' + name)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('LEFT_HAND_ALIGNMENT_SAVE')
            report['animation'] = job['animation']
            report['input_digest'] = before
            report['request_digest'] = request_digest
            report['animation_digest'] = _digest(animation)
            report['curve_digest'] = hashlib.sha256(json.dumps(curves, sort_keys=True).encode()).hexdigest()
            job['validation'] = report
            job['aligned_digest'] = report['animation_digest']
            reports.append(report)
            data['state'] = 'partial_left_hand_aligned'
            _save(path, data)
            unreal.log('[BBBActionLeftHandAlignment] ' + json.dumps(report))
        finally:
            unreal.purge_object_references(scope, True)
            gc.collect()
    return {'state': data['state'], 'jobs': reports}
