import json

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBWeaponHandlingTools import _Graph
from editor_toolset.toolsets.blueprint import BlueprintTools


_VALUES = {
    'WeaponPoseOffsetAngles': 'GetWeaponPoseOffsetAngles',
    'WeaponAimFollowSpeed': 'GetWeaponAimFollowSpeed',
    'WeaponRecoilTime': 'GetWeaponRecoilTime',
    'WeaponBackwardRecoilAlpha': 'GetWeaponBackwardRecoilStrength',
    'WeaponRecoilAnimation': 'GetWeaponRecoilAnimation',
}
_RECOIL_FUNCTIONS = ['ResetRecoilPresentation', 'UpdateRecoilShotState', 'UpdateRecoilOffset',
                     'UpdateRecoilPresentation', 'ReadRecoilAngles']
_RECOIL_VARIABLES = ['RecoilSource', 'RecoilFireSequence', 'RecoilShotCount', 'RecoilNewShots',
                     'RecoilOffsetDegrees', 'RecoilCurveAnchorDegrees', 'RecoilAngles',
                     'RecoilStartNewSegment', 'RecoilScale']


def _category(name):
    """/** @return 按当前函数用途归入最多两级英文分类 */"""
    if name == 'BlueprintThreadSafeUpdateAnimation':
        return ''
    lower = name.lower()
    for terms, category in [
        (('blendweight', 'blend_weight'), 'Animation|Blending'),
        (('framedeltatime',), 'Animation'),
        (('trj_', 'desiredcontrolleryaw', 'trajectory', 'desiredfacing'), 'MotionMatching|Trajectory'),
        (('root', 'orientationwarp', 'steering'), 'SkeletalControls|RootOffset'),
        (('handik', 'hand fk'), 'SkeletalControls|Hands'),
        (('foot', 'feet', 'skelcontrol'), 'SkeletalControls'),
        (('aim', 'head', 'weapon'), 'Aiming'),
        (('motionmatching', 'mm', 'database', 'currentselectedanim'), 'MotionMatching'),
        (('layer', 'pose', 'additive', 'montage', 'grenade'), 'Layers'),
        (('adapter',), 'Animation|Facts'),
    ]:
        if any(term in lower for term in terms):
            return category
    return 'Locomotion'


def _bypass(graph, row):
    """/** @param graph\t调用图 @param row\t待删除调用 @return 保留执行顺序 */"""
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    node = unreal.load_object(None, row['path'])
    previous = list(node.find_execute_pin().list_connected_pins())
    following = list(node.find_then_pin().list_connected_pins())
    node.find_execute_pin().break_pin_links()
    node.find_then_pin().break_pin_links()
    for source in previous:
        for target in following:
            if not source.try_create_connection(target):
                raise RuntimeError('删除更新调用时无法保留执行边界')
    editor.remove_nodes([node])


