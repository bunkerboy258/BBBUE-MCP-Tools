import json

import unreal
from BBBAssetWritePolicy import require_write_access
from BBBWeaponHandlingTools import _Graph, _function, _weapon_get, _aim_air
from editor_toolset.toolsets.blueprint import BlueprintTools


class _UpdateGraph(_Graph):
    """/** 后坐力工作线程更新图的严格连线助手 */"""

    def entry(self):
        return next(n for n in self.editor.list_all_nodes() if isinstance(n, unreal.K2Node_FunctionEntry)).find_then_pin()

    def branch(self, condition, execute):
        node = self.place(self.editor.add_branch_node())
        self.link(condition, node.find_input_pin('Condition'))
        self.link(execute, node.find_execute_pin())
        return node.find_output_pin('then'), node.find_output_pin('else')

    def invoke(self, blueprint, name, execute):
        node = self.place(self.editor.add_call_function_node(blueprint.generated_class().get_path_name() + '.' + name))
        self.link(execute, node.find_execute_pin())
        return node.find_then_pin()

    def weapon(self, name, inputs=None):
        source = self.out(self.call('/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance'))
        return self.out(self.call('/Script/ABBB_Evac.BBBEquipmentAnimInstance.' + name,
                                 source, inputs))

    def both(self, *values):
        result = values[0]
        for value in values[1:]:
            result = self.binary('BooleanAND', result, value)
        return result

    def negate(self, value):
        return self.out(self.call('Not_PreBool', inputs={'A': value}))


