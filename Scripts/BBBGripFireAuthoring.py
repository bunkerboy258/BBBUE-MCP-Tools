import copy
import hashlib

import unreal

from BBBAssetWritePolicy import require_asset_write


def hold_signature(recipe, project):
    """/** @param recipe 未开火制作源 @param project 项目根 @return 正式未开火姿势与标定摘要 */"""
    from BBBGripAuthoringToolset import _definition, _digest

    animation = project / 'Content' / (recipe['animation'].removeprefix('/Game/') + '.uasset')
    _, calibration = _definition(recipe)
    return _digest({'animation': recipe['animation'], 'bytes': hashlib.sha256(animation.read_bytes()).hexdigest(),
                    'calibration': calibration})


def prepare(hold, hold_path, project):
    """/** @param hold 未开火制作源 @param hold_path 未开火制作路径 @param project 项目根 @return 从已应用未开火结果打开开火手指制作 不应用运行配置 */"""
    from BBBGripAuthoringToolset import _fingerprint, _recipe, _write_recipe

    if hold.get('grip_role') == 'fire':
        raise RuntimeError('FIRE_GRIP_REQUIRES_HOLD_RECIPE: 请提供未开火制作源')
    if not hold.get('manual_edit', {}).get('definitionApplied') or hold.get('validation', {}).get('fingerprint') != _fingerprint(hold, project):
        raise RuntimeError('FIRE_GRIP_REQUIRES_HOLD_APPLY: 先应用本枪当前未开火握姿')
    fire_path = hold_path.with_name(hold_path.name.replace('_HandGrip_', '_FireGrip_'))
    if fire_path == hold_path:
        raise RuntimeError('FIRE_GRIP_RECIPE_NAME_REQUIRED')
    signature = hold_signature(hold, project)
    if hold.get('rebase_fire_request'):
        return _rebase(hold, hold_path, fire_path, project, signature)
    if fire_path.exists():
        recipe = _recipe(fire_path, hold['weapon_root'])
        if recipe.get('hold_signature') != signature:
            raise RuntimeError('FIRE_GRIP_BASE_CHANGED: 未开火基准已变更 请明确要求重新建立开火底稿 现有手工内容保留')
        return _open(recipe, fire_path, project, hold['animation'])
    recipe = copy.deepcopy(hold)
    recipe['grip_role'] = 'fire'
    recipe['hold_recipe'] = str(hold_path.relative_to(project)).replace('\\', '/')
    recipe['hold_signature'] = signature
    for field in ('rig', 'sequence', 'animation'):
        recipe[field] = hold[field].replace('_HandGrip', '_FireGrip')
        if recipe[field] == hold[field] or unreal.EditorAssetLibrary.does_asset_exist(recipe[field]):
            raise RuntimeError('FIRE_GRIP_DESTINATION_EXISTS: ' + recipe[field])
    for field in ('manual_edit', 'validation', 'review'):
        recipe.pop(field, None)
    require_asset_write([], [recipe[field] for field in ('rig', 'sequence', 'animation')])
    for field in ('rig', 'sequence', 'animation'):
        folder, name = recipe[field].rsplit('/', 1)
        source = unreal.load_asset(hold[field])
        created = unreal.AssetToolsHelpers.get_asset_tools().duplicate_asset(name, folder, source)
        if created is None or not unreal.EditorAssetLibrary.save_loaded_asset(created, False):
            raise RuntimeError('FIRE_GRIP_CREATE_FAILED: ' + recipe[field])
    _write_recipe(fire_path, recipe, project)
    return _open(recipe, fire_path, project, hold['animation'])


