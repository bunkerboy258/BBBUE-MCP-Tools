import json
import math
import os

import unreal

from BBBAssetWritePolicy import require_write_access


def reimport(asset_path, source_file, import_uniform_scale, lod_source_files):
    """/** @param asset_path\t目标资产 @param source_file\t基础网格 @param import_uniform_scale\t导入缩放 @param lod_source_files\t附加档位 @return 原位保存与回读结果 */"""
    if not math.isfinite(import_uniform_scale) or import_uniform_scale <= 0.0:
        raise RuntimeError("导入缩放必须为有限正数")
    if not os.path.isabs(source_file) or not os.path.isfile(source_file):
        raise RuntimeError("源文件必须是存在的绝对路径")
    if not source_file.lower().endswith(".fbx"):
        raise RuntimeError("只允许 FBX 文件")
    lod_files = list(lod_source_files)
    if len(lod_files) > 7:
        raise RuntimeError("一次最多导入七个附加细节档位")
    for path in lod_files:
        if not os.path.isabs(path) or not os.path.isfile(path) or not path.lower().endswith(".fbx"):
            raise RuntimeError("细节档位需要存在的明确 FBX 绝对路径: " + str(path))
    mesh = unreal.load_asset(asset_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("目标必须是已有骨骼网格")
    package = mesh.get_outermost().get_path_name()
    dirty = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    if any(item.get_path_name() == package for item in dirty):
        raise RuntimeError("目标存在未保存修改 拒绝覆盖: " + package)
    require_write_access(mesh)
    skeleton = mesh.skeleton
    physics_asset = mesh.physics_asset
    if skeleton is None:
        raise RuntimeError("目标没有骨架")
    bone_names = list(skeleton.get_reference_pose().get_bone_names())
    morph_names = {str(name) for name in mesh.get_all_morph_target_names()}
    original_materials = {
        str(item.material_slot_name): item.material_interface
        for item in mesh.materials
    }
    options = unreal.FbxImportUI()
    options.automated_import_should_detect_type = False
    options.import_mesh = True
    options.import_as_skeletal = True
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.original_import_type = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.skeleton = skeleton
    options.import_materials = False
    options.import_textures = False
    options.import_animations = False
    options.create_physics_asset = False
    options.skeletal_mesh_import_data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    options.skeletal_mesh_import_data.import_uniform_scale = import_uniform_scale
    options.skeletal_mesh_import_data.set_editor_property("import_morph_targets", True)
    task = unreal.AssetImportTask()
    task.filename = os.path.realpath(source_file)
    task.destination_path = package.rsplit("/", 1)[0]
    task.destination_name = mesh.get_name()
    task.automated = True
    task.replace_existing = True
    task.replace_existing_settings = True
    task.save = False
    task.options = options
    task.factory = unreal.FbxFactory()
    # 原位重导入会读取资产已保存的 FBX 导入设置
    # 明确重建当前原生 FBX 来源 避免来源处理器打开交互式选文件窗口
    import_data = unreal.FbxSkeletalMeshImportData(outer=mesh)
    import_data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    import_data.import_uniform_scale = import_uniform_scale
    import_data.set_editor_property("import_morph_targets", True)
    import_data.scripted_add_filename(os.path.realpath(source_file), 0, "")
    mesh.set_editor_property("asset_import_data", import_data)
    cvar = "Interchange.FeatureFlags.Import.FBX"
    previous_interchange = unreal.SystemLibrary.get_console_variable_bool_value(cvar)
    try:
        unreal.SystemLibrary.execute_console_command(None, cvar + " 0")
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    finally:
        unreal.SystemLibrary.execute_console_command(None, cvar + " " + str(int(previous_interchange)))
    imported = list(task.get_objects())
    if len(imported) != 1 or imported[0].get_path_name() != mesh.get_path_name():
        unreal.log_error("[BBBSkeletalReimport] 导入未返回唯一原位目标: " + package)
        raise RuntimeError("骨骼网格原位导入失败 请检查目标状态")
    result = imported[0]
    if result.physics_asset != physics_asset:
        result.physics_asset = physics_asset
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    for index, path in enumerate(lod_files, start=1):
        if subsystem.import_lod(result, index, os.path.realpath(path)) != index:
            unreal.log_error("[BBBSkeletalReimport] 细节档位导入失败: " + package + " LOD" + str(index))
            raise RuntimeError("细节档位导入失败 不保存")
    if lod_files:
        expected_count = len(lod_files) + 1
        extra = list(range(expected_count, subsystem.get_lod_count(result)))
        if extra and not subsystem.remove_lods(result, extra):
            raise RuntimeError("多余细节档位未完整移除 不保存")
        if subsystem.get_lod_count(result) != expected_count:
            raise RuntimeError("实际细节档位数量不符 不保存")
    if result.skeleton != skeleton or list(skeleton.get_reference_pose().get_bone_names()) != bone_names:
        unreal.log_error("[BBBSkeletalReimport] 骨架身份或骨名发生变化: " + package)
        raise RuntimeError("骨架校验失败 不保存")
    actual_morph_names = {str(name) for name in result.get_all_morph_target_names()}
    if not morph_names.issubset(actual_morph_names):
        raise RuntimeError("已有形变目标缺失 不保存: " + str(sorted(morph_names - actual_morph_names)))
    materials = list(result.materials)
    for item in materials:
        slot = str(item.material_slot_name)
        if slot in original_materials:
            item.material_interface = original_materials[slot]
    result.materials = materials
    actual_import_data = result.get_editor_property("asset_import_data")
    if not isinstance(actual_import_data, unreal.FbxSkeletalMeshImportData):
        raise RuntimeError("FBX 导入数据类型不符 不保存")
    actual_scale = actual_import_data.import_uniform_scale
    if not math.isclose(actual_scale, import_uniform_scale, rel_tol=1e-6):
        raise RuntimeError("实际导入缩放未生效 不保存")
    if not unreal.EditorAssetLibrary.save_loaded_asset(result, only_if_is_dirty=False):
        unreal.log_error("[BBBSkeletalReimport] 保存失败: " + package)
        raise RuntimeError("骨骼网格保存失败")
    report = {
        "asset": result.get_path_name(),
        "skeleton": skeleton.get_path_name(),
        "boneCount": len(bone_names),
        "vertexCount": subsystem.get_num_verts(result, 0),
        "materialSlots": [str(item.material_slot_name) for item in materials],
        "saved": True,
        "importUniformScale": actual_scale,
        "lods": [{"lod": index, "vertices": subsystem.get_num_verts(result, index)}
                 for index in range(subsystem.get_lod_count(result))],
        "authoredLODCount": len(lod_files) + 1 if lod_files else None,
        "morphTargets": sorted(actual_morph_names),
    }
    unreal.log("[BBBSkeletalReimport] " + json.dumps(report, ensure_ascii=False))
    return json.dumps(report, ensure_ascii=False)
