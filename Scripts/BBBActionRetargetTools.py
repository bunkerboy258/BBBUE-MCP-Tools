import json
import math
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _pose


def _read(recipe_path, write_paths):
    """/** @param recipe_path\t正式重定向制作源 @param write_paths\t明确输出 @return\t路径及配置 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBNativeRetargetActions' or data.get('schema') != 1 or not data.get('approval'):
        raise RuntimeError('RETARGET_ACTION_SOURCE_FORMAT')
    if project not in path.parents or set(write_paths) != {job['animation'] for job in data['jobs']}:
        raise RuntimeError('RETARGET_ACTION_SCOPE')
    return path, data


def _save(path, data):
    """/** @param path\t正式文件 @param data\t阶段事实 @return\t保存回读 */"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if json.loads(path.read_text(encoding='utf-8')) != data:
        raise RuntimeError('RETARGET_ACTION_SOURCE_SAVE')


def _metrics(animation, reference, mesh, times, reference_frame=0):
    """/** @param animation\t待查动作 @param reference\t正确参考 @param mesh\t目标网格 @param times\t采样时间 @return\t腕姿轨迹误差 */"""
    rate = reference.data_model_interface.get_frame_rate()
    target = _pose(reference, mesh, reference_frame * rate.denominator / rate.numerator)
    rows = []
    for time in times:
        pose = _pose(animation, mesh, time)
        values = {'seconds': time}
        for bone in ('hand_l', 'hand_r', 'lowerarm_l', 'lowerarm_r'):
            a = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD)
            b = unreal.AnimPoseExtensions.get_bone_pose(target, bone, unreal.AnimPoseSpaces.WORLD)
            values[bone] = {'cm': (a.translation - b.translation).length(),
                            'quaternion_dot': abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple())))}
        rows.append(values)
    return rows


