import json
import math

import unreal


def _library():
    library = getattr(unreal, "BBBMotionMatchingEditorLibrary", None)
    if library is None or not hasattr(library, "start_motion_matching_runtime_probe"):
        raise RuntimeError("逐帧姿态原生采集接口尚未编译")
    return library


def inspect():
    """/** @return 骨骼完成回调驱动的采集状态与覆盖 */"""
    return _library().inspect_motion_matching_runtime_probe()


def stop():
    """/** @return 释放原生回调并关闭采集后的最终状态 */"""
    return _library().stop_motion_matching_runtime_probe()


def _running():
    return json.loads(inspect()).get("state") == "running"


def start(duration_seconds, file_prefix, target_actor_path=""):
    """
    /**
     * @param duration_seconds 有限游戏采样秒数
     * @param file_prefix 本任务专属临时目录名称
     * @param target_actor_path 明确的 PIE 角色对象路径 空值使用本地玩家
     * @return 逐帧采集状态与输出路径
     */
    """
    if (not math.isfinite(duration_seconds) or not 1.0 <= duration_seconds <= 120.0
            or not file_prefix or len(file_prefix) > 100
            or not all(value.isalnum() or value in "_-" for value in file_prefix)):
        raise RuntimeError("逐帧探针要求 1 到 120 秒及明确的单级任务目录")
    library = _library()
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0) if world else None
    if target_actor_path:
        pawn = unreal.find_object(None, target_actor_path)
    if pawn is None:
        raise RuntimeError("逐帧姿态采集需要有效 PIE 角色")
    result = library.start_motion_matching_runtime_probe(pawn, duration_seconds, file_prefix)
    parsed = json.loads(result)
    if parsed.get("state") != "running":
        raise RuntimeError(parsed.get("error") or "原生逐帧采集未启动")
    from BBBMcpCapabilities import register_activity
    register_activity("motion_matching:probe", _running, blocking=False, wait=False)
    return result
