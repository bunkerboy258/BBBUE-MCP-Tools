import json

import unreal
from BBBAssetWritePolicy import require_write_access
from editor_toolset.toolsets.blueprint import BlueprintTools
from MCP.mcp_result import graph_view


def extract_update_function(graph_path, node_guids, function_name, dry_run):
    """
    /**
     * 提取单入口顺序更新片段 只接受无跨边界数据线的明确节点集合
     * @param graph_path\t来源函数图
     * @param node_guids\t片段节点及其纯值依赖
     * @param function_name\t新线程安全函数名
     * @param dry_run\t只核验边界
     * @return 边界清单及编译保存结果
     */
    """
    graph = unreal.load_object(None, graph_path)
    if not isinstance(graph, unreal.EdGraph) or not graph_path.startswith('/Game/_Project/'):
        raise RuntimeError('需要自有蓝图函数图')
    blueprint = graph.get_outer()
    if not isinstance(blueprint, unreal.Blueprint):
        raise RuntimeError('只处理直属函数图')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间禁止提取函数')
    if not function_name.isidentifier() or unreal.BlueprintEditorLibrary.find_graph(blueprint, function_name):
        raise RuntimeError('新函数名无效或已经存在')
    raw = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    snapshot = graph_view(raw, 'logic', [], 0, max(1, len(raw['nodes'])), '')
    rows = {row['guid']: row for row in snapshot['nodes']}
    selected = set(node_guids)
    if not selected or len(selected) != len(node_guids) or not selected.issubset(rows):
        raise RuntimeError('节点集合为空 重复或已失效')
    if any(rows[guid]['nodeClass'].endswith(('K2Node_FunctionEntry', 'K2Node_FunctionResult')) for guid in selected):
        raise RuntimeError('不能提取原函数接口')
    inbound = []
    outbound = []
    for link in snapshot['links']:
        source = link['source']
        target = link['target']['nodeGuid']
        if (source in selected) == (target in selected):
            continue
        pin = next(p for p in rows[source]['pins'] if p['name'] == link['pin'] and p['direction'] == 'output')
        if pin['kind'] != 'exec':
            raise RuntimeError('存在跨边界数据线 请纳入纯值依赖 ' + source + '.' + pin['name'])
        target_pin = next(p for p in rows[target]['pins'] if p['pinId'] == link['target']['pinId'])
        item = (source, pin['name'], target, target_pin['name'])
        if target in selected:
            inbound.append(item)
        if source in selected:
            outbound.append(item)
    if len(inbound) != 1 or len(outbound) > 1:
        raise RuntimeError('只支持单入口和至多一个出口的顺序片段')
    report = {'graph': graph_path, 'function': function_name, 'nodes': len(selected),
              'inbound': inbound, 'outbound': outbound, 'dryRun': dry_run}
    if dry_run:
        return report
    require_write_access(blueprint)
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    objects = {row['guid']: unreal.load_object(None, row['path']) for row in snapshot['nodes']}
    with unreal.ScopedEditorTransaction('提取线程安全更新函数'):
        blueprint.modify()
        graph.modify()
        target_graph = BlueprintTools.add_function_graph(blueprint, function_name)
        target_editor = unreal.BlueprintGraphEditor.get_graph_editor(target_graph)
        target_editor.set_is_thread_safe_function(True)
        entry = next(node for node in target_editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
        for source, pin, target, target_pin in inbound + outbound:
            objects[target].find_input_pin(target_pin).break_pin_links()
        copied = json.loads(unreal.BBBBlueprintEditorLibrary.copy_blueprint_graph_nodes(
            graph, target_graph, node_guids, {}, False))
        if copied.get('error'):
            raise RuntimeError('节点复制失败 ' + copied['error'])
        mapping = {row['sourceGuid']: unreal.load_object(None, row['path']) for row in copied['created']}
        first = inbound[0]
        if not entry.find_then_pin().try_create_connection(mapping[first[2]].find_input_pin(first[3])):
            raise RuntimeError('新函数入口连接失败')
        BlueprintTools.compile_blueprint(blueprint)
        call = editor.add_call_function_node(blueprint.generated_class().get_path_name() + '.' + function_name)
        if call is None:
            raise RuntimeError('提取函数调用创建失败')
        call.set_node_pos(unreal.IntPoint(0, 0))
        if not objects[first[0]].find_output_pin(first[1]).try_create_connection(call.find_execute_pin()):
            raise RuntimeError('原图入口连接失败')
        for source, pin, target, target_pin in outbound:
            if not call.find_then_pin().try_create_connection(objects[target].find_input_pin(target_pin)):
                raise RuntimeError('原图出口连接失败')
        editor.remove_nodes([objects[guid] for guid in node_guids])
        BlueprintTools.compile_blueprint(blueprint)
        if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError('提取后编译有错误或警告 未保存 可撤销本次事务')
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError('提取后保存失败')
    report['saved'] = True
    return report
