"""特感正式资源装配 只维护明确的自有输出 不承担玩法裁决。"""

import json
import re
import os
import hashlib

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBGenericEditorToolset import _apply_editor_property


def import_prefabs(destination_root, prefab_root, source_mesh_path, part_ids):
    """/** @param destination_root 自有特感目录 @param prefab_root 同名伤口目录 @param source_mesh_path 只读原身体 @param part_ids 分段导入的断点编号 @return 资产保存与原始制作源校验 */"""
    match = re.fullmatch(r'/Game/_Project/Mass/Monster/SpecialInfected/(UrbanZombie[234]|Whisper)', destination_root)
    if not match or prefab_root != '/Game/_Project/Mass/Monster/Zombie/Shared/Injury/'+match[1]:
        raise RuntimeError('需要同名的特感与预制目录')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间等待预制资源导入')
    if len(part_ids) > 3 or len(set(part_ids)) != len(part_ids):
        raise RuntimeError('每次最多三个互不重复的断点')
    name = match[1]
    project = os.path.abspath(unreal.Paths.project_dir())
    production = os.path.join(project, 'ArtSource', 'ZombieDestruction', 'Production', name)
    severing = os.path.join(project, 'ArtSource', 'ZombieInjury', 'Production', name)
    with open(os.path.join(severing, 'Severing.json'), encoding='utf-8-sig') as stream:
        parts = json.load(stream)['parts']
    with open(os.path.join(project, 'ArtSource', 'ZombieDestruction', 'BodyMaterials.json'), encoding='utf-8-sig') as stream:
        material_specs = next(value['materials'] for value in json.load(stream)['variants'] if value['name'] == name)
    source = unreal.load_asset(source_mesh_path)
    if not isinstance(source, unreal.SkeletalMesh):
        raise RuntimeError('源身体类型错误')
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = unreal.EditorAssetLibrary
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    root = destination_root+'/Mesh'
    require_asset_write([], destinations=[root, prefab_root])
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(path.startswith((destination_root+'/', prefab_root+'/')) for path in dirty):
        raise RuntimeError('自有目标存在未保存修改 先处理后再导入')

    def duplicate(source_asset, asset_name):
        path = root+'/'+asset_name
        existing = unreal.load_asset(path) if assets.does_asset_exist(path) else None
        if existing:
            if str(assets.get_metadata_tag(existing, 'BBB.SpecialSource')) != source_asset.get_path_name():
                raise RuntimeError('同名资源不属于此制作源 '+path)
            return existing
        value = tools.duplicate_asset(asset_name, root, source_asset)
        if not value:
            raise RuntimeError('资源复制失败 '+path)
        assets.set_metadata_tag(value, 'BBB.SpecialSource', source_asset.get_path_name())
        if not assets.save_loaded_asset(value, False):
            raise RuntimeError('资源保存失败 '+path)
        return value

    skeleton_path = root+'/SKEL_'+name
    skeleton = unreal.load_asset(skeleton_path) if assets.does_asset_exist(skeleton_path) else None
    physics = duplicate(source.get_editor_property('physics_asset'), 'PA_'+name)
    material_map = {item['slot']: unreal.load_asset(item['source']) for item in material_specs}
    if any(value is None for value in material_map.values()):
        raise RuntimeError('源身体材质缺失')
    jobs = []
    if not part_ids:
        jobs = [(root, 'SKM_'+name, [os.path.join(production, 'Body_LOD'+str(lod)+'.fbx') for lod in range(3)], True),
                (prefab_root, 'SK_Destruction', [os.path.join(production, 'SK_Destruction_LOD'+str(lod)+'.fbx') for lod in range(3)], True)]
    else:
        for part_id in part_ids:
            part = next((value for value in parts if value['id'] == part_id), None)
            if part is None:
                raise RuntimeError('未知断点 '+str(part_id))
            tissue_files = [os.path.join(severing, value['file']) for value in part['tissueLODs']]
            jobs.append((prefab_root, os.path.basename(tissue_files[0]).replace('_LOD0.fbx', ''), tissue_files, True))
            for key in ('detachedSkin', 'detachedMesh', 'remainingSkin', 'remainingMesh'):
                if key in part:
                    filename = part[key]
                    jobs.append((prefab_root, filename[:-4], [os.path.join(severing, filename)], key.endswith('Skin')))
    for folder, asset_name, files, skeletal in jobs:
        if any(not os.path.isfile(value) for value in files):
            raise RuntimeError('正式制作源缺失 '+asset_name)
    reports = []
    previous = unreal.SystemLibrary.get_console_variable_bool_value('Interchange.FeatureFlags.Import.FBX')
    try:
        unreal.SystemLibrary.execute_console_command(None, 'Interchange.FeatureFlags.Import.FBX 0')
        for folder, asset_name, files, skeletal in jobs:
            path = folder+'/'+asset_name
            digest = hashlib.sha256()
            digest.update(json.dumps(material_specs, sort_keys=True).encode())
            for filename in files:
                with open(filename, 'rb') as stream:
                    for block in iter(lambda: stream.read(1024*1024), b''):
                        digest.update(block)
            fingerprint = digest.hexdigest()
            existing = assets.does_asset_exist(path)
            value = unreal.load_asset(path) if existing else None
            expected = unreal.SkeletalMesh if skeletal else unreal.StaticMesh
            if existing:
                if not isinstance(value, expected) or str(assets.get_metadata_tag(value, 'BBB.SpecialSourceHash')) != fingerprint:
                    raise RuntimeError('目标存在但来源不符 不覆盖 '+path)
                if skeletal and (value.get_editor_property('skeleton') != skeleton or subsystem.get_lod_count(value) != len(files)):
                    raise RuntimeError('已有网格骨架或LOD不完整 '+path)
                reports.append({'asset': path, 'sourceHash': fingerprint, 'alreadySaved': True})
                continue
            options = unreal.FbxImportUI()
            options.automated_import_should_detect_type = False
            options.import_mesh = True
            options.import_as_skeletal = skeletal
            options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH if skeletal else unreal.FBXImportType.FBXIT_STATIC_MESH
            options.original_import_type = options.mesh_type_to_import
            options.import_materials = False
            options.import_textures = False
            options.import_animations = False
            options.create_physics_asset = False
            if skeletal:
                options.skeleton = skeleton
                options.skeletal_mesh_import_data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
                options.skeletal_mesh_import_data.set_editor_property('update_skeleton_reference_pose', False)
                options.skeletal_mesh_import_data.set_editor_property('use_t0_as_ref_pose', False)
            else:
                options.static_mesh_import_data.combine_meshes = True
                options.static_mesh_import_data.auto_generate_collision = False
                options.static_mesh_import_data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
            task = unreal.AssetImportTask()
            task.filename = files[0]
            task.destination_path = folder
            task.destination_name = asset_name
            task.automated = True
            task.replace_existing = False
            task.save = False
            task.options = options
            task.factory = unreal.FbxFactory()
            tools.import_asset_tasks([task])
            values = [item for item in task.get_objects() if isinstance(item, expected)]
            if len(values) != 1 or values[0].get_outermost().get_path_name() != path:
                raise RuntimeError('导入未返回唯一目标 '+path)
            value = values[0]
            if skeletal:
                if skeleton is None:
                    if asset_name != 'SKM_'+name:
                        raise RuntimeError('需要先导入正式身体建立专属骨架')
                    skeleton = value.get_editor_property('skeleton')
                    rename = unreal.AssetRenameData(skeleton, root, 'SKEL_'+name)
                    if not tools.rename_assets([rename]):
                        raise RuntimeError('专属骨架命名失败')
                    assets.set_metadata_tag(skeleton, 'BBB.SpecialSource', source.get_editor_property('skeleton').get_path_name())
                for lod, filename in enumerate(files[1:], 1):
                    if subsystem.import_lod(value, lod, filename) != lod:
                        raise RuntimeError('LOD导入失败 '+path)
                if value.get_editor_property('skeleton') != skeleton or subsystem.get_lod_count(value) != len(files):
                    raise RuntimeError('骨架或LOD回读失败 '+path)
                materials = list(value.get_editor_property('materials'))
                for slot in materials:
                    material = material_map.get(str(slot.material_slot_name))
                    if material:
                        slot.material_interface = material
                value.set_editor_property('materials', materials)
                if asset_name == 'SKM_'+name:
                    value.set_editor_property('physics_asset', physics)
            assets.set_metadata_tag(value, 'BBB.SpecialSourceHash', fingerprint)
            if not assets.save_loaded_asset(value, False):
                raise RuntimeError('导入资产保存失败 '+path)
            reports.append({'asset': path, 'sourceHash': fingerprint, 'lodCount': len(files), 'saved': True})
        if not assets.save_loaded_asset(skeleton, False):
            raise RuntimeError('专属骨架保存失败')
    finally:
        unreal.SystemLibrary.execute_console_command(None, 'Interchange.FeatureFlags.Import.FBX '+str(int(previous)))
    return json.dumps({'variant': name, 'skeleton': skeleton.get_path_name(), 'physics': physics.get_path_name(), 'assets': reports}, ensure_ascii=False)