def configure_native_weapon_presentation(main_path, base_path, layer_paths, dry_run):
    """
    /**
     * 删除蓝图通用持枪计算 直接读取动画 Processor 发布结果 并整理函数分类
     * @param main_path\t主动画蓝图
     * @param base_path\t关联层基类
     * @param layer_paths\t关联子层
     * @param dry_run\t只核对当前消费者与分类
     * @return 迁移和编译保存清单
     */
    """
    assets = [unreal.load_asset(path) for path in [main_path, base_path] + list(layer_paths)]
    if any(not isinstance(asset, unreal.AnimBlueprint) or not asset.get_path_name().startswith('/Game/_Project/') for asset in assets):
        raise RuntimeError('需要明确的自有动画蓝图')
    library = unreal.BBBBlueprintEditorLibrary
    if not hasattr(library, 'configure_blueprint_organization'):
        raise RuntimeError('需编译并重启宿主加载分类接口')
    report = {'dryRun': dry_run, 'assets': []}
    if not dry_run:
        require_asset_write(assets)
    for asset in assets:
        removed = set(['UpdateWeaponHandling'])
        if asset == assets[0]:
            removed.update(_RECOIL_FUNCTIONS)
        graphs = list(unreal.BlueprintEditorLibrary.list_graphs(asset))
        inventory = json.loads(library.configure_blueprint_organization(asset, {}, {}, True))
        summary = {'asset': asset.get_path_name(), 'organization': inventory, 'consumers': []}
        for graph in graphs:
            if graph.get_name() in removed:
                continue
            snapshot = json.loads(library.inspect_blueprint_graph_logical_snapshot(graph))
            g = _Graph(graph)
            for row in snapshot['nodes']:
                if row.get('function', {}).get('name') in removed:
                    summary['consumers'].append({'graph': graph.get_name(), 'bypass': row['function']['name']})
                    if not dry_run:
                        _bypass(graph, row)
                    continue
                path = row.get('propertyAccessPath', [])
                if path and path[-1] in _VALUES:
                    summary['consumers'].append({'graph': graph.get_name(), 'property': path})
                    if not dry_run:
                        node = unreal.load_object(None, row['path'])
                        if not library.set_property_access_path(node, [_VALUES[path[-1]]]):
                            raise RuntimeError('原生结果属性路径绑定失败 ' + str(path))
                variable = row.get('variable', {}).get('name')
                if variable not in _VALUES:
                    continue
                if not row['nodeClass'].endswith('K2Node_VariableGet'):
                    raise RuntimeError('残留的结果写入者 ' + row['path'])
                summary['consumers'].append({'graph': graph.get_name(), 'variable': variable})
                if dry_run:
                    continue
                node = unreal.load_object(None, row['path'])
                call = g.call('/Script/ABBB_Evac.BBBAnimInstance.' + _VALUES[variable])
                value = g.out(call)
                split = None
                for output in node.list_output_pins():
                    targets = list(output.list_connected_pins())
                    if not targets:
                        continue
                    name = str(output.get_pin_name())
                    source = value
                    if name != variable:
                        if variable != 'WeaponPoseOffsetAngles' or name.rsplit('_', 1)[-1] not in ('X', 'Y'):
                            raise RuntimeError('未识别的持枪结果拆分引脚 ' + name)
                        if split is None:
                            split = g.call('BreakVector2D', inputs={'InVec': value})
                        source = g.out(split, name[-1])
                    for target in targets:
                        g.link(source, target)
                g.editor.remove_nodes([node])
        if not dry_run:
            for name in removed:
                if unreal.BlueprintEditorLibrary.find_graph(asset, name) is not None:
                    BlueprintTools.remove_function_graph(asset, name)
            for name in list(_VALUES) + (_RECOIL_VARIABLES if asset == assets[0] else []):
                if name in BlueprintTools.list_variables(asset):
                    BlueprintTools.remove_variable(asset, name)
            categories = {row['name']: _category(row['name']) for row in inventory['functions'] if row['name'] not in removed}
            config_names = {'EnableControlRig', 'OffsetRootBoneEnabled', 'HeavyLandSpeedThreshold',
                            'OffsetRootTranslationRadius', 'PlantSettings_Default', 'PlantSettings_Stops',
                            'InterpolationSettings_Default', 'InterpolationSettings_Stops',
                            'TrajectoryGenerationData_Moving', 'TrajectoryGenerationData_Idle',
                            'DisableHandIK', 'WeaponAimStandAdditive', 'WeaponAimCrouchAdditive',
                            'WeaponAimStandReference', 'WeaponAimCrouchReference'}
            variable_categories = {row['name']: _category(row['name']) for row in inventory['variables']
                                   if row['name'] not in config_names}
            summary['organization'] = json.loads(library.configure_blueprint_organization(asset, categories, variable_categories, False))
            BlueprintTools.compile_blueprint(asset)
            if asset.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError('动画边界迁移编译失败或含警告 ' + asset.get_path_name())
        report['assets'].append(summary)
    if not dry_run:
        for asset in assets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError('保存失败 ' + asset.get_path_name())
        report['saved'] = True
    return report
