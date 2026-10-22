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


def _metrics(animation, reference, mesh, times):
    """/** @param animation\t待查动作 @param reference\t正确参考 @param mesh\t目标网格 @param times\t采样时间 @return\t腕姿轨迹误差 */"""
    target = _pose(reference, mesh, 0)
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


def capture(recipe_path, write_paths):
    """/** @param recipe_path\t原始动作重定向要求 @param write_paths\t输出包 @return\t新重定向动作与轨迹核对 */"""
    from BBBManualActionAuthoring import _digest
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('RETARGET_ACTION_PIE_FORBIDDEN')
    path, data = _read(recipe_path, write_paths)
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
    from BBBManualActionAuthoring import _digest
    from BBBGenericEditorToolset import _set_flat_cubic_curve
    path, data = _read(recipe_path, write_paths)
    if any(job.get('finger_repair') for job in data['jobs']):
        return {'finger_repairs': [_repair_fingers(path, data, job) for job in data['jobs'] if job.get('finger_repair')]}
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    mesh = _asset(data['target_mesh'], unreal.SkeletalMesh)
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = False
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    reference_pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(reference, 0, options)
    reports = []
    for job in data['jobs']:
        animation = _asset(job['animation'], unreal.AnimSequence)
        require_asset_write([animation])
        if job.get('aligned_digest'):
            if _digest(animation) != job['aligned_digest']:
                raise RuntimeError('RETARGET_ACTION_ALIGNED_ASSET_CHANGED')
            reports.append(job['validation'])
            continue
        if _digest(animation) != job['retarget_digest']:
            raise RuntimeError('RETARGET_ACTION_RAW_ASSET_CHANGED')
        entry_start, entry_end = job['entry_frames']
        exit_start, exit_end = job['exit_frames']
        count = animation.data_model_interface.get_number_of_keys()
        if entry_start != 0 or not entry_start < entry_end < exit_start < exit_end <= count - 1:
            raise RuntimeError('RETARGET_ACTION_ENDPOINT_WINDOWS')
        original = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, n))
                    for n in animation.data_model_interface.get_bone_track_names()}
        values = {}
        for name, transforms in original.items():
            target = unreal.AnimPoseExtensions.get_bone_pose(reference_pose, name, unreal.AnimPoseSpaces.LOCAL)
            keys = []
            for frame, transform in enumerate(transforms):
                weight = 0.0
                if frame < entry_end:
                    progress = frame / entry_end
                    weight = 1 - progress * progress * (3 - 2 * progress)
                if frame > exit_start:
                    progress = min(1.0, (frame - exit_start) / (exit_end - exit_start))
                    weight = progress * progress * (3 - 2 * progress)
                keys.append(_blend(transform, target, weight))
            values[name] = keys
        controller = animation.controller
        controller.open_bracket('新重定向动作首尾衔接正确参考姿势', False)
        try:
            for name, keys in values.items():
                if not controller.set_bone_track_keys(name, [v.translation for v in keys], [v.rotation for v in keys], [v.scale3d for v in keys], False):
                    raise RuntimeError('RETARGET_ACTION_WRITE_BONE: ' + name)
        finally:
            controller.close_bracket(False)
        rate = animation.data_model_interface.get_frame_rate()
        duration = animation.get_play_length()
        for curve in ('DisableLHandIK', 'DisableAimIK', 'DisableLeftHandPoseOverride', 'DisableRightHandPoseOverride'):
            if not unreal.AnimationLibrary.does_curve_exist(animation, curve, unreal.RawCurveTrackTypes.RCT_FLOAT):
                unreal.AnimationLibrary.add_curve(animation, curve, unreal.RawCurveTrackTypes.RCT_FLOAT, False)
            _set_flat_cubic_curve(animation, curve, [{'time': 0.0, 'value': 0.0},
                                                   {'time': entry_end * rate.denominator / rate.numerator, 'value': 1.0},
                                                   {'time': exit_end * rate.denominator / rate.numerator, 'value': 1.0},
                                                   {'time': duration, 'value': 0.0}])
        maximum = 0.0
        for name, before in original.items():
            after = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
            for frame in range(entry_end, exit_start + 1):
                maximum = max(maximum, (before[frame].translation - after[frame].translation).length())
                if maximum > 0.0001 or abs(sum(x * y for x, y in zip(before[frame].rotation.to_tuple(), after[frame].rotation.to_tuple()))) < 0.999999:
                    raise RuntimeError('RETARGET_ACTION_MIDDLE_CHANGED')
        endpoint_error = 0.0
        expected = _pose(reference, mesh, 0)
        for time in (0, duration):
            actual = _pose(animation, mesh, time)
            for bone in original:
                a = unreal.AnimPoseExtensions.get_bone_pose(actual, bone, unreal.AnimPoseSpaces.WORLD)
                b = unreal.AnimPoseExtensions.get_bone_pose(expected, bone, unreal.AnimPoseSpaces.WORLD)
                endpoint_error = max(endpoint_error, (a.translation - b.translation).length())
                if endpoint_error > 0.001 or abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))) < 0.999999:
                    raise RuntimeError('RETARGET_ACTION_ENDPOINT: ' + bone + ' cm=' + str(endpoint_error))
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('RETARGET_ACTION_ALIGNED_SAVE')
        job['aligned_digest'] = _digest(animation)
        job['validation'] = {'animation': job['animation'], 'reference': data['reference_animation'],
                             'endpoint_position_error_cm': endpoint_error, 'middle_position_error_cm': maximum,
                             'entry_frames': job['entry_frames'], 'exit_frames': job['exit_frames'],
                             'stable_tail_frames': count - 1 - exit_end, 'frames': count,
                             'original_source_unchanged': _digest(_asset(job['source'], unreal.AnimSequence)) == job['source_digest']}
        reports.append(job['validation'])
        _save(path, data)
    data['state'] = 'aligned'
    _save(path, data)
    return {'state': data['state'], 'jobs': reports}


