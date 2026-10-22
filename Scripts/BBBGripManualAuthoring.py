import json
import uuid

import unreal

from BBBAssetWritePolicy import require_asset_write


def _key(name, kind='BONE'):
    """/** @param name 元素名 @param kind 元素类型 @return 官方层级键 */"""
    return unreal.RigElementKey(type=getattr(unreal.RigElementType, kind), name=name)


def _pose(animation, names, mesh):
    """/** @param animation 正式握姿 @param names 骨名 @return 局部和组件姿势 */"""
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = True
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, 0.0, options)
    return {name: {space: unreal.AnimPoseExtensions.get_bone_pose(pose, name, mode)
                   for space, mode in [('local', unreal.AnimPoseSpaces.LOCAL), ('component', unreal.AnimPoseSpaces.WORLD)]}
            for name in names}


def _pin(transform):
    """/** @param transform 引擎变换 @return RigVM默认值 */"""
    p = transform.translation
    q = transform.rotation
    s = transform.scale3d
    return f'(Rotation=(X={q.x},Y={q.y},Z={q.z},W={q.w}),Translation=(X={p.x},Y={p.y},Z={p.z}),Scale3D=(X={s.x},Y={s.y},Z={s.z}))'


def _instance(sequence):
    """/** @param sequence 制作序列 @return 唯一制作Rig */"""
    proxies = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
    if len(proxies) != 1:
        raise RuntimeError('MANUAL_RIG_NOT_UNIQUE')
    return proxies[0].control_rig


