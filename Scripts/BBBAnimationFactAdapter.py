import json

import unreal
from BBBAssetWritePolicy import require_write_access
from BBBMotionMatchingCleanup import _prune_graph
from BBBWeaponHandlingTools import _Graph
from editor_toolset.toolsets.blueprint import BlueprintTools


def _copy_expression(source_graph, source_pin, target_graph):
    """
    /**
     * 将纯值表达式移到实际消费者 不复制更新状态
     * @param source_graph\t表达式所在图
     * @param source_pin\t明确纯值输出
     * @param target_graph\t消费者所在图
     * @return 复制后的对应输出
     */
    """
    selected = {}
    pending = [source_pin.get_owning_node()]
    while pending:
        node = pending.pop()
        if node.get_path_name() in selected:
            continue
        selected[node.get_path_name()] = node
        for pin in node.list_input_pins():
            pending.extend(link.get_owning_node() for link in pin.list_connected_pins())
    raw = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(source_graph))
    rows = {row['path']: row for row in raw['nodes']}
    if any(any(pin['kind'] == 'exec' for pin in rows[path]['pins']) for path in selected):
        raise RuntimeError('适配字段依赖执行节点 不能迁移为纯值读取')
    boundaries = []
    for node in selected.values():
        for pin in node.list_output_pins():
            for target in list(pin.list_connected_pins()):
                if target.get_owning_node().get_path_name() not in selected:
                    boundaries.append((pin, target))
    try:
        for pin, target in boundaries:
            pin.break_single_pin_link(target)
        copied = json.loads(unreal.BBBBlueprintEditorLibrary.copy_blueprint_graph_nodes(source_graph,
            target_graph, [rows[path]['guid'] for path in selected], {}, False))
        if copied.get('error'):
            raise RuntimeError('纯值表达式迁移失败 ' + copied['error'])
    finally:
        for pin, target in boundaries:
            if not pin.try_create_connection(target):
                raise RuntimeError('纯值表达式原始连接恢复失败')
    source_guid = rows[source_pin.get_owning_node().get_path_name()]['guid']
    created = next(row for row in copied['created'] if row['sourceGuid'] == source_guid)
    return unreal.load_object(None, created['path']).find_output_pin(str(source_pin.get_pin_name()))