def inspect(recipe_path, write_paths):
    """/** @param recipe_path\t正式重定向源 @param write_paths\t明确输出范围 @return\t保存后首尾轨迹 */"""
    from BBBManualActionAuthoring import _digest
    _, data = _read(recipe_path, write_paths)
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    mesh = _asset(data['target_mesh'], unreal.SkeletalMesh)
    return {'state': data['state'], 'jobs': [{'animation': job['animation'],
             'saved_digest_matches': _digest(_asset(job['animation'], unreal.AnimSequence)) == job.get('aligned_digest', job['retarget_digest']),
             'validation': job.get('validation'),
             'finger_entry': _finger_entry(_asset(job['animation'], unreal.AnimSequence), reference),
             'trajectory': _metrics(_asset(job['animation'], unreal.AnimSequence), reference, mesh,
                                    [0, job['exit_frames'][1] / 30, job['length']])} for job in data['jobs']]}


def _finger_entry(animation, reference):
    """/** @param animation\t现有装备动作 @param reference\t握持参考 @return\t手指前段逐帧局部旋转 */"""
    from BBBCommonActionSources import is_finger
    result = []
    neutral = unreal.AnimPoseExtensions.get_reference_pose(animation.get_editor_property('skeleton'))
    for bone in animation.data_model_interface.get_bone_track_names():
        if not is_finger(bone):
            continue
        keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone)
        ref = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(reference, bone)[0]
        samples = []
        for frame in (0, 2, 4, 6, 8, 10, 12, 15, 20, 30, len(keys) - 1):
            value = keys[frame]
            dot = min(1.0, abs(sum(x*y for x,y in zip(value.rotation.to_tuple(), ref.rotation.to_tuple()))))
            samples.append({'frame': frame, 'degrees_from_reference': math.degrees(2*math.acos(dot)),
                            'rotation': value.rotation.rotator().to_tuple(),
                            'named_rotation': {axis: getattr(value.rotation.rotator(), axis) for axis in ('roll', 'pitch', 'yaw')}})
        rest = unreal.AnimPoseExtensions.get_bone_pose(neutral, bone, unreal.AnimPoseSpaces.LOCAL)
        result.append({'bone': str(bone), 'neutral': rest.rotation.rotator().to_tuple(), 'reference': ref.rotation.rotator().to_tuple(), 'max_yaw': max((k.rotation.rotator().yaw, f) for f,k in enumerate(keys)), 'samples': samples})
    return result


