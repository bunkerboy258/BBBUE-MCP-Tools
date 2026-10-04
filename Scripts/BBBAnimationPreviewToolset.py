import json
import os
import re

import unreal
import toolset_registry
from toolset_registry.registration import Registration


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


_registration = Registration([BBBAnimationPreviewToolset])
