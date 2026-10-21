import uuid
import hashlib
import json

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _mesh_binding
from BBBManualActionAuthoring import _source, _save, _digest


def configure_visible_controls(data, sequence):
    """/** @param data\t显式可见控制器列表 @param sequence\t当前制作序列 @return\t保留全部关键帧的控制器显示过滤 */"""
    if 'visible_controls' not in data:
        return None
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    allowed = set(data['visible_controls'])
    keys = asset.hierarchy.get_controls()
    names = {str(key.name) for key in keys}
    if not allowed or not allowed <= names or any(name.startswith('source_') for name in allowed):
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_SCOPE')
    signature = _channel_digest(sequence)
    require_asset_write([asset])
    hierarchies = [asset.hierarchy] + [p.control_rig.get_hierarchy() for p in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)]
    for hierarchy in hierarchies:
        for key in keys:
            settings = hierarchy.get_control_settings(key)
            settings.shape_visible = str(key.name) in allowed
            hierarchy.set_control_settings(key, settings, False, True, False)
        actual = {str(key.name) for key in keys if hierarchy.get_control_settings(key).shape_visible}
        if actual != allowed:
            raise RuntimeError('ACTION_VISIBLE_CONTROLS_READBACK')
    if _channel_digest(sequence) != signature:
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_CHANGED_KEYS')
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_SAVE')
    return {'visible_controls': sorted(allowed), 'all_keys_preserved': True, 'controls_deleted': False}


