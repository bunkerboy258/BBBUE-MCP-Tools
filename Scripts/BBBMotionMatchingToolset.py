import importlib
import json

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {'analyze_runtime_probe': {'phases_json': {'type': 'array',
                                           'items': {'type': 'object',
                                                     'properties': {'name': {'type': 'string', 'minLength': 1},
                                                                    'start_frame': {'type': 'integer', 'minimum': 0},
                                                                    'end_frame': {'type': 'integer', 'minimum': 0},
                                                                    'motion': {'type': 'string',
                                                                               'enum': ['idle',
                                                                                        'steady',
                                                                                        'transition',
                                                                                        'turn',
                                                                                        'airborne',
                                                                                        'action']}},
                                                     'required': ['name', 'start_frame', 'end_frame'],
                                                     'additionalProperties': False}},
                           'limits_json': {'type': 'object', 'additionalProperties': {'type': 'number'}}},
 'migrate_configuration': {'request_json': {'type': 'object',
                                            'properties': {'assets': {'type': 'array',
                                                                      'items': {'type': 'object',
                                                                                'properties': {'source': {'type': 'string'},
                                                                                               'target': {'type': 'string'}},
                                                                                'required': ['source', 'target'],
                                                                                'additionalProperties': False}},
                                                           'objectRemaps': {'type': 'array',
                                                                            'items': {'type': 'object',
                                                                                      'properties': {'source': {'type': 'string'},
                                                                                                     'target': {'type': 'string'}},
                                                                                      'required': ['source', 'target'],
                                                                                      'additionalProperties': False}},
                                                           'blueprint': {'type': 'object',
                                                                         'properties': {'source': {'type': 'string'},
                                                                                        'target': {'type': 'string'},
                                                                                        'functions': {'type': 'array',
                                                                                                      'items': {'type': 'string'}},
                                                                                        'variables': {'type': 'array',
                                                                                                      'items': {'type': 'string'}},
                                                                                        'standardFunctions': {'type': 'array',
                                                                                                              'items': {'type': 'string'}},
                                                                                        'nodeTemplates': {'type': 'array',
                                                                                                          'items': {'type': 'object',
                                                                                                                    'properties': {'source': {'type': 'string'},
                                                                                                                                   'target': {'type': 'string'}},
                                                                                                                    'required': ['source',
                                                                                                                                 'target'],
                                                                                                                    'additionalProperties': False}},
                                                                                        'historyAtOutput': {'type': 'string'},
                                                                                        'graphEdits': {'type': 'array',
                                                                                                       'items': {'type': 'object',
                                                                                                                 'properties': {'graph': {'type': 'string'},
                                                                                                                                'nodes': {'type': 'array',
                                                                                                                                          'items': {'type': 'object',
                                                                                                                                                    'properties': {'id': {'type': 'string'},
                                                                                                                                                                   'class': {'type': 'string'},
                                                                                                                                                                   'member': {'type': 'string'},
                                                                                                                                                                   'function': {'type': 'string'},
                                                                                                                                                                   'properties': {'type': 'object',
                                                                                                                                                                                  'additionalProperties': {'type': 'string'}},
                                                                                                                                                                   'pinValues': {'type': 'object',
                                                                                                                                                                                 'additionalProperties': {'type': 'string'}},
                                                                                                                                                                   'exposePins': {'type': 'array',
                                                                                                                                                                                  'items': {'type': 'string'}}},
                                                                                                                                                    'required': ['id',
                                                                                                                                                                 'class'],
                                                                                                                                                    'additionalProperties': False}},
                                                                                                                                'links': {'type': 'array',
                                                                                                                                          'items': {'type': 'object',
                                                                                                                                                    'properties': {'from': {'type': 'string'},
                                                                                                                                                                   'fromPin': {'type': 'string'},
                                                                                                                                                                   'to': {'type': 'string'},
                                                                                                                                                                   'toPin': {'type': 'string'}},
                                                                                                                                                    'required': ['from',
                                                                                                                                                                 'fromPin',
                                                                                                                                                                 'to',
                                                                                                                                                                 'toPin'],
                                                                                                                                                    'additionalProperties': False}}},
                                                                                                                 'required': ['graph',
                                                                                                                              'links'],
                                                                                                                 'additionalProperties': False}},
                                                                                        'newVariables': {'type': 'array',
                                                                                                         'items': {'type': 'object',
                                                                                                                   'properties': {'name': {'type': 'string'},
                                                                                                                                  'category': {'type': 'string'},
                                                                                                                                  'subcategory': {'type': 'string'},
                                                                                                                                  'typePath': {'type': 'string'},
                                                                                                                                  'array': {'type': 'boolean'},
                                                                                                                                  'default': {'type': 'string'}},
                                                                                                                   'required': ['name',
                                                                                                                                'category'],
                                                                                                                   'additionalProperties': False}}},
                                                                         'required': ['source',
                                                                                      'target',
                                                                                      'functions',
                                                                                      'variables'],
                                                                         'additionalProperties': False},
                                                           'overrides': {'type': 'array',
                                                                         'items': {'type': 'object',
                                                                                   'properties': {'object': {'type': 'string'},
                                                                                                  'property': {'type': 'string'},
                                                                                                  'value': {'type': 'string'}},
                                                                                   'required': ['object',
                                                                                                'property',
                                                                                                'value'],
                                                                                   'additionalProperties': False}},
                                                           'integration': {'type': 'object',
                                                                           'properties': {'baseLayer': {'type': 'string'},
                                                                                          'layer': {'type': 'string'},
                                                                                          'chooser': {'type': 'string'}},
                                                                           'required': ['baseLayer',
                                                                                        'layer',
                                                                                        'chooser'],
                                                                           'additionalProperties': False},
                                                           'existingAssets': {'type': 'array',
                                                                              'items': {'type': 'string'}}},
                                            'required': ['assets', 'objectRemaps'],
                                            'additionalProperties': False}},
 'cleanup_animation_blueprints': {'requests_json': {'type': 'array',
                                                    'items': {'type': 'object',
                                                              'properties': {'asset': {'type': 'string'},
                                                                             'removeGraphs': {'type': 'array',
                                                                                              'items': {'type': 'string'}},
                                                                             'bypassFunctions': {'type': 'array',
                                                                                                 'items': {'type': 'string'}},
                                                                             'removeVariables': {'type': 'array',
                                                                                                 'items': {'type': 'string'}},
                                                                             'removeUnusedAliases': {'type': 'boolean'},
                                                                             'flattenStateMachines': {'type': 'array',
                                                                                                      'items': {'type': 'object',
                                                                                                                'properties': {'nodeGuid': {'type': 'string'},
                                                                                                                               'retainedState': {'type': 'string'}},
                                                                                                                'required': ['nodeGuid',
                                                                                                                             'retainedState'],
                                                                                                                'additionalProperties': False}},
                                                                             'pruneGraphs': {'type': 'array',
                                                                                             'items': {'type': 'string'}},
                                                                             'bypassPoseNodes': {'type': 'array',
                                                                                                 'items': {'type': 'object',
                                                                                                           'properties': {'graph': {'type': 'string'},
                                                                                                                          'guid': {'type': 'string'},
                                                                                                                          'input': {'type': 'string'},
                                                                                                                          'output': {'type': 'string'}},
                                                                                                           'required': ['graph',
                                                                                                                        'guid',
                                                                                                                        'input',
                                                                                                                        'output'],
                                                                                                           'additionalProperties': False}}},
                                                              'required': ['asset'],
                                                              'additionalProperties': False}}},
 'configure_in_place_root_velocities': {'velocities_json': {'type': 'array',
                                                            'items': {'type': 'array',
                                                                      'items': {'type': 'number'},
                                                                      'minItems': 3,
                                                                      'maxItems': 3}}}}