def _restore_component_snapshot(job):
    """/** @param job 同型号正式完整姿态记录与明确目标 @return 保留元数据的原位恢复证据 */"""
    import hashlib
    from BBBManualActionAuthoring import _digest
    from BBBAnimationCurveTools import _curve_values, _animation_metadata
    request = job['component_snapshot']
    project = Path(unreal.Paths.project_dir()).resolve()
    record = (project / request['record']).resolve()
    owner = job['animation'].split('/Animation/')[0].removeprefix('/Game/')
    if record.parent != (project / 'Content' / owner / 'Source/Animation').resolve():
        raise RuntimeError('COMPONENT_SNAPSHOT_OWNER_SCOPE')
    encoded = record.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != request['record_sha256']:
        raise RuntimeError('COMPONENT_SNAPSHOT_RECORD_CHANGED')
    saved = json.loads(encoded.decode('utf-8-sig'))['source_motion']
    candidates = [row for row in saved[request['group']] if row['asset'] == job['animation']]
    if len(candidates) != 1:
        raise RuntimeError('COMPONENT_SNAPSHOT_UNIQUE_ASSET')
    animation = _asset(job['animation'], unreal.AnimSequence)
    if _digest(animation) != request['expected_target_digest']:
        raise RuntimeError('COMPONENT_SNAPSHOT_TARGET_CHANGED')
    count = animation.data_model_interface.get_number_of_keys()
    samples = candidates[0]['samples']
    if len(samples) != count or [row['frame'] for row in samples] != list(range(count)):
        raise RuntimeError('COMPONENT_SNAPSHOT_COMPLETE_SAMPLES')
    names = [str(name) for name in animation.data_model_interface.get_bone_track_names()]
    mesh = _asset(saved['mesh'], unreal.SkeletalMesh)
    if mesh.get_editor_property('skeleton') != animation.get_skeleton():
        raise RuntimeError('COMPONENT_SNAPSHOT_SKELETON')
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    parents = {name: str(subsystem.get_bone_parent(mesh, name)).casefold() for name in names}
    values = {name: [] for name in names}
    for sample in samples:
        components = {}
        for name, row in sample['bones'].items():
            value = unreal.Transform(location=unreal.Vector(*[row['translation'][axis] for axis in ('x','y','z')]),
                scale=unreal.Vector(*[row['scale'][axis] for axis in ('x','y','z')]))
            value.rotation = unreal.Quat(*row['quaternion']).normalized()
            components[name.casefold()] = value
        if {name.casefold() for name in names} != set(components):
            raise RuntimeError('COMPONENT_SNAPSHOT_COMPLETE_BONES')
        for name in names:
            value = components[name.casefold()]
            if parents[name] in components:
                value = value.make_relative(components[parents[name]])
            values[name].append(value)
    metadata = _animation_metadata(animation)
    curves = _curve_values(animation)
    require_asset_write([animation])
    controller = animation.controller
    controller.open_bracket('从同型号完整制作姿态记录恢复原始骨轨', False)
    try:
        for name, keys in values.items():
            if not controller.set_bone_track_keys(name, [v.translation for v in keys], [v.rotation for v in keys], [v.scale3d for v in keys], False):
                raise RuntimeError('COMPONENT_SNAPSHOT_WRITE: ' + name)
    finally:
        controller.close_bracket(False)
    for name, expected in values.items():
        actual = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
        if len(actual) != count or any((a.translation-b.translation).length() > 0.001 or abs((a.rotation.normalized()*b.rotation.normalized().inversed()).w) < 0.999999 for a,b in zip(actual,expected)):
            raise RuntimeError('COMPONENT_SNAPSHOT_READBACK: ' + name)
    if _animation_metadata(animation) != metadata or _curve_values(animation) != curves:
        raise RuntimeError('COMPONENT_SNAPSHOT_METADATA_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('COMPONENT_SNAPSHOT_SAVE')
    return {'record': request['record'], 'record_sha256': request['record_sha256'], 'frames': count, 'bones': len(names), 'restored_digest': _digest(animation)}


def capture(recipe_path, write_paths):
    """/** @param recipe_path\t原始动作重定向要求 @param write_paths\t输出包 @return\t新重定向动作与轨迹核对 */"""
    from BBBManualActionAuthoring import _digest
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('RETARGET_ACTION_PIE_FORBIDDEN')
    path, data = _read(recipe_path, write_paths)
    if all(job.get('in_place_alignment') and job['source'] == job['animation'] for job in data['jobs']):
        reports = []
        for job in data['jobs']:
            if job.get('component_snapshot') and not job.get('retarget_digest'):
                job['snapshot_restore_result'] = _restore_component_snapshot(job)
            animation = _asset(job['animation'], unreal.AnimSequence)
            count = animation.data_model_interface.get_number_of_keys()
            if count < 2 or not animation.data_model_interface.get_bone_track_names():
                raise RuntimeError('IN_PLACE_ALIGNMENT_NONEMPTY_TRACKS_REQUIRED')
            signature = _digest(animation)
            expected = job.get('aligned_digest', job.get('retarget_digest'))
            if expected and signature != expected:
                raise RuntimeError('IN_PLACE_ALIGNMENT_INPUT_CHANGED: ' + job['animation'])
            job.setdefault('retarget_digest', signature)
            job.setdefault('source_digest', signature)
            job['frames'] = count
            job['length'] = animation.get_play_length()
            reports.append({'animation': job['animation'], 'frames': count, 'already_aligned': bool(job.get('aligned_digest'))})
        data['state'] = 'prepared'
        _save(path, data)
        return {'state': data['state'], 'jobs': reports}
    if any('source_frame_ranges' in job for job in data['jobs']):
        return _capture_frame_ranges(path, data, write_paths)
    retargeter = _asset(data['retargeter'], unreal.IKRetargeter)
    if unreal.IKRetargeterController.get_controller(retargeter).get_num_retarget_ops() == 0:
        raise RuntimeError('RETARGET_ACTION_EMPTY_OP_STACK')
    require_asset_write([], destinations=write_paths)
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    mesh = _asset(data['target_mesh'], unreal.SkeletalMesh)
    reports = []
    for job in data['jobs']:
        if job.get('retarget_digest'):
            reports.append(job)
            continue
        if unreal.EditorAssetLibrary.does_asset_exist(job['animation']):
            raise RuntimeError('RETARGET_ACTION_OUTPUT_ALREADY_EXISTS')
        options = unreal.IKRetargetBatchOperationInputs()
        options.assets_to_retarget = [unreal.EditorAssetLibrary.find_asset_data(job['source'])]
        options.source_mesh = _asset(data['source_mesh'], unreal.SkeletalMesh)
        options.target_mesh = mesh
        options.ik_retarget_asset = retargeter
        options.target_path = job['animation'].rsplit('/', 1)[0]
        options.search = job['source'].rsplit('/', 1)[-1]
        options.replace = job['animation'].rsplit('/', 1)[-1]
        options.suffix = ''
        options.prefix = ''
        options.include_referenced_assets = False
        options.overwrite_existing_files = False
        options.retain_additive_flags = True
        outputs = unreal.IKRetargetBatchOperation.run_batch_retarget(options)
        if len(outputs) != 1 or str(outputs[0].package_name) != job['animation']:
            raise RuntimeError('RETARGET_ACTION_EXACT_DESTINATION')
        animation = _asset(job['animation'], unreal.AnimSequence)
        if animation.get_editor_property('skeleton') != reference.get_editor_property('skeleton'):
            raise RuntimeError('RETARGET_ACTION_TARGET_SKELETON')
        unreal.AnimationLibrary.remove_all_animation_notify_tracks(animation)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('RETARGET_ACTION_SAVE')
        job['retarget_digest'] = _digest(animation)
        job['source_digest'] = _digest(_asset(job['source'], unreal.AnimSequence))
        job['length'] = animation.get_play_length()
        rate = animation.data_model_interface.get_frame_rate()
        job['frames'] = animation.data_model_interface.get_number_of_keys()
        frames = sorted(set([0, 4, 6, job['frames'] - 1, *range(max(0, job['frames'] - 18), job['frames'], 3)]))
        job['raw_trajectory'] = _metrics(animation, reference, mesh, [f * rate.denominator / rate.numerator for f in frames])
        reports.append(job)
        data['state'] = 'retargeted'
        _save(path, data)
    return {'state': data['state'], 'retargeter': data['retargeter'], 'jobs': reports}


def _capture_frame_ranges(path, data, write_paths):
    """Create a native sequence from explicit inclusive source ranges; reject discontinuous seams."""
    from BBBManualActionAuthoring import _digest
    mesh = _asset(data['target_mesh'], unreal.SkeletalMesh)
    reports = []
    for job in data['jobs']:
        source = _asset(job['source'], unreal.AnimSequence)
        signature = _digest(source)
        if job.get('retarget_digest'):
            output = _asset(job['animation'], unreal.AnimSequence)
            if signature != job['source_digest'] or _digest(output) != job.get('aligned_digest', job['retarget_digest']):
                raise RuntimeError('FRAME_RANGES_SAVED_ASSET_CHANGED')
            reports.append(job)
            continue
        ranges = job['source_frame_ranges']
        count = source.data_model_interface.get_number_of_keys()
        if not ranges or any(len(r) != 2 or any(type(n) is not int for n in r) or not 0 <= r[0] < r[1] < count for r in ranges):
            raise RuntimeError('FRAME_RANGES_INVALID')
        if any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:])):
            raise RuntimeError('FRAME_RANGES_ORDER')
        if job['animation'] == job['source'] or unreal.EditorAssetLibrary.does_asset_exist(job['animation']):
            raise RuntimeError('FRAME_RANGES_NEW_OUTPUT_REQUIRED')
        rate = source.data_model_interface.get_frame_rate()
        seam_cm, seam_degrees = 0.0, 0.0
        for first, second in zip(ranges, ranges[1:]):
            a = _pose(source, mesh, first[1] * rate.denominator / rate.numerator)
            b = _pose(source, mesh, second[0] * rate.denominator / rate.numerator)
            for bone in source.data_model_interface.get_bone_track_names():
                left = unreal.AnimPoseExtensions.get_bone_pose(a, bone, unreal.AnimPoseSpaces.WORLD)
                right = unreal.AnimPoseExtensions.get_bone_pose(b, bone, unreal.AnimPoseSpaces.WORLD)
                error = (left.translation - right.translation).length()
                cosine = abs(sum(x*y for x, y in zip(left.rotation.to_tuple(), right.rotation.to_tuple())))
                degrees = math.degrees(2 * math.acos(min(1.0, cosine)))
                seam_cm, seam_degrees = max(seam_cm, error), max(seam_degrees, degrees)
                if error > 0.05 or degrees > 0.2:
                    raise RuntimeError('FRAME_RANGES_SEAM: %s cm=%f degrees=%f' % (bone, error, degrees))
        frames = [f for start, end in ranges for f in range(start, end + 1)]
        tracks = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, n))
                  for n in source.data_model_interface.get_bone_track_names()}
        require_asset_write([], destinations=[job['animation']])
        output = unreal.EditorAssetLibrary.duplicate_asset(job['source'], job['animation'])
        if output is None:
            raise RuntimeError('FRAME_RANGES_CREATE')
        require_asset_write([output])
        controller = output.controller
        controller.open_bracket('按明确源帧拼接单次动作', False)
        try:
            controller.remove_all_curves_of_type(unreal.RawCurveTrackTypes.RCT_FLOAT, False)
            controller.remove_all_curves_of_type(unreal.RawCurveTrackTypes.RCT_TRANSFORM, False)
            controller.set_number_of_frames(unreal.FrameNumber(value=len(frames)-1), False)
            for bone, original in tracks.items():
                values = [original[f] for f in frames]
                if not controller.set_bone_track_keys(bone, [v.translation for v in values],
                        [v.rotation for v in values], [v.scale3d for v in values], False):
                    raise RuntimeError('FRAME_RANGES_TRACK: ' + bone)
        finally:
            controller.close_bracket(False)
        unreal.AnimationLibrary.remove_all_animation_notify_tracks(output)
        maximum = 0.0
        for bone, original in tracks.items():
            actual = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(output, bone))
            if len(actual) != len(frames):
                raise RuntimeError('FRAME_RANGES_SAMPLE_COUNT')
            for value, frame in zip(actual, frames):
                expected = original[frame]
                maximum = max(maximum, (value.translation - expected.translation).length())
                cosine = abs(sum(x*y for x, y in zip(value.rotation.to_tuple(), expected.rotation.to_tuple())))
                if maximum > 0.0001 or cosine < 0.999999 or (value.scale3d - expected.scale3d).length() > 0.00001:
                    raise RuntimeError('FRAME_RANGES_TRACK_READBACK')
        if _digest(source) != signature or not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('FRAME_RANGES_SAVE_OR_SOURCE_CHANGED')
        job.update(source_digest=signature, retarget_digest=_digest(output), frames=len(frames),
                   length=output.get_play_length(), splice_validation={'seam_position_cm': seam_cm,
                   'seam_rotation_degrees': seam_degrees, 'track_position_error_cm': maximum,
                   'source_preserved': True, 'source_frames': frames})
        reports.append(job)
        data['state'] = 'captured'
        _save(path, data)
    return {'state': data['state'], 'jobs': reports}


