import json
import math

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools
from BBBAssetWritePolicy import require_asset_write
from BBBWeaponHandlingTools import _Graph, _function
from BBBWeaponAimTools import _build_aim_update


WEIGHT_FIELDS = {
    "WeaponCarrySupportAlpha": "float",
    "WeaponMotionPitchDegrees": "float",
    "WeaponMotionYawDegrees": "float",
    "WeaponWeightLastVelocity": "Vector",
    "WeaponWeightLastFacing": "Rotator",
    "WeaponWeightMotionAngles": "Vector2D",
    "bWeaponWeightInitialized": "bool",
}


def validate_weight_settings(layer_paths, carry_support_weights, motion_pitch_degrees, motion_yaw_degrees,
        transition_blend_time, cruise_blend_time):
    """/** @return 核验逐层参数的长度 有限值及保守幅度上限 */"""
    columns = [carry_support_weights, motion_pitch_degrees, motion_yaw_degrees]
    if not layer_paths or len(set(layer_paths)) != len(layer_paths) or any(len(values) != len(layer_paths) for values in columns):
        raise RuntimeError("承重子层与三组参数必须唯一且逐项对应")
    for values, maximum in zip(columns, [0.4, 2.0, 1.5]):
        if any(not math.isfinite(value) or not 0 <= value <= maximum for value in values):
            raise RuntimeError("承重支撑或响应幅度超出保守范围")
    if not all(math.isfinite(value) for value in [transition_blend_time, cruise_blend_time]) or not 0.12 <= transition_blend_time <= cruise_blend_time <= 0.4:
        raise RuntimeError("地面过渡时间必须为 0.12 至 0.4 秒且不长于匀速混合")


def declare_weight_fields(base):
    """/** @param base 公共装备层 @return 承重配置及仅存在蓝图内的派生采样字段 */"""
    existing = {str(name) for name in unreal.BlueprintEditorLibrary.list_member_variable_names(base, False)}
    for name, kind in WEIGHT_FIELDS.items():
        if name not in existing:
            BlueprintTools.add_variable(base, name, kind)
            BlueprintTools.set_variable_category(base, name, "持枪承重")
    if not unreal.BBBWeaponAimEditorLibrary.set_weapon_weight_variable_metadata(base):
        raise RuntimeError("承重变量元数据声明失败")


def _clamp(g, value, minimum, maximum):
    return g.out(g.call("FClamp", inputs={"Value": value, "Min": minimum, "Max": maximum}))


