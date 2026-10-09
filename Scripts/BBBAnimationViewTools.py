import json
import math
import os
import re
import uuid

import unreal


def capture_animation_views(mesh_path, animation_path, sample_progress, views_json, file_prefix, exposure_bias, captures_registry):
    """
    /**
     * 在明确姿势周围取景 使用相机方向补光并保留上下观察方向
     * @param mesh_path	骨骼网格
     * @param animation_path	动画
     * @param sample_progress	归一化采样进度
     * @param views_json	偏航和俯仰角数组
     * @param file_prefix	唯一目录前缀
     * @param exposure_bias	固定曝光补偿
     * @param captures_registry	当前工具集的跨帧截图记录
     * @return 截图及相机和骨骼证据
     */
    """
    if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
        raise RuntimeError("全角度截图需要渲染宿主")

    if any(record.get("status") == "pending" for record in captures_registry.values()):
        raise RuntimeError("已有截图正在采样 必须等待完成以避免临时补光叠加")

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError("必须先启动 PIE")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
        raise RuntimeError("截图前缀无效")

    if not sample_progress or len(sample_progress) > 9 or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in sample_progress):
        raise RuntimeError("采样进度必须有限且在零至一之间 每次至多九项")

    views = json.loads(views_json)
    if not isinstance(views, list) or not views or len(views) > 32:
        raise RuntimeError("视角必须为一至三十二组偏航和俯仰角")

    for view in views:
        if not isinstance(view, list) or len(view) != 2 or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in view) or not -90.0 <= view[1] <= 90.0:
            raise RuntimeError("视角无效 俯仰须在负九十至九十度之间")

    if not math.isfinite(exposure_bias) or not -12.0 <= exposure_bias <= 12.0:
        raise RuntimeError("固定曝光补偿无效")

    mesh = unreal.load_asset(mesh_path)
    animation = unreal.load_asset(animation_path)
    if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(animation, unreal.AnimSequence) or mesh.get_editor_property("skeleton") != animation.get_editor_property("skeleton"):
        raise RuntimeError("动画与网格必须存在并使用同一骨架")

    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
    if os.path.exists(directory):
        raise RuntimeError("截图目录已存在 禁止覆盖证据")

    os.makedirs(directory)
    report_path = os.path.join(directory, "report.json")

    def save_report(report):
        """
        /**
         * 原子落盘本次截图进度 避免宿主被并行编译结束后丢失元数据
         * @param report	当前截图结果
         * @return 无返回值
         */
        """
        pending_path = os.path.join(directory, "report.pending.json")
        with open(pending_path, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(pending_path, report_path)

    def render_frames():
        """/** @return 跨帧渲染过程 每个视角等待场景代理更新 */"""
        actors = []
        captures = []
        spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
        try:
            actor = spawn(world, unreal.SkeletalMeshActor, unreal.Transform(location=unreal.Vector(0.0, 0.0, 20000.0)))
            if actor is None:
                raise RuntimeError("临时骨骼演员创建失败")

            actors.append(actor)
            component = actor.skeletal_mesh_component
            component.set_skeletal_mesh_asset(mesh)
            component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            camera = spawn(world, unreal.SceneCapture2D, unreal.Transform())
            if camera is None:
                raise RuntimeError("临时相机创建失败")

            actors.append(camera)
            lights = []
            for intensity in [30000.0, 20000.0, 15000.0]:
                light = spawn(world, unreal.PointLight, unreal.Transform())
                if light is None:
                    raise RuntimeError("临时补光创建失败")

                actors.append(light)
                light_component = light.get_component_by_class(unreal.PointLightComponent)
                light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                light_component.set_intensity(intensity)
                light_component.set_attenuation_radius(2000.0)
                light_component.set_cast_shadows(False)
                lights.append(light)

            target = unreal.RenderingLibrary.create_render_target2d(world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property("texture_target", target)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("fov_angle", 40.0)
            capture.set_editor_property("capture_every_frame", False)
            capture.set_editor_property("capture_on_movement", False)
            capture.set_editor_property("always_persist_rendering_state", True)
            capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.set_editor_property("show_only_actors", [actor])
            settings = unreal.PostProcessSettings()
            settings.set_editor_property("override_auto_exposure_method", True)
            settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
            settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
            settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
            settings.set_editor_property("override_auto_exposure_bias", True)
            settings.set_editor_property("auto_exposure_bias", exposure_bias)
            settings.set_editor_property("override_dynamic_global_illumination_method", True)
            settings.set_editor_property("dynamic_global_illumination_method", unreal.DynamicGlobalIlluminationMethod.NONE)
            settings.set_editor_property("override_reflection_method", True)
            settings.set_editor_property("reflection_method", unreal.ReflectionMethod.NONE)
            capture.set_editor_property("post_process_settings", settings)
            capture.set_editor_property("post_process_blend_weight", 1.0)
            for warmup_frame in range(15):
                yield

            for sample_index, progress in enumerate(sample_progress):
                seconds = animation.get_play_length() * progress
                if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(component, animation, seconds):
                    raise RuntimeError("动画姿势求值失败")

                bones = {}
                for bone_index in range(component.get_num_bones()):
                    name = str(component.get_bone_name(bone_index))
                    position = component.get_socket_location(name)
                    bones[name] = [position.x, position.y, position.z - 20000.0]

                framing_bones = {name: value for name, value in bones.items() if not name.lower().startswith("ik_")}
                minimum = [min(value[axis] for value in framing_bones.values()) for axis in range(3)]
                maximum = [max(value[axis] for value in framing_bones.values()) for axis in range(3)]
                center = unreal.Vector(*[(minimum[axis] + maximum[axis]) * 0.5 for axis in range(3)]) + unreal.Vector(0.0, 0.0, 20000.0)
                radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) * 0.5) ** 2 for axis in range(3))) + 15.0
                distance = radius / math.sin(math.radians(20.0)) * 1.12
                for view_index, (yaw, pitch) in enumerate(views):
                    azimuth = math.radians(yaw)
                    elevation = math.radians(pitch)
                    direction = unreal.Vector(math.cos(elevation) * math.cos(azimuth), math.cos(elevation) * math.sin(azimuth), math.sin(elevation))
                    side = unreal.Vector(-math.sin(azimuth), math.cos(azimuth), 0.0)
                    up = unreal.Vector(-math.sin(elevation) * math.cos(azimuth), -math.sin(elevation) * math.sin(azimuth), math.cos(elevation))
                    location = center + direction * distance
                    rotation = unreal.MathLibrary.find_look_at_rotation(location, center)
                    camera.set_actor_location(location, False, True)
                    camera.set_actor_rotation(rotation, True)
                    positions = [center + direction * 220.0 + up * 100.0, center + direction * 160.0 - side * 180.0, center - direction * 120.0 + side * 160.0 - up * 90.0]
                    for light, position in zip(lights, positions):
                        light.set_actor_location(position, False, True)

                    yield
                    yield
                    capture.capture_scene()
                    yield
                    capture.capture_scene()
                    yield
                    capture.capture_scene()
                    filename = "sample_%02d_view_%02d.png" % (sample_index, view_index)
                    unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                    path = os.path.join(directory, filename)
                    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
                        raise RuntimeError("截图文件缺失或异常小 必须检查渲染结果")

                    captures.append({"sampleProgress": progress, "seconds": seconds, "yaw": yaw, "pitch": pitch, "imagePath": path, "cameraDistanceCm": distance, "bones": bones})
                    save_report({"status": "running", "mesh": mesh_path, "animation": animation_path, "exposureBias": exposure_bias, "captures": captures, "temporaryActorsDestroyed": False})

            unreal.log("[BBBAnimationViews] CAPTURE " + animation_path + " count=" + str(len(captures)))
        finally:
            for actor in reversed(actors):
                actor.destroy_actor()

        report = {"status": "completed", "mesh": mesh_path, "animation": animation_path, "exposureBias": exposure_bias, "captures": captures, "reportPath": report_path, "temporaryActorsDestroyed": True}
        save_report(report)
        return json.dumps(report, ensure_ascii=False)

    capture_id = uuid.uuid4().hex
    record = {"status": "pending", "captureId": capture_id}
    captures_registry[capture_id] = record
    iterator = render_frames()
    handle = None

    def advance_frame(delta_seconds):
        """
        /**
         * 每次编辑器帧继续一个渲染阶段 世界变化时销毁本次临时对象
         * @param delta_seconds	帧间隔
         * @return 无返回值
         */
        """
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError("全角度采样期间 PIE 世界已结束")

            next(iterator)
        except StopIteration as completed:
            record["status"] = "completed"
            record["result"] = json.loads(completed.value)
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception as error:
            iterator.close()
            record["status"] = "failed"
            record["error"] = str(error)
            unreal.unregister_slate_post_tick_callback(handle)
            unreal.log_error("[BBBAnimationViews] FAILED " + str(error))

    handle = unreal.register_slate_post_tick_callback(advance_frame)
    return json.dumps(record, ensure_ascii=False)