def _channel_digest(sequence, excluded_sections=()):
    """/** @param sequence\t现有制作序列 @return\t全部通道时间值及默认值摘要 */"""
    rows = []
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                if section in excluded_sections:
                    continue
                channels = []
                for channel in section.get_all_channels():
                    keys = []
                    for key in channel.get_keys():
                        stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                        keys.append([stamp.frame_number.value, stamp.sub_frame, str(key.get_value())])
                    default = None
                    if hasattr(channel, 'get_default'):
                        default = str(channel.get_default())
                    channels.append([str(channel.channel_name), default, keys])
                rows.append([binding.get_id().export_text(), section.get_path_name(), channels])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def copy_offset_keys(path, data, sequence):
    """/** @param path\t目标制作源 @param data\t显式Offset输入 @param sequence\t目标LS @return\t只复制原生叠加键及切线 不烘焙 */"""
    if not data.get('offset_source_recipe'):
        return None
    if data.get('offset_copy'):
        return data['offset_copy']
    _, source_data = _source(data['offset_source_recipe'])
    if source_data['action'] != data['action'] or source_data['animation'] != data['animation'] or source_data['sequence'] == data['sequence']:
        raise RuntimeError('OFFSET_COPY_ACTION_SOURCE')
    source = _asset(source_data['sequence'], unreal.LevelSequence)
    for getter in ('get_display_rate', 'get_tick_resolution'):
        left, right = getattr(source, getter)(), getattr(sequence, getter)()
        if left.numerator * right.denominator != right.numerator * left.denominator:
            raise RuntimeError('OFFSET_COPY_FRAME_RATE: ' + getter)
    def layer(target):
        sections = [s for b in target.get_bindings() for t in b.get_tracks()
                    if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()
                    if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(sections) != 1:
            raise RuntimeError('OFFSET_COPY_SINGLE_LAYER')
        return sections[0]
    fields = ('interpolation_mode', 'tangent_mode', 'tangent_weight_mode', 'arrive_tangent', 'leave_tangent', 'arrive_tangent_weight', 'leave_tangent_weight')
    def snapshot(section):
        values = {}
        for channel in section.get_all_channels():
            keys = []
            for key in channel.get_keys():
                time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                keys.append({'frame': time.frame_number.value, 'sub': time.sub_frame, 'value': key.get_value(),
                             **{f: getattr(key, 'get_' + f)() for f in fields}})
            values[str(channel.channel_name)] = {'default': channel.get_default() if channel.has_default() else None, 'keys': keys}
        return values
    source_layer, target_layer = layer(source), layer(sequence)
    values = snapshot(source_layer)
    signature = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    channels = {str(c.channel_name): c for c in target_layer.get_all_channels()}
    if set(values) != set(channels) or source_layer.get_start_frame() != target_layer.get_start_frame() or source_layer.get_end_frame() != target_layer.get_end_frame():
        raise RuntimeError('OFFSET_COPY_CHANNELS_OR_RANGE')
    preserved = _channel_digest(sequence, [target_layer])
    require_asset_write([sequence])
    target_layer.set_is_locked(False)
    for name, row in values.items():
        channel = channels[name]
        for key in list(channel.get_keys()):
            channel.remove_key(key)
        if row['default'] is None:
            channel.remove_default()
        else:
            channel.set_default(row['default'])
        for row_key in row['keys']:
            key = channel.add_key(unreal.FrameNumber(value=row_key['frame']), row_key['value'], row_key['sub'], unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            for field in fields:
                getattr(key, 'set_' + field)(row_key[field])
    if snapshot(target_layer) != values or _channel_digest(sequence, [target_layer]) != preserved:
        raise RuntimeError('OFFSET_COPY_READBACK_OR_BASE_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('OFFSET_COPY_SAVE')
    result = {'source_sequence': source_data['sequence'], 'source_digest': signature,
              'key_count': sum(len(r['keys']) for r in values.values()),
              'keyed_channels': sum(bool(r['keys']) for r in values.values()),
              'tangents_preserved': True, 'base_and_attachments_preserved': True, 'baked': False}
    data['offset_copy'] = result
    data['runtime_applied'] = False
    _save(path, data)
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    return result


def prepare_preview_mesh(data, sequence):
    """/** @param data\t正式制作源 @param sequence\t保留手调的序列 @return\t同骨架完整手臂预览更新证据 */"""
    destination = data.get('preview_mesh', '/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Arms/SK_arms')
    original = _asset(data['mesh'], unreal.SkeletalMesh)
    target = _asset(destination, unreal.SkeletalMesh)
    if original == target:
        return
    if original.get_editor_property('skeleton') != target.get_editor_property('skeleton'):
        raise RuntimeError('ACTION_PREVIEW_SKELETON_MISMATCH')
    require_asset_write([sequence])
    binding = _mesh_binding(sequence, original)
    component = binding.get_object_template().skeletal_mesh_component
    signature = _channel_digest(sequence)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBPreviewMesh_' + uuid.uuid4().hex)
    try:
        before = _export(sequence, source, original, scope, 'Before')
        sequence.modify()
        component.modify()
        component.set_skeletal_mesh_asset(target)
        after = _export(sequence, source, target, scope, 'After')
        error = _compare(before, after)
        if _channel_digest(sequence) != signature or _mesh_binding(sequence, target).get_id().export_text() != binding.get_id().export_text():
            raise RuntimeError('ACTION_PREVIEW_KEYS_OR_BINDING_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('ACTION_PREVIEW_MESH_SAVE')
        data['mesh'] = destination
        data['preview_mesh'] = destination
        data['preview_mesh_update'] = {'channel_digest': signature, 'keys_preserved': True,
                                       'binding_preserved': True, 'native_bone_track_error_cm': error}
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    except Exception:
        component.set_skeletal_mesh_asset(original)
        raise
    finally:
        unreal.purge_object_references(scope, True)


def _export(sequence, source, mesh, scope, name, duplicate=True):
    """/** @param sequence\t制作序列 @param source\t源动画 @param mesh\t网格 @param scope\t瞬态作用域 @param name\t名称 @return\t官方直接导出结果 */"""
    copied = sequence
    if duplicate:
        copied = unreal.SystemLibrary.duplicate_object(sequence, scope, name + 'Sequence')
    result = unreal.SystemLibrary.duplicate_object(source, scope, name + 'Animation')
    if duplicate:
        copied.set_display_rate(unreal.FrameRate(numerator=120, denominator=1))
        copied.set_playback_start(0)
        copied.set_playback_end(round(source.get_play_length() * 120))
    options = unreal.AnimSeqExportOption()
    options.export_transforms = True
    options.export_morph_targets = False
    options.export_attribute_curves = False
    options.export_material_curves = False
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not unreal.SequencerTools.export_anim_sequence(world, copied, result, options, _mesh_binding(copied, mesh), False):
        raise RuntimeError('NATIVE_ACTION_EXPORT_FAILED')
    if duplicate and abs(result.get_play_length() - source.get_play_length()) > 0.0001:
        raise RuntimeError('NATIVE_ACTION_EXPORT_LENGTH: ' + str(result.get_play_length()))
    return result


def _compare(first, second):
    """/** @param first\t预期输出 @param second\t实际输出 @return\t全轨最大位置误差 */"""
    maximum = 0.0
    for name in first.data_model_interface.get_bone_track_names():
        a = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(first, name)
        b = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(second, name)
        if len(a) != len(b):
            raise RuntimeError('NATIVE_ACTION_KEYS: ' + str(name))
        for left, right in zip(a, b):
            error = (left.translation - right.translation).length()
            maximum = max(maximum, error)
            cosine = abs(sum(x * y for x, y in zip(left.rotation.to_tuple(), right.rotation.to_tuple())))
            if error > 0.02 or cosine < 0.99999 or (left.scale3d - right.scale3d).length() > 0.0001:
                raise RuntimeError('NATIVE_ACTION_POSE: ' + str(name) + ' cm=' + str(error))
    return maximum


def prepare_offset(data, sequence):
    """/** @param data\t制作源 @param sequence\t原序列 @return\t自动建立并选中原生叠加段 保留原键 */"""
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    tracks = _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1:
        raise RuntimeError('NATIVE_OFFSET_SINGLE_TRACK')
    track = tracks[0]
    sections = list(track.get_sections())
    layers = [section for section in sections if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(layers) > 1:
        raise RuntimeError('NATIVE_OFFSET_MULTIPLE_LAYERS')
    if not layers:
        if len(sections) != 1:
            raise RuntimeError('NATIVE_OFFSET_SINGLE_BASE')
        require_asset_write([sequence])
        unreal.LevelSequenceEditorBlueprintLibrary.empty_selection()
        scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeOffset_' + uuid.uuid4().hex)
        layer = None
        try:
            before = _export(sequence, source, mesh, scope, 'Before')
            layer = track.add_section()
            layer.set_blend_type(unreal.MovieSceneBlendType.ADDITIVE)
            layer.set_range(sections[0].get_start_frame(), sections[0].get_end_frame())
            layer.set_row_index(1)
            unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            _export(sequence, source, mesh, scope, 'Initialize', False)
            for channel in layer.get_all_channels():
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
                value = 0.0
                if str(channel.channel_name) == 'Weight':
                    value = 1.0
                channel.set_default(value)
            unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            after = _export(sequence, source, mesh, scope, 'After')
            error = _compare(before, after)
            data['native_offset'] = {'mode': 'native_additive_section', 'neutral_export_error_cm': error,
                                     'base_keys_preserved': True, 'custom_interpolation': False}
        except Exception:
            if layer is not None:
                track.remove_section(layer)
                unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            raise
        finally:
            unreal.purge_object_references(scope, True)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('NATIVE_OFFSET_SAVE')
        layers = [layer]
    unreal.LevelSequenceEditorBlueprintLibrary.empty_selection()
    unreal.LevelSequenceEditorBlueprintLibrary.select_sections(layers)
    for section in track.get_sections():
        section.set_is_locked(section not in layers)
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('NATIVE_OFFSET_LOCK_SAVE')
    if 'probe_left_delta_cm' not in data.get('native_offset', {}):
        scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeProbe_' + uuid.uuid4().hex)
        try:
            neutral = _export(sequence, source, mesh, scope, 'Neutral')
            probe = unreal.SystemLibrary.duplicate_object(sequence, scope, 'Probe')
            _export(probe, source, mesh, scope, 'InitializeProbe', False)
            probe_track = _mesh_binding(probe, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)[0]
            probe_layer = [item for item in probe_track.get_sections() if item.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE][0]
            channels = {str(channel.channel_name): channel for channel in probe_layer.get_all_channels()}
            channels['hand_l_ik_ctrl.Location.X'].set_default(1.0)
            moved = _export(probe, source, mesh, scope, 'Moved')
            from BBBControlRigAuthoringToolset import _pose
            a = _pose(neutral, mesh, 0)
            b = _pose(moved, mesh, 0)
            errors = {}
            for bone in ('hand_l', 'hand_r'):
                errors[bone] = (unreal.AnimPoseExtensions.get_bone_pose(a, bone, unreal.AnimPoseSpaces.WORLD).translation - unreal.AnimPoseExtensions.get_bone_pose(b, bone, unreal.AnimPoseSpaces.WORLD).translation).length()
            if errors['hand_l'] < 0.1 or errors['hand_l'] > 2.0 or errors['hand_r'] > 0.02:
                raise RuntimeError('NATIVE_OFFSET_PROBE: ' + str(errors))
            data['native_offset']['probe_left_delta_cm'] = errors['hand_l']
            data['native_offset']['probe_right_delta_cm'] = errors['hand_r']
        finally:
            unreal.purge_object_references(scope, True)
    return {'mode': 'native_additive_section', 'sections': len(track.get_sections()), 'custom_interpolation': False}


def inspect_manual(recipe_path, write_paths):
    """/** @param recipe_path\t制作源 @param write_paths\t占用范围 @return\t实际段与通道状态 不解释人工修改意图 */"""
    path, data = _source(recipe_path)
    if set(write_paths) != {data['sequence'], data['rig']}:
        raise RuntimeError('NATIVE_ACTION_INSPECT_SCOPE')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    tracks = _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1:
        raise RuntimeError('NATIVE_ACTION_INSPECT_TRACK')
    rows = []
    for section in tracks[0].get_sections():
        rows.append({'blend': str(section.get_blend_type().blend_type), 'row': section.get_row_index(),
                     'channels': [{'name': str(channel.channel_name), 'keys': len(channel.get_keys())}
                                  for channel in section.get_all_channels() if len(channel.get_keys())]})
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBCommonInspect_' + uuid.uuid4().hex)
    evidence = {}
    try:
        baked = _export(sequence, source, mesh, scope, 'Visible')
        evidence['native_sample_keys'] = baked.data_model_interface.get_number_of_keys()
        from BBBCommonActionSources import is_finger
        from BBBControlRigAuthoringToolset import _pose
        maximum = 0.0
        minimum_cosine = 1.0
        rate = sequence.get_display_rate()
        names = [n for n in source.data_model_interface.get_bone_track_names() if is_finger(n)]
        for frame in range(source.data_model_interface.get_number_of_keys()):
            time = frame * rate.denominator / rate.numerator
            expected = _pose(source, mesh, time)
            actual = _pose(baked, mesh, time)
            for name in names:
                a = unreal.AnimPoseExtensions.get_bone_pose(expected, name, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(actual, name, unreal.AnimPoseSpaces.LOCAL)
                maximum = max(maximum, (a.translation - b.translation).length())
                minimum_cosine = min(minimum_cosine, abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))))
        evidence['finger_source_position_error_cm'] = maximum
        evidence['finger_source_rotation_cosine_min'] = minimum_cosine
        output = unreal.load_asset(data['output_animation'])
        if output is not None:
            try:
                evidence['existing_output_error_cm'] = _compare(baked, output)
                evidence['existing_output_matches_preview'] = True
            except RuntimeError as error:
                evidence['existing_output_matches_preview'] = False
                evidence['difference'] = str(error)
    finally:
        unreal.purge_object_references(scope, True)
    return {'sequence': data['sequence'], 'sections': rows, 'bake_mode': 'official_sequencer_direct',
            'source_matches_preparation': _digest(_asset(data['animation'], unreal.AnimSequence)) == data['source_track_digest'],
            'common_source': data['animation'], 'output_animation': data['output_animation'],
            'native_evidence': evidence, 'custom_interpolation': False, 'assetModified': False}


def bake_animation(recipe_path, write_paths):
    """/** @param recipe_path\t制作源 @param write_paths\t唯一成品 @return\t序列实际求值的直接烘焙及回读 */"""
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('NATIVE_ACTION_PIE_FORBIDDEN')
    path, data = _source(recipe_path)
    destination = data['output_animation']
    if set(write_paths) != {destination} or destination.rsplit('/', 1)[0] != data['weapon_root'] + '/Animation/Sequence':
        raise RuntimeError('NATIVE_ACTION_WRITE_SCOPE')
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    if _digest(_asset(data['animation'], unreal.AnimSequence)) != data['source_track_digest']:
        raise RuntimeError('NATIVE_ACTION_SOURCE_CHANGED')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    output = unreal.load_asset(destination)
    if output is None:
        require_asset_write([], destinations=[destination])
        output = unreal.EditorAssetLibrary.duplicate_asset(data['finger_animation'], destination)
    if not isinstance(output, unreal.AnimSequence):
        raise RuntimeError('NATIVE_ACTION_OUTPUT_TYPE')
    require_asset_write([output])
    scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeBake_' + uuid.uuid4().hex)
    try:
        baked = _export(sequence, source, _asset(data['mesh'], unreal.SkeletalMesh), scope, 'Visible')
        controller = output.controller
        controller.open_bracket('直接烘焙序列可见结果', False)
        try:
            controller.remove_all_bone_tracks(False)
            controller.set_frame_rate(baked.data_model_interface.get_frame_rate(), False)
            controller.set_number_of_frames(unreal.FrameNumber(value=baked.data_model_interface.get_number_of_keys() - 1), False)
            for name in baked.data_model_interface.get_bone_track_names():
                values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(baked, name)
                if not controller.add_bone_track(name, False) or not controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                    raise RuntimeError('NATIVE_ACTION_WRITE_BONE: ' + str(name))
        finally:
            controller.close_bracket(False)
        if unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(_asset(data['finger_animation'], unreal.AnimSequence), output) < 0:
            raise RuntimeError('NATIVE_ACTION_CURVES')
        error = _compare(baked, output)
        if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('NATIVE_ACTION_SAVE')
        result = {'animation': destination, 'bake_mode': 'official_sequencer_direct', 'custom_interpolation': False,
                  'sample_keys': output.data_model_interface.get_number_of_keys(), 'seconds': output.get_play_length(),
                  'native_track_error_cm': error, 'visualAcceptance': 'pending', 'runtimeReferenceChanged': False}
        data['bake_result'] = result
        data['runtime_applied'] = False
        _save(path, data)
        return result
    finally:
        unreal.purge_object_references(scope, True)
