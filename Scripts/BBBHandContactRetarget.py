import json

import unreal

from BBBAssetWritePolicy import require_asset_write


_HAND_PAIRS = (
    ("hand_l", "ik_hand_l"),
    ("hand_r", "ik_hand_r"),
    ("hand_r", "ik_hand_gun"),
)


def configure_hand_contact_retargeters(retargeter_paths, source_rig_paths, target_rig_path):
    """
    /**
     * @param retargeter_paths\t明确的持枪重定向器
     * @param source_rig_paths\t各自只读复用的源 Rig
     * @param target_rig_path\t仅供这些重定向器使用的自有目标 Rig
     * @return\t双臂求解和实际手骨生成的持枪目标配置
     */
    """
    if not 1 <= len(retargeter_paths) <= 4 or len(retargeter_paths) != len(source_rig_paths):
        raise RuntimeError("需要一至四个明确重定向器及对应源 Rig")
    all_paths = retargeter_paths + [target_rig_path]
    if len(set(all_paths)) != len(all_paths) or any(not path.startswith("/Game/_Project/") for path in all_paths):
        raise RuntimeError("写入路径必须为互不重复的自有资产")
    assets = unreal.EditorAssetLibrary
    side = unreal.RetargetSourceOrTarget
    retargeters = [unreal.load_asset(path) for path in retargeter_paths]
    if any(not isinstance(asset, unreal.IKRetargeter) for asset in retargeters):
        raise RuntimeError("重定向器类型错误")
    controllers = [unreal.IKRetargeterController.get_controller(asset) for asset in retargeters]
    sources = [unreal.load_asset(path) for path in source_rig_paths]
    if any(not isinstance(asset, unreal.IKRigDefinition) for asset in sources):
        raise RuntimeError("源 Rig 必须存在")
    for source in sources:
        mesh = unreal.IKRigController.get_controller(source).get_skeletal_mesh()
        bones = {str(name).lower() for name in mesh.skeleton.get_reference_pose().get_bone_names()}
        if not {"hand_l", "hand_r"} <= bones:
            raise RuntimeError("源骨架缺少实际双手骨骼")
    for controller in controllers:
        kinds = [controller.get_op_controller(index).get_class().get_name() for index in range(controller.get_num_retarget_ops())]
        for kind in ("IKRetargetFKChainsController", "IKRetargetRootMotionController", "IKRetargetCurveRemapController"):
            if kinds.count(kind) != 1:
                raise RuntimeError("需要唯一 FK 根运动和曲线操作")
        if sum(str(controller.get_op_name(index)) == "Utility IK Bones" for index in range(controller.get_num_retarget_ops())) != 1:
            raise RuntimeError("需要唯一目标辅助骨操作")
    template = controllers[0].get_ik_rig(side.TARGET)
    template_controller = unreal.IKRigController.get_controller(template)
    target_mesh = template_controller.get_skeletal_mesh()
    target_bones = {str(bone).lower(): str(bone) for bone in target_mesh.skeleton.get_reference_pose().get_bone_names()}
    if not {"pelvis", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "ik_hand_l", "ik_hand_r", "ik_hand_gun"} <= set(target_bones):
        raise RuntimeError("目标骨架缺少双臂求解所需骨骼")
    if any(controller.get_preview_mesh(side.TARGET) != target_mesh for controller in controllers):
        raise RuntimeError("各重定向器必须指向同一目标网格")
    chain_names = {str(chain.chain_name) for chain in template_controller.get_retarget_chains()}
    if not {"LeftArm", "RightArm"} <= chain_names:
        raise RuntimeError("目标必须具有左右手臂链")
    for source in sources:
        names = {str(chain.chain_name) for chain in unreal.IKRigController.get_controller(source).get_retarget_chains()}
        if not chain_names <= names:
            raise RuntimeError("源与目标必须具有完整同名链")
    expected_refs = set(retargeter_paths)
    existing = []
    new = []
    for path in all_paths:
        if assets.does_asset_exist(path):
            value = unreal.load_asset(path)
            existing.append(value)
            if path not in retargeter_paths:
                if not isinstance(value, unreal.IKRigDefinition):
                    raise RuntimeError("Rig 路径类型错误: " + path)
                refs = {str(ref).split(".", 1)[0] for ref in assets.find_package_referencers_for_asset(path)}
                if refs - expected_refs:
                    raise RuntimeError("Rig 被其它制作链路使用: " + str(sorted(refs - expected_refs)))
        if not assets.does_asset_exist(path):
            new.append(path)
    require_asset_write(existing, new)
    tools = unreal.AssetToolsHelpers.get_asset_tools()

    def rig_at(path, original):
        if assets.does_asset_exist(path):
            return unreal.load_asset(path)
        folder, name = path.rsplit("/", 1)
        value = tools.duplicate_asset(name, folder, original)
        if not isinstance(value, unreal.IKRigDefinition):
            raise RuntimeError("建立自有 Rig 失败: " + path)
        return value

    target_rig = rig_at(target_rig_path, template)
    target = unreal.IKRigController.get_controller(target_rig)
    template_chains = [(chain.chain_name, template_controller.get_retarget_chain_start_bone(chain.chain_name), template_controller.get_retarget_chain_end_bone(chain.chain_name)) for chain in template_controller.get_retarget_chains()]
    target_rig.modify()
    target.set_skeletal_mesh(target_mesh)
    for index in reversed(range(target.get_num_solvers())):
        target.remove_solver(index)
    for goal in list(target.get_all_goals()):
        target.remove_goal(goal.get_editor_property("goal_name"))
    for chain in list(target.get_retarget_chains()):
        target.remove_retarget_chain(chain.chain_name)
    for name, start, end in template_chains:
        target.add_retarget_chain(name, start, end, "None")
    target.set_retarget_root("pelvis")
    for suffix, chain_name in (("l", "LeftArm"), ("r", "RightArm")):
        goal_name = "HandContact_" + suffix
        actual = target.add_new_goal(goal_name, target_bones["hand_" + suffix])
        if str(actual) != goal_name:
            raise RuntimeError("手部目标命名冲突")
        index = target.add_solver("/Script/IKRig.IKRigLimbSolver")
        if index < 0 or not target.set_start_bone(target_bones["upperarm_" + suffix], index):
            raise RuntimeError("双臂 Limb IK 创建失败")
        if not target.connect_goal_to_solver(goal_name, index) or not target.set_retarget_chain_goal(chain_name, goal_name):
            raise RuntimeError("手部 IK 目标未连接")
    reports = []
    changed = [target_rig]
    for path, source_path, source_rig, asset, controller in zip(retargeter_paths, source_rig_paths, sources, retargeters, controllers):
        asset.modify()
        controller.set_ik_rig(side.SOURCE, source_rig)
        controller.set_ik_rig(side.TARGET, target_rig)
        for value, rig in ((side.SOURCE, source_rig), (side.TARGET, target_rig)):
            controller.assign_ik_rig_to_all_ops(value, rig)
        controller.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
        for index in reversed(range(controller.get_num_retarget_ops())):
            kind = controller.get_op_controller(index).get_class().get_name()
            if kind == "IKRetargetRunIKRigController" or str(controller.get_op_name(index)) in {"Hand Contact Positions", "Hand Contact Orientations"}:
                controller.remove_retarget_op(index)
        fk_indices = [index for index in range(controller.get_num_retarget_ops()) if controller.get_op_controller(index).get_class().get_name() == "IKRetargetFKChainsController"]
        if len(fk_indices) != 1:
            raise RuntimeError("需要唯一 FK 操作")
        for label, copy_side, translation, rotation in (("Hand Contact Positions", side.SOURCE, True, False), ("Hand Contact Orientations", side.TARGET, False, True)):
            index = controller.add_retarget_op("/Script/IKRig.IKRetargetPinBoneOp")
            controller.set_op_name(label, index)
            pin = controller.get_op_controller(index)
            for hand, helper in _HAND_PAIRS:
                pin.set_bone_pair(hand, helper)
            settings = pin.get_settings()
            settings.skeleton_to_copy_from = copy_side
            settings.copy_translation = translation
            settings.copy_rotation = rotation
            settings.copy_scale = False
            pin.set_settings(settings)
        ik_index = controller.add_retarget_op("/Script/IKRig.IKRetargetRunIKRigOp")
        ik_name = controller.set_op_name("Hand Contact Solve", ik_index)
        controller.assign_ik_rig_to_all_ops(side.TARGET, target_rig)
        ik = controller.get_op_controller(controller.get_index_of_op_by_name(ik_name))
        settings = ik.get_settings()
        rows = list(settings.chains)
        for row in rows:
            row.enable_ik = str(row.target_chain_name) in {"LeftArm", "RightArm"}
            row.chain_position_alpha = 0.0
            row.chain_rotation_alpha = 0.0
        settings.chains = rows
        ik.set_settings(settings)
        weapon_index = controller.add_retarget_op("/Script/IKRig.IKRetargetWeaponGoalOp")
        weapon_name = controller.set_op_name("Two Hand Contact", weapon_index)
        if not controller.set_parent_op_by_name(weapon_name, ik_name):
            raise RuntimeError("双手约束必须在手臂求解之前执行")
        weapon = controller.get_op_controller(controller.get_index_of_op_by_name(weapon_name))
        settings = weapon.get_settings()
        settings.enable_weapon_scale = False
        settings.snap_ik_hand_gun = True
        settings.left_right_hand_ik_alpha = 1.0
        settings.left_hand_ik_alpha = 1.0
        settings.right_hand_ik_alpha = 1.0
        settings.suppress_missing_bone_warnings = True
        weapon.set_settings(settings)
        for index in range(controller.get_num_retarget_ops()):
            if str(controller.get_op_name(index)) == "Utility IK Bones":
                controller.set_retarget_op_enabled(index, True)
                controller.move_retarget_op_in_stack(index, controller.get_num_retarget_ops() - 1)
                break
        mapping = {str(chain.chain_name): str(controller.get_source_chain(chain.chain_name)) for chain in target.get_retarget_chains()}
        if any(name != value for name, value in mapping.items()):
            raise RuntimeError("手部重定向链映射不完整")
        changed.append(asset)
        reports.append({"asset": path, "sourceRig": source_path, "targetRig": target_rig_path, "mappings": mapping, "handSolvers": 2})
    for asset in changed:
        if not assets.save_loaded_asset(asset, False):
            raise RuntimeError("手部重定向资产保存失败: " + asset.get_path_name())
    return json.dumps({"saved": reports, "sourceHelpers": "actual_hand_bones", "weaponScale": False}, ensure_ascii=False)
