import json
import os

import unreal
import toolset_registry
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_write_access
from toolset_registry.registration import Registration
from editor_toolset.toolsets.blueprint import BlueprintTools
from editor_toolset.toolsets import blueprint_dsl


def _annotation_documentation(method):
    """
    /**
     * 将源代码文档标记转换为官方工具元数据正文
     * @param method	新增接口函数
     * @return 保留原实现且元数据已规范的函数
     */
    """
    lines = []
    for line in method.__doc__.splitlines():
        text = line.strip()
        if text in ("/**", "*/"):
            continue

        if text.startswith("*"):
            text = text[1:].lstrip()

        lines.append(text)

    method.__doc__ = "\n".join(lines).strip()
    return method


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
    inspect = getattr(unreal.BBBBlueprintEditorLibrary, "measure_blueprint_graph_visual_geometry", None)
    if not callable(inspect):
        raise RuntimeError("缺少 MeasureBlueprintGraphVisualGeometry 请编译原生编辑器模块后重新启动宿主")

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
    visual_pins = {}
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
            "pose": any(pin["kind"] == "pose" for pin in item["pins"]),
            "primaryOffset": min((pin["y"] for pin in item["pins"] if pin["kind"] in ("pose", "exec")), default=0),
        }
        if item["comment"]:
            snapshot["members"] = sorted(item["members"])
            comments.append(snapshot)
            continue

        objects[path] = node
        nodes[path] = snapshot
        pins_by_path[path] = list(node.list_all_pins())
        visual_pins[path] = {(pin["direction"], pin["name"]): pin for pin in item["pins"]}
        if item["estimated"]:
            raise RuntimeError("拒绝使用估算节点尺寸 " + path)

    edges = []
    for source_path in sorted(nodes):
        for source_order, pin in enumerate(pins_by_path[source_path]):
            if pin.get_pin_direction() != unreal.EdGraphPinDirection.EGPD_OUTPUT:
                continue

            connected_pins = pin.list_connected_pins()
            if not connected_pins:
                continue

            source_visual = visual_pins[source_path].get(("output", str(pin.get_pin_name())))
            if source_visual is None:
                raise RuntimeError("连接输出引脚缺少显示锚点")

            for connected in connected_pins:
                target_path = connected.get_owning_node().get_path_name()
                if target_path not in nodes:
                    raise RuntimeError("连线指向未纳入排版的节点 " + target_path)

                target_order = next(
                    index for index, candidate in enumerate(pins_by_path[target_path])
                    if candidate.is_same_native_pin(connected)
                )
                target_visual = visual_pins[target_path].get(("input", str(connected.get_pin_name())))
                if target_visual is None:
                    raise RuntimeError("连接输入引脚缺少显示锚点")

                edges.append({
                    "source": source_path,
                    "target": target_path,
                    "kind": source_visual["kind"],
                    "sourceOrder": source_order,
                    "targetOrder": target_order,
                    "sourcePin": str(pin.get_pin_name()),
                    "targetPin": str(connected.get_pin_name()),
                    "sourceOffset": [source_visual["x"], source_visual["y"]],
                    "targetOffset": [target_visual["x"], target_visual["y"]],
                    "spline": geometry["spline"],
                })

    edges.sort(key=lambda edge: (
        edge["source"],
        edge["sourceOrder"],
        edge["target"],
        edge["targetOrder"],
    ))
    return objects, nodes, edges, comments, estimated