def _build_motion_update(base):
    """/** @param base 公共装备层 @return 在工作线程中以真实速度变化和观察转向制造限幅承重响应 */"""
    g = _function(base, "UpdateWeaponWeightData")
    g.editor.set_is_thread_safe_function(True)
    entry = next(node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    if not entry.find_output_pin("DeltaTime").is_valid():
        BlueprintTools.add_function_param(g.graph, "DeltaTime", "float", True)
    delta = entry.find_output_pin("DeltaTime")
    character = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.GetBBBMainAnimInstanceThreadSafe"))
    weapon = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance", character))
    branch = g.place(g.editor.add_branch_node())
    g.link(g.editor.find_graph_entry_pin(), branch.find_execute_pin())
    g.link(g.binary("NotEqual_ObjectObject", weapon, "None"), branch.find_input_pin("Condition"))
    invalid = g.set("bWeaponWeightInitialized", False, branch.find_else_pin())
    g.set("WeaponWeightMotionAngles", "(X=0,Y=0)", invalid)

    def fact(name):
        return g.get(name, character, "/Script/ABBB_Evac.BBBAnimInstance")

    velocity = fact("SourceVelocity")
    facing = fact("SourceControlRotation")
    rotation = fact("SourceActorRotation")
    time_ok = g.binary("BooleanAND", g.binary("Greater_DoubleDouble", delta, 0.0001), g.binary("LessEqual_DoubleDouble", delta, 0.1))
    warmed = g.binary("BooleanAND", time_ok, g.get("bWeaponWeightInitialized"))
    safe_delta = g.binary("FMax", delta, 0.001)
    acceleration = g.out(g.call("Divide_VectorFloat", inputs={"A": g.binary("Subtract_VectorVector", velocity, g.get("WeaponWeightLastVelocity")), "B": safe_delta}))
    normalization = g.binary("FMax", fact("SourceMaxAcceleration"), 1200)
    forward = g.out(g.call("GetForwardVector", inputs={"InRot": rotation}))
    right = g.out(g.call("GetRightVector", inputs={"InRot": rotation}))
    longitudinal = _clamp(g, g.binary("Divide_DoubleDouble", g.binary("Dot_VectorVector", acceleration, forward), normalization), -1, 1)
    lateral = _clamp(g, g.binary("Divide_DoubleDouble", g.binary("Dot_VectorVector", acceleration, right), normalization), -1, 1)
    turn = g.out(g.call("NormalizedDeltaRotator", inputs={"A": facing, "B": g.get("WeaponWeightLastFacing")}))
    turn = g.out(g.call("BreakRotator", inputs={"InRot": turn}), "Yaw")
    turn = _clamp(g, g.binary("Divide_DoubleDouble", turn, g.binary("Multiply_DoubleDouble", safe_delta, 180)), -1, 1)
    pitch = g.binary("Multiply_DoubleDouble", longitudinal, g.binary("Multiply_DoubleDouble", g.get("WeaponMotionPitchDegrees"), -1))
    yaw = _clamp(g, g.binary("Add_DoubleDouble", lateral, g.binary("Multiply_DoubleDouble", turn, 0.4)), -1, 1)
    yaw = g.binary("Multiply_DoubleDouble", yaw, g.binary("Multiply_DoubleDouble", g.get("WeaponMotionYawDegrees"), -1))
    aiming = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.IsAiming", character))
    scale = g.binary("Multiply_DoubleDouble", g.select(0.3, 1, aiming), g.select(0.65, 1, fact("bSourceCrouching")))
    running = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.IsRunning", character))
    upper = g.out(g.call("/Script/Engine.AnimInstance.IsSlotActive", character, inputs={"SlotNodeName": "UpperBody"}))
    full = g.out(g.call("/Script/Engine.AnimInstance.IsSlotActive", character, inputs={"SlotNodeName": "FullBody"}))
    blocked = g.binary("BooleanOR", running, g.binary("BooleanOR", upper, full))
    muzzle = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.HasMuzzle", character))
    allowed = g.binary("BooleanAND", fact("bSourceMovingOnGround"), g.binary("BooleanAND", muzzle, g.out(g.call("Not_PreBool", inputs={"A": blocked}))))
    target_ok = g.binary("BooleanAND", warmed, allowed)
    current_angles = g.get("WeaponWeightMotionAngles")
    previous = g.call("BreakVector2D", inputs={"InVec": current_angles})
    result = []
    for axis, value in zip(["X", "Y"], [pitch, yaw]):
        target = g.select(g.binary("Multiply_DoubleDouble", value, scale), 0, target_ok)
        value = g.out(g.call("FInterpTo", inputs={"Current": g.out(previous, axis), "Target": target,
            "DeltaTime": _clamp(g, delta, 0, 0.1), "InterpSpeed": g.select(18, 14, aiming)}))
        bound = g.get("WeaponMotionPitchDegrees" if axis == "X" else "WeaponMotionYawDegrees")
        value = _clamp(g, value, g.binary("Multiply_DoubleDouble", bound, -1), bound)
        result.append(g.select(value, 0, warmed))
    angles = g.out(g.call("MakeVector2D", inputs={"X": result[0], "Y": result[1]}))
    execute = g.set("WeaponWeightMotionAngles", angles, branch.find_then_pin())
    visible = g.call("BreakVector2D", inputs={"InVec": current_angles})
    applied = g.out(g.call("MakeVector2D", inputs={"X": g.select(g.out(visible, "X"), 0, allowed), "Y": g.select(g.out(visible, "Y"), 0, allowed)}))
    execute = g.set("WeaponPoseOffsetAngles", g.binary("Add_Vector2DVector2D", g.get("WeaponPoseOffsetAngles"), applied), execute)
    execute = g.set("WeaponWeightLastVelocity", velocity, execute)
    execute = g.set("WeaponWeightLastFacing", facing, execute)
    g.set("bWeaponWeightInitialized", time_ok, execute)


def _connect_motion_update(base):
    """/** @param base 公共装备层 @return 在既有举枪更新之后连接一次承重更新 */"""
    graph = unreal.BlueprintEditorLibrary.find_graph(base, "BlueprintThreadSafeUpdateAnimation")
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    rows = snapshot["nodes"]
    if any(row.get("function", {}).get("name") == "UpdateWeaponWeightData" for row in rows):
        return
    previous = [row for row in rows if row.get("function", {}).get("name") == "UpdateWeaponAimData"]
    if len(previous) != 1:
        raise RuntimeError("需要唯一的既有举枪更新调用")
    objects = {node.get_path_name(): node for node in editor.list_all_nodes()}
    predecessor = objects[previous[0]["path"]].find_then_pin()
    successors = list(predecessor.list_connected_pins())
    node = editor.add_call_function_node(base.generated_class().get_path_name() + ".UpdateWeaponWeightData")
    if node is None:
        raise RuntimeError("承重更新调用未解析")
    predecessor.break_pin_links()
    if not predecessor.try_create_connection(node.find_execute_pin()):
        raise RuntimeError("承重更新入口连接失败")
    for target in successors:
        if not node.find_then_pin().try_create_connection(target):
            raise RuntimeError("承重后续执行链恢复失败")
    entry = next(value for value in editor.list_all_nodes() if isinstance(value, unreal.K2Node_FunctionEntry))
    if not entry.find_output_pin("DeltaTime").try_create_connection(node.find_input_pin("DeltaTime")):
        raise RuntimeError("承重更新缺少本帧间隔")


def _configure_ground_blend(main, transition_blend_time, cruise_blend_time):
    """/** @param main 主动画蓝图 @return 只替换连续地面返回值 空手与空中路径保持原值 */"""
    graph = unreal.BlueprintEditorLibrary.find_graph(main, "Get_MMBlendTime")
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    by_guid = {row["guid"]: row for row in snapshot["nodes"]}
    previous = next(row for row in by_guid.values() if row.get("variable", {}).get("name") == "MovementMode_LastFrame")
    switch_guid = next(link["nodeGuid"] for pin in previous["pins"] for link in pin.get("links", []))
    switch = by_guid[switch_guid]
    result_guid = next(link["nodeGuid"] for pin in switch["pins"] if pin["name"] == "NewEnumerator4" for link in pin.get("links", []))
    row = by_guid[result_guid]
    if not row["nodeClass"].endswith("K2Node_FunctionResult"):
        raise RuntimeError("连续地面返回结构不符")
    g = _Graph(graph)
    objects = {node.get_path_name(): node for node in g.editor.list_all_nodes()}
    destination = objects[row["path"]].find_input_pin("ReturnValue")
    if list(destination.list_connected_pins()):
        raise RuntimeError("地面混合已含自定义驱动 请先核对当前图")
    function_class = main.generated_class().get_path_name()
    starting = g.place(g.editor.add_call_function_node(function_class + ".IsStarting"))
    pivoting = g.place(g.editor.add_call_function_node(function_class + ".IsPivoting"))
    no_acceleration = g.out(g.call("Not_PreBool", inputs={"A": g.get("HasAcceleration")}))
    braking = g.binary("BooleanAND", no_acceleration, g.get("HasVelocity"))
    transition = g.binary("BooleanOR", g.out(starting), g.binary("BooleanOR", g.out(pivoting), braking))
    duration = g.select(transition_blend_time, cruise_blend_time, transition)
    muzzle = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.HasMuzzle"))
    duration = g.select(duration, float(next(pin["defaultValue"] for pin in row["pins"] if pin["name"] == "ReturnValue")), muzzle)
    g.link(duration, destination)


def configure_weapon_locomotion_weight(main_path, base_path, layer_paths, carry_support_weights,
        motion_pitch_degrees, motion_yaw_degrees, dependent_paths, transition_blend_time, cruise_blend_time):
    """
    /**
     * @param main_path	保留现有 MM 和空手过渡的主动画蓝图
     * @param base_path	已有举枪与持枪摆动的公共装备层
     * @param layer_paths	逐层匹配三组承重数值的子层
     * @param carry_support_weights	移动时的最小持枪支撑权重
     * @param motion_pitch_degrees	加减速引起的最大俯仰幅度
     * @param motion_yaw_degrees	侧移与转向引起的最大侧向幅度
     * @param dependent_paths	父层在前的其余依赖子层
     * @param transition_blend_time	持枪起停和急转混合秒数
     * @param cruise_blend_time	持枪匀速地面混合秒数
     * @return 编译保存与非目标姿态图未改变的证据 不执行 PIE
     */
    """
    layer_paths, dependent_paths = list(layer_paths), list(dependent_paths)
    carry_support_weights, motion_pitch_degrees, motion_yaw_degrees = list(carry_support_weights), list(motion_pitch_degrees), list(motion_yaw_degrees)
    validate_weight_settings(layer_paths, carry_support_weights, motion_pitch_degrees, motion_yaw_degrees, transition_blend_time, cruise_blend_time)
    paths = [main_path, base_path] + layer_paths + dependent_paths
    if len(set(paths)) != len(paths) or any(not path.startswith("/Game/_Project/") for path in paths):
        raise RuntimeError("承重写入范围存在重复路径")
    targets = [unreal.load_asset(path) for path in paths]
    if not all(isinstance(value, unreal.AnimBlueprint) for value in targets):
        raise RuntimeError("承重配置仅接受现有动画蓝图")
    main, base, *children = targets
    parents = [base.generated_class()]
    for child in children:
        if child.get_blueprint_parent_class() not in parents:
            raise RuntimeError("承重子层继承关系或父层顺序不符")
        parents.append(child.generated_class())
    require_asset_write(targets)
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if any(value.get_outermost().get_path_name() in dirty for value in targets):
        raise RuntimeError("承重目标存在未保存编辑")
    if unreal.BlueprintEditorLibrary.find_graph(base, "UpdateWeaponWeightData") is not None:
        raise RuntimeError("承重计算已存在 请直接调整子层配置数值")
    preserved = {}
    for blueprint, names in [(main, ["AnimGraph"]), (base, ["FullBodyAdditives", "FullBody_SkeletalControls", "UpdateWeaponHandling", "HandPose_OverrideState"])]:
        for name in names:
            graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, name)
            preserved[graph.get_path_name()] = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))["logicSignature"]
    declare_weight_fields(base)
    _build_aim_update(base)
    _build_motion_update(base)
    unreal.BlueprintEditorLibrary.compile_blueprint(base)
    if base.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("承重派生函数未无警告编译通过")
    _connect_motion_update(base)
    _configure_ground_blend(main, transition_blend_time, cruise_blend_time)
    for index, blueprint in enumerate([base] + children + [main]):
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("承重引用者编译失败 " + blueprint.get_path_name())
        if 0 < index <= len(layer_paths):
            defaults = unreal.get_default_object(blueprint.generated_class())
            for name, values in [("WeaponCarrySupportAlpha", carry_support_weights), ("WeaponMotionPitchDegrees", motion_pitch_degrees), ("WeaponMotionYawDegrees", motion_yaw_degrees)]:
                defaults.set_editor_property(name, values[index - 1])
    for path, signature in preserved.items():
        if json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(unreal.load_object(None, path)))["logicSignature"] != signature:
            raise RuntimeError("承重配置改变了非目标姿态或旧持枪计算图")
    for blueprint in targets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("承重资产保存失败 " + blueprint.get_path_name())
    return {"saved": paths, "preservedGraphs": list(preserved), "transitionBlend": transition_blend_time,
        "cruiseBlend": cruise_blend_time, "carrySupport": carry_support_weights,
        "motionPitchDegrees": motion_pitch_degrees, "motionYawDegrees": motion_yaw_degrees, "runtimeAcceptance": "user"}
