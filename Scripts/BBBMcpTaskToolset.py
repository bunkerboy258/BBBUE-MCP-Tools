import json
import builtins
import os
import sys
import time
import uuid

import unreal

from BBBMcpCapabilities import mcp_tool, active_activities
from toolset_registry.registration import Registration


if not hasattr(builtins, "BBB_MCP_HOST_ACTIVITY_STATE"):
    builtins.BBB_MCP_HOST_ACTIVITY_STATE = {
        "host_instance": uuid.uuid4().hex, "pie_generation": 0, "world_identity": (),
    }
_host_state = builtins.BBB_MCP_HOST_ACTIVITY_STATE


def _shutdown_blocked():
    """/** @return 当前世界 活动及脏包是否要求继续交接 */"""
    return bool(unreal.EditorLevelLibrary.get_pie_worlds(False)
        or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor()
        or active_activities()
        or unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        or unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())


def _shutdown_tick(delta_seconds):
    """/** @param delta_seconds 编辑器帧间隔 @return 延后执行正常退出并保留实际状态 */"""
    state = _host_state["shutdown"]
    if time.monotonic() < state["due"]:
        return
    try:
        if _shutdown_blocked():
            unreal.unregister_slate_post_tick_callback(state.pop("handle"))
            state.update(status="shutdown_blocked", code="HOST_BUSY")
            unreal.log_warning("[BBBMcpShutdown] HOST_BUSY")
            return
        if state["status"] == "shutdown_requested":
            editors = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            state["closed_blueprint_editors"] = sum(editors.close_all_editors_for_asset(asset)
                for asset in list(unreal.ObjectIterator(unreal.Blueprint)) if asset.get_path_name().startswith("/Game/"))
            state.update(status="closing_editors", due=time.monotonic() + 0.2)
            return
        unreal.unregister_slate_post_tick_callback(state.pop("handle"))
        state["status"] = "exiting"
        unreal.log("[BBBMcpShutdown] 正常退出编辑器")
        unreal.SystemLibrary.quit_editor()
    except Exception as error:
        handle = state.pop("handle", None)
        if handle is not None:
            unreal.unregister_slate_post_tick_callback(handle)
        state.update(status="shutdown_failed", code="EDITOR_SHUTDOWN_FAILED", error=str(error))
        unreal.log_error("[BBBMcpShutdown] " + str(error))


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
    def request_editor_shutdown(process_id: int, host_instance: str) -> str:
        """
        /**
         * 核对宿主及交接状态后延后正常退出
         * @param process_id\t目标进程编号
         * @param host_instance\t目标宿主代际
         * @return 已接受退出请求的身份及状态
         */
        """
        if process_id != os.getpid() or host_instance != _host_state["host_instance"]:
            raise RuntimeError("HOST_IDENTITY_CHANGED")
        state = _host_state.get("shutdown", {})
        if state.get("status") in {"shutdown_requested", "closing_editors", "exiting"}:
            return json.dumps({"status": "shutdown_requested", "process_id": process_id, "host_instance": host_instance})
        if _shutdown_blocked():
            raise RuntimeError("HOST_BUSY")
        state = {"status": "shutdown_requested", "due": time.monotonic() + 0.5}
        _host_state["shutdown"] = state
        try:
            state["handle"] = unreal.register_slate_post_tick_callback(_shutdown_tick)
        except Exception:
            state.update(status="shutdown_failed", code="EDITOR_SHUTDOWN_SCHEDULE_FAILED")
            raise
        return json.dumps({"status": "shutdown_requested", "process_id": process_id, "host_instance": host_instance})

    @mcp_tool
    @staticmethod
    def recover_asset_moves(report_json: str) -> str:
        """
        /**
         * 接续网关所属迁移批次的保存和旧源包清理
         * @param report_json	已执行迁移证据
         * @return 实际阶段及路径核验结果
         */
        """
        import BBBAssetMoveRecovery
        import importlib
        return json.dumps(importlib.reload(BBBAssetMoveRecovery).resume(json.loads(report_json)), ensure_ascii=False)

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
                package_path = path.split(".", 1)[0].split(":", 1)[0]
                asset = unreal.find_object(None, path)
                if asset is None and unreal.EditorAssetLibrary.does_asset_exist(package_path):
                    asset = unreal.EditorAssetLibrary.load_asset(package_path)
                    if asset is None:
                        raise RuntimeError("ASSET_WRITE_TARGET_UNREADABLE: " + package_path)
                if asset is not None:
                    existing.append(asset)
                if asset is None:
                    destinations.append(package_path)
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
        editor_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return json.dumps({
            "process_id": os.getpid(),
            "source_version": __import__("BBBMcpBootstrap")._loaded_source_version,
            "unavailable_native": __import__("BBBMcpBootstrap")._unavailable_native,
            "host_role": "editor",
            "saved_directory": os.path.realpath(unreal.Paths.project_saved_dir()),
            "project_root": os.path.realpath(unreal.Paths.project_dir()),
            "host_instance": _host_state["host_instance"],
            "shutdown": {key: value for key, value in _host_state.get("shutdown", {}).items() if key not in {"handle", "due"}},
            "editor_world": editor_world.get_path_name() if editor_world is not None else None,
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
