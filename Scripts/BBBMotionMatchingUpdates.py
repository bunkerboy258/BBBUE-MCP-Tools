import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from editor_toolset.toolsets.blueprint import BlueprintTools, ContainerType


def _link(source, target):
    """/** @param source 输出引脚 @param target 输入引脚 @return 严格连接 */"""
    if not source.is_valid() or not target.is_valid() or not source.try_create_connection(target):
        raise RuntimeError("动作匹配更新图连接失败: " + str(source.get_pin_name() if source.is_valid() else "无效输出") + " -> " + str(target.get_pin_name() if target.is_valid() else "无效输入"))


def _getter(editor, name):
    """/** @param editor 图编辑器 @param name 成员名称 @return 成员值引脚 */"""
    node = editor.add_get_member_variable_node(name, "")
    return node.find_output_pin(name)


def _call(editor, path, values):
    """/** @param editor 图编辑器 @param path 函数路径 @param values 明确引脚值 @return 函数节点 */"""
    node = editor.add_call_function_node(path)
    if node is None:
        raise RuntimeError("函数不可用: " + path)
    for name, value in values.items():
        target = node.find_input_pin(name)
        if isinstance(value, unreal.BlueprintGraphPin):
            _link(value, target)
        if not isinstance(value, unreal.BlueprintGraphPin) and not target.set_pin_value(str(value)):
            raise RuntimeError("函数常量写入失败: " + path + "." + name)
    return node


def _save(blueprint):
    """/** @param blueprint 动画蓝图 @return 编译保存检查 */"""
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("动作匹配更新图编译存在错误或警告")
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError("动作匹配更新图保存失败")


def _objects(graph):
    """/** @param graph 图 @return 快照与节点对象 */"""
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    objects = {node.get_path_name(): node for node in editor.list_all_nodes()}
    return snapshot, objects


