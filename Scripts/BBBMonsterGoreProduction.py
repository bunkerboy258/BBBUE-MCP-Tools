"""已批准的特感毁伤生产资源原位交付 不改变玩法或动画配置。"""

import hashlib
import json
import os
import re
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write


def _json(path):
    """/** @param path 当前制作描述 @return 已保存数据 */"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _save(asset):
    """/** @param asset 明确目标 @return 无 保存失败即报警 */"""
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError('毁伤资源保存失败 ' + asset.get_path_name())


def _texture(path, source, normal=False, masks=False):
    """/** @param path 唯一自有纹理 @param source PNG @param normal 法线 @param masks 数据图 @return 已保存纹理 */"""
    assets = unreal.EditorAssetLibrary
    existing = assets.does_asset_exist(path)
    require_asset_write([path] if existing else [], destinations=[] if existing else [path])
    dirty = {v.get_path_name() for v in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if path in dirty:
        raise RuntimeError('目标纹理有未保存更改 ' + path)
    if not source.is_file():
        raise RuntimeError('制作纹理不存在 ' + str(source))
    task = unreal.AssetImportTask()
    task.filename = str(source)
    task.destination_path, task.destination_name = path.rsplit('/', 1)
    task.automated = True
    task.replace_existing = existing
    task.replace_existing_settings = False
    task.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    values = [v for v in task.get_objects() if isinstance(v, unreal.Texture2D)]
    if len(values) != 1 or values[0].get_outermost().get_path_name() != path:
        raise RuntimeError('纹理导入目标不唯一 ' + path)
    texture = values[0]
    texture.set_editor_property('srgb', not (normal or masks))
    texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP if normal else
                                (unreal.TextureCompressionSettings.TC_MASKS if masks else unreal.TextureCompressionSettings.TC_DEFAULT))
    assets.set_metadata_tag(texture, 'BBB.GoreSourceHash', hashlib.sha256(source.read_bytes()).hexdigest())
    _save(texture)
    return texture


def _source_fingerprint(path, files):
    """/** @param path 四种特感的正式几何 @param files 当前全部档位 @return 与初始资源创建入口一致的唯一制作指纹 */"""
    names = {'UrbanZombie2', 'UrbanZombie3', 'UrbanZombie4', 'Whisper'}
    variant = next(part for part in path.split('/') if part in names)
    spec_path = Path(unreal.Paths.project_dir()).absolute() / 'ArtSource/ZombieDestruction/BodyMaterials.json'
    materials = next(value['materials'] for value in _json(spec_path)['variants'] if value['name'] == variant)
    checksum = hashlib.sha256()
    checksum.update(json.dumps(materials, sort_keys=True).encode())
    for file in files:
        checksum.update(file.read_bytes())
    return checksum.hexdigest()


def _skeletal(path, files):
    """/** @param path 已有蒙皮资源 @param files 本次明确交付 @return 原位回读 */"""
    import BBBSkeletalMeshImport
    result = json.loads(BBBSkeletalMeshImport.reimport(path, str(files[0]), 1.0, [str(v) for v in files[1:]]))
    mesh = unreal.load_asset(path)
    unreal.EditorAssetLibrary.set_metadata_tag(mesh, 'BBB.SpecialSourceHash', _source_fingerprint(path, files))
    unreal.EditorAssetLibrary.remove_metadata_tag(mesh, 'BBB.GoreSourceHash')
    _save(mesh)
    return result


def _static(path, source):
    """/** @param path 已有物理残肢 @param source 本次明确交付 @return 原位回读 */"""
    from BBBGenericEditorToolset import BBBGenericEditorToolset
    result = json.loads(BBBGenericEditorToolset.reimport_static_mesh(path, str(source)))
    mesh = unreal.load_asset(path)
    unreal.EditorAssetLibrary.set_metadata_tag(mesh, 'BBB.SpecialSourceHash', _source_fingerprint(path, [source]))
    unreal.EditorAssetLibrary.remove_metadata_tag(mesh, 'BBB.GoreSourceHash')
    _save(mesh)
    return result


def _material_instance(path, parent):
    """/** @param path 标准材质实例 @param parent 共享主材质 @return 已登记写入的实例 */"""
    assets = unreal.EditorAssetLibrary
    exists = assets.does_asset_exist(path)
    require_asset_write([path] if exists else [], destinations=[] if exists else [path])
    instance = unreal.load_asset(path) if exists else None
    if not exists:
        folder, name = path.rsplit('/', 1)
        instance = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    if not isinstance(instance, unreal.MaterialInstanceConstant):
        raise RuntimeError('需要唯一材质实例 ' + path)
    unreal.MaterialEditingLibrary.set_material_instance_parent(instance, parent)
    unreal.MaterialEditingLibrary.update_material_instance(instance)
    return instance


def _set_texture(instance, parameter, texture):
    """/** @param instance 标准实例 @param parameter 已有参数 @param texture 明确纹理 @return 无 以回读判断写入成功 */"""
    library = unreal.MaterialEditingLibrary
    names = {str(v) for v in library.get_texture_parameter_names(instance)}
    if parameter not in names:
        parent = instance.get_editor_property('parent')
        raise RuntimeError('纹理参数不存在 ' + parameter + ' Parent=' + str(parent) + ' Parameters=' + repr(sorted(names)))
    library.set_material_instance_texture_parameter_value(instance, parameter, texture)
    library.update_material_instance(instance)
    if library.get_material_instance_texture_parameter_value(instance, parameter) != texture:
        raise RuntimeError('纹理参数回读不一致 ' + parameter)


def _configure(definition_path, variant, root, production, severing):
    """/** @param definition_path 唯一表现配置 @param variant 特感 @param root 自有预制目录 @param production 制作根 @param severing 断肢根 @return 保存后的完整资源回读 */"""
    assets = unreal.EditorAssetLibrary
    presentation = unreal.load_asset(definition_path)
    if not isinstance(presentation, unreal.BBBMonsterPresentationDefinition):
        raise RuntimeError('目标不是僵尸表现配置')
    gore = presentation.get_editor_property('gore')
    style = _json(production / 'InteriorInfo.json')['runtimeStyle']
    gore.set_editor_property('tissue_tint', unreal.LinearColor(*style['tissueTint']))
    gore.set_editor_property('roughness', style['roughness'])
    gore.set_editor_property('wetness', style['wetness'])
    sources = [definition_path]
    sources += assets.list_assets(root, recursive=True, include_folder=False)
    sources += assets.list_assets('/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials', recursive=True, include_folder=False)
    require_asset_write(sources)
    regions = []
    for value in _json(production / 'Regions.json')['regions']:
        region = unreal.BBBMonsterDestructionRegionDefinition()
        for key in ('name', 'bone'):
            region.set_editor_property(key, value[key])
        for key in ('contact', 'extent'):
            region.set_editor_property(key, unreal.Vector(**value[key]))
        region.set_editor_property('rotation', unreal.Rotator(**value['rotation']))
        regions.append(region)
    if len(regions) != 8:
        raise RuntimeError('特感必须交付八处躯干毁伤')
    gore.get_editor_property('destruction').set_editor_property('regions', regions)
    gore.get_editor_property('destruction').set_editor_property('interior', unreal.load_asset(root + '/SK_Destruction'))
    specs = _json(production.parent.parent.parent / 'ZombieInjury' / variant / 'Wounds.json')['wounds']
    if len(specs) != 9 or len({v['id'] for v in specs}) != 9:
        raise RuntimeError('特感必须交付九个独立断点')
    parts = []
    for value in specs:
        part = unreal.BBBMonsterDismembermentPartDefinition()
        for key in ('id', 'name', 'bone'):
            part.set_editor_property(key, value[key])
        part.set_editor_property('region', getattr(unreal.BBBMonsterHitRegion, value['region']))
        for key in ('center', 'contact', 'extent'):
            part.set_editor_property(key, unreal.Vector(*value[key]))
        part.set_editor_property('rotation', unreal.Rotator(**value['rotation']))
        tile = value['atlas']
        part.set_editor_property('atlas_rect', unreal.Vector4(tile % 4 * .25, tile // 4 * .25, .25, .25))
        for key, prefix, optional in (('tissue', 'SK_Tissue_', False), ('detached_skin', 'SK_Detached_', False),
                                     ('detached_mesh', 'SM_Detached_', False), ('remaining_skin', 'SK_Remaining_', True),
                                     ('remaining_mesh', 'SM_Remaining_', True)):
            path = root + '/' + prefix + value['name']
            asset = unreal.load_asset(path) if assets.does_asset_exist(path) else None
            if asset is None and not optional:
                raise RuntimeError('配对资源缺失 ' + path)
            part.set_editor_property(key, asset)
        parts.append(part)
    gore.get_editor_property('dismemberment').set_editor_property('parts', parts)
    gore.set_editor_property('projection_atlas', unreal.load_asset(root + '/Textures/T_SeverProjection'))
    report = str(unreal.BBBMonsterGoreEditorLibrary.configure_wound_materials(gore))
    if report.startswith('失败'):
        raise RuntimeError(report)
    saved = str(unreal.BBBMonsterGoreEditorLibrary.save_gore_configuration(gore))
    if saved.startswith('失败'):
        raise RuntimeError(saved)
    folder = definition_path.rsplit('/', 1)[0]
    interior = gore.get_editor_property('destruction').get_editor_property('interior')
    material = interior.get_editor_property('materials')[0].material_interface
    tissue = unreal.load_asset(folder + '/MI_Tissue')
    if not isinstance(material, unreal.MaterialInstanceConstant) or not isinstance(tissue, unreal.MaterialInstanceConstant):
        raise RuntimeError('当前正式血肉材质实例缺失')
    atlas = _material_instance(root + '/MI_BakedAnatomy', material.get_editor_property('parent'))
    for parameter, filename in (('DestructionColor', 'T_Destruction_BaseColor'), ('DestructionNormal', 'T_Destruction_Normal'), ('DestructionORM', 'T_Destruction_ORM')):
        texture = unreal.load_asset(root + '/Textures/' + filename)
        _set_texture(atlas, parameter, texture)
    _save(atlas)
    # 图集放在标准父实例 样式重置只清除子实例的颜色与粗糙度参数
    for instance in (material, tissue):
        require_asset_write([instance])
        unreal.MaterialEditingLibrary.set_material_instance_parent(instance, atlas)
        values = list(instance.get_editor_property('texture_parameter_values'))
        values = [value for value in values if str(value.get_editor_property('parameter_info').get_editor_property('name'))
                  not in ('DestructionColor', 'DestructionNormal', 'DestructionORM')]
        instance.set_editor_property('texture_parameter_values', values)
        unreal.MaterialEditingLibrary.update_material_instance(instance)
        for parameter, filename in (('DestructionColor', 'T_Destruction_BaseColor'), ('DestructionNormal', 'T_Destruction_Normal'), ('DestructionORM', 'T_Destruction_ORM')):
            expected = unreal.load_asset(root + '/Textures/' + filename)
            if unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(instance, parameter) != expected:
                raise RuntimeError('子实例图集继承不一致 ' + instance.get_path_name() + ' ' + parameter)
        _save(instance)
    region_texture = unreal.load_asset('/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials/T_SpecialDestructionRegions')
    for instance in gore.get_editor_property('materials'):
        if not isinstance(instance, unreal.MaterialInstanceConstant):
            raise RuntimeError('身体伤口材质必须为共享实例')
        _set_texture(instance, 'InjuryRegions', region_texture)
        # 不套用普通僵尸衣物的位移图 保留特感自身衣料与已制作的破边
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(instance, 'InjuryClothEnabled', 0)
        _save(instance)
    assets.set_metadata_tag(presentation, 'BBB.GoreApprovedSource', _json(production / 'InteriorInfo.json')['approvedSourceSha256'])
    _save(presentation)
    result = json.loads(str(unreal.BBBMonsterGoreEditorLibrary.inspect_gore_assets(gore)))
    result.update(saved=True, variant=variant, bakedAtlas=atlas.get_path_name(), gameplayChanged=False)
    if not result.get('ready'):
        raise RuntimeError('正式配置回读未就绪 ' + json.dumps(result, ensure_ascii=False))
    return result


def import_gore(definition_path, phase, part_ids):
    """/** @param definition_path 四种特感唯一表现配置 @param phase 明确导入阶段 @param part_ids 每批至多三个断点 @return 原位保存回读 */"""
    match = re.fullmatch(r'/Game/_Project/Mass/Monster/SpecialInfected/(UrbanZombie[234]|Whisper)/DA_\1Presentation', definition_path)
    if not match or phase not in ('body', 'interior', 'parts', 'configure'):
        raise RuntimeError('需要正式特感表现路径与明确阶段')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE期间等待特感毁伤导入')
    variant = match[1]
    art = Path(unreal.Paths.project_dir()).absolute() / 'ArtSource'
    production = art / 'ZombieDestruction/Production' / variant
    severing = art / 'ZombieInjury/Production' / variant
    info = _json(production / 'InteriorInfo.json')
    if not info.get('baked') or not info.get('optimized') or info.get('stage') not in ('exported', 'imported'):
        raise RuntimeError('需要已烘焙并导出的批准制作源')
    root = '/Game/_Project/Mass/Monster/Zombie/Shared/Injury/' + variant
    destination = definition_path.rsplit('/', 1)[0]
    require_asset_write([definition_path])
    if phase == 'body':
        return json.dumps(_skeletal(destination + '/Mesh/SKM_' + variant, [production / ('Body_LOD' + str(lod) + '.fbx') for lod in range(3)]), ensure_ascii=False)
    if phase == 'interior':
        result = _skeletal(root + '/SK_Destruction', [production / ('SK_Destruction_LOD' + str(lod) + '.fbx') for lod in range(3)])
        textures = []
        for name, normal, masks in (('T_Destruction_BaseColor', False, False), ('T_Destruction_Normal', True, False),
                                    ('T_Destruction_ORM', False, True), ('T_SeverProjection', False, True)):
            textures.append(_texture(root + '/Textures/' + name, production / 'Textures' / (name + '.png'), normal, masks).get_path_name())
        textures.append(_texture('/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials/T_SpecialDestructionRegions',
                                 art / 'ZombieDestruction/Production/SpecialInfected/Textures/T_DestructionRegions.png', masks=True).get_path_name())
        return json.dumps({'mesh': result, 'textures': textures, 'saved': True}, ensure_ascii=False)
    if phase == 'parts':
        if not 1 <= len(part_ids) <= 3 or len(set(part_ids)) != len(part_ids):
            raise RuntimeError('每批需要一至三个唯一断点')
        rows = _json(severing / 'Severing.json')['parts']
        results = []
        for identity in part_ids:
            part = next((v for v in rows if v['id'] == identity), None)
            if part is None:
                raise RuntimeError('制作源中没有该断点 ' + str(identity))
            key = part['name']
            results.append(_skeletal(root + '/SK_Tissue_' + key, [severing / v['file'] for v in part['tissueLODs']]))
            for field, prefix, skeletal in (('detachedSkin', 'SK_Detached_', True), ('detachedMesh', 'SM_Detached_', False),
                                            ('remainingSkin', 'SK_Remaining_', True), ('remainingMesh', 'SM_Remaining_', False)):
                if field in part:
                    path = root + '/' + prefix + key
                    source = severing / part[field]
                    results.append(_skeletal(path, [source]) if skeletal else _static(path, source))
        return json.dumps({'variant': variant, 'assets': results, 'saved': True}, ensure_ascii=False)
    return json.dumps(_configure(definition_path, variant, root, production, severing), ensure_ascii=False)
