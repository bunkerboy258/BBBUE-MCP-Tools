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
        component.set_force_solo(True)
        component.set_age_update_mode(unreal.NiagaraAgeUpdateMode.DESIRED_AGE)
        component.set_desired_age(age_seconds)
        component.activate(True)
        component.set_seek_delta(1.0 / 120.0)

        location = origin + unreal.Vector(*camera_offset)
        camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=unreal.MathLibrary.find_look_at_rotation(location, origin)))
        actors.append(camera)
        capture = camera.capture_component2d
        capture.set_editor_property("capture_every_frame", False)
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
                    "system": system.get_path_name(), "renderFrames": 0, "error": None}
        started = time.monotonic()

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
                if time.monotonic() - started > 10.0:
                    raise RuntimeError("特效拍摄等待渲染超时")
                _capture["renderFrames"] += 1
                if _capture["renderFrames"] == 4:
                    capture.capture_scene()
                if _capture["renderFrames"] >= 5:
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
