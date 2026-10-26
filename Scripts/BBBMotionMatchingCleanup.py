import json

import unreal
from BBBAssetWritePolicy import require_asset_write


def _load(path):
    """/** @param path 自有动画蓝图 @return 核验后的资产 */"""
    asset = unreal.load_asset(path)
    if not isinstance(asset, unreal.AnimBlueprint) or not asset.get_path_name().startswith("/Game/_Project/"):
        raise RuntimeError("要求自有动画蓝图")
    return asset


def inspect_animation_blueprints(blueprint_paths):
    """/** @param blueprint_paths 明确蓝图列表 @return 函数 变量 属性路径与节点回调引用摘要 */"""
    reports = []
    for path in blueprint_paths:
        blueprint = _load(path)
        exported = json.loads(unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(blueprint))
        rows = []
        for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
            snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
            rows.append({"name": graph.get_name(), "path": graph.get_path_name(), "nodes": [{key: row[key] for key in ["guid", "nodeClass", "title", "function", "variable", "propertyAccessPath", "boundGraph"] if key in row} for row in snapshot.get("nodes", [])]})
        bindings = []
        for graph in exported.get("graphs", []):
            for node in graph.get("nodes", []):
                if node.get("nodeFunctions") or node.get("propertyBindings"):
                    bindings.append({"graph": graph["path"], "guid": node["guid"], "functions": node.get("nodeFunctions", {}), "properties": node.get("propertyBindings", [])})
        reports.append({"asset": path, "status": str(blueprint.get_editor_property("status")), "variables": [str(name) for name in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint, False)], "graphs": rows, "bindings": bindings})
    return reports


def _prune_graph(graph, apply=True):
    """/** @param graph 明确待清理图 @return 删除不参与执行或输出的孤立计算 */"""
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    rows = {row["guid"]: row for row in snapshot["nodes"]}
    live = set()
    seeds = [row["guid"] for row in rows.values() if '.AnimGraphNode_' in row['nodeClass']
             or row["nodeClass"].rsplit(".", 1)[-1] in {"K2Node_FunctionEntry", "K2Node_FunctionResult", "K2Node_Event", "K2Node_CustomEvent"}]
    pending = list(seeds)
    while pending:
        guid = pending.pop()
        if guid in live:
            continue
        live.add(guid)
        for pin in rows[guid]["pins"]:
            if pin["direction"] == "output" and pin.get("kind") == "exec":
                pending.extend(link["nodeGuid"] for link in pin["links"])
    pending = list(live)
    visited = set()
    while pending:
        guid = pending.pop()
        if guid in visited:
            continue
        visited.add(guid)
        live.add(guid)
        for pin in rows[guid]["pins"]:
            if pin["direction"] == "input" and pin.get("kind") != "exec":
                pending.extend(link["nodeGuid"] for link in pin["links"])
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    by_path = {node.get_path_name(): node for node in editor.list_all_nodes()}
    removed = [by_path[row["path"]] for row in rows.values() if row["guid"] not in live and not row.get("isComment")]
    if apply:
        editor.remove_nodes(removed)
    return [{key: row[key] for key in ['guid', 'path', 'nodeClass']} for row in rows.values()
            if row['guid'] not in live and not row.get('isComment')]