def _rebase(hold, hold_path, fire_path, project, signature):
    """/** @param hold 已应用未开火制作源 @param hold_path 未开火路径 @param fire_path 开火路径 @param project 项目根 @param signature 新基准摘要 @return 保留开火右食指并同步新握姿和挂接的底稿 */"""
    import json
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _asset, _recipe, _write_recipe, _FINGERS, _values
    from BBBAnimationTrajectoryTools import replace_tracks
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

    fire = _recipe(fire_path, hold['weapon_root'])
    mesh = _asset(hold['character_mesh'], unreal.SkeletalMesh)
    animation = _asset(fire['animation'], unreal.AnimSequence)
    names = list(hold['solution']['local_pose'])
    pose = manual._pose(animation, names, mesh)
    # 同步新握姿 保留原开火右食指的扳机姿势
    preserved = set(_FINGERS)
    count = animation.data_model_interface.get_number_of_keys()
    tracks = {}
    for name in animation.data_model_interface.get_bone_track_names():
        name = str(name)
        if name in preserved or name not in hold['solution']['local_pose']:
            continue
        value = hold['solution']['local_pose'][name]
        tracks[name] = [{'position': value[:3], 'rotation': value[3:7], 'scale': value[7:10]}] * count
    replace_tracks(fire['animation'], json.dumps(tracks))
    fire['calibration'] = copy.deepcopy(hold['calibration'])
    fire['solution'] = copy.deepcopy(hold['solution'])
    fire['hold_signature'] = signature
    fire.pop('manual_edit', None)
    fire.pop('validation', None)
    fire.pop('review', None)
    _write_recipe(fire_path, fire, project)
    result = _open(fire, fire_path, project, hold['animation'])
    sequence = _asset(fire['sequence'], unreal.LevelSequence)
    bindings = [b for b in sequence.get_bindings() if isinstance(b.get_object_template(), unreal.SkeletalMeshActor)
                and b.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == _asset(fire['weapon_mesh'], unreal.SkeletalMesh)]
    if len(bindings) != 1:
        raise RuntimeError('FIRE_REBASE_WEAPON_NOT_UNIQUE')
    value = hold['calibration']['spawn_offset']
    authoring.set_sequence_attachment_transform(fire['sequence'], bindings[0].get_name(), json.dumps(
        {'position': value[:3], 'rotation': value[3:7], 'scale': value[7:10]}))
    unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    actual = manual._pose(animation, list(_FINGERS), mesh)
    for name in preserved:
        if _values(actual[name]['local']) != _values(pose[name]['local']):
            raise RuntimeError('FIRE_REBASE_FINGERS_CHANGED: ' + name)
    hold.pop('rebase_fire_request')
    _write_recipe(hold_path, hold, project)
    result.update({'rebased': True, 'fireRightIndexPreserved': True, 'attachmentSynchronized': True})
    return result


def _open(recipe, fire_path, project, seed):
    """/** @param recipe 开火制作源 @param fire_path 制作路径 @param project 项目根 @param seed 未开火输入 @return 仅显示手指的实际制作序列 */"""
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _asset

    result = manual.prepare(recipe, fire_path, project)
    asset = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    hierarchies = [asset.hierarchy, manual._instance(sequence).get_hierarchy()]
    for hierarchy in hierarchies:
        for name in ('fk_hand_r', 'hand_l_ik_ctrl', 'elbow_l_pv_ctrl'):
            key = manual._key(name, 'CONTROL')
            settings = hierarchy.get_control_settings(key)
            settings.shape_visible = True
            hierarchy.set_control_settings(key, settings, False, True, False)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    result.update({'gripRole': 'fire', 'recipe': str(fire_path.relative_to(project)).replace('\\', '/'),
                   'seed': seed, 'calibrationShared': True, 'next': 'manual_apply_fire'})
    return result


def apply(hold, hold_path, project):
    """/** @param hold 未开火制作源 @param hold_path 未开火制作路径 @param project 项目根 @return 应用当前开火底稿 只写手指握姿引用 */"""
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _recipe

    fire_path = hold_path.with_name(hold_path.name.replace('_HandGrip_', '_FireGrip_'))
    if not fire_path.is_file():
        raise RuntimeError('FIRE_GRIP_PREPARE_REQUIRED')
    recipe = _recipe(fire_path, hold['weapon_root'])
    if hold.get('share_fire_attachment_request'):
        return _share_attachment(hold, hold_path, recipe, fire_path, project)
    if recipe.get('hold_signature') != hold_signature(hold, project):
        raise RuntimeError('FIRE_GRIP_BASE_CHANGED: 禁止应用基于旧未开火握姿的开火底稿')
    return manual.apply(recipe, fire_path, project)


