import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBWeaponHandlingTools import _function
from editor_toolset.toolsets.blueprint import BlueprintTools


def centralize_weapon_handling(main_path, base_path, layer_paths, dry_run):
    """
    /**
     * 将公共持枪派生表达式放在主动画更新 关联层只复制结果
     * @param main_path\t主动画蓝图
     * @param base_path\t关联层基类
     * @param layer_paths\t需要编译保存的关联子层
     * @param dry_run\t只核对函数与数据边界
     * @return 编译保存清单
     */
    """
    main = unreal.load_asset(main_path)
    base = unreal.load_asset(base_path)
    layers = [unreal.load_asset(path) for path in layer_paths]
    assets = [main, base] + layers
    if any(not isinstance(asset, unreal.AnimBlueprint) or not asset.get_path_name().startswith('/Game/_Project/') for asset in assets):
        raise RuntimeError('需要明确的自有主蓝图和关联层')
    source = unreal.BlueprintEditorLibrary.find_graph(base, 'UpdateWeaponHandling')
    target = unreal.BlueprintEditorLibrary.find_graph(main, 'UpdateWeaponHandling')
    if source is None:
        raise RuntimeError('公共持枪派生入口不存在')
    report = {'main': main_path, 'base': base_path, 'layers': list(layer_paths), 'dryRun': dry_run}
    if dry_run:
        return report
    require_asset_write(assets)
    values = {'WeaponPoseOffsetAngles': 'Vector2D', 'WeaponAimFollowSpeed': 'float',
              'WeaponRecoilTime': 'float', 'WeaponBackwardRecoilAlpha': 'float'}
    defaults = unreal.get_default_object(base.generated_class())
    initial = {name: defaults.get_editor_property(name) for name in list(values) + ['WeaponRecoilAnimation']}
    existing = BlueprintTools.list_variables(main)
    for name, kind in values.items():
        if name not in existing:
            BlueprintTools.add_variable(main, name, kind)
    if 'WeaponRecoilAnimation' not in existing:
        BlueprintTools.add_object_variable(main, 'WeaponRecoilAnimation', unreal.AnimSequence.static_class())
    if target is None:
        target = BlueprintTools.add_function_graph(main, 'UpdateWeaponHandling')
        unreal.BlueprintGraphEditor.get_graph_editor(target).set_is_thread_safe_function(True)
        BlueprintTools.compile_blueprint(main)
        copied = json.loads(unreal.BBBBlueprintEditorLibrary.copy_blueprint_graph_nodes(source, target, [], {}, True))
        if copied.get('error'):
            raise RuntimeError('公共持枪派生迁移失败 ' + copied['error'])
    target_editor = unreal.BlueprintGraphEditor.get_graph_editor(target)
    target_rows = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(target))['nodes']
    for row in target_rows:
        if row.get('function', {}).get('name') == 'GetBBBMainAnimInstanceThreadSafe':
            node = unreal.load_object(None, row['path'])
            for output in node.list_output_pins():
                for consumer in list(output.list_connected_pins()):
                    if str(consumer.get_pin_name()) != 'self':
                        raise RuntimeError('主实例读取存在非目标引脚消费者')
                    consumer.break_pin_links()
            target_editor.remove_nodes([node])
    BlueprintTools.compile_blueprint(main)
    main_defaults = unreal.get_default_object(main.generated_class())
    for name, value in initial.items():
        main_defaults.set_editor_property(name, value)
    top = unreal.BlueprintEditorLibrary.find_graph(main, 'BlueprintThreadSafeUpdateAnimation')
    editor = unreal.BlueprintGraphEditor.get_graph_editor(top)
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(top))
    previous = next(row for row in snapshot['nodes'] if row.get('function', {}).get('name') == 'UpdateRecoilPresentation')
    previous_node = unreal.load_object(None, previous['path'])
    consumers = list(previous_node.find_then_pin().list_connected_pins())
    if not any(row.get('function', {}).get('name') == 'UpdateWeaponHandling' for row in snapshot['nodes']):
        call = editor.add_call_function_node(main.generated_class().get_path_name() + '.UpdateWeaponHandling')
        previous_node.find_then_pin().break_pin_links()
        if not previous_node.find_then_pin().try_create_connection(call.find_execute_pin()):
            raise RuntimeError('公共持枪更新入口连接失败')
        for pin in consumers:
            if not call.find_then_pin().try_create_connection(pin):
                raise RuntimeError('公共持枪更新出口连接失败')
    g = _function(base, 'UpdateWeaponHandling')
    g.editor.set_is_thread_safe_function(True)
    for comment in list(g.editor.list_comment_nodes()):
        g.editor.remove_comment_node(comment)
    entry = next(node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    execute = entry.find_then_pin()
    adapter = g.place(g.editor.add_call_function_node(base.generated_class().get_path_name() + '.GetBBBMainAnimAdapterThreadSafe'))
    source_object = adapter.find_output_pin('ReturnValue')
    if not source_object.is_valid():
        source_object = next(pin for pin in adapter.list_output_pins() if str(pin.get_pin_name()) != 'then')
    valid = g.binary('NotEqual_ObjectObject', source_object, 'None')
    branch = g.place(g.editor.add_branch_node())
    g.link(execute, branch.find_execute_pin())
    g.link(valid, branch.find_input_pin('Condition'))
    execute = branch.find_output_pin('then')
    for name in initial:
        getter = g.place(g.editor.add_get_member_variable_node(name, main.generated_class().get_path_name()))
        g.link(source_object, getter.find_input_pin('self'))
        execute = g.set(name, getter.find_output_pin(name), execute)
    for asset in assets:
        BlueprintTools.compile_blueprint(asset)
        if asset.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError('持枪更新迁移编译有错误或警告 ' + asset.get_path_name())
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError('持枪更新迁移保存失败 ' + asset.get_path_name())
    report['saved'] = True
    return report
