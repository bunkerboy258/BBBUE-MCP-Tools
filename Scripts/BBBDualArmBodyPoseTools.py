"""通过既有Control Rig烘焙人工确认的双臂姿势"""
import hashlib
import json
import math
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _key, _pose, _read_transform, _transform


def _recipe(path):
    project = Path(unreal.Paths.project_dir()).resolve()
    target = (project / path).resolve()
    root = project / 'Content/_Project/Characters/BBBC_UA/Source/Animation'
    if target.parent != root or not target.name.endswith('_BodyPose_Authoring.json.source'):
        raise RuntimeError('BODY_POSE_SOURCE_SCOPE')
    value = json.loads(target.read_text(encoding='utf-8-sig'))
    if value.get('format') != 'BBBDualArmBodyPose' or value.get('schema') != 1:
        raise RuntimeError('BODY_POSE_SOURCE_FORMAT')
    return target, value


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    if json.loads(path.read_text(encoding='utf-8')) != value:
        raise RuntimeError('BODY_POSE_SOURCE_READBACK')


def _scope(paths, expected):
    if set(paths) != set(expected):
        raise RuntimeError('BODY_POSE_WRITE_SCOPE: ' + json.dumps(sorted(expected)))


def _compose(local, parent):
    return unreal.MathLibrary.compose_transforms(local, parent)


def _make(position, rotation, scale):
    value = unreal.Transform(location=position, scale=scale)
    value.rotation = rotation
    return value


def _global_controls(recipe, keys):
    rig = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    result = {}
    for row in keys:
        if row['frame'] != 0:
            continue
        offset = rig.hierarchy.get_global_control_offset_transform(_key(row['control'], 'CONTROL'), True)
        result[row['control']] = _compose(_transform(row['value']), offset)
    if len(result) != 6:
        raise RuntimeError('BODY_POSE_SIX_CONTROLS_REQUIRED')
    return result


def _capture(path, recipe, write_paths):
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as tools
    _scope(write_paths, [recipe['sequence']])
    names = [row['name'] for row in recipe['controls']]
    values = json.loads(tools.sample_sequence_controls(recipe['sequence'], [0], names))
    keys = [dict(row, frame=frame) for row in values for frame in (0, 1)]
    tools.set_sequence_control_local_keys(recipe['sequence'], json.dumps(keys))
    recipe['manual_edit'] = {'approved': True, 'approved_frame': 0, 'local_keys': keys,
                             'approval_note': recipe.get('approval_note', '用户确认样板完成')}
    controls = _global_controls(recipe, keys)
    recipe['approved_controls'] = {name: _read_transform(value) for name, value in controls.items()}
    recipe['status'] = 'manual_pose_approved_pending_background_bake'
    _save(path, recipe)
    return {'status': recipe['status'], 'sequence': recipe['sequence'], 'controls': recipe['approved_controls']}


def _inventory(recipe):
    layer = _asset(recipe['layer_source'], unreal.AnimBlueprint)
    cdo = unreal.get_default_object(layer.generated_class())
    schema = json.loads(unreal.ToolsetLibrary.list_struct_properties(cdo.get_class()))
    references = {}
    def collect(value, spec, label):
        if value is None:
            return
        if isinstance(value, (unreal.AnimSequence, unreal.BlendSpace, unreal.AnimMontage)):
            references[label] = {'asset': value.get_path_name().split('.')[0], 'class': value.get_class().get_name()}
        elif isinstance(spec, dict) and 'properties' in spec:
            for child, child_spec in spec['properties'].items():
                collect(value.get_editor_property(child), child_spec, label + '.' + child)
        elif isinstance(value, (list, unreal.Array)):
            for i, child in enumerate(value):
                collect(child, spec.get('items', {}), label + '.' + str(i))
    fields = schema.get('properties', schema)
    for name, spec in fields.items():
        try:
            value = cdo.get_editor_property(name)
        except Exception:
            continue
        collect(value, spec, name)
    sequences = {}
    for row in references.values():
        asset = unreal.load_asset(row['asset'])
        values = [asset]
        if isinstance(asset, unreal.BlendSpace):
            values = [sample.animation for sample in asset.get_editor_property('sample_data') if sample.animation]
        for animation in values:
            if not isinstance(animation, unreal.AnimSequence):
                continue
            ref = animation.get_editor_property('ref_pose_seq')
            sequences[animation.get_path_name().split('.')[0]] = {
                'keys': animation.data_model_interface.get_number_of_keys(), 'length': animation.get_play_length(),
                'additive': str(animation.get_editor_property('additive_anim_type')), 'reference': ref.get_path_name().split('.')[0] if ref else '',
                'curves': [str(n) for n in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)]}
    return {'layer': recipe['layer_source'], 'references': references, 'sequences': sequences}


