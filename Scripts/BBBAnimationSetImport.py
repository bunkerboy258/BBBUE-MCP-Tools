import json
import os

import unreal


def import_skeletal_animation_set(source_files_json, destination_path, mesh_name):
    """
    /**
     * 导入一个源网格及共享同一骨架的动画集合 拒绝覆盖
     * @param source_files_json\t有序 FBX 绝对路径数组
     * @param destination_path\t新的 Game 资产目录
     * @param mesh_name\t源网格名称
     * @return\t网格 骨架与逐个已保存的动画
     */
    """
    files = json.loads(source_files_json)
    if not isinstance(files, list) or not 1 <= len(files) <= 32:
        raise RuntimeError("必须提供一至三十二个 FBX")
    if not destination_path.startswith("/Game/") or any(part in {"", ".", ".."} for part in destination_path.split("/")[2:]):
        raise RuntimeError("目标必须为有效 Game 目录")
    if not mesh_name.isidentifier():
        raise RuntimeError("网格名必须为标识符")
    assets = unreal.EditorAssetLibrary
    if assets.does_directory_exist(destination_path) and assets.list_assets(destination_path, recursive=True, include_folder=False):
        raise RuntimeError("目标目录已有资产 禁止覆盖")
    names = []
    for path in files:
        if not os.path.isabs(path) or not os.path.isfile(path) or os.path.islink(path) or not path.lower().endswith(".fbx"):
            raise RuntimeError("源必须为普通绝对路径 FBX: " + str(path))
        name = os.path.splitext(os.path.basename(path))[0].replace(" ", "_").replace(".", "_")
        if not name.isidentifier() or name in names:
            raise RuntimeError("动画文件名无效或重复: " + name)
        names.append(name)

    def run_import(path, folder, name, options):
        task = unreal.AssetImportTask()
        task.filename = path
        task.destination_path = folder
        task.destination_name = name
        task.automated = True
        task.replace_existing = False
        task.save = False
        task.factory = unreal.FbxFactory()
        task.options = options
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        objects = list(task.get_objects())
        if not objects:
            raise RuntimeError("FBX 未生成资产: " + path)
        return objects

    options = unreal.FbxImportUI()
    options.automated_import_should_detect_type = False
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.original_import_type = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.import_mesh = True
    options.import_as_skeletal = True
    options.import_animations = False
    options.import_materials = False
    options.import_textures = False
    options.create_physics_asset = False
    imported = run_import(files[0], destination_path + "/Meshes", mesh_name, options)
    meshes = [obj for obj in imported if isinstance(obj, unreal.SkeletalMesh)]
    if len(meshes) != 1:
        raise RuntimeError("源网格导入结果不唯一")
    mesh = meshes[0]
    skeleton = mesh.get_editor_property("skeleton")
    if skeleton is None:
        raise RuntimeError("源网格未生成骨架")
    for obj in (mesh, skeleton):
        if not assets.save_loaded_asset(obj, only_if_is_dirty=False):
            raise RuntimeError("源网格或骨架保存失败")
    result = {"mesh": mesh.get_path_name(), "skeleton": skeleton.get_path_name(), "animations": []}
    for path, name in zip(files, names):
        options = unreal.FbxImportUI()
        options.automated_import_should_detect_type = False
        options.mesh_type_to_import = unreal.FBXImportType.FBXIT_ANIMATION
        options.original_import_type = unreal.FBXImportType.FBXIT_ANIMATION
        options.import_mesh = False
        options.import_animations = True
        options.import_materials = False
        options.import_textures = False
        options.skeleton = skeleton
        options.anim_sequence_import_data.set_editor_property("use_default_sample_rate", True)
        objects = run_import(path, destination_path + "/Animations", name, options)
        sequences = [obj for obj in objects if isinstance(obj, unreal.AnimSequence)]
        if len(sequences) != 1 or len(objects) != 1:
            raise RuntimeError("单动作 FBX 未生成唯一动画: " + path)
        sequence = sequences[0]
        if sequence.get_editor_property("skeleton") != skeleton or sequence.get_play_length() <= 0:
            raise RuntimeError("导入动画骨架或时长无效")
        sequence.set_preview_skeletal_mesh(mesh)
        if not assets.save_loaded_asset(sequence, only_if_is_dirty=False):
            raise RuntimeError("动画保存失败: " + sequence.get_path_name())
        result["animations"].append({"asset": sequence.get_path_name(), "length": sequence.get_play_length()})
    unreal.log("[BBBAnimationSetImport] " + json.dumps(result, ensure_ascii=False))
    return json.dumps(result, ensure_ascii=False)


