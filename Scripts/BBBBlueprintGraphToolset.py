import json
import os

import unreal
import toolset_registry
from toolset_registry.registration import Registration
from editor_toolset.toolsets.blueprint import BlueprintTools
from editor_toolset.toolsets import blueprint_dsl


def _read_aliases(value):
    aliases = json.loads(value)
    if not isinstance(aliases, dict):
        raise RuntimeError("节点映射必须为 JSON 对象")

    for key, target in aliases.items():
        if not isinstance(key, str) or not isinstance(target, str):
            raise RuntimeError("节点映射的键和值必须为字符串")

    return aliases


def _capture_layout_graph(graph):
    """
    /**
     * 一次读取原生引脚与尺寸 不用本地化显示文字推断执行类型
     * @param graph	目标蓝图图表
     * @return 节点对象 尺寸快照 连线 注释框和尺寸估算清单
     */
    """
    inspect = getattr(unreal.BBBBlueprintEditorLibrary, "inspect_blueprint_graph_geometry", None)
    if not callable(inspect):
        raise RuntimeError("缺少 InspectBlueprintGraphGeometry 请编译原生编辑器模块后重新启动宿主")

    geometry = json.loads(inspect(graph))
    if geometry.get("error"):
        raise RuntimeError("蓝图几何检查失败 " + str(geometry["error"]))

    if geometry.get("graph") != graph.get_path_name():
        raise RuntimeError("原生几何检查返回了不同图表")

    objects = {}
    nodes = {}
    comments = []
    estimated = []
    pins_by_path = {}
    execution_pins = {}
    graph_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    graph_nodes = list(graph_editor.list_all_nodes()) + list(graph_editor.list_comment_nodes())
    all_objects = {node.get_path_name(): node for node in graph_nodes}
    items = geometry["nodes"]
    if set(all_objects) != {item["path"] for item in items}:
        raise RuntimeError("原生几何快照与脚本节点列表不一致")

    for item in sorted(items, key=lambda value: value["path"]):
        path = item["path"]
        node = all_objects[path]
        snapshot = {
            "id": path,
            "x": int(item["x"]),
            "y": int(item["y"]),
            "width": int(item["width"]),
            "height": int(item["height"]),
            "exec": bool(item["executionPins"]),
        }
        if item["comment"]:
            snapshot["members"] = sorted(item["members"])
            comments.append(snapshot)
            continue

        objects[path] = node
        nodes[path] = snapshot
        pins_by_path[path] = list(node.list_all_pins())
        execution_pins[path] = set(item["executionPins"])
        if item["estimated"]:
            estimated.append(path)

    edges = []
    for source_path in sorted(nodes):
        for source_order, pin in enumerate(pins_by_path[source_path]):
            if pin.get_pin_direction() != unreal.EdGraphPinDirection.EGPD_OUTPUT:
                continue

            kind = "data"
            if "output:" + str(pin.get_pin_name()) in execution_pins[source_path]:
                kind = "exec"

            for connected in pin.list_connected_pins():
                target_path = connected.get_owning_node().get_path_name()
                if target_path not in nodes:
                    raise RuntimeError("连线指向未纳入排版的节点 " + target_path)

                target_order = next(
                    index for index, candidate in enumerate(pins_by_path[target_path])
                    if candidate.is_same_native_pin(connected)
                )
                edges.append({
                    "source": source_path,
                    "target": target_path,
                    "kind": kind,
                    "sourceOrder": source_order,
                    "targetOrder": target_order,
                    "sourcePin": str(pin.get_pin_name()),
                    "targetPin": str(connected.get_pin_name()),
                })

    edges.sort(key=lambda edge: (
        edge["source"],
        edge["sourceOrder"],
        edge["target"],
        edge["targetOrder"],
    ))
    return objects, nodes, edges, comments, estimated