@unreal.uclass()
class BBBBlueprintGraphToolset(unreal.ToolsetDefinition):
    """通过显式语言映射复用官方蓝图图表工具 不改变编辑器语言"""

    @mcp_tool
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

    @mcp_tool
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

    @mcp_tool
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

    @mcp_tool
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
        if plan["after"]["overlaps"]:
            warnings.append("布局仍有节点重叠 写入被拒绝 请检查固定注释框或节点尺寸")

        report = {
            "graph": graph_path,
            "nodes": len(nodes),
            "edges": len(edges),
            "execEdges": sum(edge["kind"] == "exec" for edge in edges),
            "dataEdges": sum(edge["kind"] == "data" for edge in edges),
            "poseEdges": sum(edge["kind"] == "pose" for edge in edges),
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
            "wireNodeHits": plan["wireNodeHits"],
            "measurement": "SlateFullDetail",
        }
        for warning in warnings:
            unreal.log_warning("[BBBBlueprintLayout] " + warning)

        if not dry_run and changes:
            try:
                if plan["after"]["overlaps"]:
                    raise RuntimeError("拒绝应用存在节点重叠的布局")

                if plan["after"]["wireNodeIntersections"]:
                    raise RuntimeError("拒绝应用连线穿过节点的布局")

                require_write_access(blueprint)
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

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def set_blueprint_node_positions(graph_path: str, expected_snapshot: str, positions_json: str) -> str:
        """
        /**
         * 按当前快照精确移动指定节点 支持状态机 不改变逻辑或保存资产
         * @param graph_path	项目图表完整路径
         * @param expected_snapshot	当前只读逻辑快照身份
         * @param positions_json	含 nodeGuid x y 的明确节点数组
         * @return 回读通过的节点坐标 尚未编译保存
         */
        """
        before = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        if before["snapshot"] != expected_snapshot:
            raise RuntimeError("图表快照已变化 请重新读取")
        requests = json.loads(positions_json)
        if not isinstance(requests, list) or not 1 <= len(requests) <= 512:
            raise RuntimeError("需要一至五百一十二个明确节点")
        existing = {node["guid"]: node for node in before["nodes"]}
        seen = set()
        for item in requests:
            if not isinstance(item, dict) or set(item) != {"nodeGuid", "x", "y"}:
                raise RuntimeError("节点移动字段不符")
            key = item["nodeGuid"]
            if not isinstance(key, str) or key not in existing or key in seen:
                raise RuntimeError("节点不存在或重复")
            if any(type(item[name]) is not int or abs(item[name]) > 100000 for name in ["x", "y"]):
                raise RuntimeError("节点坐标必须是范围内的整数")
            seen.add(key)
        graph = unreal.load_object(None, graph_path)
        nodes = [unreal.load_object(None, existing[item["nodeGuid"]]["path"]) for item in requests]
        positions = [unreal.IntPoint(item["x"], item["y"]) for item in requests]
        require_write_access(graph)
        if not unreal.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions(graph, nodes, positions):
            raise RuntimeError("原生节点移动失败 不保存")
        after = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        if before["logicSignature"] != after["logicSignature"]:
            raise RuntimeError("移动后逻辑发生变化 不保存")
        current = {node["guid"]: node for node in after["nodes"]}
        if any((current[item["nodeGuid"]]["x"], current[item["nodeGuid"]]["y"]) != (item["x"], item["y"]) for item in requests):
            raise RuntimeError("移动坐标回读不符 不保存")
        return json.dumps({"graph": graph_path, "moved": requests, "saved": False}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def inspect_blueprint_graph_logic(graph_path: str) -> str:
        """
        /**
         * 只读返回逻辑引用 引脚 连接和注释 不测量 Slate 几何
         * @param graph_path	项目蓝图图表完整路径
         * @return 不含显示几何的逻辑快照
         */
        """
        if not isinstance(graph_path, str) or not graph_path.startswith("/Game/"):
            raise RuntimeError("只允许读取项目蓝图图表")

        graph = unreal.load_object(None, graph_path)
        if not isinstance(graph, unreal.EdGraph):
            raise RuntimeError("目标不是蓝图图表")

        result = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
        if result.get("error"):
            raise RuntimeError("蓝图逻辑读取失败 " + result["error"])

        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def edit_blueprint_graph_comments(graph_path: str, request_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 精确删除说明框或替换节点正文 不移动节点 不编译或保存
         * @param graph_path	项目图表完整路径 支持嵌套状态与过渡图
         * @param request_json	含 expectedSnapshot removeComments nodeComments 的请求
         * @param dry_run	只读检查开关
         * @return 精确目标及事务回读结果
         */
        """
        from BBBBlueprintAnnotations import _text

        if type(dry_run) is not bool:
            raise RuntimeError("dry_run 必须为布尔值")
        before = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        request = json.loads(request_json)
        if not isinstance(request, dict) or set(request) != {"expectedSnapshot", "removeComments", "nodeComments"}:
            raise RuntimeError("请求必须只包含 expectedSnapshot removeComments nodeComments")
        if request["expectedSnapshot"] != before["snapshot"]:
            raise RuntimeError("图表快照已变化 请重新读取")

        nodes = {node["guid"]: node for node in before["nodes"]}
        seen = set()
        for field in ("removeComments", "nodeComments"):
            items = request[field]
            if not isinstance(items, list) or len(items) > 512:
                raise RuntimeError("每类注释编辑必须为不超过 512 项的数组")
            for item in items:
                fields = {"nodeGuid", "expectedText"}
                if field == "nodeComments":
                    fields.add("text")
                if not isinstance(item, dict) or set(item) != fields:
                    raise RuntimeError("注释编辑字段不符")
                key = item["nodeGuid"]
                if not isinstance(key, str) or key not in nodes or key in seen:
                    raise RuntimeError("注释目标不存在或重复")
                seen.add(key)
                node = nodes[key]
                if node["nodeComment"] != item["expectedText"] or node["isComment"] != (field == "removeComments"):
                    raise RuntimeError("注释原文或类型不符")
                if field == "nodeComments":
                    _text(item["text"], "节点正文", False)

        report = {"graph": graph_path, "dryRun": dry_run, "removeCount": len(request["removeComments"]), "replaceCount": len(request["nodeComments"]), "saved": False}
        if dry_run or not seen:
            return json.dumps(report, ensure_ascii=False)

        graph = unreal.load_object(None, graph_path)
        require_write_access(graph)
        result = json.loads(unreal.BBBBlueprintEditorLibrary.edit_blueprint_graph_comments(graph, json.dumps(request, ensure_ascii=False)))
        if result.get("error"):
            raise RuntimeError(result["error"])
        report.update(result)
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def add_blueprint_comment_node(graph_path: str, expected_snapshot: str, text: str, x: int, y: int, width: int, height: int, dry_run: bool = True) -> str:
        """
        /**
         * 在明确空白位置添加独立说明框 保留所有原有节点 连线及注释
         * @param graph_path\t项目蓝图图表完整路径 支持状态机子图
         * @param expected_snapshot\t当前逻辑快照中的 snapshot
         * @param text\t完整简体中文正文 支持换行
         * @param x\t说明框左上角横坐标
         * @param y\t说明框左上角纵坐标
         * @param width\t说明框宽度
         * @param height\t说明框高度
         * @param dry_run\t是否只读预览
         * @return 新增说明框身份及逻辑保持结果 不编译或保存
         */
        """
        from BBBBlueprintAnnotations import _text

        _text(text, "说明框正文")
        if type(dry_run) is not bool or any(type(value) is not int for value in (x, y, width, height)):
            raise RuntimeError("预览标记必须为布尔值 坐标和尺寸必须为整数")
        if not 200 <= width <= 4096 or not 100 <= height <= 4096 or max(abs(x), abs(y)) > 1000000:
            raise RuntimeError("说明框尺寸或坐标超出支持范围")

        before = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        if not expected_snapshot or before["snapshot"] != expected_snapshot:
            raise RuntimeError("图表快照已变化 请重新读取后添加说明框")

        report = {"graph": graph_path, "text": text, "bounds": [x, y, width, height], "dryRun": dry_run, "added": False, "logicUnchanged": True, "saved": False}
        for node in before["nodes"]:
            if node["isComment"] and node["nodeComment"] == text:
                if (node["x"], node["y"], node["width"], node["height"]) != (x, y, width, height):
                    raise RuntimeError("同正文说明框已存在于其它位置 不重复添加")
                report["nodeGuid"] = node["guid"]
                report["skipped"] = True
                return json.dumps(report, ensure_ascii=False)

            node_width = node.get("width", 200)
            node_height = node.get("height", 100)
            if x < node["x"] + node_width and x + width > node["x"] and y < node["y"] + node_height and y + height > node["y"]:
                raise RuntimeError("说明框必须放在空白位置 禁止覆盖原有节点或说明框 " + node["path"])

        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        graph = unreal.load_object(None, graph_path)
        blueprint = graph.get_outer()
        while blueprint is not None and not isinstance(blueprint, unreal.Blueprint):
            blueprint = blueprint.get_outer()
        if blueprint is None:
            raise RuntimeError("图表必须属于项目蓝图")
        require_write_access(blueprint)
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        comment = None
        try:
            with unreal.ScopedEditorTransaction("BBB Add Blueprint Comment"):
                blueprint.modify()
                graph.modify()
                comment = unreal.BBBBlueprintEditorLibrary.add_blueprint_comment_node(graph, expected_snapshot, text, x, y, width, height)
                if comment is None:
                    raise RuntimeError("引擎没有创建说明框")
                after = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
                original_nodes = {node["guid"]: node for node in before["nodes"]}
                remaining_nodes = {node["guid"]: node for node in after["nodes"] if node["guid"] in original_nodes}
                added = [node for node in after["nodes"] if node["guid"] not in original_nodes]
                if remaining_nodes != original_nodes or after["logicSignature"] != before["logicSignature"] or len(added) != 1:
                    raise RuntimeError("新增后原有图表发生变化 不允许保存")
                target = added[0]
                if not target["isComment"] or target["nodeComment"] != text or target["members"] or (target["x"], target["y"], target["width"], target["height"]) != (x, y, width, height):
                    raise RuntimeError("说明框回读与请求不一致 不允许保存")
                report["nodeGuid"] = target["guid"]
                report["snapshot"] = after["snapshot"]
        except Exception as error:
            if comment is not None:
                editor.remove_comment_node(comment)
            unreal.log_error("[BBBBlueprintComment] 添加失败 未保存 {} {}".format(graph_path, error))
            raise

        report["added"] = True
        unreal.log("[BBBBlueprintComment] 已添加独立说明框 graph={} guid={} 原有节点与连线保持原样".format(graph_path, report["nodeGuid"]))
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def remove_blueprint_comment_node(graph_path: str, node_guid: str, expected_text: str, dry_run: bool = True) -> str:
        """
        /**
         * 精确删除指定说明框并核验其它节点与连线 不自动编译或保存
         * @param graph_path	项目蓝图图表完整路径
         * @param node_guid	只读快照中的说明框 GUID
         * @param expected_text	必须与现有说明框完全一致的正文
         * @param dry_run	是否只读预览
         * @return 删除目标及逻辑保持结果
         */
        """
        if type(dry_run) is not bool:
            raise RuntimeError("dry_run 必须为布尔值")

        if not isinstance(node_guid, str) or not node_guid:
            raise RuntimeError("必须提供说明框 GUID")

        if not isinstance(expected_text, str) or not expected_text:
            raise RuntimeError("必须提供说明框现有正文")

        before = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        targets = [node for node in before["nodes"] if node["guid"] == node_guid]
        if len(targets) != 1:
            raise RuntimeError("说明框不存在或 GUID 不唯一 请重新读取图表")

        target = targets[0]
        if target["nodeClass"] != "/Script/UnrealEd.EdGraphNode_Comment":
            raise RuntimeError("只允许删除说明框 禁止删除逻辑节点")

        if target["nodeComment"] != expected_text:
            raise RuntimeError("说明框正文已变化 请重新确认删除目标")

        graph = unreal.load_object(None, graph_path)
        blueprint = graph.get_outer()
        if not isinstance(blueprint, unreal.Blueprint):
            raise RuntimeError("图表必须直接属于蓝图")

        report = {
            "graph": graph_path,
            "nodeGuid": node_guid,
            "text": expected_text,
            "dryRun": dry_run,
            "removed": False,
            "logicUnchanged": True,
            "saved": False,
        }
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        require_write_access(blueprint)
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        comments = [node for node in editor.list_comment_nodes() if node.get_path_name() == target["path"]]
        if len(comments) != 1:
            raise RuntimeError("说明框对象与快照不一致 不执行删除")

        try:
            with unreal.ScopedEditorTransaction("BBB Remove Blueprint Comment"):
                blueprint.modify()
                graph.modify()
                comments[0].modify()
                editor.remove_comment_node(comments[0])

                after = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
                expected_nodes = {node["guid"]: node for node in before["nodes"] if node["guid"] != node_guid}
                actual_nodes = {node["guid"]: node for node in after["nodes"]}
                if actual_nodes != expected_nodes or after["logicSignature"] != before["logicSignature"]:
                    raise RuntimeError("删除后图表回读不符 不允许保存 请撤销本次说明框删除")
        except Exception as error:
            unreal.log_error("[BBBBlueprintComment] 删除失败 尚未保存 {} {}".format(graph_path, error))
            raise

        report["removed"] = True
        report["snapshot"] = after["snapshot"]
        unreal.log("[BBBBlueprintComment] 已删除说明框 graph={} guid={} 其它节点与连线保持原样".format(graph_path, node_guid))
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def inspect_blueprint_graph(graph_path: str) -> str:
        """
        /**
         * 只读返回逻辑引用 原有注释及显示几何 不探测创建节点
         * @param graph_path	项目蓝图图表完整路径
         * @return 语义快照与无法解析的信息
         */
        """
        if not isinstance(graph_path, str) or not graph_path.startswith("/Game/"):
            raise RuntimeError("只允许读取项目蓝图图表")

        graph = unreal.load_object(None, graph_path)
        if not isinstance(graph, unreal.EdGraph):
            raise RuntimeError("目标不是蓝图图表")

        result = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_snapshot(graph))
        if result.get("error"):
            raise RuntimeError("蓝图语义读取失败 " + result["error"])

        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    @_annotation_documentation
    def annotate_blueprint_graph(graph_path: str, annotations_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 预览或添加区块与空节点注释 并联合排版 不自动保存
         * @param graph_path	项目蓝图图表完整路径
         * @param annotations_json	含快照校验值的区块与节点注释方案
         * @param dry_run	是否只读预览
         * @return 注释布局质量与实际写入结果
         */
        """
        from BBBBlueprintAnnotations import prepare_annotations, plan_annotations

        if type(dry_run) is not bool:
            raise RuntimeError("dry_run 必须为布尔值")

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止注释及排版蓝图")

        snapshot = json.loads(BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path))
        if not snapshot["layoutSupported"]:
            raise RuntimeError("图表无法完整测量 不允许注释排版 " + " ".join(snapshot["warnings"]))

        prepared = prepare_annotations(snapshot, annotations_json)
        graph = unreal.load_object(None, graph_path)
        if not prepared["blocks"] and not prepared["nodeComments"]:
            return json.dumps({"graph": graph_path, "dryRun": dry_run, "changed": False, "skipped": prepared["skipped"], "saved": False}, ensure_ascii=False)

        measurement = json.loads(unreal.BBBBlueprintEditorLibrary.measure_blueprint_graph_annotation_geometry(graph, json.dumps(prepared, ensure_ascii=False)))
        if measurement.get("error"):
            raise RuntimeError("注释显示测量失败 " + measurement["error"])

        plan = plan_annotations(snapshot, prepared, measurement)
        plan["graph"] = graph_path
        plan["dryRun"] = dry_run
        plan["changed"] = False
        for warning in plan["warnings"]:
            unreal.log_warning("[BBBBlueprintAnnotations] " + warning)

        if not dry_run:
            if not plan["canApply"]:
                raise RuntimeError("注释布局质量不满足写入要求 请检查预览报告")

            require_write_access(graph.get_outer())
            result = json.loads(unreal.BBBBlueprintEditorLibrary.apply_blueprint_graph_annotations(graph, json.dumps(plan, ensure_ascii=False)))
            if result.get("error"):
                raise RuntimeError("注释写入失败 " + result["error"])

            plan["changed"] = result["changed"]
            plan["createdBlocks"] = result["createdBlocks"]
            plan["snapshot"] = result["snapshot"]

        unreal.log("[BBBBlueprintAnnotations] graph={} dry_run={} blocks={} node_comments={} changed={}".format(graph_path, dry_run, len(prepared["blocks"]), len(prepared["nodeComments"]), plan["changed"]))
        return json.dumps(plan, ensure_ascii=False)

    @mcp_tool
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