def create_slime_assets(destination_root):
    """/** @param destination_root 不存在资源的自有目录 @return 三个已保存且互相绑定的粘液资源 */"""
    if not re.fullmatch(r'/Game/_Project/Mass/Monster/SpecialInfected/Shared/[A-Za-z0-9]+', destination_root):
        raise RuntimeError('需要明确的特感共享资源目录')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间等待粘液装配')
    names = ['M_Slime', 'MEC_Slime', 'DA_Slime']
    paths = [destination_root+'/'+value for value in names]
    if any(unreal.EditorAssetLibrary.does_asset_exist(path) for path in paths):
        raise RuntimeError('粘液资源已存在 使用明确配置工具继续')
    require_asset_write([], destinations=[destination_root])
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(names[0], destination_root, unreal.Material, unreal.MaterialFactoryNew())
    edit = unreal.MaterialEditingLibrary
    color = edit.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, -300, -100)
    color.set_editor_property('constant', unreal.LinearColor(0.012, 0.13, 0.003, 1))
    roughness = edit.create_material_expression(material, unreal.MaterialExpressionConstant, -300, 80)
    roughness.set_editor_property('r', 0.23)
    if not edit.connect_material_property(color, '', unreal.MaterialProperty.MP_BASE_COLOR):
        raise RuntimeError('粘液材质颜色连接失败')
    if not edit.connect_material_property(roughness, '', unreal.MaterialProperty.MP_ROUGHNESS):
        raise RuntimeError('粘液材质粗糙度连接失败')
    edit.recompile_material(material)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property('data_asset_class', unreal.MassEntityConfigAsset)
    config = tools.create_asset(names[1], destination_root, unreal.MassEntityConfigAsset, factory)
    trait = unreal.new_object(unreal.BBBSlimeTrait, outer=config, name='Slime')
    raw_config = config.get_editor_property('config')
    raw_config.set_editor_property('traits', [trait])
    config.set_editor_property('config', raw_config)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property('data_asset_class', unreal.BBBSlimeDefinition)
    definition = tools.create_asset(names[2], destination_root, unreal.BBBSlimeDefinition, factory)
    definition.set_editor_property('entity_config', config)
    definition.set_editor_property('material', material)
    for asset in (material, config, definition):
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError('粘液资产保存失败')
    return json.dumps({'saved': paths, 'definition': definition.get_path_name(), 'template': config.get_path_name()}, ensure_ascii=False)


