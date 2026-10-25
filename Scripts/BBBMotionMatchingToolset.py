import importlib
import json

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
    "migrate_configuration": {
        "request_json": {
            "type": "object",
            "properties": {
                "assets": {"type": "array", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}}, "required": ["source", "target"], "additionalProperties": False}},
                "objectRemaps": {"type": "array", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}}, "required": ["source", "target"], "additionalProperties": False}},
                "blueprint": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "functions": {"type": "array", "items": {"type": "string"}}, "variables": {"type": "array", "items": {"type": "string"}}, "nodeTemplates": {"type": "array", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}}, "required": ["source", "target"], "additionalProperties": False}}, "historyAtOutput": {"type": "string"}}, "required": ["source", "target", "functions", "variables"], "additionalProperties": False},
                "overrides": {"type": "array", "items": {"type": "object", "properties": {"object": {"type": "string"}, "property": {"type": "string"}, "value": {"type": "string"}}, "required": ["object", "property", "value"], "additionalProperties": False}},
                "integration": {"type": "object", "properties": {"baseLayer": {"type": "string"}, "layer": {"type": "string"}, "chooser": {"type": "string"}}, "required": ["baseLayer", "layer", "chooser"], "additionalProperties": False},
            },
            "required": ["assets", "objectRemaps"],
            "additionalProperties": False,
        },
    },
    "cleanup_animation_blueprints": {
        "requests_json": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "asset": {"type": "string"},
                    "removeGraphs": {"type": "array", "items": {"type": "string"}},
                    "bypassFunctions": {"type": "array", "items": {"type": "string"}},
                    "removeVariables": {"type": "array", "items": {"type": "string"}},
                    "removeUnusedAliases": {"type": "boolean"},
                    "pruneGraphs": {"type": "array", "items": {"type": "string"}},
                    "bypassPoseNodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"graph": {"type": "string"}, "guid": {"type": "string"}, "input": {"type": "string"}, "output": {"type": "string"}},
                            "required": ["graph", "guid", "input", "output"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["asset"],
                "additionalProperties": False,
            },
        },
    },
}


@unreal.uclass()
class BBBMotionMatchingToolset(unreal.ToolsetDefinition):
    """/** 创建并核验标准 Pose Search 数据资产 */"""

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
        expected = [row["target"] for row in request.get("assets", [])]
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
    def start_runtime_probe(duration_seconds: float = 20.0, sample_interval: float = 0.1, file_prefix: str = "MMRuntimeProbe") -> str:
        """/** @param duration_seconds 最长采样秒数 @param sample_interval 游戏时间采样间隔 @param file_prefix 本任务临时目录 @return 只读 MM 方向探针状态 */"""
        import BBBMotionMatchingRuntimeProbe
        return BBBMotionMatchingRuntimeProbe.start(duration_seconds, sample_interval, file_prefix)

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


_registration = Registration([BBBMotionMatchingToolset])