def simplify_fact_adapter(blueprint_path, dry_run):
    """
    /**
     * 消除 GASP 移植适配结构 将已有纯值表达式交给实际生产函数
     * @param blueprint_path\t已展开主管线的角色动画蓝图
     * @param dry_run\t只验证结构消费者
     * @return 真实消费者数量和保存结果
     */
    """
    blueprint = unreal.load_asset(blueprint_path)
    if not isinstance(blueprint, unreal.AnimBlueprint) or not blueprint_path.startswith('/Game/_Project/'):
        raise RuntimeError('需要自有角色动画蓝图')
    graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, 'PrepareLocomotionQuery')
    if graph is None:
        raise RuntimeError('需要已提取的查询准备函数')
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    rows = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))['nodes']
    setter_row = next(row for row in rows if row.get('variable', {}).get('name') == 'CharacterProperties')
    setter = unreal.load_object(None, setter_row['path'])
    make = setter.find_input_pin('CharacterProperties').list_connected_pins()[0].get_owning_node()
    fields = {str(pin.get_pin_name()).split('_')[0]: pin for pin in make.list_input_pins()}
    graphs = list(unreal.BlueprintEditorLibrary.list_graphs(blueprint))
    access = []
    breaks = []
    for current in graphs:
        current_editor = unreal.BlueprintGraphEditor.get_graph_editor(current)
        for node in current_editor.list_all_nodes():
            if node.get_class().get_name() == 'K2Node_PropertyAccess':
                path = list(unreal.BBBBlueprintEditorLibrary.get_property_access_path(node))
                if path and path[0] == 'CharacterProperties':
                    access.append((current, node, path))
            if node.get_class().get_name() == 'K2Node_BreakStruct':
                pins = [pin for pin in node.list_input_pins() if str(pin.get_pin_name()) == 'S_CharacterPropertiesForAnimation']
                if pins:
                    breaks.append((current, node, pins[0]))
    report = {'blueprint': blueprint_path, 'propertyAccessConsumers': len(access),
              'structConsumers': len(breaks), 'dryRun': dry_run}
    if len(access) != 8 or len(breaks) != 2:
        raise RuntimeError('适配消费者已变化 请重新核对 ' + str(report))
    for current, node, path in access:
        field = path[1].split('_')[0]
        if field not in fields:
            raise RuntimeError('未知适配字段 ' + str(path))
        if field == 'InputState' and (len(path) != 3 or not path[2].startswith('WantsToStrafe_')):
            raise RuntimeError('存在额外输入意图消费者')
    if dry_run:
        return report
    require_write_access(blueprint)
    blueprint.modify()
    for name, kind in [('JustLandedThisFrame', 'bool'), ('LandingVelocity', 'Vector')]:
        if name not in BlueprintTools.list_variables(blueprint):
            BlueprintTools.add_variable(blueprint, name, kind)
    for current, node, path in access:
        g = _Graph(current)
        field = path[1].split('_')[0]
        if field == 'InputState':
            input_make = fields[field].list_connected_pins()[0].get_owning_node()
            strafe_pin = next(pin for pin in input_make.list_input_pins() if str(pin.get_pin_name()).startswith('WantsToStrafe_'))
            if strafe_pin.list_connected_pins():
                raise RuntimeError('侧移选择不再是固定配置')
            value = g.out(g.call('/Script/Engine.KismetSystemLibrary.MakeLiteralBool', inputs={'Value': strafe_pin.get_pin_value()}))
        if field != 'InputState':
            sources = list(fields[field].list_connected_pins())
            if len(sources) != 1:
                raise RuntimeError('适配字段必须有唯一表达式 ' + field)
            value = _copy_expression(graph, sources[0], current)
        for output in node.list_output_pins():
            for consumer in list(output.list_connected_pins()):
                g.link(value, consumer)
        g.editor.remove_nodes([node])
    for current, node, input_pin in breaks:
        g = _Graph(current)
        sources = [pin.get_owning_node() for pin in input_pin.list_connected_pins()]
        for output in node.list_output_pins():
            consumers = list(output.list_connected_pins())
            if not consumers:
                continue
            name = str(output.get_pin_name())
            if name.startswith('JustLanded_'):
                value = g.get('JustLandedThisFrame')
            elif name.startswith('LandVelocity_'):
                value = g.get('LandingVelocity')
                if name.endswith(('_X', '_Y', '_Z')):
                    vector = g.call('BreakVector', inputs={'InVec': value})
                    value = g.out(vector, name[-1])
            else:
                raise RuntimeError('未覆盖的结构消费者 ' + name)
            for consumer in consumers:
                g.link(value, consumer)
        g.editor.remove_nodes([node] + sources)
    g = _Graph(graph)
    before = list(setter.find_execute_pin().list_connected_pins())
    after = list(setter.find_then_pin().list_connected_pins())
    if len(before) != 1 or after:
        raise RuntimeError('查询准备执行边界已变化')
    landed = fields['JustLanded'].list_connected_pins()[0]
    velocity = fields['LandVelocity'].list_connected_pins()[0]
    execute = g.set('JustLandedThisFrame', landed, before[0])
    g.set('LandingVelocity', velocity, execute)
    editor.remove_nodes([setter, make])
    _prune_graph(graph)
    BlueprintTools.remove_variable(blueprint, 'CharacterProperties')
    BlueprintTools.compile_blueprint(blueprint)
    if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('适配结构清理后编译失败 未保存')
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError('适配结构清理保存失败')
    report['saved'] = True
    return report