def _require_layout_checkout(blueprint):
    """
    /**
     * 写入前核对源控 不自动签出或保存目标资产
     * @param blueprint	目标蓝图
     * @return 检查通过时无返回值
     */
    """
    from editor_toolset.toolsets.asset import AssetTools

    path = blueprint.get_path_name()
    if not unreal.SourceControl.is_enabled() or not unreal.SourceControl.is_available():
        raise RuntimeError("蓝图排版写入前必须连接 Perforce")

    if unreal.SourceControl.current_provider() != "Perforce":
        raise RuntimeError("蓝图排版写入要求 Perforce 独占签出")

    package = path.split(".", 1)[0]
    filename = os.path.abspath(os.path.join(unreal.Paths.project_content_dir(), package[len("/Game/"):] + ".uasset"))
    state = unreal.SourceControl.query_file_state(filename, silent=True, use_source_control_state_cache=False)
    writable = AssetTools.is_checked_out(path) and AssetTools.can_edit_asset(path)
    if state.is_valid and state.is_added and state.can_edit and not state.is_checked_out_other:
        writable = True

    if not state.is_valid or state.is_unknown or state.is_checked_out_other or state.is_conflicted or state.is_deleted or not writable:
        raise RuntimeError("目标蓝图必须已独占签出或已打开添加且可编辑 " + path)