def _repair_fingers(path, data, job):
    """/** @param path\t正式源 @param data\t批准的现有装备指节修正 @return\t异常区间及未变骨轨核验 */"""
    from BBBManualActionAuthoring import _digest
    policy = job['finger_repair']
    if not policy.get('approval') or policy.get('mode') != 'bridge_hyperextended_finger_yaw':
        raise RuntimeError('FINGER_REPAIR_APPROVAL')
    animation = _asset(job['animation'], unreal.AnimSequence)
    if policy.get('applied'):
        if _digest(animation) != job['aligned_digest']:
            raise RuntimeError('FINGER_REPAIR_ASSET_CHANGED')
        return policy
    if _digest(animation) != job['aligned_digest']:
        raise RuntimeError('FINGER_REPAIR_SOURCE_CHANGED')
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('FINGER_REPAIR_PIE_FORBIDDEN')
    reference = _asset(data['reference_animation'], unreal.AnimSequence)
    neutral = unreal.AnimPoseExtensions.get_reference_pose(animation.get_editor_property('skeleton'))
    original = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, n))
                for n in animation.data_model_interface.get_bone_track_names()}
    replacements = {}
    reports = []
    for name, keys in original.items():
        if name not in policy['bones']:
            continue
        ref = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(reference, name)[0]
        rest = unreal.AnimPoseExtensions.get_bone_pose(neutral, name, unreal.AnimPoseSpaces.LOCAL)
        limit = max(0.0, rest.rotation.rotator().yaw, ref.rotation.rotator().yaw)
        if policy.get('extension_limit_basis') == 'reference_pose':
            limit = max(0.0, ref.rotation.rotator().yaw)
        flexions = [key.rotation.rotator().yaw for key in keys]
        frame = 1
        changed = []
        ranges = []
        updates = list(keys)
        while frame < job['exit_frames'][1]:
            if flexions[frame] <= limit:
                frame += 1
                continue
            start = frame
            while frame < job['exit_frames'][1] and flexions[frame] > limit:
                frame += 1
            end = frame - 1
            if max(flexions[start:end + 1]) <= limit + float(policy.get('minimum_excess_degrees', 5.0)):
                continue
            left, right = start - 1, frame
            if flexions[right] > limit + 0.01:
                raise RuntimeError('FINGER_REPAIR_NO_SAFE_BOUNDARY: ' + name)
            ranges.append([start, end])
            for f in range(start, end + 1):
                progress = (f - left) / (right - left)
                weight = progress * progress * (3 - 2 * progress)
                flexion = flexions[left] + (flexions[right] - flexions[left]) * weight
                rotation = keys[f].rotation.rotator()
                value = unreal.Transform(location=keys[f].translation, scale=keys[f].scale3d)
                value.rotation = unreal.Rotator(pitch=rotation.pitch, yaw=flexion, roll=rotation.roll).quaternion()
                updates[f] = value
                changed.append({'frame': f, 'before_yaw': flexions[f], 'after_yaw': flexion})
        if changed:
            replacements[name] = updates
            reports.append({'bone': name, 'limit_degrees': limit, 'ranges': ranges, 'keys': changed})
    if not reports:
        raise RuntimeError('FINGER_REPAIR_NO_ANOMALY')
    require_asset_write([animation])
    controller = animation.controller
    controller.open_bracket('修复现有装备动画反向伸展指节', False)
    try:
        for name, keys in replacements.items():
            if not controller.set_bone_track_keys(name, [k.translation for k in keys], [k.rotation for k in keys], [k.scale3d for k in keys], False):
                raise RuntimeError('FINGER_REPAIR_WRITE: ' + name)
    finally:
        controller.close_bracket(False)
    for name, before in original.items():
        after = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
        expected = replacements.get(name, before)
        for f, (a, b) in enumerate(zip(after, expected)):
            if (a.translation - b.translation).length() > 0.0001 or (a.scale3d-b.scale3d).length() > 0.0001 or abs(sum(x*y for x,y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))) < 0.999999:
                raise RuntimeError('FINGER_REPAIR_READBACK: %s:%d' % (name, f))
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('FINGER_REPAIR_SAVE')
    policy.update({'applied': True, 'previous_digest': job['aligned_digest'], 'tracks': reports,
                   'other_tracks_unchanged': True, 'translation_scale_unchanged': True})
    job['aligned_digest'] = _digest(animation)
    job['validation']['finger_entry_repaired'] = True
    _save(path, data)
    return policy


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