def _digest_tracks(animation):
    digest = hashlib.sha256()
    for name in animation.data_model_interface.get_bone_track_names():
        digest.update(str(name).encode())
        for value in unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name):
            digest.update(value.export_text().encode())
    return digest.hexdigest()


def _smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def _weight(job, time, length):
    if job.get('role') != 'action':
        return 1.0
    ending = _smooth((time - max(0.0, length - job.get('exit_seconds', 0.4))) / min(length, job.get('exit_seconds', 0.4)))
    entering = 0.0 if job.get('equip') else 1.0 - _smooth(time / min(length, 0.15))
    return max(entering, ending)


def _solver(recipe):
    blueprint = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    rig = blueprint.create_control_rig()
    rig.request_init()
    # 正式烘焙Rig接收每帧源姿势，不执行静态底稿的BasePose
    if not rig.execute_event('Forwards Solve'):
        raise RuntimeError('BODY_POSE_RIG_INIT_FAILED')
    return rig


def _fit_shoulder(hierarchy, values, side):
    """/** @param hierarchy 骨架 @param values 控制目标 @param side 左右侧 @return 锁骨调整角度 */"""
    name = 'clavicle_' + side
    control = name + '_ctrl'
    original = hierarchy.get_global_transform(_key(name))
    shoulder = hierarchy.get_global_transform(_key('upperarm_' + side))
    elbow = hierarchy.get_global_transform(_key('lowerarm_' + side))
    wrist = hierarchy.get_global_transform(_key('hand_' + side))
    reach = (elbow.translation - shoulder.translation).length() + (wrist.translation - elbow.translation).length() - 0.5
    clavicle = values[control]
    shoulder = _compose(shoulder.make_relative(original), clavicle)
    target = values['hand_' + side + '_ik_ctrl'].translation
    if (target - shoulder.translation).length() <= reach:
        return 0.0
    offset = shoulder.translation - clavicle.translation
    direction = target - clavicle.translation
    first = offset / offset.length()
    second = direction / direction.length()
    dot = max(-1.0, min(1.0, first.x * second.x + first.y * second.y + first.z * second.z))
    axis = unreal.Vector(first.y * second.z - first.z * second.y, first.z * second.x - first.x * second.z, first.x * second.y - first.y * second.x)
    if axis.length() < 0.00001:
        raise RuntimeError('BODY_POSE_SHOULDER_AXIS: ' + side)
    axis = axis / axis.length()
    high = min(math.acos(dot), math.radians(35.0))
    low = 0.0
    for _ in range(26):
        angle = (low + high) * 0.5
        sine = math.sin(angle * 0.5)
        delta = unreal.Quat(axis.x * sine, axis.y * sine, axis.z * sine, math.cos(angle * 0.5))
        location = clavicle.translation + delta.rotate_vector(offset)
        if (target - location).length() > reach:
            low = angle
        if (target - location).length() <= reach:
            high = angle
    sine = math.sin(high * 0.5)
    delta = unreal.Quat(axis.x * sine, axis.y * sine, axis.z * sine, math.cos(high * 0.5))
    if (target - clavicle.translation - delta.rotate_vector(offset)).length() > reach + 0.001:
        raise RuntimeError('BODY_POSE_SHOULDER_LIMIT: ' + side)
    clavicle.rotation = delta * clavicle.rotation
    values[control] = clavicle
    return math.degrees(high)