def _bake_static(sequence, animation, mesh):
    """/** @param sequence 人工静态序列 @param animation 正式握姿 @param mesh 实际网格 @return 官方瞬态导出及原位骨轨保存 不创建备份资产 */"""
    from BBBControlRigAuthoringToolset import _mesh_binding
    from BBBAnimationTrajectoryTools import _track_metadata

    metadata = _track_metadata(animation)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBStaticGripBake_' + uuid.uuid4().hex)
    output = unreal.SystemLibrary.duplicate_object(animation, scope, 'EvaluatedGrip')
    options = unreal.AnimSeqExportOption()
    options.export_transforms = True
    options.export_morph_targets = False
    options.export_attribute_curves = False
    options.export_material_curves = False
    options.use_custom_frame_rate = True
    options.custom_frame_rate = animation.data_model_interface.get_frame_rate()
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not unreal.SequencerTools.export_anim_sequence(world, sequence, output, options, _mesh_binding(sequence, mesh), False):
        raise RuntimeError('STATIC_GRIP_BAKE_FAILED')
    if abs(output.get_play_length() - animation.get_play_length()) > 0.0001:
        raise RuntimeError('STATIC_GRIP_BAKE_LENGTH_CHANGED')
    if output.data_model_interface.get_number_of_keys() != metadata['frames']:
        raise RuntimeError('STATIC_GRIP_BAKE_KEY_COUNT_CHANGED')
    expected = {str(name) for name in animation.data_model_interface.get_bone_track_names()}
    tracks = {str(name): unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(output, name)
              for name in output.data_model_interface.get_bone_track_names()}
    if not expected.issubset(tracks) or any(len(values) != metadata['frames'] for values in tracks.values()):
        raise RuntimeError('STATIC_GRIP_BAKE_TRACKS_CHANGED')
    controller = animation.controller
    controller.open_bracket('应用人工静态握姿骨轨', False)
    try:
        for name, values in tracks.items():
            if name not in expected and not controller.add_bone_curve(name, False):
                raise RuntimeError('STATIC_GRIP_ADD_TRACK_FAILED: ' + name)
            if not controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                raise RuntimeError('STATIC_GRIP_TRACK_FAILED: ' + str(name))
    finally:
        controller.close_bracket(False)
    if _track_metadata(animation) != metadata:
        raise RuntimeError('STATIC_GRIP_METADATA_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('STATIC_GRIP_SAVE_FAILED')


def _nodes(asset, nodes, links):
    """/** @param asset 制作Rig @param nodes 明确节点 @param links 明确连线 @return 编译后的图 */"""
    graph = asset.get_controller()
    for node in list(graph.get_graph().get_nodes()):
        graph.remove_node(node, False, False)
    for index, node in enumerate(nodes):
        created = graph.add_unit_node_from_struct_path(node['struct'], 'Execute', unreal.Vector2D(index % 4 * 400, index // 4 * 180), node['name'], False, False)
        if created is None:
            raise RuntimeError('MANUAL_NODE_FAILED: ' + node['name'])
        for name, value in node.get('defaults', {}).items():
            if not graph.set_pin_default_value(node['name'] + '.' + name, value, True, False, False, False):
                raise RuntimeError('MANUAL_PIN_FAILED: ' + node['name'] + '.' + name)
    for first, second in links:
        if not graph.add_link(first, second, False, False):
            raise RuntimeError('MANUAL_LINK_FAILED: ' + first + ' -> ' + second)
    asset.recompile_vm()
    return graph


def prepare(recipe, path, project):
    """/** @param recipe 唯一制作源 @param path 制作源路径 @param project 项目根 @return 已打开的手动制作入口 不写运行配置 */"""
    from BBBGripAuthoringToolset import _asset, _values, _write_recipe, _FINGERS
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    asset = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    if recipe.get('manual_edit', {}).get('format') == 'BBBGripManual':
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
        return {'status': 'manual_edit_ready', 'sequence': recipe['sequence'], 'resumed': True, 'definitionModified': False}
    dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if dirty & {recipe['sequence'], recipe['rig'], recipe['animation'], recipe['definition']}:
        raise RuntimeError('MANUAL_TARGET_DIRTY: 请先保存当前制作修改')
    require_asset_write([sequence, asset])
    names = list(recipe['solution']['component_pose'])
    pose = _pose(_asset(recipe['animation'], unreal.AnimSequence), names, _asset(recipe['character_mesh'], unreal.SkeletalMesh))
    hierarchy = asset.hierarchy
    controller = hierarchy.get_controller()
    for control in list(hierarchy.get_controls()):
        controller.remove_element(control, False, False)
    mesh = _asset(recipe['character_mesh'], unreal.SkeletalMesh)
    component = unreal.new_object(unreal.SkeletalMeshComponent)
    component.set_skeletal_mesh_asset(mesh)
    controls = []
    for name in ['hand_r'] + list(_FINGERS) + ['hand_l_ik_ctrl', 'elbow_l_pv_ctrl']:
        bone = name
        parent = unreal.RigElementKey()
        transform = pose.get(name, pose['hand_l'])['local']
        if name in ('hand_l_ik_ctrl', 'elbow_l_pv_ctrl'):
            bone = {'hand_l_ik_ctrl': 'hand_l', 'elbow_l_pv_ctrl': 'lowerarm_l'}[name]
            transform = pose[bone]['component']
        if name not in ('hand_l_ik_ctrl', 'elbow_l_pv_ctrl'):
            parent = _key(str(component.get_parent_bone(name)))
        settings = unreal.RigControlSettings()
        settings.control_type = unreal.RigControlType.EULER_TRANSFORM
        settings.display_name = name
        settings.shape_name = 'Circle_Thin'
        settings.shape_visible = True
        settings.shape_color = unreal.LinearColor(0.1, 0.7, 1.0, 1.0)
        if name.endswith('_r'):
            settings.shape_color = unreal.LinearColor(1.0, 0.25, 0.1, 1.0)
        control_name = name
        if name in _FINGERS or name == 'hand_r':
            control_name = 'fk_' + name
        control = controller.add_control(control_name, parent, settings, unreal.RigHierarchy.make_control_value_from_euler_transform(unreal.EulerTransform()), False, False)
        hierarchy.set_control_offset_transform(control, transform, True)
        hierarchy.set_control_offset_transform(control, transform, False)
        size = 0.35
        if name not in _FINGERS:
            size = 2.0
        hierarchy.set_control_shape_transform(control, unreal.Transform(scale=unreal.Vector(size, size, size)), True)
        controls.append(control_name)

    source = _asset('/Game/_Project/Characters/BBBC_UA/Rigs/CR_BBB_UA_LeftHand', unreal.ControlRigBlueprint).get_controller().get_graph()
    nodes = []
    for node in source.get_nodes():
        defaults = {pin.get_name(): pin.get_default_value() for pin in node.get_pins()
                    if pin.get_name() not in ('ExecutePin', 'CachedIndex', 'Transform', 'Result', 'Elbow') and pin.get_default_value()}
        nodes.append({'name': node.get_name(), 'struct': node.get_script_struct().get_path_name(), 'defaults': defaults})
    links = [link.get_pin_path_representation().split(' -> ') for link in source.get_links()]
    links.remove(['Forward.ExecutePin', 'ApplyArm.ExecutePin'])
    nodes.append({'name': 'BasePose', 'struct': '/Script/ControlRig.RigUnit_SetTransformItemArray', 'defaults': {
        'Items': '(' + ','.join('(Type=Bone,Name="' + name + '")' for name in names) + ')',
        'Transforms': '(' + ','.join(_pin(pose[name]['component']) for name in names) + ')',
        'Space': 'GlobalSpace', 'bInitial': 'False', 'bPropagateToChildren': 'True'}})
    links.append(['Forward.ExecutePin', 'BasePose.ExecutePin'])
    previous = 'BasePose'
    for name in ['hand_r'] + list(_FINGERS):
        read = 'Read_' + name
        write = 'Apply_' + name
        nodes.append({'name': read, 'struct': '/Script/ControlRig.RigUnit_GetTransform', 'defaults': {
            'Item': '(Type=Control,Name="fk_' + name + '")', 'Space': 'GlobalSpace', 'bInitial': 'False'}})
        nodes.append({'name': write, 'struct': '/Script/ControlRig.RigUnit_SetTransform', 'defaults': {
            'Item': '(Type=Bone,Name="' + name + '")', 'Space': 'GlobalSpace', 'bInitial': 'False', 'bPropagateToChildren': 'True'}})
        links.append([read + '.Transform', write + '.Value'])
        links.append([previous + '.ExecutePin', write + '.ExecutePin'])
        previous = write
        if name == 'hand_r':
            links.append([previous + '.ExecutePin', 'ApplyArm.ExecutePin'])
            previous = 'ApplyArm'
    for helper, hand in [('ik_hand_gun', 'hand_r'), ('ik_hand_r', 'hand_r'), ('ik_hand_l', 'hand_l')]:
        read = 'ReadHelper_' + helper
        write = 'ApplyHelper_' + helper
        nodes.append({'name': read, 'struct': '/Script/ControlRig.RigUnit_GetTransform', 'defaults': {
            'Item': '(Type=Bone,Name="' + hand + '")', 'Space': 'GlobalSpace', 'bInitial': 'False'}})
        nodes.append({'name': write, 'struct': '/Script/ControlRig.RigUnit_SetTransform', 'defaults': {
            'Item': '(Type=Bone,Name="' + helper + '")', 'Space': 'GlobalSpace', 'bInitial': 'False', 'bPropagateToChildren': 'True'}})
        links.append([read + '.Transform', write + '.Value'])
        links.append([previous + '.ExecutePin', write + '.ExecutePin'])
        previous = write
    _nodes(asset, nodes, links)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    character_bindings = [binding for binding in sequence.get_bindings() if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
                          and binding.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == mesh]
    if len(character_bindings) != 1:
        raise RuntimeError('MANUAL_CHARACTER_NOT_UNIQUE')
    for track in list(character_bindings[0].find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)):
        character_bindings[0].remove_track(track)
    authoring.configure_sequence_rig(recipe['sequence'], recipe['rig'], '[]', False, recipe['character_mesh'])
    rig = _instance(sequence)
    for name in controls:
        for frame in (0, 1):
            unreal.ControlRigSequencerLibrary.set_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame), unreal.EulerTransform(), set_key=True)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    frozen = {name: _values(pose[name]['local']) for name in ('upperarm_r', 'lowerarm_r')}
    recipe['manual_edit'] = {'format': 'BBBGripManual', 'frame': 0, 'controls': controls, 'frozen_right_arm': frozen,
                             'initial_right_wrist': _values(pose['hand_r']['local']), 'definitionApplied': False}
    unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    _write_recipe(path, recipe, project)
    return {'status': 'manual_edit_ready', 'sequence': recipe['sequence'], 'controls': controls,
            'definitionModified': False, 'animationModified': False, 'next': 'manual_apply'}


