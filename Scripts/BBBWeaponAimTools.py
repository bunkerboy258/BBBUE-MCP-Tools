import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBWeaponHandlingTools import _function, _weapon_get


def create_weapon_aim_additive(neutral_path, target_path, asset_path, reference_path):
    """
    /**
     * @param neutral_path\t只读中性持枪动画
     * @param target_path\t只读绝对举枪目标
     * @param asset_path\t不存在的自有加法包路径
     * @param reference_path\t不存在的无曲线静态参考包路径
     * @return 已保存的参考关系与静态加法配置
     */
    """
    if asset_path == reference_path or any(not path.startswith("/Game/_Project/")
            or unreal.EditorAssetLibrary.does_asset_exist(path) for path in (asset_path, reference_path)):
        raise RuntimeError("举枪加法目标必须为不存在的自有资产")
    neutral = unreal.load_asset(neutral_path)
    target = unreal.load_asset(target_path)
    if not isinstance(neutral, unreal.AnimSequence) or not isinstance(target, unreal.AnimSequence):
        raise RuntimeError("举枪中性基准与目标必须为动画序列")
    if neutral.get_skeleton() != target.get_skeleton() or any(
            value.get_editor_property("additive_anim_type") != unreal.AdditiveAnimationType.AAT_NONE
            for value in (neutral, target)):
        raise RuntimeError("举枪素材必须为同骨架的绝对姿势")
    require_asset_write([], destinations=[asset_path, reference_path])
    animation = unreal.EditorAssetLibrary.duplicate_asset(neutral_path, asset_path)
    reference = unreal.EditorAssetLibrary.duplicate_asset(neutral_path, reference_path)
    if not animation or not reference or not unreal.BBBWeaponAimEditorLibrary.build_aim_additive(animation, neutral, target, reference):
        raise RuntimeError("举枪增量骨轨制作失败 未保存")
    options = unreal.AnimPoseEvaluationOptions()
    options.should_retarget = False
    options.retrieve_additive_as_full_pose = False
    pose = animation.get_anim_pose_at_frame(0, options)
    curves = {str(name): pose.get_curve_weight(name) for name in pose.get_curve_names()}
    if any(abs(value) > 0.00001 for value in curves.values()):
        raise RuntimeError("举枪加法含非零曲线增量 不保存 " + str(curves))
    if not unreal.EditorAssetLibrary.save_loaded_asset(reference, False) or not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError("举枪加法保存失败")
    if animation.get_editor_property("ref_pose_seq") != reference or animation.get_editor_property("ref_frame_index") != 0:
        raise RuntimeError("举枪加法参考回读不一致")
    return {"asset": animation.get_path_name(), "neutral": neutral.get_path_name(), "target": target.get_path_name(),
            "reference": reference.get_path_name(),
            "additiveType": str(animation.get_editor_property("additive_anim_type")),
            "keys": animation.data_model_interface.get_number_of_keys(), "curveDelta": curves, "saved": True}