def _bake(path, recipe, index, write_paths):
    from BBBAnimationTrajectoryTools import _track_metadata
    jobs = recipe.get('bake_jobs', [])
    if not recipe.get('manual_edit', {}).get('approved') or not 0 <= index < len(jobs):
        raise RuntimeError('BODY_POSE_APPROVAL_AND_JOB_REQUIRED')
    job = jobs[index]
    output_path = job['output']
    _scope(write_paths, [output_path])
    source = _asset(job['source'], unreal.AnimSequence)
    if job.get('result'):
        current = _asset(output_path, unreal.AnimSequence)
        if _digest_tracks(current) != job['result']['output_digest']:
            raise RuntimeError('BODY_POSE_OUTPUT_CHANGED_AFTER_BAKE')
        return dict(job['result'], skipped=True)
    if job.get('role') == 'scaled_additive':
        import importlib
        import BBBScaledAdditiveTools
        result = importlib.reload(BBBScaledAdditiveTools).rebuild(source, output_path, job['base_animation'],
            job['source_reference_frame'], job['amplitude'], recipe['mesh'], job.get('rotation_space', 'source'))
        result['output_digest'] = _digest_tracks(_asset(output_path, unreal.AnimSequence))
        job['result'] = result
        _save(path, recipe)
        return result
    count = source.data_model_interface.get_number_of_keys()
    if count < 2 or count > 1200:
        raise RuntimeError('BODY_POSE_FRAME_RANGE')
    mesh = _asset(recipe['mesh'], unreal.SkeletalMesh)
    if source.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise RuntimeError('BODY_POSE_SKELETON_MISMATCH')
    original_digest = _digest_tracks(source)
    metadata = _track_metadata(source)
    model = source.data_model_interface
    rate = model.get_frame_rate()
    source_tracks = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, n))
                     for n in model.get_bone_track_names()}
    if job.get('role') == 'additive':
        return _rebase_additive(path, recipe, job, source, source_tracks, metadata, original_digest, mesh)
    rig = _solver(dict(recipe, rig=recipe['bake_rig']))
    hierarchy = rig.get_hierarchy()
    names = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(_pose(source, mesh, 0.0))]
    base = {n: _transform(v) for n, v in recipe['source_component_pose'].items()}
    approved = {n: _transform(v) for n, v in recipe['approved_controls'].items()}
    target_relative = {n: value.make_relative(base['spine_03']) for n, value in approved.items()}
    reference = _asset(job['reference'], unreal.AnimSequence) if job.get('reference') else source
    reference_time = reference.get_play_length() if job.get('role') == 'action' else 0.0
    reference_pose = _pose(reference, mesh, reference_time)
    reference_body = unreal.AnimPoseExtensions.get_bone_pose(reference_pose, 'spine_03', unreal.AnimPoseSpaces.WORLD)
    reference_controls = {}
    for c, b in [(c['name'], c['bone']) for c in recipe['controls']]:
        reference_controls[c] = unreal.AnimPoseExtensions.get_bone_pose(reference_pose, b, unreal.AnimPoseSpaces.WORLD).make_relative(reference_body)
    grip = approved['hand_l_ik_ctrl'].make_relative(approved['hand_r_ik_ctrl'])
    allowed = {s + '_' + side for side in ('l', 'r') for s in ('clavicle', 'upperarm', 'lowerarm', 'hand')}
    allowed.update(('ik_hand_gun', 'ik_hand_r', 'ik_hand_l'))
    prepared = {name: [] for name in source_tracks if name in allowed}
    worst_reach = 0.0
    maximum_shoulder_fit = 0.0
    for frame in range(count):
        time = min(source.get_play_length(), frame * rate.denominator / rate.numerator)
        pose = _pose(source, mesh, time)
        for name in names:
            hierarchy.set_local_transform(_key(name), unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL))
        body = hierarchy.get_global_transform(_key('spine_03'))
        weight = _weight(job, time, source.get_play_length())
        values = {}
        for row in recipe['controls']:
            name, bone = row['name'], row['bone']
            current = hierarchy.get_global_transform(_key(bone)).make_relative(body)
            ref, target = reference_controls[name], target_relative[name]
            delta = target.rotation * ref.rotation.inversed()
            delta_transform = _make(unreal.Vector(), delta, unreal.Vector(1, 1, 1))
            rotation = unreal.Transform().lerp(delta_transform, weight).rotation * current.rotation
            shifted = _make(current.translation + (target.translation - ref.translation) * weight,
                            rotation, current.scale3d)
            values[name] = _compose(shifted, body)
            motion_scale = job.get('motion_scale', 1.0)
            stable = _compose(target_relative[name], body)
            values[name] = values[name].lerp(stable, (1.0 - motion_scale) * weight)
        # 握持时保持接触，离手时保留源动作轨迹
        disabled = 0.0
        curves = unreal.AnimationLibrary.get_animation_curve_names(source, unreal.RawCurveTrackTypes.RCT_FLOAT)
        if any(str(c) == 'DisableLeftHandIK' for c in curves):
            disabled = unreal.AnimPoseExtensions.get_curve_weight(pose, 'DisableLeftHandIK')
        contact = weight * (1.0 - min(1.0, max(0.0, disabled)))
        held_left = _compose(grip, values['hand_r_ik_ctrl'])
        left = values['hand_l_ik_ctrl']
        values['hand_l_ik_ctrl'] = left.lerp(held_left, contact)
        for side in ('r', 'l'):
            maximum_shoulder_fit = max(maximum_shoulder_fit, _fit_shoulder(hierarchy, values, side))
        for name, value in values.items():
            hierarchy.set_global_transform(_key(name, 'CONTROL'), value)
        if not rig.execute_event('Forwards Solve'):
            raise RuntimeError('BODY_POSE_RIG_EVALUATION_FAILED')
        for side in ('l', 'r'):
            actual = hierarchy.get_global_transform(_key('hand_' + side))
            error = (actual.translation - values['hand_' + side + '_ik_ctrl'].translation).length()
            worst_reach = max(worst_reach, error)
            if error > job.get('maximum_reach_error_cm', 0.05):
                raise RuntimeError('BODY_POSE_UNREACHABLE: %s frame=%d side=%s error=%f' % (job['source'], frame, side, error))
        for name in prepared:
            value = hierarchy.get_local_transform(_key(name))
            # 保留骨长及缩放，仅辅助骨和明确锁骨允许改变平移
            if name not in ('clavicle_l', 'clavicle_r', 'ik_hand_gun', 'ik_hand_r', 'ik_hand_l'):
                value.translation = source_tracks[name][frame].translation
                value.scale3d = source_tracks[name][frame].scale3d
            prepared[name].append(value)
    if output_path == job['source']:
        animation = source
        require_asset_write([animation])
    else:
        if unreal.EditorAssetLibrary.does_asset_exist(output_path):
            animation = _asset(output_path, unreal.AnimSequence)
            if animation.data_model_interface.get_bone_track_names() or _track_metadata(animation) != metadata:
                raise RuntimeError('BODY_POSE_OUTPUT_ALREADY_EXISTS')
            from BBBAnimationPoseRecovery import restore_animation_bone_tracks
            restore_animation_bone_tracks(job['source'], output_path)
        if not unreal.EditorAssetLibrary.does_asset_exist(output_path):
            require_asset_write([], destinations=[output_path])
            animation = unreal.EditorAssetLibrary.duplicate_asset(job['source'], output_path)
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError('BODY_POSE_DUPLICATE_FAILED')
        if source.get_editor_property('ref_pose_seq') == source:
            animation.set_editor_property('ref_pose_seq', animation)
    controller = animation.controller
    controller.open_bracket('Bake approved dual arm Control Rig motion', False)
    try:
        for name, transforms in prepared.items():
            if not controller.set_bone_track_keys(name, [t.translation for t in transforms], [t.rotation for t in transforms], [t.scale3d for t in transforms], False):
                raise RuntimeError('BODY_POSE_SET_TRACK_FAILED: ' + name)
    finally:
        controller.close_bracket(False)
    if _track_metadata(animation) != metadata:
        raise RuntimeError('BODY_POSE_METADATA_CHANGED')
    for name, original in source_tracks.items():
        expected = prepared.get(name, original)
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
        if len(actual) != count:
            raise RuntimeError('BODY_POSE_READBACK_COUNT')
        for a, b in zip(actual, expected):
            if (a.translation - b.translation).length() > 0.001 or (a.scale3d - b.scale3d).length() > 0.001 or abs(abs((a.rotation * b.rotation.inversed()).w) - 1.0) > 1e-5:
                raise RuntimeError('BODY_POSE_READBACK_CHANGED: ' + name)
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('BODY_POSE_SAVE_FAILED')
    result = {'source': job['source'], 'animation': output_path, 'frames': count,
              'maximum_target_error_cm': worst_reach, 'input_digest': original_digest,
              'maximum_shoulder_fit_degrees': maximum_shoulder_fit,
              'source_arm_motion_scale': job.get('motion_scale', 1.0),
              'output_digest': _digest_tracks(animation), 'metadata_preserved': True,
              'unmodified_tracks_preserved': True, 'runtimeAcceptance': 'pending'}
    job['result'] = result
    _save(path, recipe)
    unreal.log('[BBBDualArmBake] ' + json.dumps(result))
    return result