def _validate_data_asset(logic):
    """/** @param logic 自有数据配置 @return UE原生数据校验计数 不启动游戏 */"""
    settings = unreal.ValidateAssetsSettings()
    settings.set_editor_property('skip_excluded_directories', False)
    settings.set_editor_property('show_if_no_failures', False)
    settings.set_editor_property('collect_per_asset_details', True)
    settings.set_editor_property('validation_usecase', unreal.DataValidationUsecase.SCRIPT)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    failures, result = unreal.get_editor_subsystem(unreal.EditorValidatorSubsystem).validate_assets_with_settings(
        [registry.get_asset_by_object_path(logic.get_path_name())], settings)
    report = {key: int(result.get_editor_property(key)) for key in
              ('num_checked', 'num_valid', 'num_invalid', 'num_warnings', 'num_unable_to_validate')}
    if failures or report['num_valid'] != 1 or report['num_invalid'] or report['num_unable_to_validate']:
        raise RuntimeError('特感逻辑数据校验失败 '+str(report)+' '+str(result.get_editor_property('assets_details')))
    return report


def build_variant(destination_root, prefab_root, recipe_json):
    """/** @param destination_root 自有特感目录 @param prefab_root 该变体预制伤口目录 @param recipe_json 完整身体 动作与两份配置的制作描述 @return 编译保存及回读结果 */"""
    recipe = json.loads(recipe_json)
    if not re.fullmatch(r'/Game/_Project/Mass/Monster/SpecialInfected/[A-Za-z0-9]+', destination_root):
        raise RuntimeError('目标必须为明确的特感自有目录')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间等待特感装配')
    name = destination_root.rsplit('/', 1)[1]
    if prefab_root != '/Game/_Project/Mass/Monster/Zombie/Shared/Injury/'+name:
        raise RuntimeError('预制目录必须与当前变体名称一致')
    mesh = unreal.load_asset(recipe['mesh'])
    source_logic = unreal.load_asset(recipe['source_logic'])
    source_presentation = unreal.load_asset(recipe['source_presentation'])
    source_actor = unreal.load_asset(recipe['source_actor'])
    if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(source_logic, unreal.BBBMonsterDefinition):
        raise RuntimeError('完整身体或逻辑基准类型错误')
    if not isinstance(source_presentation, unreal.BBBMonsterPresentationDefinition) or not isinstance(source_actor, unreal.Blueprint):
        raise RuntimeError('表现基准或载体类型错误')
    skeleton = mesh.get_editor_property('skeleton')
    sources = [unreal.load_asset(path) for path in recipe['sequences']]
    if len(sources) != 9 or any(not isinstance(value, unreal.AnimSequence) for value in sources):
        raise RuntimeError('需要待机 行走 跑步 攻击 死亡 蓄力 冲撞 恢复 喷吐九个序列')
    asset_names = ['DA_'+name+'Logic', 'DA_'+name+'Presentation', 'MEC_'+name, 'BP_'+name+'Presentation', 'ABP_'+name, 'BS_'+name+'Speed']
    paths = [destination_root+'/'+value for value in asset_names]
    signature = hashlib.sha256(json.dumps(recipe, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    for path in paths:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            value = unreal.load_asset(path)
            if str(unreal.EditorAssetLibrary.get_metadata_tag(value, 'BBB.SpecialRecipe')) != signature:
                raise RuntimeError('目标来源不属于当前制作描述 不覆盖 '+path)
    existing_presentation = unreal.load_asset(paths[1]) if unreal.EditorAssetLibrary.does_asset_exist(paths[1]) else None
    if existing_presentation and str(unreal.EditorAssetLibrary.get_metadata_tag(existing_presentation, 'BBB.SpecialComplete')) == '1':
        require_asset_write([existing_presentation])
        animation = existing_presentation.get_editor_property('animation')
        animation.set_editor_property('slow_walk_sample_speed', float(recipe['logic_properties']['walk_speed']) * .5)
        existing_presentation.set_editor_property('animation', animation)
        report = str(unreal.BBBMonsterPresentationEditorLibrary.save_configuration(existing_presentation))
        if report.startswith('失败'):
            raise RuntimeError(report)
        return json.dumps({'saved': paths, 'alreadyComplete': True, 'presentationValidation': report, 'logicValidation': _validate_data_asset(unreal.load_asset(paths[0])),
                           'birthValidation': {suffix: _validate_data_asset(unreal.load_asset(destination_root+'/DA_'+name+suffix))
                                               for suffix in ('Pool', 'Spawn')
                                               if unreal.EditorAssetLibrary.does_asset_exist(destination_root+'/DA_'+name+suffix)}}, ensure_ascii=False)
    prefabs = list(unreal.EditorAssetLibrary.list_assets(prefab_root, True, False))
    require_asset_write(prefabs, destinations=[destination_root, '/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials'])
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    def rig_for(body, rig_name):
        path = destination_root+'/Animation/'+rig_name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            rig = unreal.load_asset(path)
            if unreal.IKRigController.get_controller(rig).get_skeletal_mesh() != body:
                raise RuntimeError('重定向骨架制作源不匹配 '+path)
            return rig
        rig = tools.create_asset(rig_name, destination_root+'/Animation', unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
        controller = unreal.IKRigController.get_controller(rig)
        if not controller.set_skeletal_mesh(body) or not controller.apply_auto_generated_retarget_definition():
            raise RuntimeError('UE未识别身体重定向链 '+path)
        if not unreal.EditorAssetLibrary.save_loaded_asset(rig, False):
            raise RuntimeError('重定向骨架保存失败 '+path)
        return rig
    target_rig = rig_for(mesh, 'IKR_Target')
    native_path = '/Game/_ThirdParty/Characters/Whisper/Base_Mesh/SK_Whisper' if name == 'Whisper' else '/Game/_ThirdParty/Characters/Urban_Zombie_Pack/'+name+'/Mesh/SK_'+name
    native_body = unreal.load_asset(native_path)
    shared_body = source_presentation.get_editor_property('gore').get_editor_property('body')
    retargeters = {}
    def retargeter_for(source):
        source_skeleton = source.get_editor_property('skeleton')
        source_body = native_body if native_body.get_editor_property('skeleton') == source_skeleton else shared_body
        if source_body.get_editor_property('skeleton') != source_skeleton:
            raise RuntimeError('动作没有同骨架的明确来源身体 '+source.get_path_name())
        kind = 'Native' if source_body == native_body else 'Shared'
        if kind in retargeters:
            return source_body, retargeters[kind]
        source_rig = rig_for(source_body, 'IKR_'+kind)
        path = destination_root+'/Animation/RTG_'+kind
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            retargeter = unreal.load_asset(path)
        else:
            retargeter = tools.create_asset('RTG_'+kind, destination_root+'/Animation', unreal.IKRetargeter, unreal.IKRetargetFactory())
            controller = unreal.IKRetargeterController.get_controller(retargeter)
            controller.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
            controller.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, target_rig)
            controller.add_default_ops()
            controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
            controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, target_rig)
            controller.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
            controller.auto_align_all_bones(unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN)
            for index in reversed(range(controller.get_num_retarget_ops())):
                op = controller.get_op_controller(index)
                if op.get_class().get_name() in {'IKRetargetRunIKRigController', 'IKRetargetPinBoneController'}:
                    controller.remove_retarget_op(index)
            target_controller = unreal.IKRigController.get_controller(target_rig)
            source_controller = unreal.IKRigController.get_controller(source_rig)
            for index in range(controller.get_num_retarget_ops()):
                op = controller.get_op_controller(index)
                if op.get_class().get_name() == 'IKRetargetRootMotionController':
                    op.set_source_root_bone(source_controller.get_retarget_root())
                    op.set_target_root_bone('root')
                    op.set_target_pelvis_bone(target_controller.get_retarget_root())
                    settings = op.get_settings()
                    settings.root_motion_source = unreal.RootMotionSource.GENERATE_FROM_TARGET_PELVIS
                    settings.root_height_source = unreal.RootMotionHeightSource.SNAP_TO_GROUND
                    op.set_settings(settings)
            if not unreal.EditorAssetLibrary.save_loaded_asset(retargeter, False):
                raise RuntimeError('重定向器保存失败 '+path)
        retargeters[kind] = retargeter
        return source_body, retargeter
    def prepare_sequence(source, animation_name):
        if not isinstance(source, unreal.AnimSequence):
            raise RuntimeError('动作来源不存在 '+animation_name)
        path = destination_root+'/Animation/AS_'+animation_name
        animation = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
        if animation and str(unreal.EditorAssetLibrary.get_metadata_tag(animation, 'BBB.SpecialSource')) != source.get_path_name():
            raise RuntimeError('动作制作源不匹配 '+path)
        source_body, retargeter = retargeter_for(source)
        if not animation or str(unreal.EditorAssetLibrary.get_metadata_tag(animation, 'BBB.SpecialRetarget')) != retargeter.get_path_name():
            inputs = unreal.IKRetargetBatchOperationInputs()
            inputs.assets_to_retarget = [unreal.EditorAssetLibrary.find_asset_data(source.get_path_name())]
            inputs.source_mesh = source_body
            inputs.target_mesh = mesh
            inputs.ik_retarget_asset = retargeter
            inputs.target_path = destination_root+'/Animation'
            inputs.search = source.get_name()
            inputs.replace = 'AS_'+animation_name
            inputs.include_referenced_assets = False
            inputs.overwrite_existing_files = animation is not None
            inputs.retain_additive_flags = False
            created = [str(value.package_name) for value in unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)]
            if created != [path]:
                raise RuntimeError('IK重定向未返回唯一正式动作 '+str(created))
            animation = unreal.load_asset(path)
            unreal.EditorAssetLibrary.set_metadata_tag(animation, 'BBB.SpecialSource', source.get_path_name())
            unreal.EditorAssetLibrary.set_metadata_tag(animation, 'BBB.SpecialRetarget', retargeter.get_path_name())
        if animation.get_editor_property('skeleton') != skeleton or abs(animation.get_play_length()-source.get_play_length()) > .05:
            raise RuntimeError('重定向动作骨架或时长不匹配 '+path)
        animation.set_editor_property('enable_root_motion', False)
        animation.set_editor_property('force_root_lock', True)
        animation.set_preview_skeletal_mesh(mesh)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('动作保存失败 '+path)
        return animation
    sequences = [prepare_sequence(source, animation_name) for source, animation_name in zip(sources,
        ['Idle', 'Walk', 'Run', 'Attack', 'Death', 'Windup', 'Rush', 'Recovery', 'Spit'])]
    common = '/Game/_Project/Mass/Monster/Zombie/Male/Animations/Crawl/'
    crawl_names = ['Zombie_Crawl_Collapse', 'Zombie_Crawl_Idle', 'Zombie_Crawl_Idle_Search',
                   'Zombie_Crawl_Forward', 'Zombie_Crawl_Attack01', 'Zombie_Crawl_Death']
    crawl = [prepare_sequence(unreal.load_asset(common+value), 'Crawl'+str(index)) for index, value in enumerate(crawl_names)]
    stagger_sources = [unreal.load_asset(path) for path in recipe['stagger_sequences']]
    if len(stagger_sources) != 5 or any(not isinstance(value, unreal.AnimSequence) for value in stagger_sources):
        raise RuntimeError('需要五部位踉跄来源')
    stagger = [prepare_sequence(value, 'Stagger'+str(index)) for index, value in enumerate(stagger_sources)]
    mantle = prepare_sequence(source_presentation.get_editor_property('mantle').get_editor_property('sequence'), 'Mantle')
    climb = prepare_sequence(source_presentation.get_editor_property('climb').get_editor_property('sequence'), 'Climb')
    if recipe.get('stage') == 'animations':
        return json.dumps({'stage': 'animations', 'variant': name, 'saved': [value.get_path_name()
            for value in sequences+crawl+stagger+[mantle, climb]], 'skeleton': skeleton.get_path_name()}, ensure_ascii=False)
    def duplicate_owned(index, source):
        if unreal.EditorAssetLibrary.does_asset_exist(paths[index]):
            return unreal.load_asset(paths[index])
        value = tools.duplicate_asset(asset_names[index], destination_root, source)
        if not value:
            raise RuntimeError('资源复制失败 '+paths[index])
        unreal.EditorAssetLibrary.set_metadata_tag(value, 'BBB.SpecialRecipe', signature)
        if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
            raise RuntimeError('装配起点保存失败 '+paths[index])
        return value
    logic = duplicate_owned(0, source_logic)
    presentation = duplicate_owned(1, source_presentation)
    config = duplicate_owned(2, source_logic.get_editor_property('entity_config'))
    actor = duplicate_owned(3, source_actor)
    if any(value is None for value in (logic, presentation, config, actor)):
        raise RuntimeError('配置复制失败 保留未完成目标供接续')
    factory = unreal.AnimBlueprintFactory()
    factory.set_editor_property('parent_class', unreal.BBBMonsterFactAnimInstance)
    factory.set_editor_property('target_skeleton', skeleton)
    blueprint = unreal.load_asset(paths[4]) if unreal.EditorAssetLibrary.does_asset_exist(paths[4]) else tools.create_asset(asset_names[4], destination_root, unreal.AnimBlueprint, factory)
    unreal.EditorAssetLibrary.set_metadata_tag(blueprint, 'BBB.SpecialRecipe', signature)
    blend_factory = unreal.BlendSpaceFactory1D()
    blend_factory.set_editor_property('target_skeleton', skeleton)
    blend_exists = unreal.EditorAssetLibrary.does_asset_exist(paths[5])
    blend = unreal.load_asset(paths[5]) if blend_exists else tools.create_asset(asset_names[5], destination_root, unreal.BlendSpace1D, blend_factory)
    if not blueprint or not blend or (not blend_exists and not unreal.BBBAnimationGraphEditorLibrary.configure_speed_blend_space(blend, sequences[:3], recipe['sample_speeds'], 0.12)):
        raise RuntimeError('速度混合创建失败')
    unreal.EditorAssetLibrary.set_metadata_tag(blend, 'BBB.SpecialRecipe', signature)
    if not unreal.EditorAssetLibrary.save_loaded_asset(blend, False):
        raise RuntimeError('速度混合保存失败')
    if not unreal.BBBAnimationGraphEditorLibrary.build_fact_driven_state_machine_graph(blueprint, blend,
            sequences[3:5], [unreal.Name('BehaviorFact'), unreal.Name('MovementSpeedFact'), unreal.Name('ActionProgressFact')], [4, 5], 0.18):
        raise RuntimeError('基础事实图创建失败')
    if not unreal.BBBAnimationGraphEditorLibrary.configure_special_infected_actions(blueprint, sequences[5:9]):
        raise RuntimeError('特感事实动作创建失败')
    if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_movement_styles(blueprint, [blend, blend, blend], .16):
        raise RuntimeError('实体相位移动构图失败')
    if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_locomotion_variants(blueprint, [sequences[0]], [sequences[0]], 3, .18):
        raise RuntimeError('待机警觉相位构图失败')
    if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_body_stagger_state(blueprint, stagger, .1):
        raise RuntimeError('踉跄状态构图失败')
    if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states(blueprint, crawl, .24):
        raise RuntimeError('持续爬行构图失败')
    if unreal.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions(blueprint, .18, .08, .16, .07, .18, .24, .04) < 0:
        raise RuntimeError('战斗过渡配置失败')
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('特感动画图编译未通过')
    for field, value in recipe['presentation_properties'].items():
        _apply_editor_property(presentation, field, value)
    physics = presentation.get_editor_property('physics_asset')
    require_asset_write([physics])
    physics_report = str(unreal.BBBHitReactionEditorLibrary.configure_physics_asset(physics, 350, 24, mesh, ''))
    if physics_report.startswith('失败'):
        raise RuntimeError(physics_report)
    corpse_report = str(unreal.BBBHitReactionEditorLibrary.configure_corpse_physics(physics, recipe.get('mass_kg', 85)))
    if corpse_report.startswith('失败'):
        raise RuntimeError(corpse_report)
    if not unreal.EditorAssetLibrary.save_loaded_asset(physics, False):
        raise RuntimeError('专属身体物理保存失败')
    gore = presentation.get_editor_property('gore')
    gore.set_editor_property('body', mesh)
    project = os.path.abspath(unreal.Paths.project_dir())
    with open(os.path.join(project, 'ArtSource', 'ZombieDestruction', 'Production', name, 'Regions.json'), encoding='utf-8-sig') as stream:
        region_specs = json.load(stream)['regions']
    regions = []
    for value in region_specs:
        region = unreal.BBBMonsterDestructionRegionDefinition()
        for key in ('name', 'bone'):
            region.set_editor_property(key, value[key])
        region.set_editor_property('contact', unreal.Vector(**value['contact']))
        region.set_editor_property('rotation', unreal.Rotator(**value['rotation']))
        region.set_editor_property('extent', unreal.Vector(**value['extent']))
        regions.append(region)
    destruction = gore.get_editor_property('destruction')
    destruction.set_editor_property('regions', regions)
    destruction.set_editor_property('interior', unreal.load_asset(prefab_root+'/SK_Destruction'))
    with open(os.path.join(project, 'ArtSource', 'ZombieInjury', name, 'Wounds.json'), encoding='utf-8-sig') as stream:
        wounds = json.load(stream)['wounds']
    parts = []
    for value in wounds:
        if value['id'] < 10:
            continue
        part = unreal.BBBMonsterDismembermentPartDefinition()
        for key in ('id', 'name', 'bone'):
            part.set_editor_property(key, value[key])
        part.set_editor_property('region', getattr(unreal.BBBMonsterHitRegion, value['region']))
        for key in ('center', 'contact', 'extent'):
            part.set_editor_property(key, unreal.Vector(*value[key]))
        part.set_editor_property('rotation', unreal.Rotator(**value['rotation']))
        tile = value['atlas']
        part.set_editor_property('atlas_rect', unreal.Vector4((tile%4)*.25, (tile//4)*.25, .25, .25))
        for key, prefix in [('tissue', 'SK_Tissue_'), ('detached_skin', 'SK_Detached_'), ('detached_mesh', 'SM_Detached_'),
                            ('remaining_skin', 'SK_Remaining_'), ('remaining_mesh', 'SM_Remaining_')]:
            path = prefab_root+'/'+prefix+value['name']
            asset = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
            if not asset and key in ('tissue', 'detached_skin', 'detached_mesh'):
                raise RuntimeError('预制断点资源缺失 '+path)
            part.set_editor_property(key, asset)
        parts.append(part)
    gore.get_editor_property('dismemberment').set_editor_property('parts', parts)
    presentation.set_editor_property('animation_class', blueprint.generated_class())
    animation = presentation.get_editor_property('animation')
    animation.set_editor_property('idle_cycle_seconds', unreal.Vector(*([sequences[0].get_play_length()]*3)))
    animation.set_editor_property('alert_cycle_seconds', sequences[0].get_play_length())
    animation.set_editor_property('slow_walk_cycle_seconds', unreal.Vector(*([sequences[1].get_play_length()]*3)))
    animation.set_editor_property('pursuit_walk_cycle_seconds', unreal.Vector(*([sequences[1].get_play_length()]*3)))
    cycle = unreal.Vector(sequences[1].get_play_length(), sequences[2].get_play_length(), sequences[2].get_play_length())
    animation.set_editor_property('movement_cycle_seconds', [cycle, cycle, cycle])
    animation.set_editor_property('death_animation_duration', sequences[4].get_play_length())
    animation.set_editor_property('slow_walk_sample_speed', float(recipe['logic_properties']['walk_speed']) * .5)
    presentation.set_editor_property('animation', animation)
    for field, value in recipe['logic_properties'].items():
        _apply_editor_property(logic, field, value)
    special_recipe = recipe.get('special_properties')
    if special_recipe:
        special = unreal.new_object(unreal.BBBMonsterSpecialDefinition, outer=logic, name='SpecialAbility')
        for field, value in special_recipe.items():
            _apply_editor_property(special, field, value)
        logic.set_editor_property('special', special)
    if not special_recipe:
        logic.set_editor_property('special', None)
    logic.set_editor_property('presentation', presentation)
    logic.set_editor_property('entity_config', config)
    traversal = json.loads(str(unreal.BBBMonsterTraversalEditorLibrary.configure_traversal_assets([logic], [presentation], mantle, climb)))
    if not traversal.get('success'):
        raise RuntimeError('攀爬装配失败 '+str(traversal))
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('完整特感动画图编译未通过')
    raw_config = config.get_editor_property('config')
    definitions = 0
    visuals = 0
    for trait in raw_config.get_editor_property('traits'):
        if isinstance(trait, unreal.BBBMonsterTrait):
            trait.set_editor_property('definition', logic)
            definitions += 1
        if isinstance(trait, unreal.MassVisualizationTrait):
            trait.set_editor_property('high_res_template_actor', actor.generated_class())
            trait.set_editor_property('low_res_template_actor', actor.generated_class())
            visuals += 1
    if definitions != 1 or visuals != 1:
        raise RuntimeError('需要唯一的小怪与表现装配')
    actor_mesh = unreal.get_default_object(actor.generated_class()).get_monster_mesh()
    actor_mesh.set_skeletal_mesh_asset(mesh)
    actor_mesh.set_anim_instance_class(blueprint.generated_class())
    actor_mesh.set_physics_asset(presentation.get_editor_property('physics_asset'), True)
    actor_mesh.set_relative_transform(presentation.get_editor_property('mesh_transform'), False, True)
    reaction = unreal.get_default_object(actor.generated_class()).get_component_by_class(unreal.BBBMonsterHitReactionComponent)
    hit = presentation.get_editor_property('hit_reaction')
    # 编辑器载体预览采用躯干默认分区 运行时按同一表现配置绑定完整四分区
    reaction.set_editor_property('available_profiles', [hit.get_editor_property('torso_profile')])
    unreal.BlueprintEditorLibrary.compile_blueprint(actor)
    if actor.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('特感载体编译失败')
    material_report = str(unreal.BBBMonsterGoreEditorLibrary.configure_wound_materials(gore))
    if material_report.startswith('失败'):
        raise RuntimeError(material_report)
    report = str(unreal.BBBMonsterGoreEditorLibrary.save_gore_configuration(gore))
    if report.startswith('失败'):
        raise RuntimeError(report)
    report = str(unreal.BBBMonsterPresentationEditorLibrary.save_configuration(presentation))
    if report.startswith('失败'):
        raise RuntimeError(report)
    source_hit = source_presentation.get_editor_property('hit_reaction')
    for index, field in enumerate(('torso_profile', 'head_profile', 'arms_profile', 'legs_profile')):
        report = str(unreal.BBBMonsterPresentationEditorLibrary.import_hit_profile(presentation, index, source_hit.get_editor_property(field)))
        if report.startswith('失败'):
            raise RuntimeError(report)
    for asset in (blend, blueprint, actor, config, logic, presentation):
        unreal.EditorAssetLibrary.set_metadata_tag(asset, 'BBB.SpecialComplete', '1')
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError('特感资产保存失败 '+asset.get_path_name())
    if logic.get_editor_property('entity_config') != config or logic.get_editor_property('presentation') != presentation:
        raise RuntimeError('配置交叉引用回读失败')
    return json.dumps({'saved': paths, 'definition': logic.get_path_name(), 'presentation': presentation.get_path_name(),
                       'template': config.get_path_name(), 'mesh': mesh.get_path_name(), 'presentationValidation': report, 'logicValidation': _validate_data_asset(logic)}, ensure_ascii=False)
