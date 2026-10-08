import json
import os

import unreal

from BBBAssetWritePolicy import require_write_access
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBSkeletalMeshImportToolset(unreal.ToolsetDefinition):
    """/** 原位导入明确骨骼网格 保持资产身份和原有骨架 */"""

    @mcp_tool
    @staticmethod
    def reimport_skeletal_mesh(asset_path: str, source_file: str) -> str:
        """
        /**
         * 使用原生 FBX 工厂原位重导入 不创建动画 材质 纹理或物理资产
         * @param asset_path\t已有骨骼网格的明确对象路径
         * @param source_file\t已存在的 FBX 绝对路径
         * @return 原位保存结果 骨架与顶点数量
         */
        """
        if not os.path.isabs(source_file) or not os.path.isfile(source_file):
            raise RuntimeError("源文件必须是存在的绝对路径")
        if not source_file.lower().endswith(".fbx"):
            raise RuntimeError("只允许 FBX 文件")
        mesh = unreal.load_asset(asset_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("目标必须是已有骨骼网格")
        package = mesh.get_outermost().get_path_name()
        dirty = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        if any(item.get_path_name() == package for item in dirty):
            raise RuntimeError("目标存在未保存修改 拒绝覆盖: " + package)
        require_write_access(mesh)
        skeleton = mesh.skeleton
        if skeleton is None:
            raise RuntimeError("目标没有骨架")
        bone_names = list(skeleton.get_reference_pose().get_bone_names())
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
        task = unreal.AssetImportTask()
        task.filename = os.path.realpath(source_file)
        task.destination_path = package.rsplit("/", 1)[0]
        task.destination_name = mesh.get_name()
        task.automated = True
        task.replace_existing = True
        task.replace_existing_settings = False
        task.save = False
        task.options = options
        task.factory = unreal.FbxFactory()
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        imported = list(task.get_objects())
        if len(imported) != 1 or imported[0].get_path_name() != mesh.get_path_name():
            unreal.log_error("[BBBSkeletalReimport] 导入未返回唯一原位目标: " + package)
            raise RuntimeError("骨骼网格原位导入失败 请检查目标状态")
        result = imported[0]
        if result.skeleton != skeleton or list(skeleton.get_reference_pose().get_bone_names()) != bone_names:
            unreal.log_error("[BBBSkeletalReimport] 骨架身份或骨名发生变化: " + package)
            raise RuntimeError("骨架校验失败 不保存")
        materials = list(result.materials)
        for item in materials:
            slot = str(item.material_slot_name)
            if slot in original_materials:
                item.material_interface = original_materials[slot]
        result.materials = materials
        if not unreal.EditorAssetLibrary.save_loaded_asset(result, only_if_is_dirty=False):
            unreal.log_error("[BBBSkeletalReimport] 保存失败: " + package)
            raise RuntimeError("骨骼网格保存失败")
        subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
        report = {
            "asset": result.get_path_name(),
            "skeleton": skeleton.get_path_name(),
            "boneCount": len(bone_names),
            "vertexCount": subsystem.get_num_verts(result, 0),
            "materialSlots": [str(item.material_slot_name) for item in materials],
            "saved": True,
        }
        unreal.log("[BBBSkeletalReimport] " + json.dumps(report, ensure_ascii=False))
        return json.dumps(report, ensure_ascii=False)


_registration = Registration([BBBSkeletalMeshImportToolset])

if __name__ in {"__main__", "__bbb_editor_script__"}:
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