def _rebase_additive(path, recipe, job, source, tracks, metadata, original_digest, mesh):
    """/** @param path 制作源 @param recipe 制作数据 @param job 加法任务 @param source 动画 @param tracks 原轨道 @param metadata 元数据 @param original_digest 摘要 @param mesh 网格 @return 保持局部加法差值的结果 */"""
    from BBBAnimationTrajectoryTools import _track_metadata
    if source.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE:
        raise RuntimeError('BODY_POSE_LOCAL_ADDITIVE_REQUIRED')
    base_animation = _asset(job['base_animation'], unreal.AnimSequence)
    time = base_animation.get_play_length() if job.get('base_end') else 0.0
    pose = _pose(base_animation, mesh, time)
    old_frame = source.get_editor_property('ref_frame_index') if job.get('base_end') else 0
    prepared = {}
    for name, values in tracks.items():
        old = values[min(old_frame, len(values) - 1)]
        new = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)
        prepared[name] = [_make(new.translation + value.translation - old.translation,
                               (value.rotation * old.rotation.inversed()) * new.rotation,
                               unreal.Vector(new.scale3d.x * value.scale3d.x / old.scale3d.x,
                                             new.scale3d.y * value.scale3d.y / old.scale3d.y,
                                             new.scale3d.z * value.scale3d.z / old.scale3d.z)) for value in values]
    require_asset_write([source])
    source.controller.open_bracket('Rebase approved body pose additive motion', False)
    try:
        for name, values in prepared.items():
            if not source.controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                raise RuntimeError('BODY_POSE_ADDITIVE_TRACK_WRITE: ' + name)
    finally:
        source.controller.close_bracket(False)
    if job.get('replace_reference'):
        source.set_editor_property('ref_pose_seq', base_animation)
        metadata['reference'] = base_animation.get_path_name()
    if _track_metadata(source) != metadata:
        raise RuntimeError('BODY_POSE_ADDITIVE_METADATA_CHANGED')
    for name, expected in prepared.items():
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, name)
        for value, target in zip(actual, expected):
            if (value.translation - target.translation).length() > 0.001 or abs((value.rotation * target.rotation.inversed()).w) < 0.99999:
                raise RuntimeError('BODY_POSE_ADDITIVE_READBACK: ' + name)
    if not unreal.EditorAssetLibrary.save_loaded_asset(source, False):
        raise RuntimeError('BODY_POSE_ADDITIVE_SAVE')
    result = {'animation': job['output'], 'source': job['source'], 'frames': len(next(iter(tracks.values()))),
              'input_digest': original_digest, 'output_digest': _digest_tracks(source), 'additive_deltas_preserved': True,
              'metadata_preserved': True, 'runtimeAcceptance': 'pending'}
    job['result'] = result
    _save(path, recipe)
    return result