def create_animation_set_retargeter(source_mesh_path, target_rig_path, source_rig_path, retargeter_path):
    """
    /**
     * 使用引擎标准骨架识别 对齐和 IK 辅助骨操作建立新重定向器
     * @param source_mesh_path\t源网格
     * @param target_rig_path\t已有目标 IK Rig 不修改
     * @param source_rig_path\t新源 IK Rig
     * @param retargeter_path\t新重定向器
     * @return\t实际链映射和辅助骨映射
     */
    """
    assets = unreal.EditorAssetLibrary
    for path in (source_rig_path, retargeter_path):
        if not path.startswith("/Game/") or assets.does_asset_exist(path):
            raise RuntimeError("目标必须是新的 Game 资产: " + path)
    source_mesh = unreal.load_asset(source_mesh_path)
    target_rig = unreal.load_asset(target_rig_path)
    if not isinstance(source_mesh, unreal.SkeletalMesh) or not isinstance(target_rig, unreal.IKRigDefinition):
        raise RuntimeError("源网格或目标 IK Rig 无效")
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder, name = source_rig_path.rsplit("/", 1)
    source_rig = asset_tools.create_asset(name, folder, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    rig_controller = unreal.IKRigController.get_controller(source_rig)
    if not rig_controller.set_skeletal_mesh(source_mesh) or not rig_controller.apply_auto_generated_retarget_definition():
        raise RuntimeError("引擎未识别源骨架模板 禁止继续重定向")
    if not assets.save_loaded_asset(source_rig, False):
        raise RuntimeError("源 IK Rig 保存失败")
    folder, name = retargeter_path.rsplit("/", 1)
    retargeter = asset_tools.create_asset(name, folder, unreal.IKRetargeter, unreal.IKRetargetFactory())
    controller = unreal.IKRetargeterController.get_controller(retargeter)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, target_rig)
    controller.add_default_ops()
    controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
    controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, target_rig)
    controller.auto_map_chains(unreal.AutoMapChainType.FUZZY, True)
    target_controller = unreal.IKRigController.get_controller(target_rig)
    target_mesh = target_controller.get_skeletal_mesh()
    target_pose = unreal.AnimPoseExtensions.get_reference_pose(target_mesh.get_editor_property("skeleton"))
    target_bones = [str(bone) for bone in unreal.AnimPoseExtensions.get_bone_names(target_pose)]
    target_bone_names = {bone.lower(): bone for bone in target_bones}
    if "root" not in target_bone_names:
        raise RuntimeError("目标骨架需要明确的 root 根骨")
    mapping = {str(chain.chain_name): str(controller.get_source_chain(chain.chain_name)) for chain in target_controller.get_retarget_chains()}
    for chain in target_controller.get_retarget_chains():
        start = str(target_controller.get_retarget_chain_start_bone(chain.chain_name)).lower()
        if start in {"upperarm_l", "upperarm_r", "thigh_l", "thigh_r", "spine_01", "neck_01"} and mapping[str(chain.chain_name)] in {"", "None"}:
            raise RuntimeError("必要身体链未映射: " + str(chain.chain_name))
    controller.auto_align_all_bones(unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN)
    for index in reversed(range(controller.get_num_retarget_ops())):
        op = controller.get_op_controller(index)
        if op.get_class().get_name() in {"IKRetargetRunIKRigController", "IKRetargetPinBoneController"}:
            controller.remove_retarget_op(index)
    roots = []
    for index in range(controller.get_num_retarget_ops()):
        op = controller.get_op_controller(index)
        if op.get_class().get_name() == "IKRetargetRootMotionController":
            op.set_source_root_bone(rig_controller.get_retarget_root())
            op.set_target_root_bone(unreal.Name(target_bone_names["root"]))
            op.set_target_pelvis_bone(target_controller.get_retarget_root())
            settings = op.get_settings()
            settings.root_motion_source = unreal.RootMotionSource.GENERATE_FROM_TARGET_PELVIS
            settings.root_height_source = unreal.RootMotionHeightSource.SNAP_TO_GROUND
            op.set_settings(settings)
            roots.append(index)
    if len(roots) != 1:
        raise RuntimeError("重定向器需要唯一根骨处理操作")
    index = controller.add_retarget_op("/Script/IKRig.IKRetargetPinBoneOp")
    controller.set_op_name("Utility IK Bones", index)
    pin = controller.get_op_controller(index)
    pairs = (("root", "ik_foot_root"), ("root", "ik_hand_root"), ("hand_r", "ik_hand_gun"), ("foot_l", "ik_foot_l"), ("foot_r", "ik_foot_r"), ("hand_l", "ik_hand_l"), ("hand_r", "ik_hand_r"))
    for bone, helper in pairs:
        if bone not in target_bone_names or helper not in target_bone_names:
            raise RuntimeError("目标 IK 骨缺失: " + helper)
        pin.set_bone_pair(target_bone_names[bone], target_bone_names[helper])
    actual_pairs = {str(key): str(value) for key, value in pin.get_all_bone_pairs().items()}
    if len(actual_pairs) != len(pairs):
        raise RuntimeError("IK 辅助骨配置不完整")
    if not assets.save_loaded_asset(retargeter, False):
        raise RuntimeError("重定向器保存失败")
    return json.dumps({"retargeter": retargeter.get_path_name(), "sourceRig": source_rig.get_path_name(), "targetRig": target_rig.get_path_name(), "sourcePelvis": str(rig_controller.get_retarget_root()), "mappings": mapping, "ikPairs": actual_pairs}, ensure_ascii=False)
