import json

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


def _get_editor_property_safe(instance, property_name, default=None):
    try:
        return instance.get_editor_property(property_name)
    except Exception:
        return default


def _get_node_path(node):
    try:
        return node.get_path_name()
    except Exception:
        return ""


def _node_sort_key(node):
    node_path = _get_node_path(node)
    try:
        position = node.get_node_pos()
        position_x = position.x
        position_y = position.y
    except Exception:
        position_x = _get_editor_property_safe(node, "node_pos_x", 0)
        position_y = _get_editor_property_safe(node, "node_pos_y", 0)
    try:
        position_x = int(position_x)
    except (TypeError, ValueError):
        position_x = 0
    try:
        position_y = int(position_y)
    except (TypeError, ValueError):
        position_y = 0
    return position_y, position_x, node_path


def _is_layout_node(node):
    class_name = node.get_class().get_name()
    return "Comment" not in class_name


def _is_output_pin(pin):
    try:
        direction = pin.get_pin_direction()
    except Exception:
        direction = _get_editor_property_safe(pin, "direction", "")
    return "output" in str(direction).lower()


def _collect_layout_nodes(graph):
    try:
        graph_nodes = list(BlueprintTools.find_nodes(graph))
    except Exception as error:
        raise RuntimeError("蓝图图表节点读取失败 {}".format(error))
    layout_nodes = []
    excluded_count = 0
    for node in graph_nodes:
        if not _is_layout_node(node):
            excluded_count += 1
            continue
        if not _get_node_path(node):
            continue
        layout_nodes.append(node)
    return graph_nodes, layout_nodes, excluded_count


def _collect_layout_edges(layout_nodes):
    nodes_by_path = {_get_node_path(node): node for node in layout_nodes}
    edges = {node_path: set() for node_path in nodes_by_path}
    edge_count = 0

    for source_node in layout_nodes:
        source_path = _get_node_path(source_node)
        try:
            pins = list(source_node.list_all_pins() or [])
        except Exception:
            try:
                pins = list(source_node.get_all_pins() or [])
            except Exception:
                pins = _get_editor_property_safe(source_node, "pins", []) or []
        for pin in pins:
            if not _is_output_pin(pin):
                continue
            try:
                linked_pins = list(pin.list_connected_pins() or [])
            except Exception:
                linked_pins = _get_editor_property_safe(pin, "linked_to", []) or []
            for linked_pin in linked_pins:
                try:
                    target_node = linked_pin.get_owning_node()
                except Exception:
                    target_node = _get_editor_property_safe(linked_pin, "owning_node")
                target_path = _get_node_path(target_node)
                if target_path not in nodes_by_path or target_path == source_path:
                    continue
                if target_path in edges[source_path]:
                    continue
                edges[source_path].add(target_path)
                edge_count += 1

    return nodes_by_path, edges, edge_count