@unreal.uclass()
class BBBBlueprintGraphToolset(unreal.ToolsetDefinition):
    """通过显式语言映射复用官方蓝图图表工具 不改变编辑器语言"""

    @toolset_registry.tool_call
    @staticmethod
    def configure_blueprint_function_thread_safety(blueprint_path: str, function_name: str, thread_safe: bool, dry_run: bool = True) -> str:
        """检查或设置蓝图函数线程安全声明 编译失败时不保存"""
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改函数声明")

        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("蓝图资产不存在")

        graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, function_name)
        if graph is None:
            raise RuntimeError("蓝图函数图不存在")

        entries = [node for node in BlueprintTools.find_nodes(graph) if node.get_class().get_name() == "K2Node_FunctionEntry"]
        if len(entries) != 1:
            raise RuntimeError("函数入口数量必须为一")

        entry = entries[0]
        previous = unreal.BBBBlueprintEditorLibrary.configure_blueprint_function_thread_safety(entry, thread_safe, True)
        if previous < 0:
            raise RuntimeError("函数声明读取失败")
        result = {"blueprint": blueprint.get_path_name(), "function": function_name, "previous": previous, "requested": thread_safe, "dryRun": dry_run}
        if dry_run:
            return json.dumps(result, ensure_ascii=False)

        with unreal.ScopedEditorTransaction("配置蓝图函数线程安全声明"):
            blueprint.modify()
            entry.modify()
            if unreal.BBBBlueprintEditorLibrary.configure_blueprint_function_thread_safety(entry, thread_safe, False) < 0:
                raise RuntimeError("函数声明写入失败")
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)

        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            unreal.log_error("蓝图函数线程安全配置后编译失败 不保存 {}".format(blueprint_path))
            raise RuntimeError("函数线程安全编译检查失败")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("函数声明保存失败")

        result["saved"] = True
        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def invoke_pie_object_function(object_path: str, function_name: str, arguments_json: str) -> str:
        """调用当前 PIE 对象的反射函数 拒绝编辑器资产与默认对象"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        instance = unreal.find_object(None, object_path)
        if world is None or instance is None:
            raise RuntimeError("PIE 或目标对象不存在")

        owner = instance
        while owner is not None and owner.get_world() != world:
            owner = owner.get_outer()
        if owner is None:
            raise RuntimeError("目标对象及其所有者不属于当前 PIE")

        arguments = json.loads(arguments_json)
        if not isinstance(arguments, list):
            raise RuntimeError("参数必须为 JSON 位置参数数组")
        result = instance.call_method(function_name, tuple(arguments))
        return json.dumps({"object": object_path, "function": function_name, "result": result}, default=str, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_owned_objects(asset_path: str, class_path: str) -> str:
        """只读列出指定资产内部的指定类型对象 不遍历其它资产"""
        asset = unreal.EditorAssetLibrary.load_asset(asset_path) if asset_path else None
        target_class = unreal.load_class(None, class_path)
        if (asset_path and asset is None) or target_class is None:
            raise RuntimeError("资产或对象类型不存在")

        prefix = asset.get_path_name() + ":" if asset else ""
        results = []
        for instance in unreal.ObjectIterator(target_class):
            if not instance.get_path_name().startswith(prefix):
                continue

            item = {"path": instance.get_path_name(), "class": instance.get_class().get_path_name()}
            if isinstance(instance, unreal.Widget):
                parent = instance.get_parent()
                item["parent"] = parent.get_path_name() if parent else None
                item["visibility"] = str(instance.get_visibility())
            if isinstance(instance, unreal.TextBlock):
                item["text"] = str(instance.get_text())
            results.append(item)
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def optimize_blueprint_node_layout(
        graph_path: str,
        horizontal_spacing: int = 320,
        vertical_spacing: int = 180,
        dry_run: bool = False,
    ) -> str:
        """按蓝图连线拓扑从左到右分层排版节点 不自动保存资产"""
        from BBBBlueprintLayout import calculate_layout

        if not isinstance(graph_path, str) or not graph_path.startswith("/Game/"):
            raise RuntimeError("只能编辑项目蓝图图表")

        if type(horizontal_spacing) is not int or type(vertical_spacing) is not int:
            raise RuntimeError("节点间距必须为整数")

        if type(dry_run) is not bool:
            raise RuntimeError("dry_run 必须为布尔值")

        if not 0 < horizontal_spacing <= 10000 or not 0 < vertical_spacing <= 10000:
            raise RuntimeError("节点间距必须大于零且不超过 10000")

        graph = unreal.load_object(None, graph_path)
        if not isinstance(graph, unreal.EdGraph):
            raise RuntimeError("目标不是蓝图图表")

        blueprint = graph.get_outer()
        if not isinstance(blueprint, unreal.Blueprint):
            raise RuntimeError("图表必须直接属于蓝图")

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止修改蓝图图表")

        objects, nodes, edges, comments, estimated = _capture_layout_graph(graph)
        plan = calculate_layout(nodes, edges, comments, horizontal_spacing, vertical_spacing)
        changes = {
            path: position for path, position in plan["positions"].items()
            if position != (nodes[path]["x"], nodes[path]["y"])
        }
        warnings = list(plan["warnings"])
        if estimated:
            warnings.append("部分节点未提供有效尺寸 使用官方引擎估算 请在可视编辑器复核")

        if plan["after"]["overlaps"]:
            warnings.append("布局仍有节点重叠 写入被拒绝 请检查固定注释框或节点尺寸")

        report = {
            "graph": graph_path,
            "nodes": len(nodes),
            "edges": len(edges),
            "execEdges": sum(edge["kind"] == "exec" for edge in edges),
            "dataEdges": sum(edge["kind"] == "data" for edge in edges),
            "moved": 0,
            "plannedMoves": len(changes),
            "cycleBreaks": plan["cycleBreaks"],
            "excludedComments": len(comments),
            "commentMembers": plan["commentMembers"],
            "components": plan["components"],
            "horizontalSpacing": horizontal_spacing,
            "verticalSpacing": vertical_spacing,
            "dryRun": dry_run,
            "estimatedSizes": estimated,
            "before": plan["before"],
            "after": plan["after"],
            "positions": {path: list(position) for path, position in plan["positions"].items()},
            "warnings": warnings,
            "saved": False,
        }
        for warning in warnings:
            unreal.log_warning("[BBBBlueprintLayout] " + warning)

        if not dry_run and changes:
            try:
                if plan["after"]["overlaps"]:
                    raise RuntimeError("拒绝应用存在节点重叠的布局")

                _require_layout_checkout(blueprint)
                original = {path: (nodes[path]["x"], nodes[path]["y"]) for path in changes}
                with unreal.ScopedEditorTransaction("BBB Optimize Blueprint Node Layout"):
                    blueprint.modify()
                    graph.modify()
                    for path in changes:
                        objects[path].modify()

                    try:
                        for path, (x, y) in changes.items():
                            objects[path].set_node_pos(unreal.IntPoint(x, y))

                        current_objects, current_nodes, current_edges, current_comments, _ = _capture_layout_graph(graph)
                        if set(current_objects) != set(objects) or current_edges != edges or current_comments != comments:
                            raise RuntimeError("排版期间图表结构或固定注释发生变化")

                        for path, position in plan["positions"].items():
                            if (current_nodes[path]["x"], current_nodes[path]["y"]) != position:
                                raise RuntimeError("节点位置回读不符 " + path)

                        if hasattr(graph, "notify_graph_changed"):
                            graph.notify_graph_changed()
                    except Exception:
                        for path, (x, y) in original.items():
                            objects[path].set_node_pos(unreal.IntPoint(x, y))

                        if hasattr(graph, "notify_graph_changed"):
                            graph.notify_graph_changed()
                        raise

                report["moved"] = len(changes)
            except Exception as error:
                unreal.log_error("[BBBBlueprintLayout] 写入失败 未保存 仅回退本次节点坐标 请检查图表或撤销 " + str(error))
                raise

        unreal.log(
            "[BBBBlueprintLayout] graph={} dry_run={} planned={} moved={} exec={} data={} overlaps={}".format(
                graph_path,
                dry_run,
                len(changes),
                report["moved"],
                report["execEdges"],
                report["dataEdges"],
                plan["after"]["overlaps"],
            ),
        )
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def write_graph(graph_path: str, code: str, node_aliases_json: str, pin_aliases_json: str) -> str:
        """写入指定项目蓝图图表并编译 不自动保存 失败时保留撤销记录并明确报警"""
        if not graph_path.startswith("/Game/"):
            raise RuntimeError("只能编辑项目蓝图图表")

        graph = unreal.load_object(None, graph_path)
        if not isinstance(graph, unreal.EdGraph):
            raise RuntimeError("目标不是蓝图图表")

        blueprint = graph.get_outer()
        if not isinstance(blueprint, unreal.Blueprint):
            raise RuntimeError("图表必须直接属于蓝图")

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改蓝图图表")

        aliases = _read_aliases(node_aliases_json)
        pin_aliases = _read_aliases(pin_aliases_json)
        reverse_aliases = {value: key for key, value in aliases.items()}

        def create_node(target_graph, type_id, position):
            return BlueprintTools.create_node(target_graph, aliases.get(type_id, type_id), position)

        def node_info(node):
            info = BlueprintTools._get_node_info(node)
            info.type_id = reverse_aliases.get(info.type_id, info.type_id)
            for attribute in ("input_pins", "output_pins"):
                pins = list(getattr(info, attribute))
                for pin in pins:
                    pin.type_id = pin_aliases.get(pin.type_id, pin.type_id)
                setattr(info, attribute, pins)
            return info

        def find_types(filter_text):
            found = BlueprintTools.find_node_types(graph, aliases.get(filter_text, filter_text))
            return [reverse_aliases.get(value, value) for value in found]

        try:
            with unreal.ScopedEditorTransaction("BBB Write Blueprint Graph"):
                blueprint.modify()
                graph.modify()
                with toolset_registry.tool_raising_exceptions():
                    blueprint_dsl.Transpiler(
                        graph,
                        create_node,
                        BlueprintTools.connect_pins,
                        node_info,
                        BlueprintTools.set_pin_value,
                        lambda target_graph: BlueprintTools.find_nodes(target_graph),
                        delete_node_fn=BlueprintTools.delete_node,
                        find_node_types_fn=find_types,
                    ).transpile(code)
                    BlueprintTools.compile_blueprint(blueprint)
        except Exception as error:
            unreal.log_error("蓝图图表写入失败 尚未保存 请检查图表或撤销本次操作 {} {}".format(graph_path, error))
            raise

        return json.dumps({"graph": graph_path, "saved": False, "status": str(blueprint.get_editor_property("status"))}, ensure_ascii=False)


_registration = Registration([BBBBlueprintGraphToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
