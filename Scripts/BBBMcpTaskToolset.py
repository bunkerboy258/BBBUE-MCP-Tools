import json
import builtins
import os
import sys
import uuid

import unreal

from BBBMcpCapabilities import mcp_tool, active_activities
from toolset_registry.registration import Registration


if not hasattr(builtins, "BBB_MCP_HOST_ACTIVITY_STATE"):
    builtins.BBB_MCP_HOST_ACTIVITY_STATE = {
        "host_instance": uuid.uuid4().hex, "pie_generation": 0, "world_identity": (),
    }
_host_state = builtins.BBB_MCP_HOST_ACTIVITY_STATE


def _observe_worlds(delta_seconds=0.0):
    """
    /**
     * 跟踪 PIE 世界实际身份 不把开始请求当作已启动
     * @param delta_seconds	编辑器帧间隔
     * @return 当前 PIE 世界
     */
    """
    worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    identity = tuple(sorted((world.get_path_name(), hash(world)) for world in worlds))
    if identity != _host_state["world_identity"]:
        _host_state["pie_generation"] += 1
        _host_state["world_identity"] = identity
    return worlds


@unreal.uclass()
class BBBMcpTaskToolset(unreal.ToolsetDefinition):
    """/** 提供共享宿主的只读活动证据 */"""

    @mcp_tool
    @staticmethod
    def inspect_saved_test_inputs(asset_paths: list[str]) -> str:
        """
        /**
         * 查询测试输入的包依赖闭包
         * @param asset_paths\t地图和显式输入资产
         * @return 已保存输入包集合
         */
        """
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        if registry.is_loading_assets():
            raise RuntimeError("TEST_ASSET_REGISTRY_LOADING")
        options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True,
            include_hard_package_references=True, include_searchable_names=True,
            include_soft_management_references=True, include_hard_management_references=True)
        pending = list(asset_paths)
        visited = set()
        while pending:
            package = str(pending.pop()).split(".", 1)[0].split(":", 1)[0]
            if package in visited or package.startswith("/Script/"):
                continue
            if not package.startswith("/") or any(part in {".", ".."} for part in package.split("/")):
                raise ValueError("TEST_INPUT_PACKAGE_INVALID")
            visited.add(package)
            dependencies = registry.get_dependencies(package, options)
            if dependencies is None:
                raise RuntimeError("TEST_INPUT_DEPENDENCIES_REQUIRED")
            pending.extend(dependencies)
        files = []
        for package in sorted(visited):
            mount = "/" + package.split("/", 2)[1] + "/"
            files.append({"base": unreal.Paths.convert_relative_path_to_full(unreal.PackageTools.package_name_to_filename(package)),
                "content": unreal.Paths.convert_relative_path_to_full(unreal.PackageTools.package_name_to_filename(mount))})
        return json.dumps({"files": files})

    @mcp_tool
    @staticmethod
    def configure_test_host(map_path: str, server_port: int, players: int, net_mode: str) -> str:
        """
        /**
         * 初始化受限测试宿主的内存世界与网络设置
         * @param map_path\t已保存地图
         * @param server_port\t批次独立端口
         * @param players\t本测试玩家数量
         * @param net_mode\t单机 监听或客机模式
         * @return 实际配置证据
         */
        """
        if os.environ.get("BBB_MCP_HOST_ROLE") != "test":
            raise RuntimeError("TEST_HOST_REQUIRED")
        root = os.path.realpath(os.environ["BBB_MCP_TEST_OUTPUT"])
        saved = os.path.realpath(unreal.Paths.project_saved_dir())
        if saved != os.path.join(root, "Saved"):
            raise RuntimeError("TEST_OUTPUT_IDENTITY")
        modes = {"standalone": "PIE_Standalone", "listen": "PIE_ListenServer", "client": "PIE_Client"}
        if net_mode not in modes or not 1 <= players <= 8 or not 1024 <= server_port <= 65535:
            raise ValueError("TEST_CONFIGURATION_RANGE")
        expected = "RunUnderOneProcess=True,ServerPort=" + str(server_port) + ",PlayNumberOfClients=" + str(players) + ",PlayNetMode=" + modes[net_mode] + ",bLaunchSeparateServer=False"
        if expected not in unreal.SystemLibrary.get_command_line():
            raise RuntimeError("TEST_CONFIGURATION_IDENTITY")
        # 显式应用多玩家设置 不依赖命令行中的多字段覆盖是否被引擎逐项解析
        settings_class = unreal.load_class(None, "/Script/UnrealEd.LevelEditorPlaySettings")
        settings = unreal.get_default_object(settings_class)
        properties = {"PlayNetMode": modes[net_mode], "PlayNumberOfClients": players,
                      "RunUnderOneProcess": True, "ServerPort": server_port, "bLaunchSeparateServer": False}
        if not unreal.ToolsetLibrary.set_object_properties(settings, json.dumps(properties)):
            raise RuntimeError("TEST_PLAY_SETTINGS_FAILED")
        world = unreal.EditorLoadingAndSavingUtils.load_map(map_path)
        if world is None:
            raise RuntimeError("TEST_MAP_LOAD_FAILED")
        return json.dumps({"map": world.get_outermost().get_path_name(), "server_port": server_port, "players": players, "net_mode": net_mode})

    @mcp_tool
    @staticmethod
    def check_asset_write(object_paths: list[str]) -> str:
        """
        /**
         * 官方写入工具的实际包与源控预检
         * @param object_paths	明确对象路径 空集合核对当前世界与选中演员
         * @return 预检通过证据
         */
        """
        from BBBAssetWritePolicy import require_asset_write
        from MCP.mcp_result import McpExecutionError
        try:
            paths = set(object_paths)
            if not paths:
                world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
                paths.add(world.get_outermost().get_path_name())
                for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_selected_level_actors():
                    paths.add(actor.get_outermost().get_path_name())
            existing = []
            destinations = []
            for path in sorted(paths):
                asset = unreal.load_object(None, path)
                if asset is not None:
                    existing.append(asset)
                if asset is None:
                    destinations.append(path)
            require_asset_write(existing, destinations)
        except Exception as error:
            raise McpExecutionError("rejected", "ASSET_WRITE_PRECHECK", str(error)) from error
        return json.dumps({"checked": sorted(paths)})

    @mcp_tool
    @staticmethod
    def inspect_editor_activity() -> str:
        """
        /**
         * 回读宿主 世界和后台活动 供网关验证任务生命周期
         * @return 实际活动 JSON
         */
        """
        worlds = _observe_worlds()
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        return json.dumps({
            "process_id": os.getpid(),
            "host_role": os.environ.get("BBB_MCP_HOST_ROLE", "editor"),
            "saved_directory": os.path.realpath(unreal.Paths.project_saved_dir()),
            "project_root": os.path.realpath(unreal.Paths.project_dir()),
            "host_instance": _host_state["host_instance"],
            "pie_active": bool(subsystem.is_in_play_in_editor()),
            "pie_generation": _host_state["pie_generation"],
            "worlds": [world.get_path_name() for world in worlds],
            "paused_worlds": [world.get_path_name() for world in worlds if unreal.GameplayStatics.is_game_paused(world)],
            "activities": active_activities(),
            "dirty_packages": sorted({package.get_path_name() for package in (
                list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
                + list(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
            )}),
        }, ensure_ascii=False)


_registration = Registration([BBBMcpTaskToolset])
_observer_handle = unreal.register_slate_post_tick_callback(_observe_worlds)
