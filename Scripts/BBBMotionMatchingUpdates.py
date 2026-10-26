import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from editor_toolset.toolsets.blueprint import BlueprintTools


def _link(source, target):
    """/** @param source 输出引脚 @param target 输入引脚 @return 严格连接 */"""
    if not source.is_valid() or not target.is_valid() or not source.try_create_connection(target):
        raise RuntimeError("GASP 更新图连接失败")


def _getter(editor, name):
    """/** @param editor 图编辑器 @param name 事实或派生成员名 @return 值引脚 */"""
    return editor.add_get_member_variable_node(name, "").find_output_pin(name)


def _call(editor, path, values):
    """/** @param editor 图编辑器 @param path 函数路径 @param values 明确引脚值 @return 调用节点 */"""
    node = editor.add_call_function_node(path)
    if node is None:
        raise RuntimeError("函数不可用: " + path)
    for name, value in values.items():
        pin = node.find_input_pin(name)
        if isinstance(value, unreal.BlueprintGraphPin):
            _link(value, pin)
        if not isinstance(value, unreal.BlueprintGraphPin) and not pin.set_pin_value(str(value)):
            raise RuntimeError("函数常量写入失败: " + path + "." + name)
    return node


def _snapshot(graph):
    """/** @param graph 明确图 @return 逻辑快照 图编辑器及节点对象 */"""
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    rows = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))["nodes"]
    objects = {node.get_path_name(): node for node in editor.list_all_nodes()}
    return rows, editor, objects


def configure_main_updates(main_path, base_layer_path, layer_node_guid, dry_run=True):
    """
    /**
     * @param main_path 已迁移标准 GASP 核心函数的主动画蓝图
     * @param base_layer_path 提供搜索库的关联层基类
     * @param layer_node_guid 持续求值的关联动画层节点
     * @param dry_run 只核验当前职责边界
     * @return 原生发布事实与不可变层配置 派生数据转入线程安全更新的保存核验
     */
    """
    main = unreal.load_asset(main_path)
    base = unreal.load_asset(base_layer_path)
    if not all(isinstance(asset, unreal.AnimBlueprint) and asset.get_path_name().startswith('/Game/_Project/') for asset in [main, base]):
        raise RuntimeError("需要自有动画蓝图")
    exported = json.loads(unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(main))
    if not any(node['guid'].casefold() == layer_node_guid.casefold() and node['nodeClass'].endswith('AnimGraphNode_LinkedAnimLayer')
               for graph in exported['graphs'] for node in graph['nodes']):
        raise RuntimeError("持续关联层边界无效")
    graphs = {name: unreal.BlueprintEditorLibrary.find_graph(main, name) for name in [
        'UpdateMMDatabaseContext', 'BlueprintThreadSafeUpdateAnimation', 'EventGraph']}
    if any(graph is None for graph in graphs.values()):
        raise RuntimeError("需要完整 GASP 更新与事实适配图")
    defaults = unreal.get_default_object(main.generated_class())
    for name in ['SourceMaxAcceleration', 'SourceFacingWorld', 'SourceControlRotation', 'SourceLocomotionDatabaseChooser']:
        defaults.get_editor_property(name)
    report = {'asset': main_path, 'gameThread': 'native raw facts and immutable layer configuration only',
              'workerThread': ['CharacterProperties', 'Trajectory', 'EssentialValues', 'States', 'Databases'], 'dryRun': dry_run}
    if dry_run:
        return report
    require_asset_write([main])
    main.modify()
    context_rows, context_editor, context_objects = _snapshot(graphs['UpdateMMDatabaseContext'])
    casts = [row for row in context_rows if row['nodeClass'].endswith('K2Node_DynamicCast')]
    providers = [row for row in context_rows if row.get('function', {}).get('name') == 'SelectMMDatabases']
    linked = [row for row in context_rows if row.get('function', {}).get('name') == 'GetLinkedAnimLayerInstanceByGroup']
    if len(casts) != 1 or len(providers) != 1 or len(linked) != 1:
        raise RuntimeError("旧关联查询边界必须唯一")
    old_cast = context_objects[casts[0]['path']]
    before_cast = list(old_cast.find_execute_pin().list_connected_pins())
    after_cast = list(old_cast.find_then_pin().list_connected_pins())
    old_provider = context_objects[providers[0]['path']]
    destinations = list(old_provider.find_output_pin('Databases').list_connected_pins())
    context_editor.remove_nodes([old_cast, old_provider, context_objects[linked[0]['path']]])
    context_object = _call(context_editor, '/Script/ABBB_Evac.BBBAnimInstance.GetBBBMainAnimInstanceThreadSafe', {})
    chooser = _call(context_editor, '/Script/Chooser.ChooserFunctionLibrary.EvaluateChooserMulti', {
        'ContextObject': context_object.find_output_pin('ReturnValue'),
        'ChooserTable': _getter(context_editor, 'SourceLocomotionDatabaseChooser'),
        'ObjectClass': '/Script/PoseSearch.PoseSearchDatabase'})
    for pin in destinations:
        _link(chooser.find_output_pin('ReturnValue'), pin)
    for before in before_cast:
        for after in after_cast:
            _link(before, after)
    properties = [row for row in context_rows if row['nodeClass'].endswith('K2Node_MakeStruct')
                  and any(pin['name'].startswith('CurrentMaxAcceleration_') for pin in row['pins'])]
    if len(properties) != 1:
        raise RuntimeError("来源角色事实结构必须唯一")
    make = context_objects[properties[0]['path']]
    for prefix, fact in [('CurrentMaxAcceleration_', 'SourceMaxAcceleration'),
                         ('OrientationIntent_', 'SourceFacingWorld'), ('AimingRotation_', 'SourceControlRotation')]:
        pin = next(pin for pin in make.list_input_pins() if str(pin.get_pin_name()).startswith(prefix))
        _link(_getter(context_editor, fact), pin)
    context_editor.set_is_thread_safe_function(True)

    event_rows, event_editor, event_objects = _snapshot(graphs['EventGraph'])
    old_calls = [event_objects[row['path']] for row in event_rows if row.get('function', {}).get('name') == 'UpdateMMDatabaseContext']
    if len(old_calls) != 1:
        raise RuntimeError("旧主线程派生入口必须唯一")
    old = old_calls[0]
    previous = list(old.find_execute_pin().list_connected_pins())
    if len(previous) != 1 or list(old.find_then_pin().list_connected_pins()):
        raise RuntimeError("旧主线程更新边界不符")
    event_editor.remove_nodes([old, previous[0].get_owning_node()])

    _, worker, _ = _snapshot(graphs['BlueprintThreadSafeUpdateAnimation'])
    entry = next(node for node in worker.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    destinations = list(entry.find_then_pin().list_connected_pins())
    update = _call(worker, main.generated_class().get_path_name() + '.UpdateMMDatabaseContext',
                   {'DeltaTime': entry.find_output_pin('DeltaTime')})
    _link(entry.find_then_pin(), update.find_execute_pin())
    for destination in destinations:
        _link(update.find_then_pin(), destination)
    from BBBMotionMatchingCleanup import _prune_graph
    _prune_graph(graphs['UpdateMMDatabaseContext'])
    unreal.BlueprintEditorLibrary.compile_blueprint(main)
    if main.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("线程安全 GASP 派生图编译存在错误或警告")
    if not unreal.EditorAssetLibrary.save_loaded_asset(main, False):
        raise RuntimeError("GASP 更新职责迁移保存失败")
    report['saved'] = True
    return report