def configure_recoil_update_pipeline(blueprint_path, dry_run):
    """
    /**
     * 由已发布的装备事实创建主实例后坐力更新函数 不改姿势图与后坐力配置
     * @param blueprint_path\t自有角色主动画蓝图
     * @param dry_run\t只检查入口与原生事实接口
     * @return 编译保存结果和更新函数清单
     */
    """
    blueprint = unreal.load_asset(blueprint_path)
    if not isinstance(blueprint, unreal.AnimBlueprint) or not blueprint_path.startswith('/Game/_Project/'):
        raise RuntimeError('需要自有主动画蓝图')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间禁止构图')
    if not hasattr(unreal.BBBEquipmentAnimInstance, 'sample_recoil_curve'):
        raise RuntimeError('请先编译后坐力事实只读接口')
    names = ['ResetRecoilPresentation', 'UpdateRecoilShotState', 'UpdateRecoilOffset',
             'UpdateRecoilPresentation', 'ReadRecoilAngles']
    report = {'blueprint': blueprint_path, 'functions': names, 'dryRun': dry_run}
    if dry_run:
        return report
    require_write_access(blueprint)
    blueprint.modify()
    variables = {'RecoilFireSequence': 'int', 'RecoilShotCount': 'int', 'RecoilNewShots': 'int',
                 'RecoilOffsetDegrees': 'Vector2D', 'RecoilCurveAnchorDegrees': 'Vector2D',
                 'RecoilAngles': 'Vector2D', 'RecoilStartNewSegment': 'bool', 'RecoilScale': 'float'}
    existing = BlueprintTools.list_variables(blueprint)
    for name, kind in variables.items():
        if name not in existing:
            BlueprintTools.add_variable(blueprint, name, kind)
    if 'RecoilSource' not in existing:
        BlueprintTools.add_object_variable(blueprint, 'RecoilSource', unreal.BBBEquipmentAnimInstance.static_class())
    graphs = {}
    for name in names:
        graph = _function(blueprint, name).graph
        graphs[name] = _UpdateGraph(graph)
        graphs[name].editor.set_is_thread_safe_function(True)
    BlueprintTools.compile_blueprint(blueprint)

    g = graphs['ResetRecoilPresentation']
    execute = g.entry()
    for name, value in [('RecoilSource', 'None'), ('RecoilFireSequence', 0), ('RecoilShotCount', 0),
                        ('RecoilNewShots', 0), ('RecoilOffsetDegrees', '(X=0,Y=0)'),
                        ('RecoilCurveAnchorDegrees', '(X=0,Y=0)'), ('RecoilAngles', '(X=0,Y=0)'),
                        ('RecoilStartNewSegment', 'true')]:
        execute = g.set(name, value, execute)

    g = graphs['UpdateRecoilShotState']
    reloading = g.weapon('IsReloading')
    yes, no = g.branch(reloading, g.entry())
    end_reload = g.set('RecoilShotCount', 0, yes)
    condition = g.both(g.binary('Greater_IntInt', g.get('RecoilNewShots'), 0), g.negate(reloading))
    yes, _ = g.branch(condition, no)
    auto = g.weapon('HoldsRecoilBetweenShots')
    start = g.get('RecoilStartNewSegment')
    restart, keep = g.branch(g.both(auto, start), yes)
    restart = g.set('RecoilShotCount', 0, restart)
    anchor = g.place(g.editor.add_branch_node())
    g.link(restart, anchor.find_execute_pin())
    g.link(keep, anchor.find_execute_pin())
    g.link(g.binary('BooleanOR', g.negate(auto), start), anchor.find_input_pin('Condition'))
    sampled = g.weapon('SampleRecoilCurve', {'Position': g.get('RecoilShotCount')})
    anchored = g.set('RecoilCurveAnchorDegrees', g.binary('Subtract_Vector2DVector2D',
        g.get('RecoilOffsetDegrees'), sampled), anchor.find_output_pin('then'))
    add = g.place(g.editor.add_set_member_variable_node('RecoilShotCount'))
    g.link(anchored, add.find_execute_pin())
    g.link(anchor.find_output_pin('else'), add.find_execute_pin())
    g.link(g.binary('Add_IntInt', g.get('RecoilShotCount'), g.get('RecoilNewShots')), add.find_input_pin('RecoilShotCount'))
    g.set('RecoilStartNewSegment', 'false', add.find_then_pin())

    g = graphs['UpdateRecoilOffset']
    auto = g.weapon('HoldsRecoilBetweenShots')
    fire = g.out(g.call('/Script/ABBB_Evac.BBBAnimInstance.HasFireIntent'))
    can_sustain = g.weapon('CanSustainRecoil')
    reload = g.weapon('IsReloading')
    since = g.weapon('GetTimeSinceLastFireSeconds')
    interval = g.weapon('GetRecoilFireInterval')
    follow = g.both(g.binary('Greater_IntInt', g.get('RecoilShotCount'), 0), fire, g.negate(reload),
        g.binary('BooleanOR', can_sustain, g.binary('Greater_IntInt', g.get('RecoilNewShots'), 0)),
        g.binary('BooleanOR', auto, g.binary('Less_DoubleDouble', since, interval)))
    yes, no = g.branch(follow, g.entry())
    fraction = g.out(g.call('FClamp', inputs={'Value': g.binary('Divide_DoubleDouble', since, interval), 'Min': 0, 'Max': 1}))
    progress = g.binary('Add_DoubleDouble', g.binary('Subtract_IntInt', g.get('RecoilShotCount'), 1), fraction)
    g.set('RecoilOffsetDegrees', g.binary('Add_Vector2DVector2D', g.get('RecoilCurveAnchorDegrees'),
        g.weapon('SampleRecoilCurve', {'Position': progress})), yes)
    offset = g.get('RecoilOffsetDegrees')
    length = g.out(g.call('Distance2D', inputs={'V1': offset, 'V2': '(X=0,Y=0)'}))
    step = g.binary('Divide_DoubleDouble', g.binary('Multiply_DoubleDouble', g.weapon('GetRecoilReturnSpeed'),
        g.out(g.call('FMax', inputs={'A': g.get('FrameDeltaTime'), 'B': 0}))),
        g.out(g.call('FMax', inputs={'A': g.get('RecoilScale'), 'B': 1e-8})))
    amount = g.binary('Divide_DoubleDouble', g.out(g.call('FMax', inputs={'A': 0,
        'B': g.binary('Subtract_DoubleDouble', length, step)})),
        g.out(g.call('FMax', inputs={'A': length, 'B': 1e-8})))
    returned = g.set('RecoilOffsetDegrees', g.binary('Multiply_Vector2DFloat', offset, amount), no)
    near = g.out(g.call('IsNearlyZero2D', inputs={'A': g.get('RecoilOffsetDegrees'), 'Tolerance': 1e-4}))
    zero, _ = g.branch(near, returned)
    zero = g.set('RecoilOffsetDegrees', '(X=0,Y=0)', zero)
    g.set('RecoilShotCount', 0, zero)

    g = graphs['UpdateRecoilPresentation']
    source = g.out(g.call('/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance'))
    valid, invalid = g.branch(g.binary('NotEqual_ObjectObject', source, 'None'), g.entry())
    g.invoke(blueprint, 'ResetRecoilPresentation', invalid)
    profile = g.out(g.call('/Script/ABBB_Evac.BBBEquipmentAnimInstance.HasValidRecoilProfile', source))
    valid, invalid = g.branch(profile, valid)
    g.invoke(blueprint, 'ResetRecoilPresentation', invalid)
    changed, unchanged = g.branch(g.binary('NotEqual_ObjectObject', source, g.get('RecoilSource')), valid)
    changed = g.invoke(blueprint, 'ResetRecoilPresentation', changed)
    changed = g.set('RecoilSource', source, changed)
    sequence = g.out(g.call('/Script/ABBB_Evac.BBBEquipmentAnimInstance.GetFireSequence', source))
    changed = g.set('RecoilFireSequence', sequence, changed)
    scale_node = g.place(g.editor.add_set_member_variable_node('RecoilScale'))
    g.link(changed, scale_node.find_execute_pin())
    g.link(unchanged, scale_node.find_execute_pin())
    aiming, falling = _aim_air(g, g.out(g.call('/Script/ABBB_Evac.BBBAnimInstance.GetBBBMainAnimInstanceThreadSafe')))
    scale = g.select(g.weapon('GetAimRecoilScale'), g.weapon('GetHipRecoilScale'), aiming)
    crouch = g.select(g.weapon('GetCrouchedRecoilScale'), 1.0, g.get('bSourceCrouching'))
    air = g.select(g.weapon('GetAirborneRecoilScale'), 1.0, falling)
    g.link(g.binary('Multiply_DoubleDouble', g.binary('Multiply_DoubleDouble', scale, crouch), air), scale_node.find_input_pin('RecoilScale'))
    shots = g.out(g.call('Max', inputs={'A': g.binary('Subtract_IntInt', sequence, g.get('RecoilFireSequence')), 'B': 0}))
    execute = g.set('RecoilNewShots', shots, scale_node.find_then_pin())
    execute = g.invoke(blueprint, 'UpdateRecoilShotState', execute)
    execute = g.invoke(blueprint, 'UpdateRecoilOffset', execute)
    execute = g.set('RecoilFireSequence', sequence, execute)
    holding = g.both(g.out(g.call('/Script/ABBB_Evac.BBBAnimInstance.HasFireIntent')),
        g.weapon('CanSustainRecoil'), g.negate(g.weapon('IsReloading')))
    reset_segment = g.both(g.weapon('HoldsRecoilBetweenShots'), g.negate(holding))
    next_segment = g.binary('BooleanOR', g.get('RecoilStartNewSegment'), reset_segment)
    execute = g.set('RecoilStartNewSegment', next_segment, execute)
    angle = g.call('BreakVector2D', inputs={'InVec': g.binary('Multiply_Vector2DFloat', g.get('RecoilOffsetDegrees'), g.get('RecoilScale'))})
    limit = g.call('BreakVector2D', inputs={'InVec': g.get('SourceRecoilLimitDegrees')})
    values = {}
    for axis in ('X', 'Y'):
        values[axis] = g.out(g.call('FClamp', inputs={'Value': g.out(angle, axis),
            'Min': g.binary('Multiply_DoubleDouble', g.out(limit, axis), -1), 'Max': g.out(limit, axis)}))
    g.set('RecoilAngles', g.out(g.call('MakeVector2D', inputs=values)), execute)

    g = graphs['ReadRecoilAngles']
    result = next(n for n in g.editor.list_all_nodes() if isinstance(n, unreal.K2Node_FunctionResult))
    g.link(g.entry(), result.find_execute_pin())
    g.link(g.get('RecoilAngles'), result.find_input_pin('ReturnValue'))
    top = unreal.BlueprintEditorLibrary.find_graph(blueprint, 'BlueprintThreadSafeUpdateAnimation')
    editor = unreal.BlueprintGraphEditor.get_graph_editor(top)
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(top))
    existing_calls = [row for row in snapshot['nodes'] if row.get('function', {}).get('name') == 'UpdateRecoilPresentation']
    if len(existing_calls) > 1:
        raise RuntimeError('主入口包含重复后坐力更新')
    frame = next(row for row in snapshot['nodes'] if row.get('variable', {}).get('name') == 'FrameDeltaTime'
                 and row['nodeClass'].endswith('K2Node_VariableSet'))
    node = unreal.load_object(None, frame['path'])
    if not existing_calls:
        consumers = list(node.find_then_pin().list_connected_pins())
        call = editor.add_call_function_node(blueprint.generated_class().get_path_name() + '.UpdateRecoilPresentation')
        node.find_then_pin().break_pin_links()
        if not node.find_then_pin().try_create_connection(call.find_execute_pin()):
            raise RuntimeError('后坐力主入口连接失败')
        for pin in consumers:
            if not call.find_then_pin().try_create_connection(pin):
                raise RuntimeError('后坐力更新出口连接失败')
    BlueprintTools.compile_blueprint(blueprint)
    if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('后坐力线程安全更新编译存在错误或警告 未保存')
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError('后坐力更新保存失败')
    report['saved'] = True
    return report
