import json
import math
import os
import stat
import time

import unreal


_capture = None
_capture_handle = None


def capture_niagara_asset(system_path, age_seconds, camera_offset, file_name):
    """
    /**
     * 在瞬态 PIE 预览中拍摄明确年龄的 Niagara 特效
     * @param system_path\t\t特效资产路径
     * @param age_seconds\t\t模拟年龄秒
     * @param camera_offset\t相对特效原点的相机位置厘米
     * @param file_name\t\t任务目录与 PNG 名称
     * @return 图像路径及实际模拟年龄
     */
    """
    global _capture, _capture_handle
    if _capture_handle is not None:
        raise RuntimeError("特效拍摄仍在运行")

    parts = file_name.replace("\\", "/").split("/")
    if (len(parts) != 2 or any(not part or part in {".", ".."} or ":" in part for part in parts)
            or not parts[1].endswith(".png") or len(camera_offset) != 3
            or not all(math.isfinite(float(value)) for value in camera_offset)
            or sum(float(value) ** 2 for value in camera_offset) < 1.0
            or not math.isfinite(age_seconds) or age_seconds < 0.0 or age_seconds > 5.0):
        raise RuntimeError("特效拍摄参数无效")

    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", parts[0]))
    path = os.path.join(directory, parts[1])
    if os.path.lexists(directory) and (os.path.islink(directory)
            or getattr(os.lstat(directory), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise RuntimeError("特效拍摄目录不得为链接")

    if os.path.lexists(path):
        raise RuntimeError("特效拍摄拒绝覆盖已有文件 " + path)

    system = unreal.load_asset(system_path)
    if not isinstance(system, unreal.NiagaraSystem):
        raise RuntimeError("特效资产必须为 NiagaraSystem")

    if not unreal.BBBNiagaraEditorLibrary.prepare_system_for_preview(system_path):
        raise RuntimeError("特效系统及 GPU 着色器尚未就绪")

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError("特效拍摄需要带渲染的 PIE 世界")

    actors = []
    pending = False
    try:
        origin = unreal.Vector(0.0, 0.0, 10000.0)
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.NiagaraActor, unreal.Transform(location=origin))
        actors.append(actor)
        component = actor.get_component_by_class(unreal.NiagaraComponent)
        component.set_asset(system)
        component.set_editor_property("allow_scalability", False)
        component.set_force_solo(True)
        component.set_age_update_mode(unreal.NiagaraAgeUpdateMode.TICK_DELTA_TIME)
        component.activate(True)

        location = origin + unreal.Vector(*camera_offset)
        camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=unreal.MathLibrary.find_look_at_rotation(location, origin)))
        actors.append(camera)
        capture = camera.capture_component2d
        capture.set_editor_property("capture_every_frame", True)
        capture.set_editor_property("capture_on_movement", False)
        target = unreal.RenderingLibrary.create_render_target2d(world, 640, 640, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        capture.set_editor_property("texture_target", target)
        capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
        capture.set_editor_property("show_only_actors", [actor])
        capture.set_editor_property("fov_angle", 45.0)
        settings = capture.get_editor_property("post_process_settings")
        settings.set_editor_property("override_auto_exposure_method", True)
        settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        settings.set_editor_property("override_auto_exposure_bias", True)
        settings.set_editor_property("auto_exposure_bias", 0.0)
        settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        capture.set_editor_property("post_process_settings", settings)
        _capture = {"status": "pending", "imagePath": path, "ageSeconds": age_seconds,
                    "system": system.get_path_name(), "renderFrames": 0, "simulationSeconds": 0.0, "captured": False, "error": None}
        started = time.monotonic()
        started_world_time = unreal.GameplayStatics.get_time_seconds(world)

        def finish(status, error=None):
            global _capture_handle
            _capture["status"] = status
            _capture["error"] = error
            if _capture_handle is not None:
                unreal.unregister_slate_post_tick_callback(_capture_handle)
            _capture_handle = None
            for preview in reversed(actors):
                if unreal.SystemLibrary.is_valid(preview):
                    preview.destroy_actor()

        def tick(delta_seconds):
            try:
                current = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
                if current != world or not unreal.SystemLibrary.is_valid(actor):
                    raise RuntimeError("特效拍摄的 PIE 世界已结束")
                if time.monotonic() - started > 60.0:
                    raise RuntimeError("特效拍摄等待渲染超时")
                _capture["renderFrames"] += 1
                _capture["worldSeconds"] = unreal.GameplayStatics.get_time_seconds(world) - started_world_time
                _capture["simulationSeconds"] = unreal.BBBNiagaraEditorLibrary.read_preview_system_age(component)
                if not _capture["captured"] and _capture["simulationSeconds"] >= age_seconds:
                    capture.capture_scene()
                    _capture["captured"] = True
                    _capture["captureFrame"] = _capture["renderFrames"]
                    return
                if _capture["captured"] and _capture["renderFrames"] > _capture["captureFrame"]:
                    os.makedirs(directory, exist_ok=True)
                    unreal.RenderingLibrary.export_render_target(world, target, directory, parts[1])
                    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
                        raise RuntimeError("特效拍摄未生成有效图像")
                    unreal.log("[BBBDisplayAssetCapture] 特效图像 " + path)
                    finish("completed")
            except Exception as error:
                unreal.log_error("[BBBDisplayAssetCapture] " + str(error))
                finish("failed", str(error))

        _capture_handle = unreal.register_slate_post_tick_callback(tick)
        from BBBMcpCapabilities import register_activity
        register_activity("display:capture", lambda: _capture_handle is not None)
        pending = True
        return json.dumps(_capture)
    finally:
        if not pending:
            for actor in reversed(actors):
                if actor is not None:
                    actor.destroy_actor()


def get_niagara_capture_status():
    """/** @return 最近一次特效拍摄的真实状态 不重置回调 */"""
    return json.dumps(_capture if _capture is not None else {"status": "idle"})


_view_recording = None
_view_recording_handle = None


def record_pie_player_view(file_prefix, duration_seconds, fps, width, height):
    """
    /**
     * @param file_prefix\t任务目录名称
     * @param duration_seconds\t实际世界录制秒数
     * @param fps\t目标采样帧率
     * @param width\t输出宽度
     * @param height\t输出高度
     * @return 跨帧录制状态与时间戳记录
     */
    """
    global _view_recording, _view_recording_handle
    import re
    if (_view_recording_handle is not None or not re.fullmatch(r'[A-Za-z0-9_-]+', file_prefix)
            or not math.isfinite(duration_seconds) or not 0.1 <= duration_seconds <= 12
            or not 1 <= fps <= 30 or not 64 <= width <= 1280 or not 64 <= height <= 720):
        raise RuntimeError('录制参数无效或录制仍在运行')
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), 'temp', file_prefix))
    if os.path.lexists(directory):
        raise RuntimeError('录制目录必须不存在')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    manager = unreal.GameplayStatics.get_player_camera_manager(world, 0) if world else None
    if manager is None:
        raise RuntimeError('需要带渲染的 PIE 玩家相机')
    actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform())
    capture = actor.capture_component2d
    capture.set_editor_property('capture_every_frame', False)
    capture.set_editor_property('capture_on_movement', False)
    target = unreal.RenderingLibrary.create_render_target2d(world, width, height, unreal.TextureRenderTargetFormat.RTF_RGBA8)
    capture.set_editor_property('texture_target', target)
    capture.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    os.makedirs(directory)
    _view_recording = {'status': 'running', 'directory': directory, 'duration': duration_seconds,
                       'targetFps': fps, 'width': width, 'height': height, 'elapsed': 0.0, 'frames': [], 'pending': None}
    recording_world_time = unreal.GameplayStatics.get_time_seconds(world)
    recording_started = time.monotonic()

    def finish(status, error=None):
        global _view_recording_handle
        _view_recording['status'] = status
        _view_recording['error'] = error
        unreal.unregister_slate_post_tick_callback(_view_recording_handle)
        _view_recording_handle = None
        if unreal.SystemLibrary.is_valid(actor):
            actor.destroy_actor()
        with open(os.path.join(directory, 'frames.json'), 'w', encoding='utf-8') as stream:
            json.dump(_view_recording, stream, ensure_ascii=False, indent=2)

    def tick(delta_seconds):
        try:
            if not unreal.SystemLibrary.is_valid(actor) or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError('录制世界已结束')
            if time.monotonic() - recording_started > 180.0:
                raise RuntimeError('录制等待游戏时间推进超时')
            _view_recording['elapsed'] = unreal.GameplayStatics.get_time_seconds(world) - recording_world_time
            pending = _view_recording['pending']
            if pending is not None:
                filename = 'frame_%04d.png' % len(_view_recording['frames'])
                unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                if not os.path.isfile(os.path.join(directory, filename)):
                    raise RuntimeError('帧图像导出失败')
                _view_recording['frames'].append({'file': filename, 'time': pending})
                _view_recording['pending'] = None
            elapsed = _view_recording['elapsed']
            if elapsed >= duration_seconds:
                finish('completed')
                return
            if not _view_recording['frames'] or elapsed - _view_recording['frames'][-1]['time'] >= 1.0 / fps:
                actor.set_actor_location(manager.get_camera_location(), False, False)
                actor.set_actor_rotation(manager.get_camera_rotation(), False)
                capture.set_editor_property('fov_angle', manager.get_fov_angle())
                capture.capture_scene()
                _view_recording['pending'] = elapsed
        except Exception as error:
            finish('failed', str(error))

    _view_recording_handle = unreal.register_slate_post_tick_callback(tick)
    from BBBMcpCapabilities import register_activity
    register_activity('display:view_recording', lambda: _view_recording_handle is not None, blocking=False, wait=False)
    return json.dumps({'status': 'running', 'directory': directory})


def get_pie_view_recording_status():
    """/** @return 玩家视角录制状态与实际采样数量 */"""
    if _view_recording is None:
        return json.dumps({'status': 'idle'})
    return json.dumps({key: value for key, value in _view_recording.items() if key != 'frames'} | {'frameCount': len(_view_recording['frames'])})
