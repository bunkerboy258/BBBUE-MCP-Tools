import copy
import json

import unreal

from BBBAssetWritePolicy import require_asset_write


_LOCAL_POSE_TYPE = "/Script/Engine.PoseLink"
_MM_CLASS = "/Script/PoseSearchEditor.AnimGraphNode_MotionMatching"
_HISTORY_CLASS = "/Script/PoseSearchEditor.AnimGraphNode_PoseSearchHistoryCollector"


def _snapshot(graph):
    """/** @param graph\t明确动画图 @return 原生只读逻辑快照 */"""
    result = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    if result.get("error"):
        raise RuntimeError("读取动画图失败: " + str(result["error"]))
    return result


def _pin(row, name, direction):
    """/** @param row\t节点快照 @param name\t原生引脚名 @param direction\t方向 @return 唯一引脚 */"""
    matches = [pin for pin in row["pins"] if pin["name"] == name and pin["direction"] == direction]
    if len(matches) != 1 or matches[0].get("orphaned"):
        raise RuntimeError("引脚不存在 不唯一或已经孤立: " + row["guid"] + "." + name)
    return matches[0]


def plan_pose_replacement(snapshot, source_node_guid, source_output_pin, destination_node_guid,
                          destination_input_pin, remove_node_guids):
    """
    /**
     * 核验明确旧姿态分支的闭合边界 不推断或扩大删除范围
     * @param snapshot\t原生逻辑快照
     * @param source_node_guid\t原姿态源标识
     * @param source_output_pin\t原姿态输出引脚
     * @param destination_node_guid\t保留的下游节点标识
     * @param destination_input_pin\t保留下游输入引脚
     * @param remove_node_guids\t完整待删除分支 空数组仅删除原姿态源
     * @return 核验后的节点和边界 不修改快照
     */
    """
    nodes = snapshot.get("nodes", [])
    by_guid = {row["guid"]: row for row in nodes}
    if len(by_guid) != len(nodes):
        raise RuntimeError("动画图存在重复节点标识")
    if source_node_guid == destination_node_guid or source_node_guid not in by_guid or destination_node_guid not in by_guid:
        raise RuntimeError("源和目标必须是同一图内不同的现有节点")
    removed = list(remove_node_guids) or [source_node_guid]
    if len(removed) != len(set(removed)) or set(removed) - set(by_guid):
        raise RuntimeError("删除范围包含重复或不存在的节点")
    if source_node_guid not in removed or destination_node_guid in removed:
        raise RuntimeError("删除范围必须包含原姿态源并保留下游节点")
    if any(row["nodeClass"] in {_MM_CLASS, _HISTORY_CLASS} for row in nodes):
        raise RuntimeError("目标图已经包含 Motion Matching 或 Pose History 禁止重复构造")
    source = _pin(by_guid[source_node_guid], source_output_pin, "output")
    destination = _pin(by_guid[destination_node_guid], destination_input_pin, "input")
    for pin in [source, destination]:
        if pin.get("kind") != "pose" or pin.get("typeObject") != _LOCAL_POSE_TYPE:
            raise RuntimeError("替换边界必须是本地空间姿态引脚")
    expected = {"nodeGuid": source_node_guid, "pinId": source["pinId"]}
    if destination["links"] != [expected]:
        raise RuntimeError("目标输入与明确原姿态源不一致 请重新读取图表")
    outgoing = {"nodeGuid": destination_node_guid, "pinId": destination["pinId"]}
    if source["links"] != [outgoing]:
        raise RuntimeError("原姿态输出存在共享使用 禁止替换共享分支")
    removal = set(removed)
    all_pins = {(row["guid"], pin["pinId"]): pin for row in nodes for pin in row["pins"]}
    for row in nodes:
        if row["guid"] not in removal:
            continue
        if row.get("boundGraph") or row.get("macroGraph"):
            raise RuntimeError("删除范围含子图 请先明确拆分基础姿态边界: " + row["guid"])
        if row["nodeClass"].rsplit(".", 1)[-1] in {
                "AnimGraphNode_Root", "AnimGraphNode_LinkedInputPose", "AnimGraphNode_SaveCachedPose",
                "AnimGraphNode_UseCachedPose", "K2Node_FunctionEntry", "K2Node_FunctionResult"}:
            raise RuntimeError("禁止隐式删除图入口 输出或共享姿态缓存: " + row["guid"])
        for pin in row["pins"]:
            if pin.get("kind") == "exec":
                raise RuntimeError("旧姿态分支不得含执行逻辑: " + row["guid"])
            for link in pin["links"]:
                linked_pin = all_pins.get((link["nodeGuid"], link["pinId"]))
                if linked_pin is None:
                    raise RuntimeError("删除范围存在跨图或无效连接")
                reverse = {"nodeGuid": row["guid"], "pinId": pin["pinId"]}
                if reverse not in linked_pin["links"] or pin["direction"] == linked_pin["direction"]:
                    raise RuntimeError("删除范围存在不对称或方向错误连接")
                if link["nodeGuid"] in removal:
                    continue
                if row["guid"] == source_node_guid and pin["pinId"] == source["pinId"] and link == outgoing:
                    continue
                raise RuntimeError("删除范围存在未授权边界连接: " + row["guid"] + "." + pin["name"])
    reached = {source_node_guid}
    pending = [source_node_guid]
    while pending:
        current = pending.pop()
        for pin in by_guid[current]["pins"]:
            if pin["direction"] != "input":
                continue
            for link in pin["links"]:
                linked = link["nodeGuid"]
                if linked not in reached:
                    reached.add(linked)
                    pending.append(linked)
    if reached != removal:
        raise RuntimeError("删除范围包含与原姿态源无关的节点")
    return {"source": by_guid[source_node_guid], "destination": by_guid[destination_node_guid],
            "sourcePin": source, "destinationPin": destination, "removeNodeGuids": sorted(removal)}