@unreal.uclass()
class BBBMotionMatchingToolset(unreal.ToolsetDefinition):
    """/** 创建并核验标准 Pose Search 数据资产 */"""

    @mcp_tool
    @staticmethod
    def configure_character_montage_graph(main_path: str, dry_run: bool = True) -> str:
        """
        /**
         * 保留普通 MM 并后置全身蒙太奇 清理生命阶段直接采样与帮扶专用搜索
         * @param main_path	明确主动画蓝图
         * @param dry_run	仅检查参数和构图前提
         * @return 计划或正式编译保存结果
         */
        """
        from BBBAssetWritePolicy import require_asset_write
        import BBBMotionMatchingCleanup
        asset = unreal.load_asset(main_path)
        if not isinstance(asset, unreal.AnimBlueprint) or not main_path.startswith('/Game/_Project/'):
            raise RuntimeError("需要明确的自有主动画蓝图")
        if not dry_run:
            require_asset_write([asset])
            dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
            if asset.get_outermost().get_path_name() in dirty:
                raise RuntimeError("目标有未保存编辑 拒绝混入离散动作构图")
        report = json.loads(unreal.BBBAnimationGraphEditorLibrary.configure_character_montage_graph(asset, not dry_run))
        if report.get("error"):
            raise RuntimeError(report["error"])
        if not dry_run:
            importlib.reload(BBBMotionMatchingCleanup)._prune_graph(unreal.BlueprintEditorLibrary.find_graph(asset, 'AnimGraph'))
            unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            if asset.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("主动画图编译存在错误或警告 禁止保存: " + asset.get_path_name())
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError("主动画图保存失败: " + asset.get_path_name())
            report["saved"] = [main_path]
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_configuration(content_directory: str, object_paths: list[str]) -> str:
        """/** @param content_directory 只读参考 Content 目录 空值读取本项目 @param object_paths 明确对象列表 @return 完整配置文本及子对象 */"""
        report = json.loads(unreal.BBBMotionMatchingEditorLibrary.inspect_configuration(content_directory, object_paths))
        if report.get("error"):
            raise RuntimeError(report["error"])
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def migrate_configuration(content_directory: str, target_paths: list[str], request_json: str, dry_run: bool = True) -> str:
        """/** @param content_directory 参考 Content 目录 @param target_paths 完整写入对象范围 @param request_json 明确资产 对象和函数映射 @param dry_run 仅预检 @return 迁移报告 应用后保存与回读 */"""
        from BBBAssetWritePolicy import require_asset_write
        request = json.loads(request_json)
        expected = [row["target"] for row in request.get("assets", [])] + request.get("existingAssets", [])
        if request.get("blueprint"):
            expected.append(request["blueprint"]["target"])
        if request.get("integration"):
            expected.append(request["integration"]["layer"])
        if len(target_paths) != len(set(target_paths)) or set(target_paths) != set(expected):
            raise RuntimeError("写入范围必须与映射目标完全一致")
        if not dry_run:
            existing = [unreal.load_asset(path) for path in target_paths if unreal.EditorAssetLibrary.does_asset_exist(path)]
            destinations = [path for path in target_paths if not unreal.EditorAssetLibrary.does_asset_exist(path)]
            require_asset_write(existing, destinations)
        report = json.loads(unreal.BBBMotionMatchingEditorLibrary.migrate_configuration(content_directory, request_json, not dry_run))
        if report.get("error"):
            raise RuntimeError(report["error"])
        if not dry_run:
            for path in target_paths:
                asset = unreal.load_asset(path)
                if asset is None:
                    raise RuntimeError("迁移目标无法回读: " + path)
                if isinstance(asset, unreal.Blueprint):
                    unreal.BlueprintEditorLibrary.compile_blueprint(asset)
                    if asset.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                        raise RuntimeError("迁移蓝图编译存在错误或警告: " + path)
                if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                    raise RuntimeError("迁移资产保存失败: " + path)
            report["saved"] = list(target_paths)
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def start_runtime_probe(duration_seconds: float = 20.0, file_prefix: str = "MMRuntimeProbe", target_actor_path: str = "") -> str:
        """/** @param duration_seconds 最长游戏采样秒数 @param file_prefix 本任务临时目录 @param target_actor_path 明确的 PIE 角色路径 空值使用本地玩家 @return 原生骨骼完成回调驱动的逐帧姿态采集状态 */"""
        import BBBMotionMatchingRuntimeProbe
        return BBBMotionMatchingRuntimeProbe.start(duration_seconds, file_prefix, target_actor_path)

    @mcp_tool
    @staticmethod
    def inspect_runtime_probe() -> str:
        """/** @return 只读 MM 探针状态 方向误差汇总与最新命中快照 */"""
        import BBBMotionMatchingRuntimeProbe
        return BBBMotionMatchingRuntimeProbe.inspect()

    @mcp_tool
    @staticmethod
    def stop_runtime_probe() -> str:
        """/** @return 停止 MM 采样后的方向误差汇总和最终快照 */"""
        import BBBMotionMatchingRuntimeProbe
        return BBBMotionMatchingRuntimeProbe.stop()

    @mcp_tool
    @staticmethod
    def prepare_reference_runtime(content_directory: str, blueprint_path: str, mesh_path: str, bridge_function: str, turn_in_strafe: bool = False) -> str:
        """/** @param content_directory 只读来源目录 @param blueprint_path 来源动画蓝图 @param mesh_path 来源网格 @param bridge_function 原始事实桥接函数 @return 仅替换桥接函数的临时来源夹具编译结果 */"""
        report = json.loads(unreal.BBBMotionMatchingEditorLibrary.prepare_motion_matching_reference(
            content_directory, blueprint_path, mesh_path, bridge_function, turn_in_strafe))
        if report.get("error"):
            raise RuntimeError(report["error"])
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def start_reference_replay(capture_file: str, world_offset_x: float = 0.0, world_offset_y: float = 600.0, world_offset_z: float = 0.0, file_prefix: str = "MMReferenceReplay") -> str:
        """/** @param capture_file Saved/temp 中基础事实采集 @param world_offset_x 平地 X 偏移 @param world_offset_y 平地 Y 偏移 @param world_offset_z 平地 Z 偏移 @return 固定六十帧来源角色独立运行与逐帧回放状态 */"""
        report = json.loads(unreal.BBBMotionMatchingEditorLibrary.start_motion_matching_reference_replay(
            capture_file, unreal.Vector(world_offset_x, world_offset_y, world_offset_z)))
        if report.get("error"):
            raise RuntimeError(report["error"])
        import BBBMotionMatchingRuntimeProbe
        try:
            report["probe"] = json.loads(BBBMotionMatchingRuntimeProbe.start(
                min(120.0, report["replayDurationSeconds"] + 0.1), file_prefix, report["actorPath"]))
        except Exception:
            unreal.BBBMotionMatchingEditorLibrary.stop_motion_matching_reference_replay()
            raise
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_reference_replay() -> str:
        """/** @return 来源夹具的事实回放覆盖与失败原因 */"""
        return unreal.BBBMotionMatchingEditorLibrary.inspect_motion_matching_reference_replay()

    @mcp_tool
    @staticmethod
    def stop_reference_replay() -> str:
        """/** @return 移除回调并销毁临时来源角色后的状态 */"""
        return unreal.BBBMotionMatchingEditorLibrary.stop_motion_matching_reference_replay()

    @mcp_tool
    @staticmethod
    def analyze_runtime_probe(file_path: str, phases_json: str = "[]", limits_json: str = "{}", baseline_path: str = "", contact_curve_mode: str = "plant_speed", reference_facts_path: str = "", reference_offset_y: float = 600.0) -> str:
        """/** @param file_path Saved/temp 中的完整采集文件 @param phases_json 输入用例帧区间 @param limits_json 修复前固定的阈值 @param baseline_path 可选来源检查结果文件 @param contact_curve_mode plant_speed 或 contact_alpha @return 逐帧异常区间 覆盖和来源对照 */"""
        from pathlib import Path
        import BBBMotionMatchingPoseQuality
        analyze_capture = importlib.reload(BBBMotionMatchingPoseQuality).analyze_capture
        root = (Path(unreal.Paths.project_saved_dir()) / "temp").resolve()
        path = Path(file_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError("采集文件必须位于本项目 Saved/temp")
        baseline = None
        if baseline_path:
            reference = Path(baseline_path).resolve()
            if not reference.is_relative_to(root) or not reference.is_file():
                raise RuntimeError("来源检查结果必须位于本项目 Saved/temp")
            baseline = json.loads(reference.read_text(encoding="utf-8"))
        phases = json.loads(phases_json)
        if len({item["name"] for item in phases}) != len(phases) or any(
                item["end_frame"] < item["start_frame"] for item in phases):
            raise RuntimeError("用例名称必须唯一且帧区间有效")
        if reference_facts_path:
            facts_path = Path(reference_facts_path).resolve()
            if not facts_path.is_relative_to(root) or not facts_path.is_file():
                raise RuntimeError("回放事实必须位于本项目 Saved/temp")
        return json.dumps(analyze_capture(path, phases, json.loads(limits_json), baseline, contact_curve_mode,
            reference_facts_path, (0, reference_offset_y, 0)), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_schema(asset_path: str, skeleton_path: str, bone_names: list[str], trajectory_offsets: list[float], sample_rate: int = 30) -> str:
        """
        /**
         * @param asset_path 新格式路径
         * @param skeleton_path 目标骨架路径
         * @param bone_names 姿态通道采样骨
         * @param trajectory_offsets 轨迹采样秒数
         * @param sample_rate 索引每秒采样数
         * @return 保存后的格式与通道
         */
        """
        import BBBMotionMatchingAssets
        return importlib.reload(BBBMotionMatchingAssets).create_schema(asset_path, skeleton_path, bone_names, trajectory_offsets, sample_rate)

    @mcp_tool
    @staticmethod
    def create_database(asset_path: str, schema_path: str, animation_paths: list[str], replace_existing: bool = False) -> str:
        """
        /**
         * @param asset_path 新数据库路径
         * @param schema_path 已有格式路径
         * @param animation_paths 明确动画序列列表
         * @param replace_existing 明确允许重建已有数据库的全部条目
         * @return 保存后的数据库条目 不代表索引构建完成
         */
        """
        import BBBMotionMatchingAssets
        return importlib.reload(BBBMotionMatchingAssets).create_database(asset_path, schema_path, animation_paths, replace_existing)

    @mcp_tool
    @staticmethod
    def inspect_database(asset_path: str) -> str:
        """
        /**
         * @param asset_path 数据库路径
         * @return 格式和完整条目 资产保存不等于索引就绪
         */
        """
        import BBBMotionMatchingAssets
        return importlib.reload(BBBMotionMatchingAssets).inspect_database(asset_path)

    @mcp_tool
    @staticmethod
    def configure_database_provider(base_path: str, layer_path: str, standing_database_paths: list[str], crouching_database_paths: list[str], rising_database_paths: list[str], falling_database_paths: list[str], landing_database_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * @param base_path 基础动画层
         * @param layer_path 派生动画层
         * @param standing_database_paths 站立候选数据库
         * @param crouching_database_paths 蹲姿候选数据库
         * @param rising_database_paths 上升候选数据库
         * @param falling_database_paths 下落候选数据库
         * @param landing_database_paths 落地候选数据库
         * @param dry_run 仅检查配置
         * @return 线程安全数据库提供接口及配置
         */
        """
        import BBBMotionMatchingProvider
        return json.dumps(importlib.reload(BBBMotionMatchingProvider).configure_database_provider(base_path, layer_path, standing_database_paths, crouching_database_paths, rising_database_paths, falling_database_paths, landing_database_paths, dry_run), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_animation_blueprints(blueprint_paths: list[str]) -> str:
        """/** @param blueprint_paths 明确蓝图列表 @return 函数 变量 属性路径与节点回调引用摘要 */"""
        import BBBMotionMatchingCleanup
        return json.dumps(importlib.reload(BBBMotionMatchingCleanup).inspect_animation_blueprints(blueprint_paths), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def cleanup_animation_blueprints(blueprint_paths: list[str], requests_json: str, dry_run: bool = True) -> str:
        """/** @param blueprint_paths 明确蓝图列表 @param requests_json 精确清理请求 @param dry_run 仅预检 @return 编译保存后的清理报告 */"""
        import BBBMotionMatchingCleanup
        return json.dumps(importlib.reload(BBBMotionMatchingCleanup).cleanup_animation_blueprints(blueprint_paths, requests_json, dry_run), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_main_updates(main_path: str, base_layer_path: str, layer_node_guid: str, dry_run: bool = True) -> str:
        """
        /**
         * @param main_path 主动画蓝图
         * @param base_layer_path 数据库提供基础层
         * @param layer_node_guid 持续保留的关联层节点
         * @param dry_run 仅核验事实与图表
         * @return 轨迹与数据库更新函数
         */
        """
        import BBBMotionMatchingUpdates
        return json.dumps(importlib.reload(BBBMotionMatchingUpdates).configure_main_updates(main_path, base_layer_path, layer_node_guid, dry_run), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def collapse_animation_states(blueprint_path: str, graph_path: str, retained_state_name: str, new_state_name: str, merged_state_names: list[str], dry_run: bool = True) -> str:
        """
        /**
         * @param blueprint_path 明确的动画蓝图
         * @param graph_path 同一状态机图
         * @param retained_state_name 保留的状态
         * @param new_state_name 合并后的状态名称
         * @param merged_state_names 完整合并范围
         * @param dry_run 只读核验转换与别名
         * @return 合并计划或保存结果
         */
        """
        from BBBAssetWritePolicy import require_asset_write
        blueprint = unreal.load_asset(blueprint_path)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("要求动画蓝图")
        if not dry_run:
            require_asset_write([blueprint], [])
        report = json.loads(unreal.BBBMotionMatchingEditorLibrary.collapse_animation_states(blueprint, graph_path, retained_state_name, new_state_name, merged_state_names, not dry_run))
        if report.get("error"):
            raise RuntimeError(report["error"])
        if not dry_run:
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("合并后的蓝图存在编译错误或警告")
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
                raise RuntimeError("合并后的蓝图保存失败")
        return json.dumps(report, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def replace_motion_matching_pose(graph_path: str, source_node_guid: str, source_output_pin: str, destination_node_guid: str, destination_input_pin: str, database_path: str, trajectory_variable: str, remove_node_guids: list[str], on_update_function: str = "", dry_run: bool = True, expected_snapshot: str = "") -> str:
        """
        /**
         * @param graph_path 明确的姿势图
         * @param source_node_guid 原姿势源标识
         * @param source_output_pin 原输出引脚
         * @param destination_node_guid 保留节点标识
         * @param destination_input_pin 保留输入引脚
         * @param database_path 初始数据库
         * @param trajectory_variable 蓝图持有的轨迹变量
         * @param remove_node_guids 明确旧分支完整节点集合
         * @param on_update_function 数据库更新回调
         * @param dry_run 仅检查边界
         * @param expected_snapshot 预检快照标识
         * @return 原生 MM 和姿势历史连接证据
         */
        """
        import BBBMotionMatchingGraph
        return json.dumps(importlib.reload(BBBMotionMatchingGraph).replace_motion_matching_pose(graph_path, source_node_guid, source_output_pin, destination_node_guid, destination_input_pin, database_path, trajectory_variable, remove_node_guids, on_update_function, dry_run, expected_snapshot), ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def configure_in_place_root_velocities(asset_paths: list[str], velocities_json: str, dry_run: bool = True) -> str:
        """/** @param asset_paths 明确自有原地动画 @param velocities_json 对应动画局部索引速度 @param dry_run 只校验 @return 保存与非根轨道摘要核验 */"""
        import BBBAnimationCurveTools
        return json.dumps(importlib.reload(BBBAnimationCurveTools).configure_in_place_root_velocities(
            asset_paths, json.loads(velocities_json), dry_run), ensure_ascii=False)


_registration = Registration([BBBMotionMatchingToolset])