def configure_main_updates(main_path, base_layer_path, layer_node_guid, dry_run=True):
    """
    /**
     * @param main_path 主动画蓝图
     * @param base_layer_path 数据库提供基础层
     * @param layer_node_guid 持续关联动画层节点
     * @param dry_run 仅核验事实与接口
     * @return 主线程数据库上下文与线程安全轨迹更新配置
     */
    """
    main = unreal.load_asset(main_path)
    base = unreal.load_asset(base_layer_path)
    if not all(isinstance(value, unreal.AnimBlueprint) and value.get_path_name().startswith("/Game/_Project/") for value in [main, base]):
        raise RuntimeError("要求自有动画蓝图")
    provider = unreal.BlueprintEditorLibrary.find_graph(base, "SelectMMDatabases")
    callback = unreal.BlueprintEditorLibrary.find_graph(main, "UpdateMotionMatching")
    if provider is None or callback is None:
        raise RuntimeError("要求已有普通运动数据库接口与节点回调")
    facts = {"ActorRotation": "SourceActorRotation", "MeshWorldTransform": "SourceMeshWorldTransform", "Velocity": "SourceVelocity", "Acceleration": "SourceAcceleration", "bMovingOnGround": "bSourceMovingOnGround", "GravityZ": "SourceGravityZ", "MaxSpeed": "SourceMaxSpeed", "BrakingDeceleration": "SourceBrakingDecelerationWalking", "GroundFriction": "SourceGroundFriction", "BrakingFriction": "SourceBrakingFriction", "BrakingFrictionFactor": "SourceBrakingFrictionFactor", "bUseSeparateBrakingFriction": "bSourceUseSeparateBrakingFriction", "BrakingSubStepTime": "SourceBrakingSubStepTime"}
    defaults = unreal.get_default_object(main.generated_class())
    for name in facts.values():
        defaults.get_editor_property(name)
    report = {"asset": main_path, "function": "UpdateMotionMatching", "facts": facts, "dryRun": dry_run}
    if dry_run:
        return report
    require_asset_write([main])
    main.modify()
    members = set(str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(main, False))
    for name, kind in [("MMPreviousGrounded", "bool"), ("MMContextInitialized", "bool"), ("MMLandingRemaining", "float")]:
        if name not in members:
            BlueprintTools.add_variable(main, name, kind)
    callback_editor = unreal.BlueprintGraphEditor.get_graph_editor(callback)
    entry = next(node for node in callback_editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    callback_editor.remove_nodes([node for node in callback_editor.list_all_nodes() if node != entry])
    callback_snapshot, callback_objects = _objects(callback)
    entry_row = next(row for row in callback_snapshot["nodes"] if row["path"] == entry.get_path_name())
    node_parameters = [pin["name"] for pin in entry_row["pins"] if pin.get("typeObject", "").endswith(".AnimNodeReference")]
    if len(node_parameters) != 1:
        raise RuntimeError("节点回调必须具有唯一 AnimNodeReference 输入")
    conversion = _call(callback_editor, "/Script/PoseSearch.MotionMatchingAnimNodeLibrary.ConvertToMotionMatchingNodePure", {"Node": entry.find_output_pin(node_parameters[0])})
    setter = _call(callback_editor, "/Script/PoseSearch.MotionMatchingAnimNodeLibrary.SetDatabasesToSearch", {"MotionMatchingNode": conversion.find_output_pin("MotionMatchingNode"), "Databases": _getter(callback_editor, "MMSelectedDatabases"), "InterruptMode": "InterruptOnDatabaseChangeAndInvalidateContinuingPose"})
    _link(entry.find_then_pin(), setter.find_execute_pin())
    callback_editor.set_is_thread_safe_function(True)

    update_graph = unreal.BlueprintEditorLibrary.find_graph(main, "BlueprintThreadSafeUpdateAnimation")
    update_editor = unreal.BlueprintGraphEditor.get_graph_editor(update_graph)
    snapshot, objects = _objects(update_graph)
    for row in snapshot["nodes"]:
        if row.get("function", {}).get("name") in ["UpdateGroundTrajectory", "UpdateLocomotionTrajectory"] or (row["nodeClass"].endswith("K2Node_VariableSet") and row.get("variable", {}).get("name") in {"HasVelocity", "IsCrouching", "IsFirstUpdate"}):
            node = objects[row["path"]]
            inputs = list(node.find_execute_pin().list_connected_pins())
            outputs = list(node.find_then_pin().list_connected_pins())
            update_editor.remove_nodes([node])
            for before in inputs:
                for after in outputs:
                    _link(before, after)
    update_entry = next(node for node in update_editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    targets = list(update_entry.find_then_pin().list_connected_pins())
    values = {pin: _getter(update_editor, name) for pin, name in facts.items()}
    values.update({"TrajectoryData": _getter(update_editor, "MMTrajectoryData"), "DeltaTime": update_entry.find_output_pin("DeltaTime"), "InOutTrajectory": _getter(update_editor, "MMTrajectory"), "InOutPreviousActorYaw": _getter(update_editor, "MMPreviousActorYaw")})
    trajectory = _call(update_editor, "/Script/ABBB_Evac.BBBMotionMatchingLibrary.UpdateLocomotionTrajectory", values)
    speed = _call(update_editor, "/Script/Engine.KismetMathLibrary.VSizeXYSquared", {"A": _getter(update_editor, "SourceVelocity")})
    moving = _call(update_editor, "/Script/Engine.KismetMathLibrary.Greater_DoubleDouble", {"A": speed.find_output_pin("ReturnValue"), "B": "1.0"})
    velocity_flag = update_editor.add_set_member_variable_node("HasVelocity")
    _link(moving.find_output_pin("ReturnValue"), velocity_flag.find_input_pin("HasVelocity"))
    crouch_flag = update_editor.add_set_member_variable_node("IsCrouching")
    _link(_getter(update_editor, "bSourceCrouching"), crouch_flag.find_input_pin("IsCrouching"))
    _link(trajectory.find_then_pin(), velocity_flag.find_execute_pin())
    _link(velocity_flag.find_then_pin(), crouch_flag.find_execute_pin())
    for target in targets:
        _link(crouch_flag.find_then_pin(), target)
    _link(update_entry.find_then_pin(), trajectory.find_execute_pin())

    event_graph = unreal.BlueprintEditorLibrary.find_graph(main, "EventGraph")
    event_editor = unreal.BlueprintGraphEditor.get_graph_editor(event_graph)
    events = [node for node in event_editor.list_all_nodes() if isinstance(node, unreal.K2Node_Event) and "BlueprintUpdateAnimation" in str(node.get_node_title())]
    if len(events) != 1:
        raise RuntimeError("动画主线程更新事件必须唯一")
    event = events[0]
    connected = set()
    pending = [pin.get_owning_node() for pin in event.find_then_pin().list_connected_pins()]
    while pending:
        node = pending.pop()
        if node in connected or node == event:
            continue
        if isinstance(node, unreal.K2Node_Event):
            raise RuntimeError("动画更新分支连接了其它事件")
        connected.add(node)
        for pin in list(node.list_input_pins()) + list(node.list_output_pins()):
            pending.extend(link.get_owning_node() for link in pin.list_connected_pins())
    event_editor.remove_nodes(list(connected))
    context_graph = unreal.BlueprintEditorLibrary.find_graph(main, "UpdateMMDatabaseContext")
    if context_graph is None:
        context_graph = BlueprintTools.add_function_graph(main, "UpdateMMDatabaseContext")
        BlueprintTools.add_function_param(context_graph, "DeltaTime", "float", True)
    context_editor = unreal.BlueprintGraphEditor.get_graph_editor(context_graph)
    context_entry = next(node for node in context_editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    context_editor.remove_nodes([node for node in context_editor.list_all_nodes() if node != context_entry])
    velocity = _call(context_editor, "/Script/Engine.KismetMathLibrary.BreakVector", {"InVec": _getter(context_editor, "SourceVelocity")})
    context = _call(context_editor, "/Script/ABBB_Evac.BBBMotionMatchingLibrary.UpdateLocomotionContext", {"DeltaTime": context_entry.find_output_pin("DeltaTime"), "bMovingOnGround": _getter(context_editor, "bSourceMovingOnGround"), "VerticalVelocity": velocity.find_output_pin("Z"), "bInOutPreviousGrounded": _getter(context_editor, "MMPreviousGrounded"), "bInOutInitialized": _getter(context_editor, "MMContextInitialized"), "InOutLandingRemaining": _getter(context_editor, "MMLandingRemaining")})
    _link(context_entry.find_then_pin(), context.find_execute_pin())
    linked = _call(context_editor, "/Script/Engine.AnimInstance.GetLinkedAnimLayerInstanceByGroup", {"InGroup": "ItemAnimLayers"})
    available = list(context_editor.list_available_nodes([]))
    casts = [value for value in available if value.rsplit("|", 1)[-1] == "CastTo" + base.get_name()]
    if len(casts) != 1:
        raise RuntimeError("基础动画层转换节点不唯一")
    cast = context_editor.create_node_from_name(casts[0], unreal.Vector2D(), [])
    _link(context.find_then_pin(), cast.find_execute_pin())
    _link(linked.find_output_pin("ReturnValue"), cast.find_input_pin("Object"))
    as_base = next(pin for pin in cast.list_output_pins() if str(pin.get_pin_name()).startswith("As"))
    select = _call(context_editor, base.generated_class().get_path_name() + ".SelectMMDatabases", {"self": as_base, "Crouching": _getter(context_editor, "bSourceCrouching"), "Airborne": context.find_output_pin("bOutAirborne"), "Rising": context.find_output_pin("bOutRising"), "Landing": context.find_output_pin("bOutLanding")})
    for valid, execute, databases in [(True, cast.find_then_pin(), select.find_output_pin("Databases")), (False, cast.find_output_pin("CastFailed"), _getter(context_editor, "MMEmptyDatabases"))]:
        flag = context_editor.add_set_member_variable_node("MMDatabaseProviderValid")
        flag.find_input_pin("MMDatabaseProviderValid").set_pin_value(str(valid))
        _link(execute, flag.find_execute_pin())
        chosen = context_editor.add_set_member_variable_node("MMSelectedDatabases")
        _link(databases, chosen.find_input_pin("MMSelectedDatabases"))
        _link(flag.find_then_pin(), chosen.find_execute_pin())
    unreal.BlueprintEditorLibrary.compile_blueprint(main)
    update_call = _call(event_editor, main.generated_class().get_path_name() + ".UpdateMMDatabaseContext", {"DeltaTime": event.find_output_pin("DeltaTimeX")})
    _link(event.find_then_pin(), update_call.find_execute_pin())
    for graph in [callback, context_graph]:
        for index, node in enumerate(unreal.BlueprintGraphEditor.get_graph_editor(graph).list_all_nodes()):
            node.set_node_pos(unreal.IntPoint((index % 5) * 340, (index // 5) * 230))
    for graph in unreal.BlueprintEditorLibrary.list_graphs(main):
        for node in unreal.BlueprintGraphEditor.get_graph_editor(graph).list_all_nodes():
            if isinstance(node, unreal.AnimGraphNode_MotionMatching):
                data = node.get_editor_property("node")
                data.set_editor_property("database", None)
                node.set_editor_property("node", data)
                pin = node.find_input_pin("Database")
                if pin.is_valid() and not pin.set_pin_value("None"):
                    raise RuntimeError("主 MM 节点默认数据库清理失败")
    foot_graph = unreal.BlueprintEditorLibrary.find_graph(main, "GetFootPlacementAlpha")
    foot_editor = unreal.BlueprintGraphEditor.get_graph_editor(foot_graph)
    foot_snapshot, foot_objects = _objects(foot_graph)
    selectors = [row for row in foot_snapshot["nodes"] if row.get("function", {}).get("name") == "SelectFloat"]
    if len(selectors) != 1:
        raise RuntimeError("贴地权重的布尔选择边界不唯一")
    gate = _call(foot_editor, "/Script/Engine.KismetMathLibrary.BooleanAND", {"A": _getter(foot_editor, "UseFootPlacement"), "B": _getter(foot_editor, "bSourceMovingOnGround")})
    _link(gate.find_output_pin("ReturnValue"), foot_objects[selectors[0]["path"]].find_input_pin("bPickA"))
    from BBBMotionMatchingCleanup import _prune_graph
    _prune_graph(foot_graph)
    _save(main)
    report["saved"] = True
    return report