def _replace_nested(owner, parts, replacement):
    """/** @param owner 属性所有者 @param parts 属性路径 @param replacement 动画 @return 更新后的属性值 */"""
    name = parts[0]
    if isinstance(owner, (list, unreal.Array)):
        index = int(name)
        value = replacement if len(parts) == 1 else _replace_nested(owner[index], parts[1:], replacement)
        owner[index] = value
        return owner
    value = replacement if len(parts) == 1 else _replace_nested(owner.get_editor_property(name), parts[1:], replacement)
    owner.set_editor_property(name, value)
    return owner


def _sync_grip(recipe, grip, grip_path):
    """/** @param recipe 身体制作源 @param grip 握姿制作源 @param grip_path 正式路径 @return 同步后的制作指纹 */"""
    from BBBGripManualAuthoring import _pose as grip_pose, _pin
    from BBBGripAuthoringToolset import _values, _inputs, _fingerprint, _write_recipe
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring
    project = Path(unreal.Paths.project_dir()).resolve()
    mesh = _asset(grip['character_mesh'], unreal.SkeletalMesh)
    names = list(grip['solution']['component_pose'])
    pose = grip_pose(_asset(grip['animation'], unreal.AnimSequence), names, mesh)
    rig = _asset(grip['rig'], unreal.ControlRigBlueprint)
    sequence = _asset(grip['sequence'], unreal.LevelSequence)
    require_asset_write([rig, sequence])
    controller = rig.get_controller()
    transforms = '(' + ','.join(_pin(pose[name]['component']) for name in names) + ')'
    if not controller.set_pin_default_value('BasePose.Transforms', transforms, True, False, False, False):
        raise RuntimeError('BODY_POSE_GRIP_BASE_SYNC')
    manual = grip['manual_edit']
    for name in manual['controls']:
        bone = name.removeprefix('fk_')
        transform = pose.get(bone, pose['hand_l'])['local']
        if name in ('hand_l_ik_ctrl', 'elbow_l_pv_ctrl'):
            bone = {'hand_l_ik_ctrl': 'hand_l', 'elbow_l_pv_ctrl': 'lowerarm_l'}[name]
            transform = pose[bone]['component']
        key = _key(name, 'CONTROL')
        rig.hierarchy.set_control_offset_transform(key, transform, True)
        rig.hierarchy.set_control_offset_transform(key, transform, False)
    rig.recompile_vm()
    if not unreal.EditorAssetLibrary.save_loaded_asset(rig, False):
        raise RuntimeError('BODY_POSE_GRIP_RIG_SAVE')
    keys = [{'control': name, 'frame': frame, 'value': {'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}}
            for name in manual['controls'] for frame in (0, 1)]
    authoring.set_sequence_control_local_keys(grip['sequence'], json.dumps(keys))
    instance = _solver({'rig': grip['rig']})
    for name in names:
        actual = instance.get_hierarchy().get_local_transform(_key(name))
        expected = pose[name]['local']
        if (actual.translation - expected.translation).length() > 0.02 or abs((actual.rotation * expected.rotation.inversed()).w) < 0.99999:
            raise RuntimeError('BODY_POSE_GRIP_DRAFT_MISMATCH: ' + name)
    manual['frozen_right_arm'] = {name: _values(pose[name]['local']) for name in ('upperarm_r', 'lowerarm_r')}
    manual['initial_right_wrist'] = _values(pose['hand_r']['local'])
    manual['body_pose_source'] = recipe['sequence']
    manual['definitionApplied'] = True
    grip['solution']['calibration'] = grip['calibration']
    grip['solution']['local_pose'] = {name: _values(pose[name]['local']) for name in names}
    grip['solution']['component_pose'] = {name: _values(pose[name]['component']) for name in names}
    inputs = _inputs(grip, project)
    grip['solution']['inputs'] = inputs
    grip['solution']['input_digest'] = inputs['digest']
    grip['validation'] = {'passed': True, 'fingerprint': _fingerprint(grip, project),
                          'scope': 'approved_dual_arm_bake_and_offsets', 'geometryProven': False}
    _write_recipe(grip_path, grip, project)
    return grip['validation']['fingerprint']


def _finalize(path, recipe, write_paths):
    """/** @param path 制作源路径 @param recipe 制作数据 @param write_paths 明确范围 @return 正式引用与静态核验 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    grip_path = project / recipe['grip_recipe']
    grip = json.loads(grip_path.read_text(encoding='utf-8-sig'))
    _scope(write_paths, [recipe['definition'], recipe['layer_target'], grip['rig'], grip['sequence']])
    for job in recipe['bake_jobs']:
        if not job.get('result') or _digest_tracks(_asset(job['output'], unreal.AnimSequence)) != job['result']['output_digest']:
            raise RuntimeError('BODY_POSE_INCOMPLETE_OR_CHANGED: ' + job['output'])
    mesh = _asset(recipe['mesh'], unreal.SkeletalMesh)
    base = {n: _transform(v) for n, v in recipe['source_component_pose'].items()}
    approved = {n: _transform(v) for n, v in recipe['approved_controls'].items()}
    endpoint_errors = {}
    for job in recipe['bake_jobs']:
        if job.get('role') != 'action':
            continue
        animation = _asset(job['output'], unreal.AnimSequence)
        pose = _pose(animation, mesh, animation.get_play_length())
        spine = unreal.AnimPoseExtensions.get_bone_pose(pose, 'spine_03', unreal.AnimPoseSpaces.WORLD)
        errors = {}
        for side in ('l', 'r'):
            actual = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_' + side, unreal.AnimPoseSpaces.WORLD).make_relative(spine)
            target = approved['hand_' + side + '_ik_ctrl'].make_relative(base['spine_03'])
            position = (actual.translation - target.translation).length()
            angle = math.degrees(2 * math.acos(min(1.0, abs((actual.rotation * target.rotation.inversed()).w))))
            errors[side] = {'position_cm': position, 'rotation_degrees': angle}
            if position > 0.02 or angle > 0.05:
                raise RuntimeError('BODY_POSE_ACTION_END_MISMATCH: ' + job['output'] + str(errors))
        endpoint_errors[job['output']] = errors
    layer = _asset(recipe['layer_target'], unreal.AnimBlueprint)
    definition = unreal.load_asset(recipe['definition'])
    require_asset_write([definition, layer])
    replacements = {job['source']: job['output'] for job in recipe['bake_jobs']}
    cdo = unreal.get_default_object(layer.generated_class())
    for field, row in recipe['inventory']['references'].items():
        if row['asset'] in replacements and replacements[row['asset']] != row['asset']:
            _replace_nested(cdo, field.split('.'), _asset(replacements[row['asset']], unreal.AnimSequence))
    unreal.BlueprintEditorLibrary.compile_blueprint(layer)
    if layer.get_editor_property('status') == unreal.BlueprintStatus.BS_ERROR:
        raise RuntimeError('BODY_POSE_LAYER_COMPILE')
    if not unreal.EditorAssetLibrary.save_loaded_asset(layer, False):
        raise RuntimeError('BODY_POSE_LAYER_SAVE')
    actual_refs = _inventory(dict(recipe, layer_source=recipe['layer_target']))['references']
    for field, row in recipe['inventory']['references'].items():
        if actual_refs[field]['asset'] != replacements.get(row['asset'], row['asset']):
            raise RuntimeError('BODY_POSE_LAYER_REFERENCE: ' + field)
    if 'runtime_configuration' not in recipe:
        old = base['hand_l'].make_relative(base['hand_r'])
        current_offset = definition.get_editor_property('left_hand_ik_offset')
        current_rotation = definition.get_editor_property('left_hand_ik_rotation').quaternion()
        if (current_offset - unreal.Vector(*grip['calibration']['left_ik_offset'])).length() > 0.001:
            raise RuntimeError('BODY_POSE_CONFIG_CHANGED')
        socket_position = old.translation - current_offset
        socket_rotation = old.rotation * current_rotation.inversed()
        target = approved['hand_l_ik_ctrl'].make_relative(approved['hand_r_ik_ctrl'])
        recipe['runtime_configuration'] = {'left_ik_offset': list((target.translation - socket_position).to_tuple()),
                                            'left_ik_rotation': list((socket_rotation.inversed() * target.rotation).normalized().to_tuple()),
                                            'spawn_offset': list(grip['calibration']['spawn_offset'])}
        _save(path, recipe)
    config = recipe['runtime_configuration']
    definition.set_editor_property('left_hand_ik_offset', unreal.Vector(*config['left_ik_offset']))
    definition.set_editor_property('left_hand_ik_rotation', unreal.Quat(*config['left_ik_rotation']).rotator())
    definition.set_editor_property('character_animation_layer_class', layer.generated_class())
    if not unreal.EditorAssetLibrary.save_loaded_asset(definition, False):
        raise RuntimeError('BODY_POSE_DEFINITION_SAVE')
    if (definition.get_editor_property('left_hand_ik_offset') - unreal.Vector(*config['left_ik_offset'])).length() > 0.001:
        raise RuntimeError('BODY_POSE_DEFINITION_READBACK')
    if definition.get_editor_property('character_animation_layer_class') != layer.generated_class():
        raise RuntimeError('BODY_POSE_LAYER_CLASS_READBACK')
    grip['calibration']['left_ik_offset'] = config['left_ik_offset']
    grip['calibration']['left_ik_rotation'] = config['left_ik_rotation']
    fingerprint = _sync_grip(recipe, grip, grip_path)
    recipe['status'] = 'baked_applied_static_verified'
    recipe['runtime_applied'] = True
    recipe['validation'] = {'layer_references': len(actual_refs), 'action_endpoint_errors': endpoint_errors,
                             'grip_fingerprint': fingerprint, 'runtimeAcceptance': 'pending_user_pie'}
    _save(path, recipe)
    return {'status': recipe['status'], 'definition': recipe['definition'], 'layer': recipe['layer_target'],
            'animations': len(recipe['bake_jobs']), 'configuration': config, 'validation': recipe['validation']}


def process(recipe_path, action, write_paths, job_index):
    if recipe_path.endswith('_GripMargin.json.source'):
        import importlib
        import BBBGripMarginTools
        return importlib.reload(BBBGripMarginTools).process(recipe_path, action, write_paths, job_index)
    if recipe_path.endswith('_AnimationMetadata.json.source'):
        import importlib
        import BBBAnimationMetadataRecovery
        return importlib.reload(BBBAnimationMetadataRecovery).process(recipe_path, action, write_paths, job_index)
    if recipe_path.endswith('_LeftHandMotion.json.source'):
        import importlib
        import BBBLeftHandMotionCalibration
        return importlib.reload(BBBLeftHandMotionCalibration).run(recipe_path, action, write_paths, job_index)
    if recipe_path.endswith('_RetargetActions.json.source'):
        import importlib
        import BBBActionRetargetTools
        importlib.reload(BBBActionRetargetTools)
        if action == 'capture':
            return BBBActionRetargetTools.capture(recipe_path, write_paths)
        if action == 'finalize':
            return BBBActionRetargetTools.finalize(recipe_path, write_paths)
        if action == 'inspect':
            return BBBActionRetargetTools.inspect(recipe_path, write_paths)
        raise RuntimeError('RETARGET_ACTION_REQUIRED')
    if recipe_path.endswith('CommonActionBaselines.json.source'):
        import importlib
        import BBBCommonActionSources
        importlib.reload(BBBCommonActionSources)
        if action == 'capture':
            return BBBCommonActionSources.build(recipe_path, write_paths)
        if action == 'inspect':
            return BBBCommonActionSources.inspect_catalog(recipe_path, write_paths)
        if action == 'finalize':
            return BBBCommonActionSources.adopt_saved(recipe_path, write_paths)
        raise RuntimeError('COMMON_ACTION_CAPTURE_REQUIRED')
    if action == 'bake' and recipe_path.endswith('_ManualAction.json.source'):
        import importlib
        import BBBManualActionAuthoring
        importlib.reload(BBBManualActionAuthoring)
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        return BBBManualActionNative.bake_animation(recipe_path, write_paths)
    if action == 'inspect' and recipe_path.endswith('_ManualAction.json.source'):
        import importlib
        import BBBManualActionAuthoring
        importlib.reload(BBBManualActionAuthoring)
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        return BBBManualActionNative.inspect_manual(recipe_path, write_paths)
    if action == 'prepare_action':
        import importlib
        import BBBManualActionAuthoring
        importlib.reload(BBBManualActionAuthoring)
        return BBBManualActionAuthoring.prepare(recipe_path, write_paths)
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('BODY_POSE_PIE_FORBIDDEN')
    path, recipe = _recipe(recipe_path)
    if action == 'capture':
        return _capture(path, recipe, write_paths)
    if action == 'inspect':
        _scope(write_paths, [recipe['rig']])
        return _inventory(recipe)
    if action == 'finalize':
        return _finalize(path, recipe, write_paths)
    if action == 'bake':
        for attempt in range(21):
            try:
                return _bake(path, recipe, job_index, write_paths)
            except RuntimeError as error:
                if 'BODY_POSE_SHOULDER_LIMIT' not in str(error) or attempt == 20:
                    raise
                job = recipe['bake_jobs'][job_index]
                job['motion_scale'] = job.get('motion_scale', 1.0) * 0.85
                unreal.log_warning('[BBBDualArmBake] 统一收敛整段上臂摆幅以保持骨长和握持: ' + str(job['motion_scale']))
    raise RuntimeError('BODY_POSE_ACTION_REQUIRED: capture inspect bake')