def cleanup_animation_blueprints(blueprint_paths, requests_json, dry_run=True):
    """
    /**
     * @param blueprint_paths 明确允许写入的蓝图列表
     * @param requests_json 按资产指定删除图 函数旁路 姿态节点旁路及删除变量
     * @param dry_run 仅验证明确编辑范围
     * @return 编译保存后的实际清理报告
     */
    """
    requests = json.loads(requests_json)
    if not isinstance(requests, list) or {row["asset"] for row in requests} != set(blueprint_paths):
        raise RuntimeError("清理请求与明确蓝图范围不一致")
    assets = {path: _load(path) for path in blueprint_paths}
    report = {"requests": requests, "dryRun": dry_run}
    report['pruning'] = []
    for request in requests:
        blueprint = assets[request["asset"]]
        names = set(str(graph.get_name()) for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint))
        if set(request.get("removeGraphs", [])) - names:
            raise RuntimeError("删除图不存在: " + request["asset"])
        for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
            if str(graph.get_name()) in request.get('pruneGraphs', []):
                report['pruning'].append({'graph': graph.get_path_name(), 'removed': _prune_graph(graph, False)})
        for item in request.get("flattenStateMachines", []):
            result = json.loads(unreal.BBBMotionMatchingEditorLibrary.flatten_animation_state_machine(
                blueprint, item["nodeGuid"], item["retainedState"], False))
            if result.get("error"):
                raise RuntimeError(result["error"])
    if dry_run:
        return report
    require_asset_write(list(assets.values()))
    for request in requests:
        blueprint = assets[request["asset"]]
        blueprint.modify()
        for item in request.get("flattenStateMachines", []):
            result = json.loads(unreal.BBBMotionMatchingEditorLibrary.flatten_animation_state_machine(
                blueprint, item["nodeGuid"], item["retainedState"], True))
            if result.get("error"):
                raise RuntimeError(result["error"])
        remove_graphs = set(request.get("removeGraphs", []))
        exported = json.loads(unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(blueprint))
        update_bindings = {(graph["path"], node["guid"]): node.get("nodeFunctions", {}).get("onUpdate") for graph in exported.get("graphs", []) for node in graph.get("nodes", [])}
        for graph in list(unreal.BlueprintEditorLibrary.list_graphs(blueprint)):
            if str(graph.get_name()) in remove_graphs:
                continue
            editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
            snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
            objects = {node.get_path_name(): node for node in editor.list_all_nodes()}
            bypass_functions = set(request.get("bypassFunctions", []))
            for row in snapshot.get("nodes", []):
                if update_bindings.get((graph.get_path_name(), row["guid"])) in remove_graphs:
                    if not unreal.BBBMotionMatchingEditorLibrary.set_animation_node_update_function(objects[row["path"]], "None", True):
                        raise RuntimeError("旧动画节点更新绑定清理失败")
                if row.get("function", {}).get("name") in bypass_functions:
                    node = objects[row["path"]]
                    before = list(node.find_execute_pin().list_connected_pins())
                    after = list(node.find_then_pin().list_connected_pins())
                    editor.remove_nodes([node])
                    for source in before:
                        for target in after:
                            if not source.try_create_connection(target):
                                raise RuntimeError("执行链旁路失败")
            for item in request.get("bypassPoseNodes", []):
                if item["graph"] != graph.get_path_name():
                    continue
                row = next(row for row in snapshot["nodes"] if row["guid"] == item["guid"])
                node = objects[row["path"]]
                before = list(node.find_input_pin(item["input"]).list_connected_pins())
                after = list(node.find_output_pin(item["output"]).list_connected_pins())
                if len(before) != 1:
                    raise RuntimeError("姿态旁路需要唯一上游")
                editor.remove_nodes([node])
                for target in after:
                    if not before[0].try_create_connection(target):
                        raise RuntimeError("姿态链旁路失败")
            if request.get("removeUnusedAliases", False):
                aliases = [node for node in editor.list_all_nodes() if isinstance(node, unreal.AnimStateAliasNode) and not any(link for pin in list(node.list_input_pins()) + list(node.list_output_pins()) for link in pin.list_connected_pins())]
                editor.remove_nodes(aliases)
            if str(graph.get_name()) in request.get("pruneGraphs", []):
                _prune_graph(graph)
        remaining_names = {str(graph.get_name()) for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint)}
        names = [name for name in request.get("removeGraphs", []) if name in remaining_names]
        if names and unreal.BBBMotionMatchingEditorLibrary.remove_animation_graphs(blueprint, names) != len(names):
            raise RuntimeError("动画图批量移除失败")
        for name in request.get("removeVariables", []):
            graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, "AnimGraph")
            if graph is None:
                graph = next(iter(unreal.BlueprintEditorLibrary.list_graphs(blueprint)), None)
            if graph is None:
                raise RuntimeError("删除成员变量需要蓝图自身的一个编辑图")
            editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
            editor.remove_member_variable(name)
            if name in {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint, False)}:
                raise RuntimeError("成员变量删除失败: " + name)
    for path in blueprint_paths:
        blueprint = assets[path]
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("清理后蓝图编译存在错误或警告: " + path)
    for blueprint in assets.values():
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("清理后蓝图保存失败")
    report["saved"] = True
    return report
