import json
import math
from pathlib import Path

import unreal
from BBBMcpCapabilities import mcp_tool, register_activity
from toolset_registry.registration import Registration


_render = {"status": "idle"}
_executor = None
_hide_handle = None


@unreal.uclass()
class BBBCinematicToolset(unreal.ToolsetDefinition):
    """/** 在当前编辑器制作与渲染明确的摄影序列 */"""

    @mcp_tool
    @staticmethod
    def create_shot(asset_path: str, location: list[float], rotation: list[float],
                    dolly_cm: float = 45.0, fov: float = 75.0, frames: int = 60, fps: int = 30, replace_existing: bool = False) -> str:
        """
        /**
         * @param asset_path	新建摄影序列
         * @param location	用户指定世界位置
         * @param rotation	Pitch Yaw Roll 朝向
         * @param dolly_cm	沿视线推进距离
         * @param fov	水平视场角
         * @param frames	输出帧数
         * @param fps	输出帧率
         * @param replace_existing	明确重建已存在的序列
         * @return 保存后序列与摄影机证据
         */
        """
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path) and not replace_existing:
            raise RuntimeError("目标序列已存在 禁止静默覆盖")
        if len(location) != 3 or len(rotation) != 3 or not 10 <= fov <= 120 or not 1 <= frames <= 900 or not 1 <= fps <= 60:
            raise ValueError("摄影参数超出范围")
        if not all(math.isfinite(v) for v in location + rotation + [dolly_cm]):
            raise ValueError("摄影参数必须为有限值")
        folder, name = asset_path.rsplit("/", 1)
        seq = unreal.load_asset(asset_path) if replace_existing else None
        if seq is None:
            seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
        if not isinstance(seq, unreal.LevelSequence):
            raise RuntimeError("目标不是 LevelSequence")
        for old_binding in seq.get_bindings():
            old_binding.remove()
        for old_track in seq.get_tracks():
            seq.remove_track(old_track)
        seq.set_display_rate(unreal.FrameRate(fps, 1))
        seq.set_playback_start(0)
        seq.set_playback_end(frames)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        camera = actors.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(*location), unreal.Rotator(pitch=rotation[0], yaw=rotation[1], roll=rotation[2]), transient=True)
        component = camera.get_cine_camera_component()
        filmback = component.get_editor_property("filmback")
        filmback.sensor_width = 36.0
        filmback.sensor_height = 20.25
        component.set_editor_property("filmback", filmback)
        component.set_editor_property("current_focal_length", 18.0 / math.tan(math.radians(fov / 2.0)))
        component.set_editor_property("current_aperture", 8.0)
        focus = component.get_editor_property("focus_settings")
        focus.focus_method = unreal.CameraFocusMethod.DISABLE
        component.set_editor_property("focus_settings", focus)
        binding = seq.add_spawnable_from_instance(camera)
        actors.destroy_actor(camera)
        direction = unreal.MathLibrary.get_forward_vector(unreal.Rotator(pitch=rotation[0], yaw=rotation[1], roll=rotation[2]))
        end = [location[0] + direction.x * dolly_cm, location[1] + direction.y * dolly_cm, location[2] + direction.z * dolly_cm]
        section = binding.add_track(unreal.MovieScene3DTransformTrack).add_section()
        section.set_range(0, frames)
        channels = section.get_all_channels()
        start_values = location + [rotation[2], rotation[0], rotation[1]] + [1.0, 1.0, 1.0]
        end_values = end + [rotation[2], rotation[0], rotation[1]] + [1.0, 1.0, 1.0]
        unreal.log("Cinematic: authoring transform keys")
        for index, channel in enumerate(channels[:9]):
            channel.add_key(unreal.FrameNumber(0), start_values[index], interpolation=unreal.MovieSceneKeyInterpolation.LINEAR)
            channel.add_key(unreal.FrameNumber(frames), end_values[index], interpolation=unreal.MovieSceneKeyInterpolation.LINEAR)
        unreal.log("Cinematic: transform keyed; creating camera cut")
        cut = seq.add_track(unreal.MovieSceneCameraCutTrack).add_section()
        cut.set_range(0, frames)
        unreal.log("Cinematic: setting camera cut binding")
        cut.set_camera_binding_id(seq.get_binding_id(binding))
        unreal.EditorAssetLibrary.save_loaded_asset(seq)
        return json.dumps({"asset": seq.get_path_name(), "start": list(location), "end": end, "rotation": list(rotation), "fov": fov, "frames": frames, "fps": fps})

    @mcp_tool
    @staticmethod
    def render_shot(asset_path: str, expected_level: str, file_prefix: str,
                    width: int = 3840, height: int = 2160, temporal_samples: int = 8, warmup_frames: int = 120,
                    excluded_actor_names: list[str] = []) -> str:
        """
        /**
         * @param asset_path	已保存摄影序列
         * @param expected_level	当前拍摄地图
         * @param file_prefix	任务输出目录名称
         * @param width	输出宽度
         * @param height	输出高度
         * @param temporal_samples	原生时间采样次数
         * @param warmup_frames	渲染前实际预热帧数
         * @param excluded_actor_names	仅在渲染世界隐藏的演员名称
         * @return 原生 MRQ 任务状态
         */
        """
        global _executor, _render, _hide_handle
        import re
        if _render["status"] == "running" or not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
            raise RuntimeError("渲染仍在运行或任务目录无效")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_outermost().get_path_name() != expected_level:
            raise RuntimeError("当前地图与摄影目标不符")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("请先结束 PIE 再启动 MRQ")
        if not 64 <= width <= 4096 or not 64 <= height <= 2160 or not 1 <= temporal_samples <= 16 or not 48 <= warmup_frames <= 600:
            raise ValueError("渲染规格超出范围")
        output = Path(unreal.Paths.project_saved_dir()).resolve() / "temp" / file_prefix
        if output.exists():
            raise RuntimeError("输出目录必须不存在")
        seq = unreal.load_asset(asset_path)
        if not isinstance(seq, unreal.LevelSequence):
            raise RuntimeError("需要有效摄影序列")
        subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        if subsystem.is_rendering():
            raise RuntimeError("电影渲染队列正被占用")
        queue = subsystem.get_queue()
        if queue.get_jobs():
            raise RuntimeError("队列已有用户任务 请先交接")
        job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        try:
            job.set_editor_property("sequence", unreal.SoftObjectPath(seq.get_path_name()))
            job.set_editor_property("map", unreal.SoftObjectPath(expected_level))
            config = job.get_configuration()
            config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
            config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
            settings = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            settings.set_editor_property("output_resolution", unreal.IntPoint(width, height))
            settings.set_editor_property("output_directory", unreal.DirectoryPath(str(output)))
            settings.set_editor_property("file_name_format", "frame_{frame_number}")
            settings.set_editor_property("zero_pad_frame_numbers", 4)
            settings.set_editor_property("use_custom_frame_rate", True)
            settings.set_editor_property("output_frame_rate", seq.get_display_rate())
            aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
            aa.set_editor_property("spatial_sample_count", 1)
            aa.set_editor_property("temporal_sample_count", temporal_samples)
            aa.set_editor_property("override_anti_aliasing", True)
            aa.set_editor_property("anti_aliasing_method", unreal.AntiAliasingMethod.AAM_NONE)
            aa.set_editor_property("engine_warm_up_count", warmup_frames)
            aa.set_editor_property("render_warm_up_count", 32)
            overrides = config.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
            overrides.set_editor_property("cinematic_quality_settings", True)
            overrides.set_editor_property("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.NONE)
            overrides.set_editor_property("use_high_quality_shadows", False)
            overrides.set_editor_property("override_view_distance_scale", False)
            overrides.set_editor_property("use_lod_zero", False)
            overrides.set_editor_property("disable_hlo_ds", False)
            overrides.set_editor_property("override_grass_cull_distance_scale", False)
            overrides.set_editor_property("flush_grass_streaming", True)
            _render = {"status": "running", "directory": str(output), "asset": asset_path, "errors": []}
            excluded = set(excluded_actor_names)

            def hide_gameplay(delta):
                game = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
                if game is not None:
                    for actor in unreal.GameplayStatics.get_all_actors_of_class(game, unreal.Actor):
                        if actor.get_name() in excluded:
                            actor.destroy_actor()
                            continue
                        if isinstance(actor, unreal.Pawn):
                            actor.set_actor_hidden_in_game(True)
                            actor.set_actor_tick_enabled(False)

            def finished(executor, success):
                global _hide_handle
                _render["status"] = "completed" if success else "failed"
                _render["frames"] = len(list(output.glob("*.png")))
                if _hide_handle is not None:
                    unreal.unregister_slate_pre_tick_callback(_hide_handle)
                    _hide_handle = None
                queue.delete_job(job)

            def errored(executor, pipeline, fatal, message):
                _render["errors"].append(str(message))

            _hide_handle = unreal.register_slate_pre_tick_callback(hide_gameplay)
            _executor = unreal.MoviePipelinePIEExecutor()
            _executor.on_executor_finished_delegate.add_callable(finished)
            _executor.on_executor_errored_delegate.add_callable(errored)
            register_activity("cinematic:render", lambda: _render, blocking=True, wait=True)
            subsystem.render_queue_with_executor_instance(_executor)
            return json.dumps(_render)
        except Exception:
            if _hide_handle is not None:
                unreal.unregister_slate_pre_tick_callback(_hide_handle)
                _hide_handle = None
            _render["status"] = "failed"
            queue.delete_job(job)
            import traceback
            unreal.log_error(traceback.format_exc())
            raise

    @mcp_tool
    @staticmethod
    def inspect_render() -> str:
        """/** @return 最近一次原生电影渲染的状态与输出数量 */"""
        return json.dumps(_render)

    @mcp_tool
    @staticmethod
    def create_media_ui_material(asset_path: str, texture_path: str, ink_mask: bool = False, ink_reference: float = 0.75,
                                 uv_offset: list[float] = [0.0, 0.0], uv_scale: list[float] = [1.0, 1.0], replace_existing: bool = False) -> str:
        """
        /**
         * @param asset_path	新建 UI 材质
         * @param texture_path	明确的原始纹理或媒体纹理
         * @param ink_mask	将纹理亮度和透明度作为墨迹覆盖度
         * @param ink_reference	线性采样中完整墨迹的亮度
         * @param uv_offset	采样区域起点
         * @param uv_scale	采样区域尺寸
         * @param replace_existing	明确重建未通过的材质
         * @return 保存与编译后的 UI 材质
         */
        """
        if not 0.01 <= ink_reference <= 1.0:
            raise ValueError("墨迹参考亮度必须在零与一之间")
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path) and not replace_existing:
            raise RuntimeError("目标 UI 材质已存在")
        texture = unreal.load_asset(texture_path)
        if not isinstance(texture, unreal.Texture):
            raise RuntimeError("需要已导入纹理")
        folder, name = asset_path.rsplit("/", 1)
        material = unreal.load_asset(asset_path) if replace_existing else None
        if material is None:
            material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
        if not isinstance(material, unreal.Material):
            raise RuntimeError("目标不是材质")
        unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
        material.set_editor_property("material_domain", unreal.MaterialDomain.MD_UI)
        material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT if ink_mask else unreal.BlendMode.BLEND_OPAQUE)
        library = unreal.MaterialEditingLibrary
        sample = library.create_material_expression(material, unreal.MaterialExpressionTextureSampleParameter2D, -350, 0)
        sample.set_editor_property("texture", texture)
        sample.set_editor_property("parameter_name", "ImageTexture" if ink_mask else "VideoTexture")
        sample.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        connections = []
        if ink_mask:
            coordinates = library.create_material_expression(material, unreal.MaterialExpressionTextureCoordinate, -1000, 0)
            scale = library.create_material_expression(material, unreal.MaterialExpressionConstant2Vector, -1000, 140)
            scale.set_editor_property("r", uv_scale[0])
            scale.set_editor_property("g", uv_scale[1])
            offset = library.create_material_expression(material, unreal.MaterialExpressionConstant2Vector, -800, 220)
            offset.set_editor_property("r", uv_offset[0])
            offset.set_editor_property("g", uv_offset[1])
            multiply = library.create_material_expression(material, unreal.MaterialExpressionMultiply, -800, 0)
            add = library.create_material_expression(material, unreal.MaterialExpressionAdd, -600, 0)
            connections.append(library.connect_material_expressions(coordinates, "", multiply, "A"))
            connections.append(library.connect_material_expressions(scale, "", multiply, "B"))
            connections.append(library.connect_material_expressions(multiply, "", add, "A"))
            connections.append(library.connect_material_expressions(offset, "", add, "B"))
            connections.append(library.connect_material_expressions(add, "", sample, "UVs"))
            white = library.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, -350, 500)
            white.set_editor_property("constant", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
            coefficients = library.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, -350, 300)
            coefficients.set_editor_property("constant", unreal.LinearColor(0.2126, 0.7152, 0.0722, 1.0))
            luminance = library.create_material_expression(material, unreal.MaterialExpressionDotProduct, -100, 100)
            divide = library.create_material_expression(material, unreal.MaterialExpressionDivide, 100, 100)
            divide.set_editor_property("const_b", ink_reference)
            saturate = library.create_material_expression(material, unreal.MaterialExpressionSaturate, 300, 100)
            coverage = library.create_material_expression(material, unreal.MaterialExpressionMultiply, 500, 100)
            connections.append(library.connect_material_expressions(sample, "RGB", luminance, "A"))
            connections.append(library.connect_material_expressions(coefficients, "", luminance, "B"))
            connections.append(library.connect_material_expressions(luminance, "", divide, "A"))
            connections.append(library.connect_material_expressions(divide, "", saturate, ""))
            connections.append(library.connect_material_expressions(saturate, "", coverage, "A"))
            connections.append(library.connect_material_expressions(sample, "A", coverage, "B"))
            connections.append(library.connect_material_property(white, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR))
            connections.append(library.connect_material_property(coverage, "", unreal.MaterialProperty.MP_OPACITY))
        if not ink_mask:
            connections.append(library.connect_material_property(sample, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR))
        if not all(connections):
            raise RuntimeError("UI 材质存在未连接的图节点 禁止保存")
        library.recompile_material(material)
        unreal.EditorAssetLibrary.save_loaded_asset(material)
        return json.dumps({"asset": material.get_path_name(), "domain": "UI", "ink_mask": ink_mask})


_registration = Registration([BBBCinematicToolset])
