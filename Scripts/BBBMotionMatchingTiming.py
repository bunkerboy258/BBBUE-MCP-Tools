import json
import os
import re
import time

import unreal


_capture = {}
_handle = None
_previous_channels = []


def _finish(state, error=''):
    """/** @param state 结束状态 @param error 失败原因 @return 释放本次跟踪并恢复通道 */"""
    global _handle
    if _handle is None:
        return
    unreal.unregister_slate_post_tick_callback(_handle)
    _handle = None
    unreal.TraceUtilLibrary.trace_mark_region_end('MMPerformanceCapture')
    unreal.TraceUtilLibrary.stop_tracing()
    for name in unreal.TraceUtilLibrary.get_enabled_channels():
        if name not in _previous_channels:
            unreal.TraceUtilLibrary.toggle_channel(name, False)
    for name in _previous_channels:
        unreal.TraceUtilLibrary.toggle_channel(name, True)
    _capture.update(state=state, error=error)


def capture(action, file_prefix='', duration_seconds=8.0):
    """
    /**
     * @param action           start status stop
     * @param file_prefix      新的任务临时目录
     * @param duration_seconds 最长游戏秒数
     * @return                仅 CPU 跟踪状态 不采集骨骼或候选
     */
    """
    global _capture, _handle, _previous_channels
    if action == 'stop':
        _finish('stopped')
    if action in ('status', 'stop'):
        return json.dumps(_capture)
    if action != 'start' or not re.fullmatch(r'[A-Za-z0-9_-]+', file_prefix) or not 1 <= duration_seconds <= 15:
        raise RuntimeError('要求 start/status/stop 新目录和一至十五秒')
    library = unreal.TraceUtilLibrary
    if _handle is not None or library.is_tracing():
        raise RuntimeError('已有跟踪正在运行 不接管其它任务')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError('需要 PIE 世界')
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), 'temp', file_prefix))
    if os.path.lexists(directory):
        raise RuntimeError('性能输出目录必须不存在')
    os.makedirs(directory)
    path = os.path.join(directory, 'cpu.utrace')
    _previous_channels = list(library.get_enabled_channels())
    for name in _previous_channels:
        library.toggle_channel(name, False)
    if not library.start_trace_to_file(path, ['cpu', 'frame', 'bookmark', 'region']):
        for name in _previous_channels:
            library.toggle_channel(name, True)
        raise RuntimeError('原生 CPU 跟踪启动失败')
    library.trace_mark_region_start('MMPerformanceCapture')
    start_time = unreal.GameplayStatics.get_time_seconds(world)
    start_wall = time.monotonic()
    _capture = {'state': 'running', 'filePath': path, 'startWorldTime': start_time, 'duration': duration_seconds,
                'enabledChannels': list(library.get_enabled_channels()), 'availableChannels': list(library.get_all_channels())}

    def tick(delta_seconds):
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                _finish('failed', 'PIE world ended')
                return
            elapsed = unreal.GameplayStatics.get_time_seconds(world) - start_time
            _capture['elapsed'] = elapsed
            if elapsed >= duration_seconds:
                _finish('completed')
                return
            if time.monotonic() - start_wall > 60 or (os.path.isfile(path) and os.path.getsize(path) > 256 * 1024 * 1024):
                _finish('failed', 'Capture time or size limit exceeded')
        except Exception as error:
            _finish('failed', str(error))

    _handle = unreal.register_slate_post_tick_callback(tick)
    from BBBMcpCapabilities import register_activity
    register_activity('motion_matching:timing', lambda: _handle is not None, blocking=False, wait=False)
    return json.dumps(_capture)
