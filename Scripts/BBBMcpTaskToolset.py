import json
import builtins
import os
import sys
import uuid

import unreal

from BBBMcpCapabilities import mcp_tool
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


def _activities():
    """
    /**
     * 汇总已加载模块的异步工作 不导入或重置采样模块
     * @return 尚未完成的活动标识
     */
    """
    active = []
    records = (
        ("BBBAnimationPreviewToolset", "_transition_captures"),
        ("BBBAnimationPreviewToolset", "_population_runs"),
        ("BBBHitReactionToolset", "_captures"),
    )
    for module_name, attribute in records:
        module = sys.modules.get(module_name)
        for identifier, record in getattr(module, attribute, {}).items():
            if record.get("status") in {"pending", "running"}:
                active.append(module_name + ":" + attribute + ":" + str(identifier))
    for module_name, attribute in (
        ("BBBAnimationMotionTools", "_capture_handle"),
        ("BBBGenericEditorToolset", "_pie_audio_capture"),
        ("BBBDisplayAssetCaptureTools", "_capture_handle"),
    ):
        if getattr(sys.modules.get(module_name), attribute, None) is not None:
            active.append(module_name + ":" + attribute)
    recoil = getattr(builtins, "BBB_BACKWARD_RECOIL_RUNTIME_PROBE", None)
    if recoil is not None and recoil.get("status") in {"pending", "running"}:
        active.append("BBBRecoilAnimationTools:runtime_probe")
    library = getattr(unreal, "BBBPIEInputEditorLibrary", None)
    if library is not None:
        status = json.loads(library.get_pie_input_sequence_status())
        if status.get("running") or status.get("status") in {"pending", "running"} or status.get("state") == "running":
            active.append("BBBPIEInputEditorLibrary:input_sequence")
        if status.get("releaseError"):
            active.append("BBBPIEInputEditorLibrary:input_release_failed")
    return active


@unreal.uclass()
class BBBMcpTaskToolset(unreal.ToolsetDefinition):
    """/** 提供共享宿主的只读活动证据 */"""

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
            "project_root": os.path.realpath(unreal.Paths.project_dir()),
            "host_instance": _host_state["host_instance"],
            "pie_active": bool(subsystem.is_in_play_in_editor()),
            "pie_generation": _host_state["pie_generation"],
            "worlds": [world.get_path_name() for world in worlds],
            "paused_worlds": [world.get_path_name() for world in worlds if unreal.GameplayStatics.is_game_paused(world)],
            "activities": _activities(),
            "dirty_packages": sorted({package.get_path_name() for package in (
                list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
                + list(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
            )}),
        }, ensure_ascii=False)


_registration = Registration([BBBMcpTaskToolset])
_observer_handle = unreal.register_slate_post_tick_callback(_observe_worlds)
