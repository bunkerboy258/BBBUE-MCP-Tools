import uuid
import hashlib
import json

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _mesh_binding
from BBBManualActionAuthoring import _source, _save, _digest


def _channel_digest(sequence):
    """/** @param sequence\t现有制作序列 @return\t全部通道时间值及默认值摘要 */"""
    rows = []
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
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
    source = _asset(data['animation'], unreal.AnimSequence)
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
    source = _asset(data['animation'], unreal.AnimSequence)
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
    return {'sequence': data['sequence'], 'sections': rows, 'bake_mode': 'official_sequencer_direct',
            'source_matches_preparation': _digest(_asset(data['animation'], unreal.AnimSequence)) == data['source_track_digest'],
            'custom_interpolation': False, 'assetModified': False}


def bake_review(recipe_path, write_paths):
    """/** @param recipe_path\t制作源 @param write_paths\t唯一成品 @return\t序列实际求值的直接烘焙及回读 */"""
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('NATIVE_ACTION_PIE_FORBIDDEN')
    path, data = _source(recipe_path)
    destination = data['review_bake']['animation']
    if set(write_paths) != {destination} or destination.rsplit('/', 1)[0] != data['weapon_root'] + '/Animation/Sequence':
        raise RuntimeError('NATIVE_ACTION_WRITE_SCOPE')
    source = _asset(data['animation'], unreal.AnimSequence)
    if _digest(source) != data['source_track_digest']:
        raise RuntimeError('NATIVE_ACTION_SOURCE_CHANGED')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    output = _asset(destination, unreal.AnimSequence)
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
        if unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(source, output) < 0:
            raise RuntimeError('NATIVE_ACTION_CURVES')
        error = _compare(baked, output)
        if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('NATIVE_ACTION_SAVE')
        result = {'animation': destination, 'bake_mode': 'official_sequencer_direct', 'custom_interpolation': False,
                  'sample_keys': output.data_model_interface.get_number_of_keys(), 'seconds': output.get_play_length(),
                  'native_track_error_cm': error, 'visualAcceptance': 'pending', 'runtimeReferenceChanged': False}
        data['review_bake']['direct_result'] = result
        data['review_bake']['human_visual_acceptance'] = 'pending'
        _save(path, data)
        return result
    finally:
        unreal.purge_object_references(scope, True)
