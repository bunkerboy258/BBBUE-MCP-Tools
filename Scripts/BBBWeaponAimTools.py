import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBWeaponHandlingTools import _function, _weapon_get
from editor_toolset.toolsets.blueprint import BlueprintTools


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


def _build_aim_update(base):
    """/** @param base 公共装备层 @return 线程安全举枪与独立 IK 门控更新已重建 */"""
    fields = set(BlueprintTools.list_variables(base))
    if "WeaponAimBlendPhase" not in fields:
        BlueprintTools.add_variable(base, "WeaponAimBlendPhase", "float")
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
    invalid = g.set("WeaponAimBlendPhase", 0, branch.find_else_pin())
    invalid = g.set("WeaponAimAlpha", 0, invalid)
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
    references = g.binary("BooleanAND",
        g.binary("NotEqual_ObjectObject", g.get("WeaponAimStandReference"), "None"),
        g.binary("NotEqual_ObjectObject", g.get("WeaponAimCrouchReference"), "None"))
    assets = g.binary("BooleanAND", assets, references)
    raise_gate = g.binary("BooleanAND", g.binary("BooleanAND", ready, not_running), g.binary("BooleanAND", assets, can_use))
    target = g.select(1, 0, raise_gate)
    speed = g.select(4, 1 / 0.3, raise_gate)
    phase = g.out(g.call("FInterpTo_Constant", inputs={"Current": g.get("WeaponAimBlendPhase"), "Target": target, "DeltaTime": delta, "InterpSpeed": speed}))
    execute = g.set("WeaponAimBlendPhase", phase, branch.find_then_pin())
    alpha = g.out(g.call("FInterpEaseInOut", inputs={"A": 0, "B": 1, "Alpha": g.get("WeaponAimBlendPhase"), "Exponent": 2}))
    alpha = g.out(g.call("FClamp", inputs={"Value": alpha, "Min": 0, "Max": 1}))
    alpha = g.select(alpha, 0, g.binary("BooleanAND", assets, can_use))
    execute = g.set("WeaponAimAlpha", alpha, execute)
    ik_gate = g.binary("BooleanAND", g.binary("BooleanOR", not_running, ready), muzzle)
    ik = g.out(g.call("FInterpTo", inputs={"Current": g.get("LocomotionAimIKAlpha"),
        "Target": g.select(1, 0, ik_gate), "DeltaTime": delta, "InterpSpeed": 10}))
    g.set("LocomotionAimIKAlpha", ik, execute)


def configure_upper_body_pose(interface_path, base_path, main_path, layer_paths):
    """
    /**
     * 将端枪姿势独立为上半身层 并清除两处旧举枪叠加
     * @param interface_path	已有装备动画层接口
     * @param base_path	公共装备动画层
     * @param main_path	角色主动画蓝图
     * @param layer_paths	按父层在前排列的全部装备引用者
     * @return 编译保存后的图表结构与素材保持检查
     */
    """
    paths = [interface_path, base_path] + list(layer_paths) + [main_path]
    if len(paths) != len(set(paths)) or not layer_paths:
        raise RuntimeError("上半身层目标列表必须唯一且包含引用者")
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改上半身层")
    targets = [unreal.load_asset(path) for path in paths]
    if not all(isinstance(value, unreal.AnimBlueprint) for value in targets):
        raise RuntimeError("上半身层目标必须为现有动画蓝图")
    interface, base = targets[:2]
    main = targets[-1]
    children = targets[2:-1]
    require_asset_write(targets)
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(value.get_outermost().get_path_name() in dirty for value in targets):
        raise RuntimeError("目标含未保存编辑 拒绝混入其它会话")
    parents = [base.generated_class()]
    for child in children:
        if child.get_blueprint_parent_class() not in parents:
            raise RuntimeError("装备引用者必须按父层在前排列 " + child.get_path_name())
        parents.append(child.generated_class())
    fields = ("WeaponAimStandAdditive", "WeaponAimCrouchAdditive", "WeaponAimStandReference", "WeaponAimCrouchReference")
    def references():
        return {value.get_path_name(): {
            field: str(unreal.get_default_object(value.generated_class()).get_editor_property(field).get_path_name())
            if unreal.get_default_object(value.generated_class()).get_editor_property(field) else None
            for field in fields} for value in [base] + children}
    before = references()
    if not unreal.BBBWeaponAimEditorLibrary.ensure_upper_body_pose_interface(interface):
        raise RuntimeError("UpperBodyPose 接口构造失败 未保存")
    unreal.BlueprintEditorLibrary.compile_blueprint(interface)
    if interface.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("UpperBodyPose 接口编译失败 未保存")
    if not unreal.BBBWeaponAimEditorLibrary.configure_upper_body_pose(interface, base, main):
        raise RuntimeError("UpperBodyPose 迁移检查失败 未保存")
    _build_aim_update(base)
    for value in targets[1:]:
        unreal.BlueprintEditorLibrary.compile_blueprint(value)
        if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("上半身层引用者编译失败 未保存 " + value.get_path_name())
    if before != references():
        raise RuntimeError("端枪素材引用意外变化 未保存")
    snapshots = {}
    for graph_name, expected in (("UpperBodyPose", 16), ("FullBodyAdditives", 12), ("FullBody_SkeletalControls", 40)):
        graph = unreal.BlueprintEditorLibrary.find_graph(base, graph_name)
        snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
        if len(snapshot["nodes"]) != expected:
            raise RuntimeError("迁移后的图表节点数不符 未保存 " + graph_name)
        snapshots[graph_name] = snapshot
    for value in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
            raise RuntimeError("上半身层保存失败 " + value.get_path_name())
    return {"saved": paths, "graphs": snapshots, "poseReferencesUnchanged": True,
            "runtimeAcceptance": "user"}