def _blend(a, b, weight):
    """/** @param a\t动作局部变换 @param b\t参考局部变换 @param weight\t参考权重 @return\t最短弧旋转和局部位置插值 */"""
    if weight <= 0:
        return a
    if weight >= 1:
        return b
    left = list(a.rotation.normalized().to_tuple())
    right = list(b.rotation.normalized().to_tuple())
    dot = sum(x * y for x, y in zip(left, right))
    if dot < 0:
        right = [-x for x in right]
        dot = -dot
    result = unreal.Transform(location=a.translation + (b.translation - a.translation) * weight,
                              scale=a.scale3d + (b.scale3d - a.scale3d) * weight)
    if dot > 0.9995:
        result.rotation = unreal.Quat(*[x + (y - x) * weight for x, y in zip(left, right)]).normalized()
        return result
    angle = math.acos(min(1.0, dot))
    result.rotation = unreal.Quat(*[(x * math.sin((1 - weight) * angle) + y * math.sin(weight * angle)) / math.sin(angle)
                                   for x, y in zip(left, right)]).normalized()
    return result


def finalize(recipe_path, write_paths):
    """/** @param recipe_path\t明确首尾窗口的制作源 @param write_paths\t公共动作输出 @return\t首尾参考和中段保留核验 */"""
    import hashlib
    from BBBManualActionAuthoring import _digest
    from BBBAnimationCurveTools import _curve_values, _animation_metadata
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('CURVE_ALIGNMENT_PIE_FORBIDDEN')
    path, data = _read(recipe_path, write_paths)
    curve_name = data.get('blend_curve', 'DisableLeftHandIK')
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    reports = []
    for job in data['jobs']:
        animation = _asset(job['animation'], unreal.AnimSequence)
        curves_before = _curve_values(animation)
        curve_digest = hashlib.sha256(json.dumps(curves_before, sort_keys=True).encode()).hexdigest()
        if job.get('aligned_digest'):
            validation = job.get('validation', {})
            if validation.get('mode') != 'curve_driven':
                raise RuntimeError('CURVE_ALIGNMENT_REBAKE_REQUIRED: ' + job['animation'])
            if _digest(animation) != job['aligned_digest'] or validation['curve_digest'] != curve_digest:
                raise RuntimeError('CURVE_ALIGNMENT_SAVED_ASSET_CHANGED: ' + job['animation'])
            reports.append(validation)
            continue
        if _digest(animation) != job['retarget_digest']:
            raise RuntimeError('CURVE_ALIGNMENT_RAW_ASSET_CHANGED: ' + job['animation'])
        model = animation.data_model_interface
        count = model.get_number_of_keys()
        rate = model.get_frame_rate()
        original = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, n)) for n in model.get_bone_track_names()}
        if not original or any(len(keys) != count for keys in original.values()):
            raise RuntimeError('CURVE_ALIGNMENT_COMPLETE_TRACKS_REQUIRED')
        metadata = _animation_metadata(animation)
        playback = job.get('playback_frame_range')
        if playback is not None:
            if playback[0] != 0 or not 1 < playback[1] < count or curves_before or metadata['notifies']:
                raise RuntimeError('CURVE_ALIGNMENT_PLAYBACK_RANGE_OR_METADATA')
            count = playback[1] + 1
            original = {name: keys[:count] for name, keys in original.items()}
        names = unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)
        stored_curve = next((name for name in names if str(name).casefold() == curve_name.casefold()), None)
        raw_weights = [1.0] * count
        if stored_curve is not None:
            raw_weights = [unreal.AnimationLibrary.get_float_value_at_time(animation, stored_curve, frame * rate.denominator / rate.numerator) for frame in range(count)]
        if any(not math.isfinite(value) for value in raw_weights):
            raise RuntimeError('CURVE_ALIGNMENT_NONFINITE_WEIGHT')
        action_weights = [min(1.0, max(0.0, value)) for value in raw_weights]
        mix_reference = any(weight < 1.0 for weight in action_weights)
        neutral = reference
        neutral_frame = 0
        target_kind = 'common_fal'
        additive = animation.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE
        reference_pose = None
        if not mix_reference:
            neutral = animation
            target_kind = 'authored_unchanged'
        if additive and mix_reference:
            target_kind = 'additive_neutral'
            pose_type = animation.get_editor_property('ref_pose_type')
            neutral_frame = animation.get_editor_property('ref_frame_index')
            neutral = animation.get_editor_property('ref_pose_seq')
            if pose_type == unreal.AdditiveBasePoseType.ABPT_LOCAL_ANIM_FRAME:
                neutral = animation
            if pose_type == unreal.AdditiveBasePoseType.ABPT_REF_POSE:
                neutral = None
                reference_pose = unreal.AnimPoseExtensions.get_reference_pose(animation.get_skeleton())
            if neutral is None and reference_pose is None:
                raise RuntimeError('CURVE_ALIGNMENT_ADDITIVE_REFERENCE_REQUIRED')
        targets = {}
        for name in original:
            if not mix_reference:
                targets[name] = original[name][0]
                continue
            if reference_pose is not None:
                targets[name] = unreal.AnimPoseExtensions.get_bone_pose(reference_pose, name, unreal.AnimPoseSpaces.LOCAL)
                continue
            keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(neutral, name)
            if not keys or not 0 <= neutral_frame < len(keys):
                raise RuntimeError('CURVE_ALIGNMENT_REFERENCE_TRACK: ' + name)
            targets[name] = keys[neutral_frame]
        prepared = {name: [_blend(value, targets[name], 1.0 - action_weights[frame]) for frame, value in enumerate(keys)] for name, keys in original.items()}
        modified = playback is not None or any(weight < 1.0 for weight in action_weights)
        if modified:
            require_asset_write([animation])
            controller = animation.controller
            controller.open_bracket('按左手IK曲线同步原动作与基准姿势', False)
            try:
                if playback is not None:
                    controller.set_number_of_frames(unreal.FrameNumber(value=count - 1), False)
                for name, keys in prepared.items():
                    if not controller.set_bone_track_keys(name, [v.translation for v in keys], [v.rotation for v in keys], [v.scale3d for v in keys], False):
                        raise RuntimeError('CURVE_ALIGNMENT_WRITE_TRACK: ' + name)
            finally:
                controller.close_bracket(False)
        maximum_position = 0.0
        maximum_rotation = 0.0
        full_action_position = 0.0
        full_action_rotation = 0.0
        for name, expected in prepared.items():
            actual = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
            if len(actual) != count:
                raise RuntimeError('CURVE_ALIGNMENT_SAMPLE_COUNT')
            for frame, (a, b) in enumerate(zip(actual, expected)):
                position = (a.translation - b.translation).length()
                left, right = a.rotation.to_tuple(), b.rotation.to_tuple()
                cosine = abs(sum(x*y for x,y in zip(left,right))) / math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
                angle = math.degrees(2 * math.acos(min(1.0, cosine)))
                maximum_position = max(maximum_position, position)
                maximum_rotation = max(maximum_rotation, angle)
                if action_weights[frame] >= 1.0:
                    full_action_position = max(full_action_position, position)
                    full_action_rotation = max(full_action_rotation, angle)
                if position > 0.001 or angle > 0.001 or (a.scale3d-b.scale3d).length() > 0.00001:
                    raise RuntimeError('CURVE_ALIGNMENT_POSE_READBACK: %s:%d' % (name, frame))
        if _curve_values(animation) != curves_before or _animation_metadata(animation) != metadata:
            raise RuntimeError('CURVE_ALIGNMENT_CURVE_OR_METADATA_CHANGED')
        if modified and not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('CURVE_ALIGNMENT_SAVE_FAILED')
        job['aligned_digest'] = _digest(animation)
        job['frames'] = count
        job['length'] = animation.get_play_length()
        job['validation'] = {'mode': 'curve_driven', 'animation': job['animation'], 'curve': str(stored_curve) if stored_curve is not None else None,
            'curve_digest': curve_digest, 'weight_formula': 'reference=1-clamp(curve,0,1); missing_curve=preserve_authored',
            'reference_kind': target_kind, 'reference': neutral.get_path_name().split('.')[0] if neutral is not None else 'skeleton_reference',
            'reference_frame': neutral_frame, 'raw_curve_range': [min(raw_weights), max(raw_weights)],
            'action_weights': action_weights, 'full_action_frames': sum(value >= 1.0 for value in action_weights),
            'pose_position_error_cm': maximum_position, 'pose_rotation_error_degrees': maximum_rotation,
            'full_action_position_error_cm': full_action_position, 'full_action_rotation_error_degrees': full_action_rotation,
            'frames': count, 'bones': len(original), 'curves_and_metadata_preserved': True, 'bone_tracks_rewritten': modified,
            'animation_digest': job['aligned_digest']}
        reports.append(job['validation'])
        _save(path, data)
    data['state'] = 'aligned'
    _save(path, data)
    return {'state': data['state'], 'jobs': reports}


