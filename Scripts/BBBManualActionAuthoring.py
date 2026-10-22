"""人工调整武器整段动作的正式制作入口"""
import copy
import hashlib
import json
import math
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _key, _pose, _read_transform
from BBBGripManualAuthoring import _nodes


def _save(path, data):
    """
    /**
     * @param path	正式制作源
     * @param data	当前制作数据
     * @return	保存并回读
     */
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    if json.loads(path.read_text(encoding='utf-8')) != data:
        raise RuntimeError('ACTION_SOURCE_READBACK')


ACTION_MONTAGE_FIELDS = {
    'equip': ('character_equip_montage', 'equipment_equip_montage'),
    'reload': ('character_reload_montage', 'equipment_reload_montage'),
    'reload_start': ('character_reload_start_montage', 'equipment_reload_start_montage'),
    'reload_insert': ('character_reload_montage', 'equipment_reload_montage'),
    'reload_end': ('character_reload_end_montage', 'equipment_reload_end_montage'),
}


def _source(recipe_path):
    """
    /**
     * @param recipe_path	型号制作文件
     * @return	正式路径与已验证制作要求
     */
    """
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    root = data['weapon_root']
    expected = project / 'Content' / root.removeprefix('/Game/') / 'Source/Animation'
    if not root.startswith('/Game/_Project/') or path.parent != expected.resolve() or not path.name.endswith('_ManualAction.json.source'):
        raise RuntimeError('ACTION_SOURCE_SCOPE')
    if data.get('format') != 'BBBManualWeaponAction' or data.get('schema') != 2:
        raise RuntimeError('ACTION_SOURCE_FORMAT')
    if data.get('action') not in ACTION_MONTAGE_FIELDS or not data.get('approval'):
        raise RuntimeError('ACTION_APPROVED_KIND_REQUIRED')
    if data.get('status') not in ('prepare_approved', 'track_created', 'keys_written', 'previews_created', 'manual_edit_ready'):
        raise RuntimeError('ACTION_SOURCE_STATUS')
    for field, folder in [('sequence', 'work'), ('rig', 'work'), ('output_animation', 'Sequence')]:
        if data[field].rsplit('/', 1)[0] != root + '/Animation/' + folder:
            raise RuntimeError('ACTION_ASSET_SCOPE: ' + field)
    if data['finger_animation'] != data['animation'] and data['finger_animation'].rsplit('/', 1)[0] != root + '/Animation/Sequence':
        raise RuntimeError('ACTION_FINGER_SOURCE_SCOPE')
    import BBBCommonActionSources
    row = BBBCommonActionSources.source_for(data)
    if _digest(_asset(data['animation'], unreal.AnimSequence)) != row['validation']['animation_digest']:
        raise RuntimeError('ACTION_COMMON_SOURCE_CHANGED')
    return path, data


def _digest(animation):
    """
    /**
     * @param animation	动画
     * @return	当前骨轨摘要
     */
    """
    digest = hashlib.sha256()
    for name in animation.data_model_interface.get_bone_track_names():
        digest.update(str(name).encode())
        for value in unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name):
            digest.update(value.export_text().encode())
    return digest.hexdigest()


def _graph(data, names, fingers):
    """
    /**
     * @param data	制作要求
     * @param names	身体骨骼
     * @param fingers	手指骨
     * @return	完整双臂及逐节FK制作图
     */
    """
    project = Path(unreal.Paths.project_dir()).resolve()
    template = json.loads((project / data['arm_graph_source']).read_text(encoding='utf-8-sig'))
    graph = copy.deepcopy(template['graph'])
    graph['nodes'] = [node for node in graph['nodes'] if node['name'] != 'BasePose']
    graph['links'] = [link for link in graph['links'] if not any(pin.startswith('BasePose.') for pin in link)]
    identity = '(Rotation=(X=0,Y=0,Z=0,W=1),Translation=(X=0,Y=0,Z=0),Scale3D=(X=1,Y=1,Z=1))'
    graph['nodes'].append({'name': 'OriginalPose', 'struct': '/Script/ControlRig.RigUnit_SetTransformItemArray', 'defaults': {
        'Items': '(' + ','.join('(Type=Bone,Name="' + name + '")' for name in names) + ')',
        'Transforms': '(' + ','.join(identity for name in names) + ')', 'bPropagateToChildren': 'True'}})
    graph['links'].extend([['Forward.ExecutePin', 'OriginalPose.ExecutePin'], ['OriginalPose.ExecutePin', 'ApplyShoulder_r.ExecutePin']])
    for index, bone in enumerate(names):
        node = 'Source_' + str(index)
        graph['nodes'].append({'name': node, 'struct': '/Script/ControlRig.RigUnit_GetTransform', 'defaults': {
            'Item': '(Type=Control,Name="source_' + bone + '")', 'Space': 'GlobalSpace'}})
        graph['links'].append([node + '.Transform', 'OriginalPose.Transforms.' + str(index)])
    previous = 'Apply_ik_hand_l'
    for bone in fingers:
        read = 'FKRead_' + bone
        apply = 'FKApply_' + bone
        graph['nodes'].extend([
            {'name': read, 'struct': '/Script/ControlRig.RigUnit_GetTransform', 'defaults': {'Item': '(Type=Control,Name="fk_' + bone + '")', 'Space': 'GlobalSpace'}},
            {'name': apply, 'struct': '/Script/ControlRig.RigUnit_SetTransform', 'defaults': {'Item': '(Type=Bone,Name="' + bone + '")', 'Space': 'GlobalSpace', 'bPropagateToChildren': 'True'}},
        ])
        graph['links'].extend([[previous + '.ExecutePin', apply + '.ExecutePin'], [read + '.Transform', apply + '.Value']])
        previous = apply
    return graph


def _create_rig(data, names, fingers, first_pose):
    """
    /**
     * @param data	制作要求
     * @param names	身体骨骼
     * @param fingers	手指骨
     * @param first_pose	起始姿势
     * @return	正式动作Rig
     */
    """
    rig = None
    if unreal.EditorAssetLibrary.does_asset_exist(data['rig']):
        rig = _asset(data['rig'], unreal.ControlRigBlueprint)
        if data.get('reuse_rig'):
            graph = rig.get_controller()
            if graph.get_graph().find_node_by_name('RuntimeWristApply') is not None:
                require_asset_write([rig])
                graph.set_pin_default_value('RuntimeWristApply.Weight', '0.0', True, False, False, False)
                rig.recompile_vm()
                if not unreal.EditorAssetLibrary.save_loaded_asset(rig, False):
                    raise RuntimeError('WRIST_PREVIEW_PREPARE_SAVE')
            return rig
        require_asset_write([rig])
        for control in list(rig.hierarchy.get_controls()):
            rig.hierarchy.get_controller().remove_element(control, False, False)
    if rig is None:
        require_asset_write([], destinations=[data['rig']])
        rig = unreal.ControlRigBlueprintFactory.create_new_control_rig_asset(data['rig'], False)
        rig.hierarchy.get_controller().import_bones_from_asset(data['mesh'], '', True, True, False)
    rig.set_preview_mesh(_asset(data['mesh'], unreal.SkeletalMesh))
    hierarchy = rig.hierarchy
    controller = hierarchy.get_controller()
    component = unreal.new_object(unreal.SkeletalMeshComponent)
    component.set_skeletal_mesh_asset(_asset(data['mesh'], unreal.SkeletalMesh))
    controls = [('source_' + name, name, 'source') for name in names]
    controls.extend([(kind + '_' + side + suffix, bone + '_' + side, 'arm') for side in ('r', 'l')
                     for kind, suffix, bone in [('clavicle', '_ctrl', 'clavicle'), ('hand', '_ik_ctrl', 'hand'), ('elbow', '_pv_ctrl', 'lowerarm')]])
    controls.extend([('fk_' + bone, bone, 'finger') for bone in fingers])
    for name, bone, role in controls:
        settings = unreal.RigControlSettings()
        settings.control_type = unreal.RigControlType.EULER_TRANSFORM
        settings.display_name = name
        settings.shape_visible = role != 'source'
        settings.shape_name = 'Circle_Thin'
        settings.shape_color = unreal.LinearColor(0.1, 0.7, 1, 1)
        if bone.endswith('_r'):
            settings.shape_color = unreal.LinearColor(1, 0.3, 0.1, 1)
        parent = unreal.RigElementKey()
        if role == 'finger':
            parent = _key(str(component.get_parent_bone(bone)))
        initial = unreal.EulerTransform()
        if role in ('source', 'finger'):
            space = unreal.AnimPoseSpaces.WORLD
            if role == 'finger':
                space = unreal.AnimPoseSpaces.LOCAL
            value = unreal.AnimPoseExtensions.get_bone_pose(first_pose, bone, space)
            initial = unreal.EulerTransform(location=value.translation, rotation=value.rotation.rotator(), scale=value.scale3d)
        key = controller.add_control(name, parent, settings, unreal.RigHierarchy.make_control_value_from_euler_transform(initial), False, False)
        if role == 'arm':
            offset = unreal.AnimPoseExtensions.get_bone_pose(first_pose, bone, unreal.AnimPoseSpaces.WORLD)
            hierarchy.set_control_offset_transform(key, offset, True)
            hierarchy.set_control_offset_transform(key, offset, False)
        size = 2.0
        if role == 'finger':
            size = 0.35
        hierarchy.set_control_shape_transform(key, unreal.Transform(scale=unreal.Vector(size, size, size)), True)
    graph = _graph(data, names, fingers)
    _nodes(rig, graph['nodes'], graph['links'])
    if not unreal.EditorAssetLibrary.save_loaded_asset(rig, False):
        raise RuntimeError('ACTION_RIG_SAVE')
    return rig


def _prepare_sequence(data, animation, count):
    """
    /**
     * @param data	制作要求
     * @param animation	当前正式动作
     * @param count	帧数
     * @return	原位更新的制作序列
     */
    """
    sequence = unreal.load_asset(data['sequence'])
    if sequence is None:
        if data['status'] != 'prepare_approved':
            raise RuntimeError('ACTION_EXISTING_SEQUENCE_REQUIRED')
        require_asset_write([], destinations=[data['sequence']])
        package, name = data['sequence'].rsplit('/', 1)
        sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, package, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    require_asset_write([sequence])
    unreal.EditorAssetLibrary.remove_metadata_tag(sequence, 'BBB_RuntimeRightWristPreview')
    unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
    for binding in list(sequence.get_bindings()):
        binding.remove()
    rate = animation.data_model_interface.get_frame_rate()
    sequence.set_display_rate(rate)
    sequence.set_playback_start(0)
    sequence.set_playback_end(count)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(), transient=True)
    actor.set_actor_label('Character')
    actor.skeletal_mesh_component.set_skeletal_mesh_asset(_asset(data['mesh'], unreal.SkeletalMesh))
    actor.skeletal_mesh_component.set_editor_property('disable_post_process_blueprint', True)
    binding = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem).add_spawnable_from_instance(sequence, actor)
    binding.set_name('Character')
    actors.destroy_actor(actor)
    lifetime = binding.find_tracks_by_type(unreal.MovieSceneBindingLifetimeTrack)
    lifetime_track = lifetime[0] if lifetime else binding.add_track(unreal.MovieSceneBindingLifetimeTrack)
    if lifetime_track is None:
        raise RuntimeError('ACTION_BINDING_LIFETIME_REQUIRED')
    sections = lifetime_track.get_sections()
    spawn = sections[0] if sections else lifetime_track.add_section()
    spawn.set_range(0, count)
    section = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack).add_section()
    parameters = section.get_editor_property('params')
    parameters.animation = animation
    parameters.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(data['source_time_scale'])
    section.set_editor_property('params', parameters)
    section.set_range(0, count)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    return sequence


def _write_keys(data, sequence, keys, finger_keys, count, phase):
    """
    /**
     * @param data	制作要求
     * @param sequence	制作序列
     * @param keys	组件目标
     * @param finger_keys	手指局部轨迹
     * @param count	帧数
     * @return	官方接口关键帧回读
     */
    """
    from BBBControlRigAuthoringToolset import _mesh_binding, _transform
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    binding = _mesh_binding(sequence, _asset(data['mesh'], unreal.SkeletalMesh))
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    track = unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(world, sequence, asset.get_control_rig_class(), binding, is_layered_control_rig=False)
    for section in track.get_sections():
        section.set_range(0, count)
    for source in binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack):
        for section in source.get_sections():
            section.set_is_active(False)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    if phase == 'create':
        unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
        return
    proxies = [p for p in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence) if p.track == track]
    if len(proxies) != 1:
        raise RuntimeError('ACTION_SEQUENCE_RIG_NOT_UNIQUE')
    rig = proxies[0].control_rig
    grouped = {}
    for row in keys:
        grouped.setdefault(row['control'], []).append(row)
    requested = {}
    frames = [unreal.FrameNumber(value=i) for i in range(count)]
    for name, rows in grouped.items():
        offset = rig.get_hierarchy().get_global_control_offset_transform(_key(name, 'CONTROL'), True)
        values = []
        for row in rows:
            local = _transform(row['value']).make_relative(offset)
            values.append(unreal.EulerTransform(location=local.translation, rotation=local.rotation.rotator(), scale=local.scale3d))
        requested[name] = values
    requested.update({'fk_' + bone: values for bone, values in finger_keys.items()})
    if phase == 'write':
        channels = {str(channel.channel_name): channel for section in track.get_sections() for channel in section.get_all_channels()}
        suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
        for name, values in requested.items():
            targets = [channels[name + '.' + suffix] for suffix in suffixes]
            previous = None
            for frame, value in zip(frames, values):
                angles = [value.rotation.roll, value.rotation.pitch, value.rotation.yaw]
                if previous is not None:
                    angles = [a + 360 * round((b - a) / 360) for a, b in zip(angles, previous)]
                previous = angles
                numbers = list(value.location.to_tuple()) + angles + list(value.scale.to_tuple())
                for channel, number in zip(targets, numbers):
                    channel.add_key(frame, number, 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
        return
    channels = {str(channel.channel_name): channel for section in track.get_sections() for channel in section.get_all_channels()}
    suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
    for name, values in requested.items():
        stored = []
        for suffix in suffixes:
            actual = {key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).frame_number.value: key.get_value()
                      for key in channels[name + '.' + suffix].get_keys()}
            if set(actual) != set(range(count)):
                raise RuntimeError('ACTION_KEYS_COUNT: ' + name + '.' + suffix)
            stored.append(actual)
        previous = None
        for frame, value in enumerate(values):
            angles = [value.rotation.roll, value.rotation.pitch, value.rotation.yaw]
            if previous is not None:
                angles = [a + 360 * round((b - a) / 360) for a, b in zip(angles, previous)]
            previous = angles
            numbers = list(value.location.to_tuple()) + angles + list(value.scale.to_tuple())
            if any(abs(channel[frame] - number) > 0.001 for channel, number in zip(stored, numbers)):
                raise RuntimeError('ACTION_CHANNEL_READBACK: %s frame=%d' % (name, frame))
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('ACTION_SEQUENCE_SAVE')


def _verify_sequence(data, sequence, animation, mesh, count):
    """
    /**
     * @param data	制作要求
     * @param sequence	序列
     * @param animation	原动作
     * @param mesh	角色网格
     * @param count	帧数
     * @return	官方瞬态烘焙求值误差
     */
    """
    from BBBControlRigAuthoringToolset import _mesh_binding
    from BBBCommonActionSources import is_finger
    finger_animation = _asset(data['finger_animation'], unreal.AnimSequence)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    scope = unreal.new_object(unreal.LevelSequence, name='BBBManualActionAudit_' + uuid.uuid4().hex)
    copied = unreal.SystemLibrary.duplicate_object(sequence, scope, 'Sequence')
    baked = unreal.SystemLibrary.duplicate_object(animation, scope, 'Animation')
    if any(value.get_outermost().get_path_name() != '/Engine/Transient' for value in (scope, copied, baked)):
        raise RuntimeError('ACTION_AUDIT_TRANSIENT_ONLY')
    binding = _mesh_binding(copied, mesh)
    rate = sequence.get_display_rate()
    maximum = 0.0
    try:
        options = unreal.AnimSeqExportOption()
        options.export_transforms = True
        options.export_morph_targets = False
        options.export_attribute_curves = False
        options.export_material_curves = False
        baked.controller.remove_all_bone_tracks(False)
        if not unreal.SequencerTools.export_anim_sequence(world, copied, baked, options, binding, False):
            raise RuntimeError('ACTION_TRANSIENT_EXPORT_FAILED')
        if baked.sequence_length + 0.001 < animation.sequence_length:
            raise RuntimeError('ACTION_TRANSIENT_EXPORT_LENGTH')
        for frame in range(count):
            time = frame * rate.denominator / rate.numerator
            pose = _pose(animation, mesh, time * data['source_time_scale'])
            finger_pose = _pose(finger_animation, mesh, time)
            result = _pose(baked, mesh, time)
            for bone in unreal.AnimPoseExtensions.get_bone_names(pose):
                expected_pose = pose
                space = unreal.AnimPoseSpaces.WORLD
                if is_finger(bone):
                    expected_pose = finger_pose
                    space = unreal.AnimPoseSpaces.LOCAL
                if str(bone).lower().startswith('ik_hand_'):
                    continue
                expected = unreal.AnimPoseExtensions.get_bone_pose(expected_pose, bone, space)
                actual = unreal.AnimPoseExtensions.get_bone_pose(result, bone, space)
                error = (actual.translation - expected.translation).length()
                maximum = max(maximum, error)
                cosine = abs(sum(a * b for a, b in zip(actual.rotation.to_tuple(), expected.rotation.to_tuple())))
                if error > 0.05 or cosine < 0.99999:
                    raise RuntimeError('ACTION_PLAYER_POSE: %s frame=%d cm=%f cosine=%f' % (bone, frame, error, cosine))
    finally:
        binding = None
        options = None
        copied = None
        baked = None
        unreal.purge_object_references(scope, True)
    return maximum


def _attachment(sequence, label, mesh, socket, transform, ranges, animation=None, play_rate=1.0):
    """
    /**
     * @param sequence	制作序列
     * @param label	唯一展示名
     * @param mesh	展示网格
     * @param socket	角色骨骼
     * @param transform	局部位置
     * @param ranges	生命周期
     * @param animation	枪体动作
     * @param play_rate	同步速度
     * @return	当前可选择的展示绑定
     */
    """
    from BBBControlRigAuthoringToolset import _transform
    for binding in list(sequence.get_bindings()):
        if binding.get_name() == label:
            binding.remove()
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if isinstance(mesh, unreal.SkeletalMesh):
        actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(), transient=True)
        actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
    elif isinstance(mesh, unreal.StaticMesh):
        actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(), transient=True)
        actor.static_mesh_component.set_static_mesh(mesh)
    else:
        raise RuntimeError('ACTION_PREVIEW_MESH_TYPE')
    actor.set_actor_label(label)
    actor.set_actor_enable_collision(False)
    actor.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    binding = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem).add_spawnable_from_instance(sequence, actor)
    binding.set_name(label)
    actors.destroy_actor(actor)
    lifetime = binding.find_tracks_by_type(unreal.MovieSceneBindingLifetimeTrack)
    track = lifetime[0] if lifetime else binding.add_track(unreal.MovieSceneBindingLifetimeTrack)
    for section in list(track.get_sections()):
        track.remove_section(section)
    for start, end in ranges:
        track.add_section().set_range(start, end)
    character = [b for b in sequence.get_bindings() if b.get_name() == 'Character']
    if len(character) != 1:
        raise RuntimeError('ACTION_PREVIEW_CHARACTER')
    identifier = unreal.MovieSceneObjectBindingID()
    identifier.set_editor_property('guid', character[0].get_id())
    attach = binding.add_track(unreal.MovieScene3DAttachTrack).add_section()
    attach.set_range(0, sequence.get_playback_end())
    attach.set_constraint_binding_id(identifier)
    attach.set_editor_property('attach_socket_name', socket)
    attach.set_editor_property('attach_component_name', character[0].get_object_template().skeletal_mesh_component.get_name())
    for kind in ('location', 'rotation', 'scale'):
        attach.set_editor_property('attachment_' + kind + '_rule', unreal.AttachmentRule.KEEP_RELATIVE)
    value = _transform(transform)
    rotator = value.rotation.rotator()
    for existing in list(binding.find_tracks_by_type(unreal.MovieScene3DTransformTrack)):
        binding.remove_track(existing)
    section = binding.add_track(unreal.MovieScene3DTransformTrack).add_section()
    section.set_range(0, sequence.get_playback_end())
    numbers = list(value.translation.to_tuple()) + [rotator.roll, rotator.pitch, rotator.yaw] + list(value.scale3d.to_tuple())
    for channel, number in zip(section.get_all_channels(), numbers):
        channel.set_default(number)
    if animation is not None:
        section = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack).add_section()
        section.set_range(0, sequence.get_playback_end())
        params = section.get_editor_property('params')
        params.animation = animation
        params.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(play_rate)
        section.set_editor_property('params', params)
    return binding


def _single_segment(montage):
    """
    /**
     * @param montage	当前实际引用
     * @return	唯一正向完整片段 禁止猜测时间映射
     */
    """
    slots = montage.get_editor_property('slot_anim_tracks')
    segments = [segment for slot in slots for segment in slot.get_editor_property('anim_track').get_editor_property('anim_segments')]
    if len(segments) != 1:
        raise RuntimeError('ACTION_PREVIEW_SINGLE_SEGMENT_REQUIRED')
    segment = segments[0]
    if segment.get_editor_property('looping_count') != 1 or segment.get_editor_property('anim_play_rate') <= 0:
        raise RuntimeError('ACTION_PREVIEW_FORWARD_SEGMENT_REQUIRED')
    if abs(segment.get_editor_property('start_pos')) > 0.0001 or abs(segment.get_editor_property('anim_start_time')) > 0.0001:
        raise RuntimeError('ACTION_PREVIEW_TRIMMED_SEGMENT_REQUIRES_EXPLICIT_MAPPING')
    return segment


def _notify_events(owner):
    """
    /**
     * @param owner	通知所属动画或蒙太奇
     * @return	经实例身份校验的事件和原生起止秒数
     */
    """
    native = json.loads(unreal.BBBHandPoseLayerEditorLibrary.inspect_animation_notify_timing(owner))
    events = list(unreal.AnimationLibrary.get_animation_notify_events(owner))
    if native.get('error') or not native.get('readOnly') or len(native.get('events', [])) != len(events):
        raise RuntimeError('ACTION_NATIVE_NOTIFY_TIMING')
    result = []
    for index, event in enumerate(events):
        state = event.get_editor_property('notify_state_class')
        instance = state or event.get_editor_property('notify')
        timing = native['events'][index]
        if timing['sourceIndex'] != index or timing['notifyInstance'] != (instance.get_path_name() if instance else ''):
            raise RuntimeError('ACTION_NATIVE_NOTIFY_IDENTITY')
        result.append((state, timing['nativeTriggerTime'], timing['nativeEndTriggerTime']))
    return result


def _weapon_preview_animation(data, source, montage, weapon_rate):
    """
    /**
     * @param data	明确的预览输出
     * @param source	当前枪体动作
     * @param montage	当前枪体蒙太奇
     * @param weapon_rate	蒙太奇片段速度
     * @return	按正式显隐通知制作的预览动画与原生时间窗口
     */
    """
    windows = []
    for owner, multiplier in ((source, 1.0), (montage, weapon_rate)):
        for state, start, end in _notify_events(owner):
            if state is not None and state.get_class().get_name() == 'BBBEquipmentBoneVisibilityDisplayAnimNotifyState':
                windows.append({'bone': str(state.get_editor_property('bone_name')), 'start': start * multiplier,
                                'end': end * multiplier, 'notify_instance': state.get_path_name()})
    if not windows:
        return source, []
    destination = data['preview_animation']
    if destination.rsplit('/', 1)[0] != data['weapon_root'] + '/Animation/Sequence':
        raise RuntimeError('ACTION_PREVIEW_ANIMATION_SCOPE')
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        output = _asset(destination, unreal.AnimSequence)
        require_asset_write([output])
    else:
        require_asset_write([], destinations=[destination])
        output = unreal.EditorAssetLibrary.duplicate_asset(source.get_path_name().split('.')[0], destination)
    rate = source.data_model_interface.get_frame_rate()
    for bone in {row['bone'] for row in windows}:
        values = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, bone))
        if not values:
            raise RuntimeError('ACTION_PREVIEW_BONE_TRACK: ' + bone)
        scales = [value.scale3d for value in values]
        for index in range(len(values)):
            time = index * rate.denominator / rate.numerator
            if any(row['bone'] == bone and row['start'] <= time < row['end'] for row in windows):
                scales[index] = unreal.Vector()
        if not output.controller.set_bone_track_keys(bone, [value.translation for value in values], [value.rotation for value in values], scales, False):
            raise RuntimeError('ACTION_PREVIEW_BONE_WRITE')
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(output, bone)
        if len(actual) != len(values) or any((value.scale3d - scale).length() > 0.00001 for value, scale in zip(actual, scales)):
            raise RuntimeError('ACTION_PREVIEW_BONE_READBACK')
    if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
        raise RuntimeError('ACTION_PREVIEW_ANIMATION_SAVE')
    return output, windows


def _previews(data, sequence, animation, count):
    """
    /**
     * @param data	制作要求
     * @param sequence	制作序列
     * @param animation	正式角色动作
     * @param count	帧数
     * @return	按实际通知实例建立的枪体弹匣制作输入
     */
    """
    definition = unreal.load_asset(data['definition'])
    weapon_mesh = definition.get_editor_property('equipment_mesh')
    spawn = _read_transform(definition.get_editor_property('spawn_offset'))
    weapon_animation = None
    speed = 1.0
    previews = []
    held_objects = []
    visibility = []
    if data['action'].startswith('reload'):
        character_field, weapon_field = ACTION_MONTAGE_FIELDS[data['action']]
        character_montage = definition.get_editor_property(character_field)
        character_segment = _single_segment(character_montage)
        character_source = character_segment.get_editor_property('anim_reference')
        if character_source is None or not character_source.get_path_name().startswith(data['weapon_root'] + '/Animation/Sequence/'):
            raise RuntimeError('ACTION_RELOAD_REFERENCE_CHANGED')
        character_rate = character_segment.get_editor_property('anim_play_rate')
        weapon_montage = definition.get_editor_property(weapon_field)
        weapon_segment = _single_segment(weapon_montage)
        weapon_animation = weapon_segment.get_editor_property('anim_reference')
        weapon_rate = weapon_segment.get_editor_property('anim_play_rate')
        speed = weapon_rate / character_rate
        weapon_animation, visibility = _weapon_preview_animation(data, weapon_animation, weapon_montage, weapon_rate)
        rate = sequence.get_display_rate().numerator / sequence.get_display_rate().denominator
        for owner, multiplier in ((_asset(data['finger_animation'], unreal.AnimSequence), 1.0), (character_montage, character_rate)):
            for state, start, end in _notify_events(owner):
                if state is None:
                    continue
                kind = state.get_class().get_name()
                if kind == 'BBBCharacterHeldObjectDisplayAnimNotifyState':
                    start *= multiplier
                    end *= multiplier
                    ranges = [[max(0, math.ceil(start * rate - 0.0001)), min(count, math.ceil(end * rate - 0.0001))]]
                    held_mesh = state.get_editor_property('object_mesh')
                    if held_mesh is None or ranges[0][1] <= ranges[0][0]:
                        raise RuntimeError('ACTION_HELD_OBJECT_PREVIEW_INPUT')
                    transform = _read_transform(state.get_editor_property('hand_object_transform'))
                    socket = str(state.get_editor_property('hand_bone_name'))
                    label = 'HeldObject_' + str(len(held_objects))
                    held_objects.append({'label': label, 'mesh': held_mesh.get_path_name().split('.')[0],
                                         'socket': socket, 'transform': transform, 'ranges': ranges,
                                         'notify_owner': owner.get_path_name(), 'notify_instance': state.get_path_name()})
                    _attachment(sequence, label, held_mesh, socket, transform, ranges)
                    continue
                if kind not in ('BBBCharacterOldMagazineDisplayAnimNotifyState', 'BBBCharacterNewMagazineDisplayAnimNotifyState'):
                    continue
                label = 'OldMagazine' if 'OldMagazine' in kind else 'NewMagazine'
                if any(row['label'] == label for row in previews):
                    raise RuntimeError('ACTION_DUPLICATE_MAGAZINE_NOTIFY')
                start *= multiplier
                end *= multiplier
                ranges = [[max(0, math.ceil(start * rate - 0.0001)), min(count, math.ceil(end * rate - 0.0001))]]
                magazine = state.get_editor_property('magazine_mesh')
                transform = _read_transform(state.get_editor_property('hand_magazine_transform'))
                socket = str(state.get_editor_property('hand_bone_name'))
                if magazine is None or ranges[0][1] <= ranges[0][0]:
                    raise RuntimeError('ACTION_MAGAZINE_PREVIEW_INPUT')
                previews.append({'label': label, 'mesh': magazine.get_path_name().split('.')[0], 'socket': socket,
                                 'transform': transform, 'ranges': ranges, 'notify_owner': owner.get_path_name(), 'notify_instance': state.get_path_name()})
                _attachment(sequence, label, magazine, socket, transform, ranges)
        if data['action'] == 'reload' and not (
                {row['label'] for row in previews} == {'OldMagazine', 'NewMagazine'}
                or (not previews and held_objects)):
            raise RuntimeError('ACTION_RELOAD_MAGAZINE_NOTIFIES_REQUIRED')
    _attachment(sequence, 'Weapon', weapon_mesh, 'WeaponGrip_R', spawn, [[0, count]], weapon_animation, speed)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence, False)
    return {'mesh': weapon_mesh.get_path_name().split('.')[0], 'spawn_offset': spawn,
            'animation': weapon_animation.get_path_name() if weapon_animation else None, 'play_rate': speed,
            'magazines': previews, 'held_objects': held_objects, 'bone_visibility': visibility}


def _verify_finger_edit(instance):
    """
    /**
     * @param instance	独立制作Rig实例
     * @return	两侧手指逐节FK的子节跟随结果 不写入制作序列
     */
    """
    hierarchy = instance.get_hierarchy()
    from BBBCommonActionSources import is_finger
    result = {}
    for side in ('l', 'r'):
        name = 'fk_index_01_' + side
        key = _key(name, 'CONTROL')
        initial = hierarchy.get_control_value(key)
        value = unreal.RigHierarchy.get_euler_transform_from_control_value(initial)
        before = hierarchy.get_global_transform(_key('index_03_' + side))
        local_before = hierarchy.get_local_transform(_key('index_02_' + side))
        value.rotation = (value.rotation.quaternion() * unreal.Rotator(pitch=12).quaternion()).rotator()
        hierarchy.set_control_value(key, unreal.RigHierarchy.make_control_value_from_euler_transform(value))
        instance.execute_event('Forwards Solve')
        after = hierarchy.get_global_transform(_key('index_03_' + side))
        local_after = hierarchy.get_local_transform(_key('index_02_' + side))
        distance = (after.translation - before.translation).length()
        if distance < 0.05 or (local_after.translation - local_before.translation).length() > 0.001:
            raise RuntimeError('ACTION_FINGER_FK_PROPAGATION: ' + side)
        result[side] = {'child_moved_cm': distance, 'child_length_error_cm': (local_after.translation - local_before.translation).length()}
        hierarchy.set_control_value(key, initial)
        instance.execute_event('Forwards Solve')
    return result


def _verify_previews(sequence, preview):
    """
    /**
     * @param sequence	已保存序列
     * @param preview	制作预览
     * @return	枪体和弹匣实际挂接偏差
     */
    """
    from BBBControlRigAuthoringToolset import _transform
    rows = [{'label': 'Weapon', 'socket': 'WeaponGrip_R', 'transform': preview['spawn_offset'], 'ranges': [[0, sequence.get_playback_end()]]}]
    rows.extend(preview['magazines'])
    rows.extend(preview.get('held_objects', []))
    maximum = 0.0
    for row in rows:
        frame = row['ranges'][0][0]
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(frame)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        bindings = [binding for binding in sequence.get_bindings() if binding.get_name() == row['label']]
        if len(bindings) != 1:
            raise RuntimeError('ACTION_PREVIEW_BINDING: ' + row['label'])
        identifier = unreal.MovieSceneObjectBindingID()
        identifier.set_editor_property('guid', bindings[0].get_id())
        objects = unreal.LevelSequenceEditorBlueprintLibrary.get_bound_objects(identifier)
        if len(objects) != 1 or not isinstance(objects[0], unreal.Actor):
            raise RuntimeError('ACTION_PREVIEW_NOT_SPAWNED: ' + row['label'])
        actor = objects[0]
        parent = actor.root_component.get_attach_parent()
        if parent is None:
            raise RuntimeError('ACTION_PREVIEW_NOT_ATTACHED: ' + row['label'])
        actual = unreal.MathLibrary.make_relative_transform(actor.get_actor_transform(), parent.get_socket_transform(row['socket'], unreal.RelativeTransformSpace.RTS_WORLD))
        expected = _transform(row['transform'])
        error = (actual.translation - expected.translation).length()
        maximum = max(maximum, error)
        if error > 0.01 or abs((actual.rotation * expected.rotation.inversed()).w) < 0.99999:
            raise RuntimeError('ACTION_PREVIEW_TRANSFORM: %s cm=%f actual=%s expected=%s socket=%s rootRelative=%s' % (row['label'], error, actual.export_text(), expected.export_text(), str(actor.root_component.get_attach_socket_name()), actor.root_component.get_relative_transform().export_text()))
    return maximum


def prepare(recipe_path, write_paths):
    """
    /**
     * @param recipe_path	型号动作制作源
     * @param write_paths	唯一LS及Rig
     * @return	可手调动作及起始一致性结果
     */
    """
    from BBBCommonActionSources import is_finger
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('ACTION_PREPARE_PIE_FORBIDDEN')
    path, data = _source(recipe_path)
    if data.get('apply_baked_request'):
        import importlib
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        return BBBManualActionNative.apply_baked_animation(path, data, write_paths)
    if data.get('reload_timing_request'):
        import importlib
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        return BBBManualActionNative.sync_reload_timing(path, data, write_paths)
    required = {data['sequence'], data['rig']}
    if data.get('preview_animation'):
        required.add(data['preview_animation'])
    if set(write_paths) != required:
        raise RuntimeError('ACTION_WRITE_SCOPE')
    sequence = unreal.load_asset(data['sequence'])
    if sequence is not None:
        import importlib
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        timeline = BBBManualActionNative.repair_timeline_range(sequence)
        if data.pop('timeline_ui_request', False):
            data['timeline_range_repair'] = timeline
            _save(path, data)
            return {'sequence': data['sequence'], 'timeline': timeline, 'runtimeModified': False}
    if data.get('status') in ('previews_created', 'manual_edit_ready'):
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        if data.get('refresh_weapon_animation_request'):
            from BBBManualActionNative import _channel_digest
            signature = _channel_digest(sequence)
            definition = _asset(data['definition'], unreal.DataAsset)
            character_field, weapon_field = ACTION_MONTAGE_FIELDS[data['action']]
            character = _single_segment(definition.get_editor_property(character_field))
            montage = definition.get_editor_property(weapon_field)
            segment = _single_segment(montage)
            rate = segment.get_editor_property('anim_play_rate')
            output, windows = _weapon_preview_animation(data, segment.get_editor_property('anim_reference'), montage, rate)
            weapons = [b for b in sequence.get_bindings() if b.get_name() == 'Weapon']
            tracks = [t for t in weapons[0].find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack) if t.get_sections()] if len(weapons) == 1 else []
            if len(tracks) != 1 or len(tracks[0].get_sections()) != 1:
                raise RuntimeError('ACTION_REFRESH_WEAPON_TRACK_REQUIRED')
            section = tracks[0].get_sections()[0]
            params = section.get_editor_property('params')
            params.animation = output
            speed = rate / character.get_editor_property('anim_play_rate')
            params.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(speed)
            section.set_editor_property('params', params)
            if _channel_digest(sequence) != signature:
                raise RuntimeError('ACTION_REFRESH_WEAPON_CHANGED_KEYS')
            if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
                raise RuntimeError('ACTION_REFRESH_WEAPON_SAVE')
            data['weapon_preview'].update(animation=output.get_path_name(), play_rate=speed, bone_visibility=windows)
            data['weapon_preview_refresh'] = {'source': segment.get_editor_property('anim_reference').get_path_name(),
                'all_control_and_transform_keys_preserved': True}
            data.pop('refresh_weapon_animation_request')
        if data.get('finger_repair_source'):
            import importlib
            import BBBActionRetargetTools
            importlib.reload(BBBActionRetargetTools)
            BBBActionRetargetTools.sync_finger_repair(path, data, sequence)
        import importlib
        import BBBManualActionNative
        importlib.reload(BBBManualActionNative)
        BBBManualActionNative.refresh_magazine_preview_timing(data, sequence)
        BBBManualActionNative.reset_unkeyed_finger_offsets(data, sequence)
        BBBManualActionNative.prepare_preview_mesh(data, sequence)
        native_edit = BBBManualActionNative.prepare_offset(data, sequence)
        control_visibility = BBBManualActionNative.configure_visible_controls(data, sequence)
        import BBBCommonActionSources
        importlib.reload(BBBCommonActionSources)
        BBBCommonActionSources.prepare_base(data, sequence)
        offset_copy = BBBManualActionNative.copy_offset_keys(path, data, sequence)
        if 'preview_attachment_error_cm' not in data['validation']:
            data['validation']['preview_attachment_error_cm'] = _verify_previews(sequence, data['weapon_preview'])
        data['status'] = 'manual_edit_ready'
        BBBManualActionNative.prepare_right_wrist_preview(data, sequence)
        BBBManualActionNative.freeze_right_wrist_rotation(data, sequence)
        BBBManualActionNative.match_reload_phase_offset(data, sequence)
        _save(path, data)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        for proxy in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence):
            proxy.control_rig.clear_control_selection(False)
            proxy.control_rig.select_control('hand_l_ik_ctrl', True, False)
        return {'status': data['status'], 'sequence': data['sequence'], 'resumed': True, 'runtimeModified': False,
            'native_edit': native_edit, 'control_visibility': control_visibility, 'offset_copy': offset_copy, 'common_source': data['animation'], 'common_base': data['common_base']}
    animation = _asset(data['animation'], unreal.AnimSequence)
    finger_animation = _asset(data['finger_animation'], unreal.AnimSequence)
    if abs(finger_animation.get_play_length() * data['source_time_scale'] - animation.get_play_length()) > 0.0001:
        raise RuntimeError('ACTION_EXPLICIT_SOURCE_TIME_SCALE')
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    count = finger_animation.data_model_interface.get_number_of_keys()
    if count < 2 or count > 600:
        raise RuntimeError('ACTION_FRAME_RANGE')
    rate = finger_animation.data_model_interface.get_frame_rate()
    first = _pose(animation, mesh, 0)
    names = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(first)]
    fingers = [f'{finger}_{joint:02}_{side}' for side in ('l', 'r') for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)]
    if data.get('status') in ('track_created', 'keys_written'):
        data['reuse_rig'] = True
    rig = _create_rig(data, names, fingers, first)
    control_map = {kind + '_' + side + suffix: bone + '_' + side for side in ('r', 'l')
                   for kind, suffix, bone in [('clavicle', '_ctrl', 'clavicle'), ('hand', '_ik_ctrl', 'hand'), ('elbow', '_pv_ctrl', 'lowerarm')]}
    keys = []
    finger_keys = {name: [] for name in fingers}
    maximum_error = 0.0
    instance = rig.create_control_rig()
    instance.request_init()
    instance.execute_event('Forwards Solve')
    hierarchy = instance.get_hierarchy()
    for frame in range(count):
        pose = _pose(animation, mesh, frame * rate.denominator / rate.numerator * data['source_time_scale'])
        finger_pose = _pose(finger_animation, mesh, frame * rate.denominator / rate.numerator)
        values = {'source_' + n: unreal.AnimPoseExtensions.get_bone_pose(pose, n, unreal.AnimPoseSpaces.WORLD) for n in names}
        values.update({c: unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.WORLD) for c, b in control_map.items()})
        for name, value in values.items():
            hierarchy.set_global_transform(_key(name, 'CONTROL'), value)
            keys.append({'frame': frame, 'control': name, 'value': _read_transform(value)})
        for name in fingers:
            local = unreal.AnimPoseExtensions.get_bone_pose(finger_pose, name, unreal.AnimPoseSpaces.LOCAL)
            value = unreal.EulerTransform(location=local.translation, rotation=local.rotation.rotator(), scale=local.scale3d)
            hierarchy.set_control_value(_key('fk_' + name, 'CONTROL'), unreal.RigHierarchy.make_control_value_from_euler_transform(value))
            finger_keys[name].append(value)
        if not instance.execute_event('Forwards Solve'):
            raise RuntimeError('ACTION_RIG_SOLVE')
        for name in names:
            original_pose = pose
            space = unreal.AnimPoseSpaces.WORLD
            actual = hierarchy.get_global_transform(_key(name))
            if is_finger(name):
                original_pose = finger_pose
                space = unreal.AnimPoseSpaces.LOCAL
                actual = hierarchy.get_local_transform(_key(name))
            if name.lower().startswith('ik_hand_'):
                continue
            original = unreal.AnimPoseExtensions.get_bone_pose(original_pose, name, space)
            error = (actual.translation - original.translation).length()
            maximum_error = max(maximum_error, error)
            cosine = abs(sum(a * b for a, b in zip(actual.rotation.to_tuple(), original.rotation.to_tuple())))
            if error > 0.02 or cosine < 0.99999:
                raise RuntimeError('ACTION_INITIAL_POSE_CHANGED: %s frame=%d cm=%f cosine=%f' % (name, frame, error, cosine))
    if data.get('status') not in ('track_created', 'keys_written'):
        sequence = _prepare_sequence(data, animation, count)
        _write_keys(data, sequence, keys, finger_keys, count, 'create')
        data['status'] = 'track_created'
        _save(path, data)
        return {'status': data['status'], 'next': 'prepare_action', 'runtimeModified': False}
    if data['status'] == 'track_created':
        _write_keys(data, sequence, keys, finger_keys, count, 'write')
        data['status'] = 'keys_written'
        _save(path, data)
        return {'status': data['status'], 'next': 'prepare_action', 'runtimeModified': False}
    finger_validation = _verify_finger_edit(instance)
    _write_keys(data, sequence, keys, finger_keys, count, 'verify')
    player_error = _verify_sequence(data, sequence, animation, mesh, count)
    preview = _previews(data, sequence, animation, count)
    data['status'] = 'previews_created'
    data['source_track_digest'] = _digest(animation)
    data['frames'] = count
    data['frame_rate'] = [rate.numerator, rate.denominator]
    data['controls'] = list(control_map) + ['fk_' + n for n in fingers]
    data['validation'] = {'all_frames_source_position_error_cm': maximum_error, 'sequence_export_position_error_cm': player_error, 'finger_fk': finger_validation, 'runtimeModified': False, 'humanEdited': False}
    data['weapon_preview'] = preview
    _save(path, data)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    return {'status': data['status'], 'sequence': data['sequence'], 'rig': data['rig'], 'controls': data['controls'],
            'frames': count, 'validation': data['validation'], 'next': 'prepare_action'}