def _build_aim_update(base, stable_pose=False):
    """/** @param base 公共装备层 @return 线程安全举枪与独立 IK 门控更新已重建 */"""
    g = _function(base, "UpdateWeaponAimData")
    g.editor.set_is_thread_safe_function(True)
    entry = next(node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    delta = entry.find_output_pin("DeltaTime")
    if not delta.is_valid():
        raise RuntimeError("举枪更新缺少帧间隔输入")
    character = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.GetBBBMainAnimInstanceThreadSafe"))
    weapon = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance", character))
    valid = g.binary("NotEqual_ObjectObject", weapon, "None")
    branch = g.place(g.editor.add_branch_node())
    g.link(g.editor.find_graph_entry_pin(), branch.find_execute_pin())
    g.link(valid, branch.find_input_pin("Condition"))
    invalid = g.set("WeaponAimAlpha", 0, branch.find_else_pin())
    g.set("LocomotionAimIKAlpha", 0, invalid)

    aiming = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.IsAiming", character))
    firing = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.HasFireIntent", character))
    fired = g.binary("Greater_IntInt", _weapon_get(g, weapon, "GetFireSequence"), 0)
    recent = g.binary("Less_DoubleDouble", _weapon_get(g, weapon, "GetTimeSinceLastFireSeconds"), 0.5)
    ready = g.binary("BooleanOR", aiming, g.binary("BooleanOR", firing, g.binary("BooleanAND", fired, recent)))
    running = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.IsRunning", character))
    not_running = g.out(g.call("Not_PreBool", inputs={"A": running}))
    upper_action = g.out(g.call("/Script/Engine.AnimInstance.IsSlotActive", character, inputs={"SlotNodeName": "UpperBody"}))
    full_action = g.out(g.call("/Script/Engine.AnimInstance.IsSlotActive", character, inputs={"SlotNodeName": "FullBody"}))
    montage = g.binary("BooleanOR", upper_action, full_action)
    no_montage = g.out(g.call("Not_PreBool", inputs={"A": montage}))
    muzzle = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.HasMuzzle", character))
    can_use = g.binary("BooleanAND", muzzle, no_montage)
    stand = g.binary("NotEqual_ObjectObject", g.get("WeaponAimStandAdditive"), "None")
    crouch = g.binary("NotEqual_ObjectObject", g.get("WeaponAimCrouchAdditive"), "None")
    assets = g.binary("BooleanAND", stand, crouch)
    if stable_pose:
        references = g.binary("BooleanAND",
            g.binary("NotEqual_ObjectObject", g.get("WeaponAimStandReference"), "None"),
            g.binary("NotEqual_ObjectObject", g.get("WeaponAimCrouchReference"), "None"))
        assets = g.binary("BooleanAND", assets, references)
    raise_gate = g.binary("BooleanAND", g.binary("BooleanAND", ready, not_running), g.binary("BooleanAND", assets, can_use))
    target = g.select(1, 0, raise_gate)
    speed = g.select(12.5, 10, raise_gate)
    alpha = g.out(g.call("FInterpTo", inputs={"Current": g.get("WeaponAimAlpha"), "Target": target, "DeltaTime": delta, "InterpSpeed": speed}))
    alpha = g.out(g.call("FClamp", inputs={"Value": alpha, "Min": 0, "Max": 1}))
    alpha = g.select(alpha, 0, g.binary("BooleanAND", assets, can_use))
    execute = g.set("WeaponAimAlpha", alpha, branch.find_then_pin())
    ik_gate = g.binary("BooleanAND", g.binary("BooleanOR", not_running, ready), can_use)
    ik = g.out(g.call("FInterpTo", inputs={"Current": g.get("LocomotionAimIKAlpha"), "Target": g.select(1, 0, ik_gate),
                                          "DeltaTime": delta, "InterpSpeed": 10}))
    g.set("LocomotionAimIKAlpha", ik, execute)


def configure_weapon_aim_additives(base_path, layer_paths, stand_paths, crouch_paths, dependent_paths):
    """
    /**
     * @param base_path	已有 FullBodyAdditives 和举枪字段的公共装备层
     * @param layer_paths	需要配置举枪的直接子层
     * @param stand_paths	逐层匹配的站立局部空间加法
     * @param crouch_paths	逐层匹配的蹲伏局部空间加法
     * @param dependent_paths	按父层在前排列的其余依赖子层
     * @return 复用现有加法层后的编译保存结果
     */
    """
    layer_paths = list(layer_paths)
    stand_paths = list(stand_paths)
    crouch_paths = list(crouch_paths)
    dependent_paths = list(dependent_paths)
    if not layer_paths or len(layer_paths) != len(stand_paths) or len(layer_paths) != len(crouch_paths):
        raise RuntimeError("举枪子层与两类姿势必须逐项对应")
    paths = [base_path] + layer_paths + dependent_paths
    if len(paths) != len(set(paths)):
        raise RuntimeError("举枪写入与依赖列表必须唯一")
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改举枪图")
    base, *children = [unreal.load_asset(path) for path in paths]
    if not all(isinstance(value, unreal.AnimBlueprint) for value in [base] + children):
        raise RuntimeError("举枪目标必须为现有动画蓝图")
    names = {str(name) for name in unreal.BlueprintEditorLibrary.list_member_variable_names(base, False)}
    if not {"WeaponAimStandAdditive", "WeaponAimCrouchAdditive", "WeaponAimAlpha"} <= names or unreal.BlueprintEditorLibrary.find_graph(base, "UpdateWeaponAimData") is None:
        raise RuntimeError("公共装备层缺少已声明的举枪数据和线程安全更新函数")
    parents = [base.generated_class()]
    for child in children:
        if child.get_blueprint_parent_class() not in parents:
            raise RuntimeError("举枪子层必须继承指定公共层且按父层在前排列 " + child.get_path_name())
        parents.append(child.generated_class())
    sources = [unreal.load_asset(path) for path in stand_paths + crouch_paths]
    if not all(isinstance(value, unreal.AnimSequence)
               and value.get_editor_property("skeleton") == base.get_editor_property("target_skeleton")
               and value.get_editor_property("additive_anim_type") == unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE
               for value in sources):
        raise RuntimeError("举枪输入需要同骨架局部空间加法")
    targets = [base] + children
    require_asset_write(targets)
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(value.get_outermost().get_path_name() in dirty for value in targets):
        raise RuntimeError("举枪目标有未保存编辑 拒绝混入其它会话")
    graph = unreal.BlueprintEditorLibrary.find_graph(base, "FullBodyAdditives")
    if graph is None:
        raise RuntimeError("缺少原有全身加法层")
    original = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    if not unreal.BBBWeaponAimEditorLibrary.configure_aim_additives(base):
        raise RuntimeError("现有加法层举枪合成失败 尚未保存")
    _build_aim_update(base)
    for index, value in enumerate(targets):
        unreal.BlueprintEditorLibrary.compile_blueprint(value)
        if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("举枪引用者编译未通过 " + value.get_path_name())
        if 0 < index <= len(layer_paths):
            defaults = unreal.get_default_object(value.generated_class())
            defaults.set_editor_property("WeaponAimStandAdditive", sources[index - 1])
            defaults.set_editor_property("WeaponAimCrouchAdditive", sources[len(layer_paths) + index - 1])
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    if {node["guid"] for node in original["nodes"]} - {node["guid"] for node in snapshot["nodes"]}:
        raise RuntimeError("举枪构图意外删除原加法层节点 不保存")
    if len(snapshot["nodes"]) != len(original["nodes"]) + 8:
        raise RuntimeError("举枪加法节点增量不为八 不保存")
    for value in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
            raise RuntimeError("举枪资产保存失败 " + value.get_path_name())
    return {"saved": [value.get_path_name() for value in targets], "configuredLayers": layer_paths,
            "layer": "FullBodyAdditives", "nodesBefore": len(original["nodes"]),
            "nodesAfter": len(snapshot["nodes"]), "runtimeAcceptance": "user"}


def configure_stable_aim_pose(base_path, layer_paths, dependent_paths):
    """
    /**
     * 在共享骨骼控制层的 AimIK 前构建静态参考与举枪加法混合
     * @param base_path\t公共装备动画层
     * @param layer_paths\t直接装备子层路径
     * @param dependent_paths\t其他依赖子层路径
     * @return 编译保存与图表节点摘要
     */
    """
    paths = [base_path] + list(layer_paths) + list(dependent_paths)
    if len(paths) != len(set(paths)) or not layer_paths:
        raise RuntimeError("瞄准稳定层目标列表无效")
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改瞄准稳定层")
    targets = [unreal.load_asset(path) for path in paths]
    if not all(isinstance(value, unreal.AnimBlueprint) for value in targets):
        raise RuntimeError("目标必须是现有动画蓝图")
    require_asset_write(targets)
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(value.get_outermost().get_path_name() in dirty for value in targets):
        raise RuntimeError("目标含未保存编辑")
    base = targets[0]
    graph = unreal.BlueprintEditorLibrary.find_graph(base, "FullBody_SkeletalControls")
    before = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    configured = "WeaponAimStandReference" in {
        str(name) for name in unreal.BlueprintEditorLibrary.list_member_variable_names(base, False)}
    if not configured:
        if not unreal.BBBWeaponAimEditorLibrary.configure_stable_aim_pose(base):
            raise RuntimeError("静态端枪混合构图失败")
        unreal.BlueprintEditorLibrary.compile_blueprint(base)
    _build_aim_update(base, stable_pose=True)
    overlays = [node for node in unreal.BlueprintGraphEditor.get_graph_editor(graph).list_all_nodes()
                if isinstance(node, unreal.AnimGraphNode_LayeredBoneBlend)]
    if len(overlays) != 1:
        raise RuntimeError("稳定端枪分支必须唯一")
    overlay = overlays[0]
    settings = overlay.get_editor_property("node")
    filters = []
    for bone, depth in (("spine_01", 5), ("hand_l", -1), ("hand_r", -1)):
        branch = unreal.BranchFilter()
        branch.set_editor_property("bone_name", bone)
        branch.set_editor_property("blend_depth", depth)
        filters.append(branch)
    layer = unreal.InputBlendPose()
    layer.set_editor_property("branch_filters", filters)
    settings.set_editor_property("layer_setup", [layer])
    overlay.set_editor_property("node", settings)
    for value in targets:
        unreal.BlueprintEditorLibrary.compile_blueprint(value)
        if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图编译失败 " + value.get_path_name())
        defaults = unreal.get_default_object(value.generated_class())
        stand = defaults.get_editor_property("WeaponAimStandAdditive")
        crouch = defaults.get_editor_property("WeaponAimCrouchAdditive")
        defaults.set_editor_property("WeaponAimStandReference", stand.get_editor_property("ref_pose_seq") if stand else None)
        defaults.set_editor_property("WeaponAimCrouchReference", crouch.get_editor_property("ref_pose_seq") if crouch else None)
    after = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    if not configured and len(after["nodes"]) <= len(before["nodes"]):
        raise RuntimeError("静态端枪混合图节点未增加")
    for value in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
            raise RuntimeError("保存失败 " + value.get_path_name())
    return {"saved": paths, "graph": "FullBody_SkeletalControls", "nodesBefore": len(before["nodes"]),
            "nodesAfter": len(after["nodes"]), "runtimeAcceptance": "user"}