def inspect(recipe_path, write_paths):
    """/** @param recipe_path\t正式重定向源 @param write_paths\t明确输出范围 @return\t保存后首尾轨迹 */"""
    import hashlib
    from BBBManualActionAuthoring import _digest
    from BBBAnimationCurveTools import _curve_values
    _, data = _read(recipe_path, write_paths)
    reports = []
    for job in data['jobs']:
        animation = _asset(job['animation'], unreal.AnimSequence)
        validation = job.get('validation', {})
        curves = _curve_values(animation)
        digest = hashlib.sha256(json.dumps(curves, sort_keys=True).encode()).hexdigest()
        reports.append({'animation': job['animation'], 'saved_digest_matches': _digest(animation) == job.get('aligned_digest', job.get('retarget_digest')),
            'curve_digest_matches': digest == validation.get('curve_digest'), 'validation': validation})
    return {'state': data['state'], 'jobs': reports}


def sync_finger_repair(path, data, sequence):
    """/** @param path\t型号正式源 @param data\t制作要求 @param sequence\t保留人工Offset的序列 @return\t仅同步异常源指节 */"""
    import hashlib
    from BBBManualActionAuthoring import _save as save_manual
    repair_path = Path(unreal.Paths.project_dir()) / data['finger_repair_source']
    source = json.loads(repair_path.read_text(encoding='utf-8-sig'))
    job = next(j for j in source['jobs'] if j['kind'] == data['action'])
    policy = job['finger_repair']
    if not policy.get('applied') or data['finger_animation'] != job['animation']:
        raise RuntimeError('FINGER_SYNC_SOURCE')
    if data.get('finger_repair_applied') == job['aligned_digest']:
        return
    if data['source_track_digest'] != policy['previous_digest']:
        raise RuntimeError('FINGER_SYNC_PREVIOUS_SOURCE')
    edits = {('fk_' + row['bone'] + '.Rotation.Z', key['frame']): key
             for row in policy['tracks'] for key in row['keys']}
    sections = [s for b in sequence.get_bindings() for t in b.get_tracks()
                if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()]
    bases = [s for s in sections if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE]
    if len(bases) != 1:
        raise RuntimeError('FINGER_SYNC_ABSOLUTE_LAYER')
    def digest():
        rows = []
        for section in sections:
            for channel in section.get_all_channels():
                for key in channel.get_keys():
                    time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                    identity = (str(channel.channel_name), time.frame_number.value)
                    if section == bases[0] and identity in edits:
                        continue
                    rows.append([section.get_path_name(), str(channel.channel_name), time.frame_number.value, time.sub_frame, str(key.get_value())])
        return hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    found = {}
    for channel in bases[0].get_all_channels():
        for key in channel.get_keys():
            time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            identity = (str(channel.channel_name), time.frame_number.value)
            if identity in edits:
                expected = edits[identity]['before_yaw']
                if time.sub_frame != 0 or abs((key.get_value() - expected + 180) % 360 - 180) > 0.05:
                    raise RuntimeError('FINGER_SYNC_HAND_EDIT_CONFLICT: ' + str(identity))
                found[identity] = key
    if set(found) != set(edits):
        raise RuntimeError('FINGER_SYNC_KEYS_MISSING')
    preserved = digest()
    require_asset_write([sequence])
    bases[0].set_is_locked(False)
    try:
        for identity, key in found.items():
            key.set_value(edits[identity]['after_yaw'])
        for identity, key in found.items():
            if abs(key.get_value() - edits[identity]['after_yaw']) > 0.001:
                raise RuntimeError('FINGER_SYNC_KEY_READBACK')
    finally:
        bases[0].set_is_locked(True)
    if digest() != preserved:
        raise RuntimeError('FINGER_SYNC_OTHER_KEYS_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('FINGER_SYNC_SAVE')
    data['finger_repair_applied'] = job['aligned_digest']
    data['finger_repair_validation'] = {'changed_keys': len(found), 'other_control_keys_preserved': True, 'offset_keys_preserved': True}
    save_manual(path, data)
