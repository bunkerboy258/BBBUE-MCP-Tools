import unreal
from BBBAssetWritePolicy import require_asset_write
from editor_toolset.toolsets.blueprint import BlueprintTools, ContainerType


def _connect(output, input_pin):
    """/** @param output 输出引脚 @param input_pin 输入引脚 @return 严格建立连接 */"""
    if not output.is_valid() or not input_pin.is_valid() or not output.try_create_connection(input_pin):
        raise RuntimeError("数据库提供函数连接失败")


def configure_database_provider(base_path, layer_path, standing_database_paths, crouching_database_paths,
                                rising_database_paths, falling_database_paths, landing_database_paths, dry_run=True):
    """
    /**
     * @param base_path 基础动画层
     * @param layer_path 需要配置的派生动画层
     * @param standing_database_paths 站立候选数据库
     * @param crouching_database_paths 蹲姿候选数据库
     * @param rising_database_paths 上升候选数据库
     * @param falling_database_paths 下落候选数据库
     * @param landing_database_paths 落地候选数据库
     * @param dry_run 仅检查配置
     * @return 线程安全数据提供函数及实际配置
     */
    """
    base = unreal.load_asset(base_path)
    layer = unreal.load_asset(layer_path)
    if not all(isinstance(value, unreal.AnimBlueprint) and value.get_path_name().startswith("/Game/_Project/") for value in [base, layer]):
        raise RuntimeError("要求自有基础和派生动画蓝图")
    if layer.get_blueprint_parent_class() != base.generated_class():
        raise RuntimeError("目标层必须直接继承指定基础层")
    groups = [standing_database_paths, crouching_database_paths, rising_database_paths, falling_database_paths, landing_database_paths]
    variable_names = ["MMStandingDatabases", "MMCrouchingDatabases", "MMRisingDatabases", "MMFallingDatabases", "MMLandingDatabases"]
    databases = []
    for paths in groups:
        if not paths or len(paths) != len(set(paths)):
            raise RuntimeError("候选数据库不能为空或重复")
        values = [unreal.load_asset(path) for path in paths]
        if any(not isinstance(value, unreal.PoseSearchDatabase) for value in values):
            raise RuntimeError("候选资产必须是 Pose Search Database")
        for database in values:
            schema = database.get_editor_property("schema")
            skeletons = schema.get_editor_property("skeletons")
            if len(skeletons) != 1 or skeletons[0].get_editor_property("skeleton") != base.get_editor_property("target_skeleton"):
                raise RuntimeError("数据库与动画层骨架不一致")
        databases.append(values)
    report = {"base": base_path, "layer": layer_path, "groups": {name: list(paths) for name, paths in zip(variable_names, groups)}, "dryRun": dry_run}
    if dry_run:
        return report
    require_asset_write([base, layer], [])
    with unreal.ScopedEditorTransaction("配置普通运动数据库提供接口"):
        existing = set(str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(base, False))
        for name in variable_names:
            if name not in existing:
                BlueprintTools.add_object_variable(base, name, unreal.PoseSearchDatabase.static_class(), container_type=ContainerType.ARRAY)
                BlueprintTools.set_variable_category(base, name, "动作匹配")
        graph = unreal.BlueprintEditorLibrary.find_graph(base, "SelectMMDatabases")
        if graph is None:
            graph = BlueprintTools.add_function_graph(base, "SelectMMDatabases")
            for name in ["Crouching", "Airborne", "Rising", "Landing"]:
                BlueprintTools.add_function_param(graph, name, "bool", True)
            BlueprintTools.add_object_function_param(graph, "Databases", unreal.PoseSearchDatabase.static_class(), False, ContainerType.ARRAY)
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        body = [node for node in editor.list_all_nodes() if not isinstance(node, (unreal.K2Node_FunctionEntry, unreal.K2Node_FunctionResult))]
        editor.remove_nodes(body)
        entry = next(node for node in editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
        result = next(node for node in editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionResult))
        candidates = [name for name in editor.list_available_nodes([]) if str(name).split("|")[-1] in ("Select", "选择")]
        if len(candidates) != 1:
            raise RuntimeError("无法唯一确定通用选择节点")
        values = {}
        for name in variable_names:
            getter = editor.add_get_member_variable_node(name, "")
            values[name] = getter.find_output_pin(name)

        def select(condition, false_value, true_value):
            """/** @param condition 条件 @param false_value 假值 @param true_value 真值 @return 候选数据库数组 */"""
            node = editor.create_node_from_name(candidates[0], unreal.Vector2D(), [])
            _connect(entry.find_output_pin(condition), node.find_input_pin("Index"))
            options = [pin for pin in node.list_input_pins() if str(pin.get_pin_name()) != "Index"]
            if len(options) != 2:
                raise RuntimeError("布尔选择节点候选数量错误")
            _connect(false_value, options[0])
            _connect(true_value, options[1])
            return node.find_output_pin("ReturnValue")

        ground = select("Crouching", values["MMStandingDatabases"], values["MMCrouchingDatabases"])
        grounded = select("Landing", ground, values["MMLandingDatabases"])
        airborne = select("Rising", values["MMFallingDatabases"], values["MMRisingDatabases"])
        chosen = select("Airborne", grounded, airborne)
        _connect(chosen, result.find_input_pin("Databases"))
        _connect(entry.find_then_pin(), result.find_execute_pin())
        editor.set_is_pure_function(True)
        editor.set_is_thread_safe_function(True)
        for index, node in enumerate(editor.list_all_nodes()):
            node.set_node_pos(unreal.IntPoint((index % 5) * 340, (index // 5) * 220))
        unreal.BlueprintEditorLibrary.compile_blueprint(base)
        unreal.BlueprintEditorLibrary.compile_blueprint(layer)
        if base.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE or layer.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("数据库提供接口编译失败")
        defaults = unreal.get_default_object(layer.generated_class())
        defaults.modify()
        for name, values in zip(variable_names, databases):
            defaults.set_editor_property(name, values)
        for asset in [base, layer]:
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError("数据库提供接口保存失败")
        report["readback"] = {name: [value.get_path_name() for value in defaults.get_editor_property(name)] for name in variable_names}
    return report