def _calculate_layout_levels(nodes_by_path, edges):
    indegree = {node_path: 0 for node_path in nodes_by_path}
    for targets in edges.values():
        for target_path in targets:
            indegree[target_path] += 1

    remaining = set(nodes_by_path)
    levels = {node_path: 0 for node_path in nodes_by_path}
    cycle_break_count = 0

    while remaining:
        roots = [node_path for node_path in remaining if indegree[node_path] == 0]
        roots.sort(key=lambda node_path: _node_sort_key(nodes_by_path[node_path]))
        if not roots:
            roots = [min(remaining, key=lambda node_path: _node_sort_key(nodes_by_path[node_path]))]
            cycle_break_count += 1

        pending = list(roots)
        while pending:
            current_path = pending.pop(0)
            if current_path not in remaining:
                continue
            remaining.remove(current_path)

            targets = sorted(edges[current_path], key=lambda node_path: _node_sort_key(nodes_by_path[node_path]))
            for target_path in targets:
                if target_path not in remaining:
                    continue
                levels[target_path] = max(levels[target_path], levels[current_path] + 1)
                indegree[target_path] -= 1
                if indegree[target_path] == 0:
                    pending.append(target_path)

    return levels, cycle_break_count


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
    ) -> str:
        """按蓝图连线拓扑从左到右分层排版节点 不自动保存资产"""
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

        try:
            horizontal_spacing = int(horizontal_spacing)
            vertical_spacing = int(vertical_spacing)
        except (TypeError, ValueError):
            raise RuntimeError("节点间距必须为整数")

        if horizontal_spacing <= 0 or vertical_spacing <= 0:
            raise RuntimeError("节点间距必须大于零")

        if horizontal_spacing > 10000 or vertical_spacing > 10000:
            raise RuntimeError("节点间距不能超过 10000")

        all_nodes, layout_nodes, excluded_count = _collect_layout_nodes(graph)
        nodes_by_path, edges, edge_count = _collect_layout_edges(layout_nodes)
        levels, cycle_break_count = _calculate_layout_levels(nodes_by_path, edges)

        if not layout_nodes:
            unreal.log_warning("蓝图节点排版未找到可排版节点 {}".format(graph_path))
            return json.dumps(
                {
                    "graph": graph_path,
                    "nodes": 0,
                    "edges": edge_count,
                    "moved": 0,
                    "cycleBreaks": cycle_break_count,
                    "excludedComments": excluded_count,
                    "horizontalSpacing": horizontal_spacing,
                    "verticalSpacing": vertical_spacing,
                    "saved": False,
                },
                ensure_ascii=False,
            )

        moved_count = 0
        try:
            from editor_toolset.toolsets.blueprint_layout import GraphFormatter

            original_positions = {
                node_path: (
                    nodes_by_path[node_path].get_node_pos().x,
                    nodes_by_path[node_path].get_node_pos().y,
                )
                for node_path in nodes_by_path
            }

            formatter = GraphFormatter(
                get_out_pins=lambda node: BlueprintTools._list_pins(
                    node,
                    unreal.EdGraphPinDirection.EGPD_OUTPUT,
                ),
                get_connected_pins=lambda pin: pin.list_connected_pins(),
                get_pin_owner=lambda pin: pin.get_owning_node(),
                get_node_pos=lambda node: (
                    node.get_node_pos().x,
                    node.get_node_pos().y,
                ),
                set_node_pos=lambda node, position_x, position_y: node.set_node_pos(
                    unreal.IntPoint(position_x, position_y),
                ),
                get_node_size=lambda node: (
                    int(node.get_node_size().x),
                    int(node.get_node_size().y),
                ),
            )
            formatter.COL_PADDING = horizontal_spacing
            formatter.ROW_PADDING = vertical_spacing

            with unreal.ScopedEditorTransaction("BBB Optimize Blueprint Node Layout"):
                blueprint.modify()
                graph.modify()
                formatter.arrange(all_nodes, set(layout_nodes))

                for node_path, original_position in original_positions.items():
                    node = nodes_by_path[node_path]
                    current_position = node.get_node_pos()
                    if (
                        current_position.x == original_position[0]
                        and current_position.y == original_position[1]
                    ):
                        continue
                    moved_count += 1

                if hasattr(graph, "notify_graph_changed"):
                    graph.notify_graph_changed()
        except Exception as error:
            unreal.log_error(
                "蓝图节点排版失败 尚未保存 请检查图表或撤销本次操作 {} {}".format(
                    graph_path,
                    error,
                ),
            )
            raise

        if cycle_break_count > 0:
            unreal.log_warning(
                "蓝图节点排版检测到 {} 个环路断点 图层仅用于视觉排版 {}".format(
                    cycle_break_count,
                    graph_path,
                ),
            )

        if excluded_count > 0:
            unreal.log_warning(
                "蓝图节点排版跳过 {} 个注释节点 注释框位置保持不变 {}".format(
                    excluded_count,
                    graph_path,
                ),
            )

        unreal.log(
            "[BBBBlueprintLayout] graph={} nodes={} edges={} moved={} cycles={} excluded_comments={}".format(
                graph_path,
                len(layout_nodes),
                edge_count,
                moved_count,
                cycle_break_count,
                excluded_count,
            ),
        )
        return json.dumps(
            {
                "graph": graph_path,
                "nodes": len(layout_nodes),
                "edges": edge_count,
                "moved": moved_count,
                "cycleBreaks": cycle_break_count,
                "excludedComments": excluded_count,
                "horizontalSpacing": horizontal_spacing,
                "verticalSpacing": vertical_spacing,
                "saved": False,
            },
            ensure_ascii=False,
        )

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