def _share_attachment(hold, hold_path, fire, fire_path, project):
    """Explicitly promote the edited fire attachment to the shared hold calibration, retaining finger keys."""
    import json
    import BBBGripManualAuthoring as manual
    from BBBGripAuthoringToolset import _asset, _write_recipe
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring
    from BBBManualActionNative import _channel_digest

    pending = hold.get('shared_fire_attachment')
    sequence = _asset(fire['sequence'], unreal.LevelSequence)
    if pending:
        if _channel_digest(sequence) != pending['fire_channel_digest']:
            raise RuntimeError('SHARED_FIRE_CONTENT_CHANGED')
        from BBBGripAuthoringToolset import _definition, _transform, _values, _socket, _apply_definition, _fingerprint, _inputs
        definition, current = _definition(hold)
        old_spawn = _transform(current['spawn_offset'])
        requested = pending['transform']
        new_spawn = _transform(requested['position'] + requested['rotation'] + requested['scale'])
        if abs((old_spawn.rotation * new_spawn.rotation.inversed()).w) < 0.999999 or (old_spawn.scale3d - new_spawn.scale3d).length() > 0.00001:
            raise RuntimeError('SHARED_FIRE_TRANSLATION_ONLY: 旋转或缩放变更须回未开火阶段')
        attachment = _transform(_socket(_asset(hold['character_mesh'], unreal.SkeletalMesh), hold['attachment_socket'])['local'])
        displacement = attachment.rotation.rotate_vector(new_spawn.translation - old_spawn.translation)
        calibration = copy.deepcopy(hold['solution']['calibration'])
        calibration['spawn_offset'] = _values(new_spawn)
        calibration['left_ik_offset'] = list((unreal.Vector(*current['left_ik_offset']) - displacement).to_tuple())
        hold['calibration'] = calibration
        hold['solution']['calibration'] = calibration
        require_asset_write([definition])
        _apply_definition(hold)
        hold['solution']['inputs'] = _inputs(hold, project)
        hold['solution']['input_digest'] = hold['solution']['inputs']['digest']
        hold['validation']['fingerprint'] = _fingerprint(hold, project)
        result = {'status': 'shared_attachment_applied_without_pose_rebake'}
        fire['hold_signature'] = hold_signature(hold, project)
        fire['shared_attachment_adopted'] = {'transform': pending['transform'],
            'fire_keys_preserved': True, 'hold_applied': result['status']}
        hold.pop('share_fire_attachment_request')
        hold.pop('shared_fire_attachment')
        _write_recipe(hold_path, hold, project)
        _write_recipe(fire_path, fire, project)
        manual.prepare(fire, fire_path, project)
        return {'status': 'shared_attachment_hold_applied', 'next': 'manual_apply_fire',
                'fire_keys_preserved': True, 'sequence': fire['sequence']}
    if fire.get('hold_signature') != hold_signature(hold, project):
        raise RuntimeError('FIRE_GRIP_BASE_CHANGED')
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    preserved = _channel_digest(sequence)
    bindings = [b for b in sequence.get_bindings() if isinstance(b.get_object_template(), unreal.SkeletalMeshActor)
                and b.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == _asset(fire['weapon_mesh'], unreal.SkeletalMesh)]
    if len(bindings) != 1:
        raise RuntimeError('SHARED_FIRE_ATTACHMENT_WEAPON_NOT_UNIQUE')
    tracks = bindings[0].find_tracks_by_type(unreal.MovieScene3DTransformTrack)
    if len(tracks) != 1 or len(tracks[0].get_sections()) != 1:
        raise RuntimeError('SHARED_FIRE_ATTACHMENT_TRACK')
    numbers = []
    for channel in tracks[0].get_sections()[0].get_all_channels():
        value = float(channel.get_default())
        if channel.get_keys():
            bounds = channel.compute_effective_range()
            bounds.set_start_seconds(0)
            rate = sequence.get_display_rate()
            bounds.set_end_seconds(rate.denominator / rate.numerator)
            samples = channel.evaluate_keys(bounds, rate)
            if not samples:
                raise RuntimeError('SHARED_FIRE_ATTACHMENT_EVALUATION')
            value = float(samples[0])
        numbers.append(value)
    spawn = unreal.Transform(location=unreal.Vector(*numbers[:3]),
        rotation=unreal.Rotator(roll=numbers[3], pitch=numbers[4], yaw=numbers[5]),
        scale=unreal.Vector(*numbers[6:9]))
    transform = {'position': list(spawn.translation.to_tuple()), 'rotation': list(spawn.rotation.to_tuple()),
                 'scale': list(spawn.scale3d.to_tuple())}
    manual.prepare(hold, hold_path, project)
    hold_sequence = _asset(hold['sequence'], unreal.LevelSequence)
    hold_bindings = [b for b in hold_sequence.get_bindings() if isinstance(b.get_object_template(), unreal.SkeletalMeshActor)
                     and b.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == _asset(hold['weapon_mesh'], unreal.SkeletalMesh)]
    if len(hold_bindings) != 1:
        raise RuntimeError('SHARED_FIRE_HOLD_WEAPON_NOT_UNIQUE')
    authoring.set_sequence_attachment_transform(hold['sequence'], hold_bindings[0].get_name(), json.dumps(transform))
    if _channel_digest(sequence) != preserved:
        raise RuntimeError('SHARED_FIRE_FINGER_KEYS_CHANGED')
    hold['shared_fire_attachment'] = {'transform': transform, 'fire_channel_digest': preserved}
    _write_recipe(hold_path, hold, project)
    return {'status': 'shared_attachment_hold_ready', 'next': 'manual_apply_fire',
            'fire_keys_preserved': True, 'sequence': hold['sequence']}
