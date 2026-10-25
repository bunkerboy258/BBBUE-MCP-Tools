import json
import math
import os
import time
from collections import Counter

import unreal


_capture = None
_handle = None
_output = None


def inspect():
    """/** @return 动作匹配采样状态 汇总与最新快照 */"""
    if _capture is None:
        return json.dumps({"state": "idle"})
    result = {key: value for key, value in _capture.items() if key not in {"world", "pawn", "last_world_time", "next_sample", "deadline", "animations", "errors"}}
    result["animations"] = _capture["animations"].most_common(8)
    errors = sorted(_capture["errors"])
    result["directionErrorMean"] = sum(errors) / len(errors) if errors else None
    result["directionErrorP95"] = errors[min(len(errors) - 1, int(len(errors) * 0.95))] if errors else None
    return json.dumps(result, ensure_ascii=False)


def stop(state="stopped", error=None):
    """/** @param state 采样终态 @param error 可选失败原因 @return 汇总和最终快照 */"""
    global _handle, _output
    if _handle is not None:
        unreal.unregister_slate_post_tick_callback(_handle)
        _handle = None
    if _output is not None:
        _output.close()
        _output = None
    if _capture is not None:
        _capture["state"] = state
        _capture["error"] = error
    if error:
        unreal.log_error("[BBB][MMProbe] " + error)
    return inspect()


def _tick(delta_seconds):
    try:
        if time.monotonic() >= _capture["deadline"]:
            stop("completed")
            return
        world = _capture["world"]
        pawn = _capture["pawn"]
        try:
            alive = unreal.SystemLibrary.is_valid(world) and unreal.SystemLibrary.is_valid(pawn)
        except (TypeError, RuntimeError):
            stop("world_ended")
            return
        if not alive:
            stop("world_ended")
            return
        world_time = float(unreal.GameplayStatics.get_time_seconds(world))
        if world_time <= _capture["last_world_time"] or world_time < _capture["next_sample"]:
            return
        _capture["last_world_time"] = world_time
        _capture["next_sample"] = world_time + _capture["sampleInterval"]
        sample = json.loads(unreal.BBBMotionMatchingEditorLibrary.probe_motion_matching_runtime(pawn))
        if sample.get("status") != "ok":
            raise RuntimeError("原生采样失败 " + str(sample))
        _output.write(json.dumps(sample, ensure_ascii=False) + "\n")
        _capture["sampleCount"] += 1
        _capture["latest"] = sample
        for match in sample.get("matches", []):
            if match.get("weight", 0.0) <= 0.001:
                continue
            _capture["animations"][match.get("animation", "")] += 1
            value = match.get("directionErrorDegrees")
            if value is not None and math.isfinite(value):
                _capture["errors"].append(value)
    except Exception as error:
        stop("failed", str(error))


def start(duration_seconds, sample_interval, file_prefix):
    """
    /**
     * @param duration_seconds 有限采样时长 单位秒
     * @param sample_interval 游戏时间采样间隔 单位秒
     * @param file_prefix 本任务专属临时目录名称
     * @return 启动后的采样状态和输出路径
     */
    """
    global _capture, _handle, _output
    if _handle is not None:
        raise RuntimeError("动作匹配探针正在运行 请先停止")
    if (not math.isfinite(duration_seconds) or not 1.0 <= duration_seconds <= 120.0
            or not math.isfinite(sample_interval) or not 0.05 <= sample_interval <= 1.0
            or not file_prefix or len(file_prefix) > 80
            or not all(value.isalnum() or value in "_-" for value in file_prefix)):
        raise RuntimeError("动作匹配探针要求 1 到 120 秒 0.05 到 1 秒间隔及明确任务目录")
    library = getattr(unreal, "BBBMotionMatchingEditorLibrary", None)
    if library is None or not hasattr(library, "probe_motion_matching_runtime"):
        raise RuntimeError("动作匹配原生运行时探针尚未编译")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0) if world else None
    if pawn is None:
        raise RuntimeError("动作匹配探针需要 PIE 本地玩家")
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "MMRuntime_" + time.strftime("%Y%m%d_%H%M%S") + ".jsonl")
    _output = open(path, "x", encoding="utf-8", buffering=1)
    _capture = {"state": "recording", "path": path, "sampleCount": 0,
        "sampleInterval": sample_interval, "durationSeconds": duration_seconds,
        "world": world, "pawn": pawn, "last_world_time": -1.0, "next_sample": 0.0,
        "deadline": time.monotonic() + duration_seconds, "animations": Counter(), "errors": [], "latest": None}
    _handle = unreal.register_slate_post_tick_callback(_tick)
    from BBBMcpCapabilities import register_activity
    register_activity("motion_matching:probe", lambda: _handle is not None, blocking=False, wait=False)
    unreal.log("[BBB][MMProbe] 已启动有界只读采样 " + path)
    return inspect()
