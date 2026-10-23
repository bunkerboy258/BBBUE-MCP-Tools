import json
import uuid

import unreal

from BBBAssetWritePolicy import require_asset_write


FULL_CHARACTER_MESH = '/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Sk_CombinedMesh'
PREVIEW_BINDING_TAG = 'BBB_WeaponCharacterPreview'
WEAPON_ROOT = '/Game/_Project/Characters/BBBC_UA/Items/Equipment/'


def mesh_binding(sequence, mesh):
    """/** @param sequence\t制作序列 @param mesh\t计算或显示网格 @return\t精确网格或明确映射的角色绑定 */"""
    matches = [binding for binding in sequence.get_bindings()
               if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
               and binding.get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset() == mesh]
    if not matches:
        preview = resolve_binding(sequence, mesh)
        if preview is not None:
            matches.append(preview)
    if len(matches) != 1:
        raise RuntimeError('CHARACTER_PREVIEW_BINDING_NOT_UNIQUE')
    return matches[0]


def resolve_binding(sequence, mesh):
    """/** @param sequence\t制作序列 @param mesh\t计算网格 @return\t显式预览映射所指定的唯一角色绑定 */"""
    encoded = unreal.EditorAssetLibrary.get_metadata_tag(sequence, PREVIEW_BINDING_TAG)
    if not encoded:
        return None
    mapping = json.loads(encoded)
    if mapping['source_mesh'] != mesh.get_path_name().split('.')[0]:
        return None
    matches = [binding for binding in sequence.get_bindings()
               if binding.get_id().export_text() == mapping['binding']]
    if len(matches) != 1:
        raise RuntimeError('CHARACTER_PREVIEW_BINDING_CHANGED')
    actor = matches[0].get_object_template()
    if not isinstance(actor, unreal.SkeletalMeshActor):
        raise RuntimeError('CHARACTER_PREVIEW_ACTOR_CHANGED')
    displayed = actor.skeletal_mesh_component.get_skeletal_mesh_asset()
    if displayed.get_path_name().split('.')[0] != mapping['preview_mesh']:
        raise RuntimeError('CHARACTER_PREVIEW_MESH_CHANGED')
    if displayed.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise RuntimeError('CHARACTER_PREVIEW_SKELETON_CHANGED')
    return matches[0]


def prepare(sequence, mesh, source):
    """/** @param sequence\t项目武器制作序列 @param mesh\t保持不变的计算网格 @param source\t导出核对源动画 @return\t完整人物预览与关键帧保持证据 */"""
    from BBBManualActionNative import _channel_digest, _copy_sequence, _export, _compare

    path = sequence.get_path_name().split('.')[0]
    if not path.startswith(WEAPON_ROOT) or '/Animation/work/' not in path:
        raise RuntimeError('CHARACTER_PREVIEW_WEAPON_SEQUENCE_SCOPE')
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('CHARACTER_PREVIEW_PIE_ACTIVE')
    target = unreal.load_asset(FULL_CHARACTER_MESH)
    if not isinstance(target, unreal.SkeletalMesh) or mesh.get_editor_property('skeleton') != target.get_editor_property('skeleton'):
        raise RuntimeError('CHARACTER_PREVIEW_SKELETON_MISMATCH')
    binding = mesh_binding(sequence, mesh)
    component = binding.get_object_template().skeletal_mesh_component
    current = component.get_skeletal_mesh_asset()
    if current == target:
        return {'modified': False, 'sequence': path, 'preview_mesh': FULL_CHARACTER_MESH}
    signature = _channel_digest(sequence)
    identifier = binding.get_id().export_text()
    scope = unreal.new_object(unreal.LevelSequence, name='BBBFullCharacterPreview_' + uuid.uuid4().hex)
    previous_tag = unreal.EditorAssetLibrary.get_metadata_tag(sequence, PREVIEW_BINDING_TAG)
    original_materials = list(component.get_editor_property('override_materials'))
    saved = False
    try:
        before = _export(sequence, source, current, scope, 'Before')
        candidate = _copy_sequence(sequence, scope, 'Candidate')
        candidate_binding = mesh_binding(candidate, current)
        candidate_binding.get_object_template().skeletal_mesh_component.set_skeletal_mesh_asset(target)
        candidate_binding.get_object_template().skeletal_mesh_component.set_editor_property('override_materials', [])
        after = _export(candidate, source, target, scope, 'After')
        error = _compare(before, after)
        require_asset_write([sequence])
        sequence.modify()
        component.modify()
        component.set_skeletal_mesh_asset(target)
        component.set_editor_property('override_materials', [])
        mapping = {'binding': identifier, 'source_mesh': mesh.get_path_name().split('.')[0], 'preview_mesh': FULL_CHARACTER_MESH}
        unreal.EditorAssetLibrary.set_metadata_tag(sequence, PREVIEW_BINDING_TAG, json.dumps(mapping))
        if _channel_digest(sequence) != signature or mesh_binding(sequence, mesh).get_id().export_text() != identifier:
            raise RuntimeError('CHARACTER_PREVIEW_KEYS_OR_BINDING_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('CHARACTER_PREVIEW_SAVE_FAILED')
        saved = True
        library = unreal.LevelSequenceEditorBlueprintLibrary
        if library.get_current_level_sequence() == sequence:
            frame = library.get_current_time()
            unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).close_all_editors_for_asset(sequence)
            library.open_level_sequence(sequence)
            library.set_current_time(frame)
            library.force_update()
        return {'modified': True, 'sequence': path, 'preview_mesh': FULL_CHARACTER_MESH,
                'keys_preserved': True, 'binding_preserved': True, 'native_bone_track_error_cm': error}
    except Exception:
        if saved:
            raise
        component.set_skeletal_mesh_asset(current)
        component.set_editor_property('override_materials', original_materials)
        if previous_tag:
            unreal.EditorAssetLibrary.set_metadata_tag(sequence, PREVIEW_BINDING_TAG, previous_tag)
        if not previous_tag:
            unreal.EditorAssetLibrary.remove_metadata_tag(sequence, PREVIEW_BINDING_TAG)
        raise
    finally:
        unreal.purge_object_references(scope, True)


