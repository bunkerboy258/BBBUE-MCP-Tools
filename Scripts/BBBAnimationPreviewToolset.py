import json
import os
import re
import uuid

import unreal
import toolset_registry
from toolset_registry.registration import Registration


_transition_captures = {}


@unreal.uclass()
class BBBAnimationPreviewToolset(unreal.ToolsetDefinition):
    """
    /**
     * 在临时对象上渲染明确动画的多个采样姿势 不修改源资产
     */
    """

    @toolset_registry.tool_call
    @staticmethod
    def capture_animation_samples(mesh_path: str, animation_paths: list[str], sample_progress: list[float], file_prefix: str) -> str:
        """
        /**
         * 在当前唯一渲染宿主的 PIE 世界逐动画生成姿势对比图
         * @param mesh_path		明确骨骼网格路径
         * @param animation_paths	明确动画路径 每次至多八条
         * @param sample_progress	归一化时间 从左至右 至多三项
         * @param file_prefix		不含目录的唯一截图前缀
         * @return 截图路径 实际采样时间与临时对象清理结果
         */
        """
        if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("姿势截图需要渲染宿主 NullRHI 不提供视觉证据")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("必须先启动当前唯一宿主的 PIE")

        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
            raise RuntimeError("截图前缀无效")

        if not animation_paths or len(animation_paths) > 8 or len(set(animation_paths)) != len(animation_paths):
            raise RuntimeError("动画数量或唯一性无效")

        if not sample_progress or len(sample_progress) > 3 or any(not 0.0 <= value <= 1.0 for value in sample_progress):
            raise RuntimeError("采样时间必须在零至一之间 每次至多三项")

        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("骨骼网格不存在")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "AnimationSamples"))
        requests = []
        for path in animation_paths:
            animation = unreal.load_asset(path)
            if not isinstance(animation, unreal.AnimSequence) or animation.get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
                raise RuntimeError("动画不存在或骨架不匹配: " + path)

            filename = file_prefix + "_" + animation.get_name() + ".png"
            if os.path.exists(os.path.join(directory, filename)):
                raise RuntimeError("截图已存在 禁止覆盖: " + filename)

            requests.append((animation, filename))

        os.makedirs(directory, exist_ok=True)
        reports = []
        spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
        for animation, filename in requests:
            actors = []
            try:
                for index, progress in enumerate(sample_progress):
                    offset = (index - (len(sample_progress) - 1) * 0.5) * 180.0
                    actor = spawn(world, unreal.SkeletalMeshActor, unreal.Transform(location=unreal.Vector(0.0, offset, 20000.0), rotation=unreal.Rotator(pitch=0.0, yaw=90.0, roll=0.0)))
                    if actor is None:
                        raise RuntimeError("临时骨骼演员创建失败")

                    actors.append(actor)
                    component = actor.skeletal_mesh_component
                    component.set_skeletal_mesh_asset(mesh)
                    component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                    if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(component, animation, animation.get_play_length() * progress):
                        raise RuntimeError("姿势求值失败")

                light = spawn(world, unreal.PointLight, unreal.Transform(location=unreal.Vector(-220.0, 0.0, 20230.0)))
                if light is None:
                    raise RuntimeError("临时补光创建失败")

                actors.append(light)
                light_component = light.get_component_by_class(unreal.PointLightComponent)
                light_component.set_intensity(50000.0)
                light_component.set_attenuation_radius(1600.0)
                camera = spawn(world, unreal.SceneCapture2D, unreal.Transform(location=unreal.Vector(-650.0, 0.0, 20095.0)))
                if camera is None:
                    raise RuntimeError("临时相机创建失败")

                actors.append(camera)
                target = unreal.RenderingLibrary.create_render_target2d(world, 960, 540, unreal.TextureRenderTargetFormat.RTF_RGBA8)
                capture = camera.capture_component2d
                capture.set_editor_property("texture_target", target)
                capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
                capture.set_editor_property("fov_angle", 55.0)
                capture.set_editor_property("capture_every_frame", False)
                capture.set_editor_property("capture_on_movement", False)
                settings = unreal.PostProcessSettings()
                settings.set_editor_property("override_auto_exposure_method", True)
                settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
                settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
                settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
                capture.set_editor_property("post_process_settings", settings)
                capture.set_editor_property("post_process_blend_weight", 1.0)
                capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
                capture.set_editor_property("show_only_actors", actors[:-2])
                capture.capture_scene()
                unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                image_path = os.path.join(directory, filename)
                if not os.path.isfile(image_path) or os.path.getsize(image_path) < 1024:
                    raise RuntimeError("截图生成失败 不接受空白证据")

                report = {"animation": animation.get_path_name(), "imagePath": image_path, "sampleSeconds": [animation.get_play_length() * progress for progress in sample_progress]}
                reports.append(report)
                unreal.log("[BBBAnimationPreview] CAPTURE " + animation.get_name())
            finally:
                for actor in reversed(actors):
                    actor.destroy_actor()

        return json.dumps({"mesh": mesh.get_path_name(), "captures": reports, "temporaryActorsDestroyed": True}, ensure_ascii=False)


    @toolset_registry.tool_call
    @staticmethod
    def capture_monster_animation_transition(actor_blueprint_path: str, initial_state: int, target_state: int, initial_progress: float, target_progress: float, sample_seconds: list[float], bone_names: list[str], file_prefix: str) -> str:
        """
        /**
         * 在无 Mass 实体的临时表现演员上渲染真实动画蓝图切换 不写玩法状态
         * @param actor_blueprint_path		明确表现演员蓝图
         * @param initial_state			初始表现状态 零至五
         * @param target_state			目标表现状态 零至五
         * @param initial_progress		初始非循环动作进度
         * @param target_progress			目标非循环动作进度
         * @param sample_seconds			切换后秒数 从左至右 至多三项
         * @param bone_names			需要记录的组件空间骨骼 可为空
         * @param file_prefix			唯一截图前缀
         * @return 实际蓝图类 采样时间 骨骼位置与临时对象清理结果
         */
        """
        if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("运行时姿势截图需要渲染宿主")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if world is None or library is None:
            raise RuntimeError("缺少 PIE 世界或真实动画蓝图同步求值接口")

        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
            raise RuntimeError("截图前缀无效")

        if initial_state not in range(6) or target_state not in range(6) or not 0.0 <= initial_progress <= 1.0 or not 0.0 <= target_progress <= 1.0:
            raise RuntimeError("表现状态或逻辑进度无效")

        if not sample_seconds or len(sample_seconds) > 3 or any(not 0.0 <= value <= 0.5 for value in sample_seconds) or sample_seconds != sorted(sample_seconds):
            raise RuntimeError("采样时刻须有序且位于零至半秒 每次至多三项")

        blueprint = unreal.load_asset(actor_blueprint_path)
        if not isinstance(blueprint, unreal.Blueprint):
            raise RuntimeError("表现演员蓝图不存在")

        states = [unreal.BBBMonsterBehavior.IDLE, unreal.BBBMonsterBehavior.SCOUT, unreal.BBBMonsterBehavior.CHASE, unreal.BBBMonsterBehavior.ATTACK, unreal.BBBMonsterBehavior.HURT, unreal.BBBMonsterBehavior.DEAD]
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "AnimationSamples"))
        filename = file_prefix + "_" + blueprint.get_name() + ".png"
        image_path = os.path.join(directory, filename)
        if os.path.exists(image_path):
            raise RuntimeError("截图已存在 禁止覆盖")

        os.makedirs(directory, exist_ok=True)
        if any(item["status"] == "pending" for item in _transition_captures.values()):
            raise RuntimeError("已有姿势截图等待完成 禁止并行采样")

        capture_id = str(uuid.uuid4())

        def capture_frames():
            actors = []
            samples = []
            centers = []
            spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
            try:
                for index, seconds in enumerate(sample_seconds):
                    offset = (index - (len(sample_seconds) - 1) * 0.5) * 180.0
                    actor = spawn(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector(0.0, offset, 20090.0), rotation=unreal.Rotator(pitch=0.0, yaw=180.0, roll=0.0)))
                    if actor is None:
                        raise RuntimeError("临时表现演员创建失败")

                    actors.append(actor)
                    mesh = actor.get_monster_mesh()
                    presentation = actor.get_monster_presentation()
                    for name in ("idle_animation_variants", "chase_animation_variants", "attack_animation_variants", "hurt_animation_variants", "dead_animation_variants"):
                        presentation.set_editor_property(name, [])

                    mesh.set_component_tick_enabled(False)
                    presentation.call_method("ApplyPresentationState", (states[initial_state], 100.0, 1.0, 1, initial_progress))
                    if not library.evaluate_animation_blueprint_frame(mesh, 0.001):
                        raise RuntimeError("初始动画蓝图求值失败")

                    for warmup in range(3):
                        yield
                        if not library.evaluate_animation_blueprint_frame(mesh, 0.001):
                            raise RuntimeError("初始姿势跨帧求值失败")

                    height = unreal.SystemLibrary.get_component_bounds(mesh)[1].z * 2.0
                    if height <= 0.001:
                        raise RuntimeError("临时表现网格包围盒高度无效")

                    preview_scale = 180.0 / height
                    actor.set_actor_scale3d(unreal.Vector(preview_scale, preview_scale, preview_scale))
                    before = {name: mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation for name in bone_names}
                    yield
                    presentation.call_method("ApplyPresentationState", (states[target_state], 100.0, 2.0, 2, target_progress))
                    if not library.evaluate_animation_blueprint_frame(mesh, 0.0001):
                        raise RuntimeError("目标动画蓝图求值失败")

                    elapsed = 0.0
                    while elapsed < seconds - 0.000001:
                        delta = min(1.0 / 60.0, seconds - elapsed)
                        yield
                        if not library.evaluate_animation_blueprint_frame(mesh, delta):
                            raise RuntimeError("过渡动画蓝图求值失败")

                        elapsed += delta

                    instance = mesh.get_anim_instance()
                    bones = {}
                    for name in bone_names:
                        if mesh.get_bone_index(name) < 0:
                            raise RuntimeError("运行时网格缺少骨骼 " + name)

                        position = mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation
                        original = before[name]
                        distance = ((position.x - original.x) ** 2 + (position.y - original.y) ** 2 + (position.z - original.z) ** 2) ** 0.5
                        bones[name] = {"position": [position.x, position.y, position.z], "initialPosition": [original.x, original.y, original.z], "distanceFromInitialCm": distance}

                    centers.append(unreal.SystemLibrary.get_component_bounds(mesh)[0].z)
                    samples.append({"seconds": seconds, "animationClass": instance.get_class().get_path_name(), "activeAnimation": instance.get_active_animation().get_path_name(), "explicitTime": instance.get_active_animation_time(), "channelBActive": instance.is_channel_b_active(), "bones": bones, "runtimeGraph": json.loads(unreal.BBBBlueprintEditorLibrary.probe_animation_instance_runtime(instance))})

                for render_warmup in range(30):
                    yield

                light = spawn(world, unreal.PointLight, unreal.Transform(location=unreal.Vector(-220.0, 0.0, max(centers) + 130.0)))
                if light is None:
                    raise RuntimeError("临时补光创建失败")

                actors.append(light)
                light_component = light.get_component_by_class(unreal.PointLightComponent)
                light_component.set_intensity(50000.0)
                light_component.set_attenuation_radius(1600.0)
                camera = spawn(world, unreal.SceneCapture2D, unreal.Transform(location=unreal.Vector(-650.0, 0.0, sum(centers) / len(centers))))
                if camera is None:
                    raise RuntimeError("临时相机创建失败")

                actors.append(camera)
                target = unreal.RenderingLibrary.create_render_target2d(world, 960, 540, unreal.TextureRenderTargetFormat.RTF_RGBA8)
                capture = camera.capture_component2d
                capture.set_editor_property("texture_target", target)
                capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
                capture.set_editor_property("fov_angle", 55.0)
                capture.set_editor_property("capture_every_frame", False)
                capture.set_editor_property("capture_on_movement", False)
                settings = unreal.PostProcessSettings()
                settings.set_editor_property("override_auto_exposure_method", True)
                settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
                settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
                settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
                capture.set_editor_property("post_process_settings", settings)
                capture.set_editor_property("post_process_blend_weight", 1.0)
                capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
                capture.set_editor_property("show_only_actors", actors[:-2])
                capture.capture_scene()
                unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                if not os.path.isfile(image_path) or os.path.getsize(image_path) < 1024:
                    raise RuntimeError("运行时截图导出失败")
            finally:
                for actor in reversed(actors):
                    actor.destroy_actor()

            report = {"actorBlueprint": actor_blueprint_path, "initialState": initial_state, "targetState": target_state, "imagePath": image_path, "samples": samples, "temporaryActorsDestroyed": True}
            report_path = os.path.join(directory, file_prefix + "_" + blueprint.get_name() + ".json")
            with open(report_path, "x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=4)

            unreal.log("[BBBAnimationTransition] CAPTURE " + actor_blueprint_path)
            return json.dumps(report, ensure_ascii=False)

        iterator = capture_frames()
        record = {"status": "pending", "captureId": capture_id}
        _transition_captures[capture_id] = record
        handle = None

        def advance_frame(delta_seconds):
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                    raise RuntimeError("采样期间 PIE 世界已结束")

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
                unreal.log_error("[BBBAnimationTransition] FAILED " + str(error))

        handle = unreal.register_slate_post_tick_callback(advance_frame)
        return json.dumps(record, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_transition_capture(capture_id: str) -> str:
        """
        /**
         * 查询跨引擎帧截图结果 不重复执行采样
         * @param capture_id	截图启动返回的唯一编号
         * @return 待完成 完成或失败状态及证据
         */
        """
        if capture_id not in _transition_captures:
            raise RuntimeError("截图编号不存在")

        return json.dumps(_transition_captures[capture_id], ensure_ascii=False)


_registration = Registration([BBBAnimationPreviewToolset])