def apply(recipe, path, project):
    """/** @param recipe 唯一制作源 @param path 制作源路径 @param project 项目根 @return 手工结果烘焙与正式偏移 不运行拟合 */"""
    from BBBGripAuthoringToolset import _asset, _values, _transform, _socket, _inputs, _write_recipe, _apply_definition, _fingerprint, _FINGERS
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

    manual = recipe.get('manual_edit', {})
    if manual.get('format') != 'BBBGripManual':
        raise RuntimeError('MANUAL_PREPARE_REQUIRED')
    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    if unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence() != sequence:
        raise RuntimeError('MANUAL_SEQUENCE_NOT_OPEN: 必须保留当前制作序列')
    if unreal.LevelSequenceEditorBlueprintLibrary.get_current_time() != 0:
        raise RuntimeError('MANUAL_FRAME_ZERO_REQUIRED')
    require_asset_write([_asset(recipe[field], expected) for field, expected in [('rig', unreal.ControlRigBlueprint), ('sequence', unreal.LevelSequence), ('animation', unreal.AnimSequence), ('definition', unreal.DataAsset)]])
    rig = _instance(sequence)
    hierarchy = rig.get_hierarchy()
    names = list(recipe['solution']['component_pose'])
    local = {name: hierarchy.get_local_transform(_key(name)) for name in names}
    component = {name: hierarchy.get_global_transform(_key(name)) for name in names}
    for name, values in manual['frozen_right_arm'].items():
        initial = _transform(values)
        current = local[name]
        if (current.translation - initial.translation).length() > 0.01 or abs((current.rotation * initial.rotation.inversed()).w) < 0.999999:
            raise RuntimeError('MANUAL_RIGHT_ARM_CHANGED: ' + name)
    for name in list(_FINGERS) + ['hand_r']:
        value = unreal.RigHierarchy.get_euler_transform_from_control_value(hierarchy.get_control_value(_key('fk_' + name, 'CONTROL')))
        if value.location.length() > 0.01:
            raise RuntimeError('MANUAL_FINGER_TRANSLATED: 手指只旋转 ' + name)
    bindings = [binding for binding in sequence.get_bindings() if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
                and binding.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == _asset(recipe['weapon_mesh'], unreal.SkeletalMesh)]
    if len(bindings) != 1:
        raise RuntimeError('MANUAL_WEAPON_NOT_UNIQUE')
    identifier = unreal.MovieSceneObjectBindingID()
    identifier.set_editor_property('guid', bindings[0].get_id())
    bound = unreal.LevelSequenceEditorBlueprintLibrary.get_bound_objects(identifier)
    if len(bound) != 1 or not isinstance(bound[0], unreal.SkeletalMeshActor):
        raise RuntimeError('MANUAL_WEAPON_NOT_SPAWNED')
    weapon = bound[0]
    character_mesh = _asset(recipe['character_mesh'], unreal.SkeletalMesh)
    attachment = _socket(character_mesh, recipe['attachment_socket'])
    if attachment['parent'].lower() != 'hand_r':
        raise RuntimeError('MANUAL_ATTACHMENT_PARENT_REQUIRED')
    actor_component = weapon.skeletal_mesh_component
    attach_parent = weapon.root_component.get_attach_parent()
    if attach_parent is None:
        raise RuntimeError('MANUAL_WEAPON_ATTACHMENT_REQUIRED')
    right_world = attach_parent.get_socket_transform('hand_r', unreal.RelativeTransformSpace.RTS_WORLD)
    socket_world = attach_parent.get_socket_transform(recipe['attachment_socket'], unreal.RelativeTransformSpace.RTS_WORLD)
    spawn = unreal.MathLibrary.make_relative_transform(weapon.get_actor_transform(), socket_world)
    left_socket_world = actor_component.get_socket_transform(recipe['left_socket'], unreal.RelativeTransformSpace.RTS_WORLD)
    socket_right = unreal.MathLibrary.make_relative_transform(left_socket_world, right_world)
    hand_right = unreal.MathLibrary.make_relative_transform(component['hand_l'], component['hand_r'])
    calibration = {'mode': 'fixed', 'spawn_offset': _values(spawn),
                   'left_ik_offset': list((hand_right.translation - socket_right.translation).to_tuple()),
                   'left_ik_rotation': list((socket_right.rotation.inversed() * hand_right.rotation).normalized().to_tuple()),
                   'right_wrist_delta': recipe['calibration']['right_wrist_delta']}
    reference = _pose(_asset(recipe['reference_animation'], unreal.AnimSequence), ['hand_r'], character_mesh)['hand_r']['local']
    calibration['right_wrist_delta'] = list((local['hand_r'].rotation * reference.rotation.inversed()).normalized().to_tuple())
    control_values = {name: unreal.RigHierarchy.get_euler_transform_from_control_value(hierarchy.get_control_value(_key(name, 'CONTROL')))
                      for name in manual['controls']}
    is_fire = recipe.get('grip_role') == 'fire'
    if is_fire:
        from BBBGripAuthoringToolset import _definition, _recipe
        from BBBGripFireAuthoring import hold_signature

        hold_path = project / recipe['hold_recipe']
        hold = _recipe(hold_path, recipe['weapon_root'])
        if recipe['hold_signature'] != hold_signature(hold, project):
            raise RuntimeError('FIRE_GRIP_BASE_CHANGED')
        baseline = _pose(_asset(hold['animation'], unreal.AnimSequence), names, character_mesh)
        for name in names:
            if name in _FINGERS:
                continue
            if (local[name].translation - baseline[name]['local'].translation).length() > 0.02 or abs((local[name].rotation * baseline[name]['local'].rotation.inversed()).w) < 0.99999:
                raise RuntimeError('FIRE_GRIP_ONLY_FINGERS: 开火握姿只允许编辑指骨 ' + name)
        definition, current = _definition(hold)
        expected_spawn = _transform(current['spawn_offset'])
        if (spawn.translation - expected_spawn.translation).length() > 0.01 or abs((spawn.rotation * expected_spawn.rotation.inversed()).w) < 0.99999:
            raise RuntimeError('FIRE_GRIP_SHARED_ATTACHMENT: 请在未开火阶段调整武器位置')
        calibration = hold['solution']['calibration']
    for name, value in control_values.items():
        for frame in (0, 1):
            unreal.ControlRigSequencerLibrary.set_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame), value, set_key=True)
    transform_tracks = bindings[0].find_tracks_by_type(unreal.MovieScene3DTransformTrack)
    if len(transform_tracks) != 1 or len(transform_tracks[0].get_sections()) != 1:
        raise RuntimeError('MANUAL_WEAPON_TRANSFORM_NOT_UNIQUE')
    for channel in transform_tracks[0].get_sections()[0].get_all_channels():
        for key in list(channel.get_keys()):
            channel.remove_key(key)
    authoring.set_sequence_attachment_transform(recipe['sequence'], bindings[0].get_name(), json.dumps({'position': _values(spawn)[:3], 'rotation': _values(spawn)[3:7], 'scale': _values(spawn)[7:10]}))
    unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    _bake_static(sequence, _asset(recipe['animation'], unreal.AnimSequence), character_mesh)
    baked = _pose(_asset(recipe['animation'], unreal.AnimSequence), names, character_mesh)
    for name in list(_FINGERS) + ['hand_r', 'hand_l', 'upperarm_r', 'lowerarm_r']:
        actual = baked[name]['local']
        if (actual.translation - local[name].translation).length() > 0.02 or abs((actual.rotation * local[name].rotation.inversed()).w) < 0.99999:
            raise RuntimeError('MANUAL_BAKE_MISMATCH: ' + name)
    recipe['calibration'] = calibration
    recipe['pose']['mode'] = 'fixed'
    recipe['pose']['local_rotations'] = {name: list(baked[name]['local'].rotation.to_tuple()) for name in _FINGERS}
    inputs = _inputs(recipe, project)
    recipe['solution'] = {'input_digest': inputs['digest'], 'inputs': inputs, 'calibration': calibration,
                          'local_pose': {name: _values(baked[name]['local']) for name in names},
                          'component_pose': {name: _values(baked[name]['component']) for name in names},
                          'finger_rotations': recipe['pose']['local_rotations'], 'passed': True, 'origin': 'human_manual_edit'}
    if is_fire:
        definition.set_editor_property('character_fire_grip_pose', _asset(recipe['animation'], unreal.AnimSequence))
        if not unreal.EditorAssetLibrary.save_loaded_asset(definition, False):
            raise RuntimeError('FIRE_GRIP_DEFINITION_SAVE_FAILED')
    if not is_fire:
        _apply_definition(recipe)
    recipe['manual_edit']['definitionApplied'] = True
    recipe['validation'] = {'passed': True, 'fingerprint': _fingerprint(recipe, project), 'scope': 'manual_bake_readback_and_offsets', 'geometryProven': False}
    recipe.pop('review', None)
    _write_recipe(path, recipe, project)
    return {'status': 'manual_applied', 'animation': recipe['animation'], 'definition': recipe['definition'],
            'calibration': calibration, 'rightArmPreserved': True, 'runtimeAcceptance': 'pending',
            'gripRole': 'fire' if is_fire else 'hold', 'next': 'next_weapon_hold' if is_fire else 'manual_prepare_fire'}