def _retained_rows(snapshot, removal, destination_guid, destination_pin_id):
    """/** @param snapshot\t图快照 @param removal\t删除集合 @param destination_guid\t下游标识 @param destination_pin_id\t边界引脚 @return 可比较的保留逻辑 */"""
    rows = {}
    for original in snapshot["nodes"]:
        if original["guid"] in removal or original.get("isComment"):
            continue
        row = copy.deepcopy(original)
        row.pop("tooltip", None)
        if row["guid"] == destination_guid:
            for pin in row["pins"]:
                if pin["pinId"] == destination_pin_id:
                    pin["links"] = []
        rows[row["guid"]] = row
    return rows


def _connection(output, input_pin):
    """/** @param output\t输出引脚 @param input_pin\t输入引脚 @return 无返回 连接失败时抛错 */"""
    if not output.is_valid() or not input_pin.is_valid() or not output.try_create_connection(input_pin):
        raise RuntimeError("Motion Matching 姿态连线失败 不保存")


def replace_motion_matching_pose(graph_path, source_node_guid, source_output_pin, destination_node_guid,
                                 destination_input_pin, database_path, trajectory_variable,
                                 remove_node_guids=(), on_update_function="", dry_run=True,
                                 expected_snapshot=""):
    """
    /**
     * 将明确且闭合的旧姿态分支替换为标准 MM 和外部轨迹 Pose History
     * @param graph_path\t项目动画图完整对象路径
     * @param source_node_guid\t旧姿态源标识
     * @param source_output_pin\t旧姿态输出原生引脚名
     * @param destination_node_guid\t保留下游节点标识
     * @param destination_input_pin\t保留下游输入原生引脚名
     * @param database_path\t相同骨架且已有动画的数据库
     * @param trajectory_variable\t本蓝图已有的 TransformTrajectory 变量
     * @param remove_node_guids\t明确删除分支 空数组只删除源节点
     * @param on_update_function\t已有线程安全动画节点更新函数 可为空
     * @param dry_run\t只预检 不创建节点 不编译或保存
     * @param expected_snapshot\t应用前要求匹配的只读快照标识
     * @return 删除与新增节点 连接 编译 保存及回读结果
     */
    """
    if not isinstance(graph_path, str) or not graph_path.startswith("/Game/_Project/"):
        raise RuntimeError("需要明确的项目自有动画图路径")
    if type(dry_run) is not bool or not isinstance(trajectory_variable, str) or not trajectory_variable:
        raise RuntimeError("需要布尔 dry_run 和已有轨迹变量名")
    graph = unreal.load_object(None, graph_path)
    if graph is None:
        raise RuntimeError("动画图不存在")
    before = _snapshot(graph)
    blueprint = unreal.load_asset(before["blueprint"])
    if not isinstance(blueprint, unreal.AnimBlueprint) or not any(name in before["schemaClass"] for name in ["AnimationGraphSchema", "AnimationStateGraphSchema"]):
        raise RuntimeError("目标必须为动画蓝图中的动画姿态图")
    if expected_snapshot and before["snapshot"] != expected_snapshot:
        raise RuntimeError("动画图已变化 请重新预检")
    plan = plan_pose_replacement(before, source_node_guid, source_output_pin, destination_node_guid,
                                 destination_input_pin, remove_node_guids)
    database = unreal.load_asset(database_path)
    if not isinstance(database, unreal.PoseSearchDatabase):
        raise RuntimeError("目标不是 Pose Search Database")
    schema = database.get_editor_property("schema")
    skeletons = list(schema.get_editor_property("skeletons")) if schema is not None else []
    if len(skeletons) != 1 or skeletons[0].get_editor_property("skeleton") != blueprint.get_editor_property("target_skeleton"):
        raise RuntimeError("数据库必须使用与动画蓝图相同的单一骨架")
    if database.get_num_animation_assets() <= 0:
        raise RuntimeError("数据库没有动画条目")
    default = unreal.get_default_object(blueprint.generated_class())
    if not isinstance(default.get_editor_property(trajectory_variable), unreal.TransformTrajectory):
        raise RuntimeError("轨迹变量必须为当前 TransformTrajectory 类型")
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    objects = {node.get_path_name(): node for node in editor.list_all_nodes()}
    source = objects[plan["source"]["path"]]
    destination = objects[plan["destination"]["path"]]
    removed = [objects[row["path"]] for row in before["nodes"] if row["guid"] in plan["removeNodeGuids"]]
    callback_library = None
    if on_update_function:
        callback_library = getattr(unreal, "BBBMotionMatchingEditorLibrary", None)
        if callback_library is None or not hasattr(callback_library, "set_animation_node_update_function"):
            raise RuntimeError("原生动画节点回调绑定能力尚未编译")
        if not callback_library.set_animation_node_update_function(source, on_update_function, False):
            raise RuntimeError("更新函数不存在或未通过线程安全签名预检")
    report = {"asset": blueprint.get_path_name(), "graph": graph_path, "database": database.get_path_name(),
              "trajectoryVariable": trajectory_variable, "onUpdateFunction": on_update_function,
              "removeNodeGuids": plan["removeNodeGuids"], "snapshot": before["snapshot"],
              "dryRun": dry_run, "compiled": False, "saved": False}
    if dry_run:
        return report
    require_asset_write([blueprint])
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if blueprint.get_outermost().get_path_name() in dirty:
        raise RuntimeError("目标存在未保存编辑 禁止混入本次构图")
    library = unreal.BBBBlueprintEditorLibrary
    if before["snapshot"] != _snapshot(graph)["snapshot"]:
        raise RuntimeError("预检期间动画图发生变化")
    try:
        with unreal.ScopedEditorTransaction("BBB Replace Motion Matching Pose"):
            blueprint.modify()
            graph.modify()
            position = source.get_node_pos()
            motion = library.create_native_animation_node(graph, unreal.AnimGraphNode_MotionMatching.static_class(), position)
            history = library.create_native_animation_node(graph, unreal.AnimGraphNode_PoseSearchHistoryCollector.static_class(),
                unreal.IntPoint(position.x + 350, position.y))
            if motion is None or history is None:
                raise RuntimeError("创建标准 MM 或 Pose History 节点失败")
            node = motion.get_editor_property("node")
            node.set_editor_property("database", database)
            motion.set_editor_property("node", node)
            database_pin = motion.find_input_pin("Database")
            if not database_pin.is_valid() or not database_pin.set_pin_value(database.get_path_name()):
                raise RuntimeError("MM 数据库输入写入失败")
            history_data = history.get_editor_property("node")
            if history_data.get_editor_property("generate_trajectory") or history_data.get_editor_property("root_bone_recovery_time") != 0:
                raise RuntimeError("Pose History 默认开启了实验行为 拒绝继续")
            if not library.bind_animation_node_input(history, "TransformTrajectory", [trajectory_variable]):
                raise RuntimeError("Pose History 外部轨迹绑定失败")
            if callback_library is not None and not callback_library.set_animation_node_update_function(motion, on_update_function, True):
                raise RuntimeError("MM 更新函数绑定失败")
            target = destination.find_input_pin(destination_input_pin)
            _connection(motion.find_output_pin("Pose"), history.find_input_pin("Source"))
            target.break_pin_links()
            _connection(history.find_output_pin("Pose"), target)
            editor.remove_nodes(removed)
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("Motion Matching 图编译有错误或警告")
            after = _snapshot(graph)
            original_guids = {row["guid"] for row in before["nodes"]}
            new_rows = [row for row in after["nodes"] if row["guid"] not in original_guids]
            created_classes = sorted(row["nodeClass"] for row in new_rows)
            expected_classes = sorted([_MM_CLASS, _HISTORY_CLASS, "/Script/PropertyAccessNode.K2Node_PropertyAccess"])
            if created_classes != expected_classes:
                raise RuntimeError("构图产生非预期节点 不保存: " + json.dumps(created_classes))
            removal = set(plan["removeNodeGuids"])
            preserved_before = _retained_rows(before, removal, destination_node_guid, plan["destinationPin"]["pinId"])
            preserved_after = _retained_rows(after, {row["guid"] for row in new_rows}, destination_node_guid, plan["destinationPin"]["pinId"])
            if preserved_before != preserved_after:
                raise RuntimeError("保留下游逻辑发生额外变化 不保存")
            report["created"] = [{"guid": row["guid"], "path": row["path"], "class": row["nodeClass"]} for row in new_rows]
            report["connections"] = [{"nodeGuid": row["guid"], "pin": pin["name"], "links": pin["links"]}
                for row in new_rows for pin in row["pins"] if pin["links"]]
            report["compiled"] = True
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                raise RuntimeError("Motion Matching 动画蓝图保存失败")
            readback = _snapshot(graph)
            if readback["logicSignature"] != after["logicSignature"]:
                raise RuntimeError("保存后动画图回读不一致")
            report.update({"saved": True, "snapshot": readback["snapshot"], "retainedLogicUnchanged": True})
    except Exception as error:
        unreal.log_error("[BBBMotionMatching] 构图失败 请核查当前事务和未保存状态: {} {}".format(graph_path, error))
        raise
    unreal.log("[BBBMotionMatching] 已替换明确姿态分支并通过编译保存: " + graph_path)
    return report