def prepare_grip(recipe, path, project):
    """/** @param recipe\t握姿制作源 @param path\t源文件 @param project\t项目根 @return\t仅显示变更的证据并保持已有效的应用指纹 */"""
    from BBBGripAuthoringToolset import _asset, _fingerprint, _write_recipe

    previous = _fingerprint(recipe, project)
    was_valid = recipe.get('validation', {}).get('fingerprint') == previous and previous is not None
    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    result = prepare(sequence, _asset(recipe['character_mesh'], unreal.SkeletalMesh),
                     _asset(recipe['animation'], unreal.AnimSequence))
    if result['modified']:
        current = _fingerprint(recipe, project)
        if was_valid:
            recipe['validation']['fingerprint'] = current
            if recipe.get('review', {}).get('fingerprint') == previous:
                recipe['review']['fingerprint'] = current
            for dependent_path in path.parent.glob('*.json.source'):
                dependent = json.loads(dependent_path.read_text(encoding='utf-8-sig'))
                reference = dependent.get('grip_recipe_path')
                if reference and (project / reference).resolve() == path.resolve() and dependent.get('grip_fingerprint') == previous:
                    dependent['grip_fingerprint'] = current
                    _write_recipe(dependent_path, dependent, project)
        recipe['character_preview'] = result
    requested = recipe.pop('full_character_preview_request', False)
    if isinstance(requested, dict):
        other_results = []
        for asset_path in requested.get('sequences', []):
            if asset_path.rsplit('/', 1)[0] != recipe['weapon_root'] + '/Animation/work':
                raise RuntimeError('CHARACTER_PREVIEW_RECIPE_SEQUENCE_SCOPE')
            other = _asset(asset_path, unreal.LevelSequence)
            mesh = _asset(recipe['character_mesh'], unreal.SkeletalMesh)
            candidates = [binding for binding in other.get_bindings()
                          if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
                          and binding.get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset().get_editor_property('skeleton') == mesh.get_editor_property('skeleton')]
            if len(candidates) != 1:
                raise RuntimeError('CHARACTER_PREVIEW_EXISTING_CHARACTER_NOT_UNIQUE: ' + asset_path)
            mesh = candidates[0].get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset()
            source = _asset(recipe['animation'], unreal.AnimSequence)
            animations = [section.get_editor_property('params').animation
                          for track in candidates[0].find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack)
                          for section in track.get_sections() if section.get_editor_property('params').animation]
            if animations:
                source = animations[0]
            other_results.append(prepare(other, mesh, source))
        result['additional_sequences'] = other_results
    if result['modified'] or requested:
        _write_recipe(path, recipe, project)
    return result
