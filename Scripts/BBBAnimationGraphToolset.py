import json
import math
import os
import re

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration
from BBBAssetWritePolicy import require_asset_write, require_write_access


@unreal.uclass()
class BBBAnimationGraphToolset(unreal.ToolsetDefinition):
    """
    /**
     * 创建显式时间双通道动画图并配置明确的骨骼表现组件
     */
    """

    @mcp_tool
    @staticmethod
    def create_directional_blend_space(asset_path: str, sequence_paths: list[str], maximum_speed: float) -> str:
        """
        /**
         * 创建待机与四向实际速度二维循环混合资产
         * @param asset_path		不存在的项目资产包
         * @param sequence_paths	待机 前 后 左 右五个同骨架循环
         * @param maximum_speed	两个速度轴的正上限 单位厘米每秒
         * @return 新资产和已保存的样本数量
         */
        """
        if len(sequence_paths) != 5 or not math.isfinite(maximum_speed) or maximum_speed <= 0.0:
            raise RuntimeError("四向混合需要五个序列与有限正速度")

        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("拒绝覆盖已有混合资产")

        require_asset_write([], destinations=[asset_path])
        sequences = [unreal.load_asset(path) for path in sequence_paths]
        if any(not isinstance(value, unreal.AnimSequence) for value in sequences):
            raise RuntimeError("四向动画序列无效")

        factory = unreal.BlendSpaceFactoryNew()
        factory.target_skeleton = sequences[0].get_editor_property("skeleton")
        directory, name = asset_path.rsplit("/", 1)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.BlendSpace, factory)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_directional_blend_space(asset, sequences, maximum_speed):
            raise RuntimeError("四向混合构建失败 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("四向混合保存失败")

        return json.dumps({"asset": asset_path, "samples": 5, "saved": True})

    @mcp_tool
    @staticmethod
    def configure_character_downed_state(asset_path: str, interface_path: str, base_layer_path: str,
                                         entry_path: str, locomotion_path: str, child_layer_paths: list[str],
                                         character_config_path: str) -> str:
        """
        /**
         * 将倒地接入移动状态机和基础继承层 保持统一姿态输出
         * @param asset_path		已独占签出的角色主动画蓝图
         * @param interface_path	已有移动动画层接口
         * @param base_layer_path	已有基础动画层
         * @param entry_path		同骨架倒地入场序列
         * @param locomotion_path	同骨架二维倒地循环
         * @param child_layer_paths	直接继承基础层的装备动画层
         * @param character_config_path	移除旧入场蒙太奇字段后的角色配置
         * @return 编译与保存清单 失败不保存 未生成备份
         */
        """
        blueprint = unreal.load_asset(asset_path)
        interface = unreal.load_asset(interface_path)
        base = unreal.load_asset(base_layer_path)
        entry = unreal.load_asset(entry_path)
        locomotion = unreal.load_asset(locomotion_path)
        children = [unreal.load_asset(path) for path in child_layer_paths]
        config = unreal.load_asset(character_config_path)
        if not all(isinstance(value, unreal.AnimBlueprint) for value in [blueprint, interface, base] + children):
            raise RuntimeError("角色主图 接口或继承动画层类型无效")
        if not isinstance(entry, unreal.AnimSequence) or not isinstance(locomotion, unreal.BlendSpace) or config is None:
            raise RuntimeError("倒地序列 混合或角色配置无效")
        if any(child.get_blueprint_parent_class() != base.generated_class() for child in children):
            raise RuntimeError("装备层必须直接继承基础层")
        sequences = [entry] + [sample.get_editor_property("animation") for sample in locomotion.get_editor_property("sample_data")]
        if len(sequences) != 6 or any(not isinstance(value, unreal.AnimSequence) for value in sequences):
            raise RuntimeError("倒地必须使用入场 待机和四向六个序列")
        targets = [interface, base, blueprint] + children + sequences + [config]
        require_asset_write(targets)
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(value.get_outermost().get_path_name() in dirty for value in targets):
            raise RuntimeError("目标存在未保存编辑 拒绝混入本次构图")
        if unreal.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function(
                interface, "FullBody_DownedState", "InputPose", "None") != 1:
            raise RuntimeError("倒地接口必须是一次新增 不覆盖现有实现")
        for value in [interface, base, blueprint]:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_character_downed_state(blueprint, base, entry, locomotion):
            raise RuntimeError("倒地状态机或继承层构图失败 不保存")
        library = unreal.AnimationLibrary
        curve_type = unreal.RawCurveTrackTypes.RCT_FLOAT
        for animation in sequences:
            for name in ["DisableLegIK", "DisableAimIK", "DisableLHandIK", "DisableLocomotionAdditives"]:
                if name in [str(value) for value in library.get_animation_curve_names(animation, curve_type)]:
                    raise RuntimeError("倒地曲线已存在 拒绝覆盖 " + name)
                library.add_curve(animation, name, curve_type, False)
                library.add_float_curve_key(animation, name, 0.0, 1.0)
                library.add_float_curve_key(animation, name, animation.sequence_length, 1.0)
        for value in [interface, base, blueprint] + children:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
            if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("动画层存在编译错误或警告 不保存 " + value.get_path_name())
        saved = []
        for value in targets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
                raise RuntimeError("保存失败 已保存清单 " + json.dumps(saved))
            saved.append(value.get_path_name())
        return json.dumps({"asset": asset_path, "layer": "FullBody_DownedState", "saved": saved}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_character_rescue_state(asset_path: str, interface_path: str, base_layer_path: str,
                                        animation_path: str, child_layer_paths: list[str],
                                        recovery_blend_seconds: float = 0.5) -> str:
        """
        /**
         * 在既有移动状态机加入帮扶状态 并由基础层提供装备继承姿势
         * @param asset_path		已有角色主动画蓝图
         * @param interface_path	已有移动动画层接口
         * @param base_layer_path	已有基础动画层
         * @param animation_path	同骨架半蹲帮扶循环
         * @param child_layer_paths	直接继承基础层的装备动画层
         * @param recovery_blend_seconds	倒地恢复到正常移动的混合秒数
         * @return 无警告编译和保存清单 不改主图节点布局
         */
        """
        if not math.isfinite(recovery_blend_seconds) or not 0.0 <= recovery_blend_seconds <= 1.0:
            raise RuntimeError("恢复混合秒数无效")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置帮扶状态")
        blueprint = unreal.load_asset(asset_path)
        interface = unreal.load_asset(interface_path)
        base = unreal.load_asset(base_layer_path)
        animation = unreal.load_asset(animation_path)
        children = [unreal.load_asset(path) for path in child_layer_paths]
        if not all(isinstance(value, unreal.AnimBlueprint) for value in [blueprint, interface, base] + children):
            raise RuntimeError("角色主图 接口或继承动画层类型无效")
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError("帮扶循环序列无效")
        if any(child.get_blueprint_parent_class() != base.generated_class() for child in children):
            raise RuntimeError("装备层必须直接继承基础层")
        targets = [interface, base, blueprint] + children + [animation]
        require_asset_write(targets)
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(value.get_outermost().get_path_name() in dirty for value in targets):
            raise RuntimeError("目标存在未保存编辑 拒绝混入本次构图")
        if unreal.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function(
                interface, "FullBody_RescueState", "InputPose", "None") != 1:
            raise RuntimeError("帮扶接口必须是一次新增 不覆盖现有实现")
        for value in [interface, base, blueprint]:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_character_rescue_state(
                blueprint, base, animation, recovery_blend_seconds):
            raise RuntimeError("帮扶状态机或继承层构图失败 不保存")
        library = unreal.AnimationLibrary
        curve_type = unreal.RawCurveTrackTypes.RCT_FLOAT
        for name in ["DisableLegIK", "DisableAimIK", "DisableLHandIK", "DisableLocomotionAdditives"]:
            if name in [str(value) for value in library.get_animation_curve_names(animation, curve_type)]:
                raise RuntimeError("帮扶禁用曲线已存在 拒绝覆盖 " + name)
            library.add_curve(animation, name, curve_type, False)
            library.add_float_curve_key(animation, name, 0.0, 1.0)
            library.add_float_curve_key(animation, name, animation.sequence_length, 1.0)
        for value in [interface, base, blueprint] + children:
            unreal.BlueprintEditorLibrary.compile_blueprint(value)
            if value.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("动画层存在编译错误或警告 不保存 " + value.get_path_name())
        saved = []
        for value in targets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(value, False):
                raise RuntimeError("保存失败 已保存清单 " + json.dumps(saved))
            saved.append(value.get_path_name())
        return json.dumps({"asset": asset_path, "layer": "FullBody_RescueState",
                           "recoveryBlendSeconds": recovery_blend_seconds, "saved": saved}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_mass_scene_population() -> str:
        """
        /**
         * 只读检查当前 PIE 的全部小怪事实 不生成临时展示配置
         * @return 当前实体 生命 移动 爬行与导航诊断
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("群体检查必须位于当前 PIE")

        return unreal.BBBMassValidationLibrary.inspect_population(world, [])

    @mcp_tool
    @staticmethod
    def inspect_mass_variation_network() -> str:
        """
        /**
         * 同时只读检查全部 PIE 世界的当前小怪出生属性
         * @return 各世界实体身份 个体属性和表现诊断 不生成或修改实体
         */
        """
        worlds = list(unreal.EditorLevelLibrary.get_pie_worlds(False))
        if not worlds:
            raise RuntimeError("跨端个体检查必须位于 PIE")
        results = []
        for world in worlds:
            population = json.loads(unreal.BBBMassValidationLibrary.inspect_population(world, []))
            if population.get("error"):
                raise RuntimeError(population["error"])
            results.append({"world": world.get_path_name(), "population": population})
        return json.dumps({"worlds": results, "readOnly": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_fact_stagger_state(asset_path: str, sequence_paths: list[str], blend_duration: float = 0.12) -> str:
        """
        /**
         * 为六行为站立事实图加入一个踉跄状态 保留爬行和死亡
         * @param asset_path\t独占持有的僵尸动画蓝图
         * @param sequence_paths\t头部 左向 右向三个同骨架序列
         * @param blend_duration\t惯性混合秒数
         * @return 无警告编译保存结果
         */
        """
        if len(sequence_paths) != 3 or len(set(sequence_paths)) != 3 or not asset_path.startswith("/Game/_Project/") or not math.isfinite(blend_duration) or not 0.0 < blend_duration <= 0.3:
            raise RuntimeError("踉跄需要项目动画蓝图 三个不同序列和有效混合时间")

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置踉跄状态")

        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if library is None or not hasattr(library, "configure_fact_stagger_state"):
            raise RuntimeError("请先编译踉跄构图能力")

        blueprint = unreal.load_asset(asset_path)
        sequences = [unreal.load_asset(path) for path in sequence_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or any(not isinstance(sequence, unreal.AnimSequence) for sequence in sequences):
            raise RuntimeError("踉跄蓝图或序列无效")

        require_write_access(blueprint)
        if not library.configure_fact_stagger_state(blueprint, sequences, blend_duration):
            raise RuntimeError("踉跄构图失败 不保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("踉跄图未通过无警告编译 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("踉跄图保存失败")

        return json.dumps({"asset": asset_path, "sequences": list(sequence_paths), "state": "Stagger", "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def capture_monster_stagger_samples(actor_blueprint_paths: list[str], hit_region: int, sample_progress: list[float], file_prefix: str) -> str:
        """
        /**
         * 在临时非 Mass 载体上采样正式踉跄蓝图 不修改场景实例或资产
         * @param actor_blueprint_paths\t明确表现蓝图 每批最多十项
         * @param hit_region\t六种命中部位编号
         * @param sample_progress\t踉跄进度 至多三项 一表示结束回移动
         * @param file_prefix\tSaved/temp 下不存在的截图前缀
         * @return 正式蓝图运行图 骨骼位置 截图与临时对象清理结果
         */
        """
        if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("踉跄截图需要渲染宿主")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if world is None or library is None:
            raise RuntimeError("缺少 PIE 世界或原生同步动画求值")

        if not actor_blueprint_paths or len(actor_blueprint_paths) > 10 or len(set(actor_blueprint_paths)) != len(actor_blueprint_paths) or any(not path.startswith("/Game/_Project/") for path in actor_blueprint_paths):
            raise RuntimeError("必须明确一至十个不同项目表现蓝图")

        if hit_region not in range(6) or not sample_progress or len(sample_progress) > 3 or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in sample_progress) or sample_progress != sorted(sample_progress):
            raise RuntimeError("命中部位或有序采样进度无效")

        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
            raise RuntimeError("截图前缀无效")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
        if os.path.exists(directory):
            raise RuntimeError("截图目录已存在 禁止覆盖")

        blueprints = [unreal.load_asset(path) for path in actor_blueprint_paths]
        if any(not isinstance(blueprint, unreal.Blueprint) for blueprint in blueprints):
            raise RuntimeError("表现蓝图不存在")

        regions = [unreal.BBBMonsterHitRegion.TORSO, unreal.BBBMonsterHitRegion.HEAD,
                   unreal.BBBMonsterHitRegion.LEFT_ARM, unreal.BBBMonsterHitRegion.RIGHT_ARM,
                   unreal.BBBMonsterHitRegion.LEFT_LEG, unreal.BBBMonsterHitRegion.RIGHT_LEG]
        spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
        os.makedirs(directory)
        reports = []
        for blueprint in blueprints:
            actors = []
            samples = []
            centers = []
            try:
                for index, progress in enumerate(sample_progress):
                    offset = (index - (len(sample_progress) - 1) * 0.5) * 180.0
                    actor = spawn(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector(0.0, offset, 20090.0), rotation=unreal.Rotator(yaw=180.0)))
                    if actor is None:
                        raise RuntimeError("临时表现载体创建失败")

                    actors.append(actor)
                    mesh = actor.get_monster_mesh()
                    presentation = actor.get_monster_presentation()
                    mesh.set_component_tick_enabled(False)
                    presentation.call_method("ApplyPresentationState", (unreal.BBBMonsterBehavior.CHASE, 180.0, 1.0, 1, 0.0))
                    for frame in range(20):
                        if not library.evaluate_animation_blueprint_frame(mesh, 1.0 / 60.0):
                            raise RuntimeError("初始移动姿势求值失败")

                    presentation.call_method("ApplyStaggerState", (True, min(progress, 0.999), regions[hit_region]))
                    presentation.call_method("ApplyPresentationState", (unreal.BBBMonsterBehavior.CHASE, 0.0, 1.0, 1, 0.0))
                    for frame in range(20):
                        if not library.evaluate_animation_blueprint_frame(mesh, 1.0 / 60.0):
                            raise RuntimeError("踉跄姿势求值失败")

                    if progress >= 1.0:
                        presentation.call_method("ApplyStaggerState", (False, 1.0, regions[hit_region]))
                        presentation.call_method("ApplyPresentationState", (unreal.BBBMonsterBehavior.CHASE, 180.0, 1.0, 1, 0.0))
                        for frame in range(20):
                            if not library.evaluate_animation_blueprint_frame(mesh, 1.0 / 60.0):
                                raise RuntimeError("踉跄结束回移动求值失败")

                    animation = mesh.get_anim_instance()
                    runtime = json.loads(unreal.BBBBlueprintEditorLibrary.probe_animation_instance_runtime(animation))
                    bones = {}
                    for name in ("pelvis", "spine_03", "head", "foot_l", "foot_r"):
                        position = mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation
                        bones[name] = [position.x, position.y, position.z]
                    samples.append({"progress": progress, "animationClass": animation.get_class().get_path_name(), "runtimeGraph": runtime, "bones": bones})
                    centers.append(unreal.SystemLibrary.get_component_bounds(mesh)[0].z)

                light = spawn(world, unreal.PointLight, unreal.Transform(location=unreal.Vector(-220.0, 0.0, max(centers) + 130.0)))
                if light is None:
                    raise RuntimeError("临时补光创建失败")
                actors.append(light)
                component = light.get_component_by_class(unreal.PointLightComponent)
                component.set_intensity(50000.0)
                component.set_attenuation_radius(1600.0)
                camera = spawn(world, unreal.SceneCapture2D, unreal.Transform(location=unreal.Vector(-650.0, 0.0, sum(centers) / len(centers))))
                if camera is None:
                    raise RuntimeError("临时相机创建失败")
                actors.append(camera)
                target = unreal.RenderingLibrary.create_render_target2d(world, 960, 540, unreal.TextureRenderTargetFormat.RTF_RGBA8)
                capture = camera.capture_component2d
                capture.set_editor_property("texture_target", target)
                capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
                capture.set_editor_property("capture_every_frame", False)
                capture.set_editor_property("capture_on_movement", False)
                capture.set_editor_property("fov_angle", 55.0)
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
                filename = blueprint.get_name() + ".png"
                image_path = os.path.join(directory, filename)
                unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                if not os.path.isfile(image_path) or os.path.getsize(image_path) < 1024:
                    raise RuntimeError("踉跄截图导出失败")
                reports.append({"actorBlueprint": blueprint.get_path_name(), "imagePath": image_path, "samples": samples})
            finally:
                for actor in reversed(actors):
                    actor.destroy_actor()

        unreal.log("[BBBMonsterStaggerCapture] Completed=" + str(len(reports)))
        return json.dumps({"captures": reports, "temporaryActorsDestroyed": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_fact_crawl_states(asset_path: str, sequence_paths: list[str], blend_duration: float = 0.18) -> str:
        """
        /**
         * 为当前事实图配置持续爬行的六种姿势 不创建玩法状态
         * @param asset_path\t\t独占持有的事实动画蓝图
         * @param sequence_paths\t\t倒地 待机 警觉 移动 攻击 死亡六个序列
         * @param blend_duration\t\t姿势切换秒数
         * @return 无警告编译与保存结果
         */
        """
        if len(sequence_paths) != 6 or not math.isfinite(blend_duration) or not 0.0 < blend_duration <= 0.5:
            raise RuntimeError("爬行必须使用六个明确序列与有效混合时间")

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置爬行姿势")

        blueprint = unreal.load_asset(asset_path)
        sequences = [unreal.load_asset(path) for path in sequence_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or any(not isinstance(sequence, unreal.AnimSequence) for sequence in sequences):
            raise RuntimeError("爬行动画蓝图或序列无效")

        require_write_access(blueprint)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states(blueprint, sequences, blend_duration):
            raise RuntimeError("爬行构图失败 不保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("爬行图编译未通过 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("爬行图保存失败")

        return json.dumps({"asset": asset_path, "sequences": list(sequence_paths), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def audit_animation_tracks(asset_paths: list[str], bone_names: list[str], file_prefix: str) -> str:
        """
        /**
         * 审查明确动画的全部根骨关键帧与局部骨骼首末接缝并保存原始摘要
         * @param asset_paths		实际动画路径
         * @param bone_names		局部接缝检查骨骼
         * @param file_prefix		不存在的诊断文件前缀
         * @return 各动画全帧根位移 旋转 缩放和局部循环接缝
         */
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix) or not asset_paths or len(asset_paths) > 64:
            raise RuntimeError("诊断前缀或数量无效")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", "AnimationAudits"))
        path = os.path.join(directory, file_prefix + ".json")
        if os.path.exists(path):
            raise RuntimeError("诊断文件存在 禁止覆盖")

        def angle(rotation):
            return math.degrees(2.0 * math.acos(min(1.0, abs(float(rotation.w)))))

        reports = []
        for asset_path in asset_paths:
            animation = unreal.load_asset(asset_path)
            if not isinstance(animation, unreal.AnimSequence):
                raise RuntimeError("明确动画无效: " + asset_path)

            tracks = {str(name).lower(): name for name in animation.data_model_interface.get_bone_track_names()}
            if "root" not in tracks:
                raise RuntimeError("动画缺少根轨道: " + asset_path)

            root = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, tracks["root"])
            if not root:
                raise RuntimeError("无法读取完整根轨道: " + asset_path)

            maximum_translation = max(math.sqrt(key.translation.x ** 2 + key.translation.y ** 2 + key.translation.z ** 2) for key in root)
            maximum_rotation = max(angle(key.rotation) for key in root)
            maximum_scale = max(max(abs(key.scale3d.x - 1.0), abs(key.scale3d.y - 1.0), abs(key.scale3d.z - 1.0)) for key in root)
            seams = {}
            for bone in bone_names:
                actual = tracks.get(bone.lower())
                if actual is None:
                    raise RuntimeError("动画缺少明确接缝骨骼: " + bone)
                keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, actual)
                first, last = keys[0], keys[-1]
                delta = first.translation - last.translation
                first_rotation = first.rotation
                last_rotation = last.rotation
                rotation_dot = first_rotation.x * last_rotation.x + first_rotation.y * last_rotation.y + first_rotation.z * last_rotation.z + first_rotation.w * last_rotation.w
                rotation_delta = math.degrees(2.0 * math.acos(min(1.0, abs(rotation_dot))))
                seams[bone] = {"translationCm": math.sqrt(delta.x ** 2 + delta.y ** 2 + delta.z ** 2), "rotationDegrees": rotation_delta, "keys": len(keys)}

            reports.append({"asset": asset_path, "keysAudited": len(root), "length": animation.get_play_length(), "rootMaxTranslationCm": maximum_translation, "rootMaxRotationDegrees": maximum_rotation, "rootMaxScaleDeviation": maximum_scale, "inPlacePassed": maximum_translation < 0.001 and maximum_rotation < 0.001 and maximum_scale < 0.001, "localSeams": seams})

        os.makedirs(directory, exist_ok=True)
        report = {"path": path, "animations": reports, "allInPlacePassed": all(item["inPlacePassed"] for item in reports), "readOnly": True}
        with open(path, "w", encoding="utf-8") as destination:
            json.dump(report, destination, ensure_ascii=False, indent=2)
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def prepare_in_place_cycles(asset_paths: list[str], compression_reference_path: str) -> str:
        """
        /**
         * 将明确循环序列根轨道归零 并平滑骨盆尾段接缝
         * @param asset_paths		已独占持有的项目循环动画
         * @param compression_reference_path	同骨架已验证压缩配置来源
         * @return 保存与根轨道接缝复核结果
         */
        """
        if not asset_paths or len(asset_paths) > 16 or len(set(asset_paths)) != len(asset_paths) or any(not path.startswith("/Game/_Project/") for path in asset_paths):
            raise RuntimeError("循环动画清单无效")
        sequences = [unreal.load_asset(path) for path in asset_paths]
        reference = unreal.load_asset(compression_reference_path)
        if not isinstance(reference, unreal.AnimSequence) or any(not isinstance(value, unreal.AnimSequence) or value.get_editor_property("skeleton") != reference.get_editor_property("skeleton") for value in sequences):
            raise RuntimeError("循环动画与压缩来源类型或骨架不一致")
        require_asset_write(sequences)
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(value.get_outermost().get_path_name() in dirty for value in sequences):
            raise RuntimeError("循环动画有未保存编辑")
        results = []
        for sequence in sequences:
            root = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(sequence, "root"))
            pelvis = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(sequence, "pelvis"))
            if len(root) < 2 or len(pelvis) < 4:
                raise RuntimeError("循环根轨道或骨盆轨道不完整")
            controller = sequence.controller
            controller.open_bracket("Prepare project in-place cycle", False)
            if not controller.set_bone_track_keys("root", [unreal.Vector(0, 0, 0)] * len(root), [unreal.Quat(0, 0, 0, 1)] * len(root), [unreal.Vector(1, 1, 1)] * len(root), False):
                controller.close_bracket(False)
                raise RuntimeError("根轨道写入失败 不保存")
            positions = [key.translation for key in pelvis]
            rotations = [key.rotation for key in pelvis]
            scales = [key.scale3d for key in pelvis]
            correction = positions[0] - positions[-1]
            tail = max(2, min(8, len(pelvis) // 4))
            for offset in range(tail):
                fraction = float(offset + 1) / tail
                weight = fraction * fraction * (3.0 - 2.0 * fraction)
                index = len(positions) - tail + offset
                positions[index] = positions[index] + correction * weight
            rotations[-1] = rotations[0]
            scales[-1] = scales[0]
            success = controller.set_bone_track_keys("pelvis", positions, rotations, scales, False)
            controller.close_bracket(False)
            if not success:
                raise RuntimeError("骨盆循环写入失败 不保存")
            sequence.set_editor_property("enable_root_motion", False)
            sequence.set_editor_property("force_root_lock", True)
            for name in ["bone_compression_settings", "curve_compression_settings"]:
                sequence.set_editor_property(name, reference.get_editor_property(name))
            if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
                raise RuntimeError("循环动画保存失败 " + sequence.get_path_name())
            keys = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(sequence, "root"))
            if any(key.translation.length() > 0.001 for key in keys):
                raise RuntimeError("归零根轨道回读失败")
            results.append({"asset": sequence.get_path_name(), "pelvisCorrectionCm": correction.length(), "keys": len(keys)})
        return json.dumps({"saved": results}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_mass_presentation_variant(source_actor_path: str, source_definition_path: str, source_config_path: str, mesh_path: str, destination_root: str, variant_name: str) -> str:
        """
        /**
         * 为正式合并网格创建独立表现蓝图 定义与实体模板
         * @param source_actor_path		已验证的预算载体蓝图
         * @param source_definition_path		同类正式静态定义
         * @param source_config_path		同类正式实体模板
         * @param mesh_path		已保存的完整合并网格
         * @param destination_root		不存在变体资产的自有目录
         * @param variant_name		稳定英文外观名称
         * @return 三个资产路径及明确互相引用
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建正式变体配置")

        if not destination_root.startswith("/Game/_Project/") or not variant_name.isascii() or not variant_name.isalnum():
            raise RuntimeError("变体目录或名称无效")

        mesh = unreal.load_asset(mesh_path)
        source_actor = unreal.load_asset(source_actor_path)
        source_definition = unreal.load_asset(source_definition_path)
        source_config = unreal.load_asset(source_config_path)
        if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(source_actor, unreal.Blueprint) or not isinstance(source_config, unreal.MassEntityConfigAsset) or source_definition is None:
            raise RuntimeError("源配置或完整网格无效")

        names = ["BP_BBBZombie" + variant_name + "Presentation", "DA_BBBZombie" + variant_name + "Definition", "MEC_BBBZombie" + variant_name]
        paths = [destination_root + "/" + name for name in names]
        if any(unreal.EditorAssetLibrary.does_asset_exist(path) for path in paths):
            raise RuntimeError("变体资产已存在 禁止覆盖")

        assets = []
        for name, source in zip(names, (source_actor, source_definition, source_config)):
            asset = unreal.AssetToolsHelpers.get_asset_tools().duplicate_asset(name, destination_root, source)
            if asset is None:
                raise RuntimeError("变体复制失败 保留未完成资产供诊断")
            assets.append(asset)

        actor, definition, config = assets
        actor_mesh = unreal.get_default_object(actor.generated_class()).get_monster_mesh()
        if actor_mesh.get_skeletal_mesh_asset().get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
            raise RuntimeError("变体网格与动画骨架不一致 不保存")

        actor_mesh.set_skeletal_mesh_asset(mesh)
        unreal.BlueprintEditorLibrary.compile_blueprint(actor)
        if actor.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("变体载体编译未通过 不保存")

        if unreal.get_default_object(actor.generated_class()).get_monster_mesh().get_skeletal_mesh_asset() != mesh:
            raise RuntimeError("编译后的变体网格引用不一致 不保存")

        definition.set_editor_property("entity_config", config)
        traits = config.get_editor_property("config").get_editor_property("traits")
        definition_links = 0
        visualization_links = 0
        for trait in traits:
            if isinstance(trait, unreal.BBBMonsterTrait):
                trait.set_editor_property("definition", definition)
                definition_links += 1
            if isinstance(trait, unreal.MassVisualizationTrait):
                trait.set_editor_property("high_res_template_actor", actor.generated_class())
                trait.set_editor_property("low_res_template_actor", actor.generated_class())
                visualization_links += 1

        if definition_links != 1 or visualization_links != 1:
            raise RuntimeError("变体模板必须有一个小怪配置与一个表现装配 不保存")

        for asset in assets:
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError("变体资产保存失败")

        return json.dumps({"actor": paths[0], "definition": paths[1], "entityConfig": paths[2], "mesh": mesh_path, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_merged_skeletal_asset(asset_path: str, part_paths: list[str]) -> str:
        """
        /**
         * 用模块导入数据创建三层 LOD 的正式合并网格 不保存运行时临时合并结果
         * @param asset_path		不存在的自有资产路径
         * @param part_paths		同骨架头部 身体 服装模块
         * @return 原生构建验证与保存结果
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止生成正式合并资产")

        if not asset_path.startswith("/Game/_Project/") or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("合并目标必须为不存在的自有资产")

        parts = [unreal.load_asset(path) for path in part_paths]
        if len(parts) < 2 or any(not isinstance(part, unreal.SkeletalMesh) for part in parts):
            raise RuntimeError("模块必须是明确有效的骨骼网格")

        mesh = unreal.BBBAnimationGraphEditorLibrary.create_merged_skeletal_asset(asset_path, parts)
        if mesh is None:
            raise RuntimeError("导入几何 蒙皮或 LOD 构建失败 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(mesh, False):
            raise RuntimeError("正式合并网格保存失败")

        return json.dumps({"asset": mesh.get_path_name(), "parts": list(part_paths), "sourceMeshDescription": True, "lodCount": 3, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_fact_action_variants(asset_path: str, variant_paths: list[str], counts: list[int], progress_pivots: list[float], sample_pivots: list[float], progress_ends: list[float], blend_duration: float = 0.16) -> str:
        """
        /**
         * 为现有事实状态机配置线程安全动作变体及同状态惯性重启
         * @param asset_path		独占持有的动画蓝图
         * @param variant_paths		按攻击 死亡分组的序列路径
         * @param counts		各分组数量
         * @param blend_duration		重启过渡秒数
         * @return 严格编译保存结果
         */
        """
        if len(counts) != 2 or any(count < 1 for count in counts) or sum(counts) != len(variant_paths):
            raise RuntimeError("动作变体必须明确分为攻击 死亡两个非空组")

        if any(len(values) != len(variant_paths) for values in (progress_pivots, sample_pivots, progress_ends)):
            raise RuntimeError("时间锚点必须与全部动作变体一一对应")

        for pivot, sample, end in zip(progress_pivots, sample_pivots, progress_ends):
            if not all(math.isfinite(value) for value in (pivot, sample, end)) or not 0.0 < pivot < end <= 1.0 or not 0.0 < sample < 1.0:
                raise RuntimeError("动作时间锚点无效")

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置动作变体")

        blueprint = unreal.load_asset(asset_path)
        sequences = [unreal.load_asset(path) for path in variant_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or any(not isinstance(sequence, unreal.AnimSequence) for sequence in sequences):
            raise RuntimeError("动画蓝图或序列无效")

        require_write_access(blueprint)

        if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_action_variants(blueprint, sequences, counts, progress_pivots, sample_pivots, progress_ends, blend_duration):
            raise RuntimeError("变体构图失败 不保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("变体图未无警告编译通过 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("变体动画蓝图保存失败")

        return json.dumps({"asset": asset_path, "variants": list(variant_paths), "counts": list(counts), "progressPivots": list(progress_pivots), "samplePivots": list(sample_pivots), "progressEnds": list(progress_ends), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_fact_locomotion_variants(asset_path: str, idle_paths: list[str], alert_paths: list[str], stationary_speed: float = 3.0, blend_duration: float = 0.18) -> str:
        """
        /**
         * 在事实移动状态中配置身份选择待机 搜索与稳定起点错相
         * @param asset_path		独占持有的事实动画蓝图
         * @param idle_paths		同骨架循环待机序列
         * @param scout_paths		同骨架循环搜索序列
         * @param stationary_speed		静止判定厘米每秒上限
         * @param blend_duration		静止搜索过渡秒数
         * @return 严格编译与保存结果
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置移动变体")

        blueprint = unreal.load_asset(asset_path)
        idle = [unreal.load_asset(path) for path in idle_paths]
        alert = [unreal.load_asset(path) for path in alert_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or any(not isinstance(sequence, unreal.AnimSequence) for sequence in idle + alert):
            raise RuntimeError("动画蓝图或静止序列无效")

        require_write_access(blueprint)
        if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_locomotion_variants(blueprint, idle, alert, stationary_speed, blend_duration):
            raise RuntimeError("静止搜索构图失败 不保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("静止搜索图未无警告编译通过 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("静止搜索动画蓝图保存失败")

        return json.dumps({"asset": asset_path, "idle": list(idle_paths), "alert": list(alert_paths), "continuousEntityPhase": True, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_fact_movement_styles(asset_path: str, style_paths: list[str], blend_duration: float = 0.18) -> str:
        """
        /**
         * 以实体固定风格与连续相位重建巡逻追击 只采样一个移动分支
         * @param asset_path		独占持有的事实动画蓝图
         * @param style_paths		三个同骨架一维实际速度混合资产
         * @param blend_duration	姿势过渡秒数
         * @return 无警告编译与保存结果
         */
        """
        if len(style_paths) != 3 or len(set(style_paths)) != 3 or not math.isfinite(blend_duration) or not 0.0 < blend_duration <= 0.3:
            raise RuntimeError("移动风格必须是三个不同资产且过渡时间有效")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止配置移动风格")
        blueprint = unreal.load_asset(asset_path)
        styles = [unreal.load_asset(path) for path in style_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or any(not isinstance(value, unreal.BlendSpace1D) for value in styles):
            raise RuntimeError("动画蓝图或一维移动混合类型无效")
        require_write_access(blueprint)
        dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if blueprint.get_outermost().get_path_name() in dirty:
            raise RuntimeError("目标有未保存编辑 拒绝混入")
        if not unreal.BBBAnimationGraphEditorLibrary.configure_fact_movement_styles(blueprint, styles, blend_duration):
            raise RuntimeError("移动风格构图失败 不保存")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("移动风格图未无警告编译通过 不保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("移动风格动画蓝图保存失败")
        return json.dumps({"asset": asset_path, "styles": list(style_paths), "continuousEntityPhase": True, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def reparent_presentation_blueprint(asset_path: str, parent_class_path: str) -> str:
        """
        /**
         * 将独占持有的表现载体蓝图改为明确的原生父类并核验网格
         * @param asset_path		表现载体蓝图路径
         * @param parent_class_path		原生表现载体父类路径
         * @return 保存结果及实际默认网格类型
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改载体父类")

        blueprint = unreal.load_asset(asset_path)
        parent = unreal.load_class(None, parent_class_path)
        if not isinstance(blueprint, unreal.Blueprint) or parent is None or not hasattr(unreal.get_default_object(parent), "get_monster_mesh"):
            raise RuntimeError("蓝图或表现载体父类无效")

        require_write_access(blueprint)

        unreal.BlueprintEditorLibrary.reparent_blueprint(blueprint, parent)
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("载体未无警告编译通过 不保存")

        mesh = unreal.get_default_object(blueprint.generated_class()).get_monster_mesh()
        expected = unreal.get_default_object(parent).get_monster_mesh().get_class()
        if mesh is None or mesh.get_class() != expected:
            raise RuntimeError("继承网格实际类型不匹配 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("载体保存失败")

        return json.dumps({"asset": asset_path, "parent": parent_class_path, "mesh_class": mesh.get_class().get_path_name(), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_speed_blend_space(asset_path: str, sequence_paths: list[str], speeds: list[float], smoothing_time: float = 0.12) -> str:
        """
        /**
         * 创建具有速度轴平滑的同骨架一维循环混合资产
         * @param asset_path		不存在的新混合资产路径
         * @param sequence_paths		按速度排序的序列
         * @param speeds		对应厘米每秒速度 首项为零
         * @param smoothing_time		速度轴平滑秒数
         * @return 保存路径及实际样本配置 新资产仍须登记版本控制
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建混合资产")

        if not asset_path.startswith("/Game/") or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("目标必须为不存在的项目路径")

        sequences = [unreal.load_asset(path) for path in sequence_paths]
        if len(sequences) < 2 or len(sequences) != len(speeds) or any(not isinstance(sequence, unreal.AnimSequence) for sequence in sequences):
            raise RuntimeError("动画与速度样本无效")

        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if library is None or not hasattr(library, "configure_speed_blend_space"):
            raise RuntimeError("请先编译速度混合构图能力")

        factory = unreal.BlendSpaceFactory1D()
        factory.set_editor_property("target_skeleton", sequences[0].get_editor_property("skeleton"))
        directory, name = asset_path.rsplit("/", 1)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.BlendSpace1D, factory)
        if not library.configure_speed_blend_space(asset, sequences, speeds, smoothing_time):
            raise RuntimeError("速度混合配置失败 尚未保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("速度混合保存失败")

        return json.dumps({"asset": asset_path, "sequences": list(sequence_paths), "speeds": list(speeds), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def rebuild_fact_driven_state_machine(asset_path: str, locomotion_path: str, action_paths: list[str], fact_properties: list[str], action_values: list[int], blend_duration: float = 0.18, parent_class_path: str = "") -> str:
        """
        /**
         * 在独占持有的动画蓝图上干净重建六行为事实状态机
         * @param asset_path		目标动画蓝图
         * @param locomotion_path		同骨架移动混合资产
         * @param action_paths		攻击 死亡序列
         * @param fact_properties		行为 速度 进度只读属性
         * @param action_values		递增动作枚举值
         * @param blend_duration		状态过渡秒数
         * @param parent_class_path		可选事实动画父类 迁移时明确指定
         * @return 编译 保存和实际状态机结构 未成功不得作为验收通过
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止重建动画图")

        if len(action_paths) != 2 or list(action_values) != [4, 5] or len(fact_properties) != 3:
            raise RuntimeError("六行为图只接受攻击 死亡两个动作及枚举值四 五")

        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if library is None or not hasattr(library, "build_fact_driven_state_machine_graph"):
            raise RuntimeError("请先编译事实状态机构图能力")

        blueprint = unreal.load_asset(asset_path)
        locomotion = unreal.load_asset(locomotion_path)
        actions = [unreal.load_asset(path) for path in action_paths]
        if not isinstance(blueprint, unreal.AnimBlueprint) or not isinstance(locomotion, unreal.BlendSpace):
            raise RuntimeError("动画蓝图或移动混合资产无效")

        if len(actions) != 2 or any(not isinstance(action, unreal.AnimSequence) for action in actions):
            raise RuntimeError("必须指定攻击 死亡两个有效动作序列")

        require_write_access(blueprint)

        if parent_class_path:
            parent = unreal.load_class(None, parent_class_path)
            if parent is None or not isinstance(unreal.get_default_object(parent), unreal.AnimInstance):
                raise RuntimeError("父类必须为有效动画实例")

            for name in fact_properties:
                unreal.get_default_object(parent).get_editor_property(name)

            unreal.BlueprintEditorLibrary.reparent_blueprint(blueprint, parent)

        if not library.build_fact_driven_state_machine_graph(blueprint, locomotion, actions, [unreal.Name(name) for name in fact_properties], action_values, blend_duration):
            raise RuntimeError("状态机构图失败 尚未保存 请保留诊断现场")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("状态机尚未无警告编译通过 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")

        unreal.log("[BBBAnimationGraph] FACT_STATE_MACHINE_SAVED " + asset_path)
        return json.dumps({"asset": asset_path, "actions": list(action_paths), "locomotion": locomotion_path, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def rebuild_sequence_crossfade_blueprint(asset_path: str, preview_animation_path: str, getter_names: list[str]) -> str:
        """
        /**
         * 将本工具生成的事实图还原为标准显式双通道图 不接收任意手工图
         * @param asset_path		已备份且独占持有的动画蓝图
         * @param preview_animation_path	同骨架预览序列
         * @param getter_names		六个原有只读查询
         * @return 严格编译和保存结果
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止重建动画蓝图")

        blueprint = unreal.load_asset(asset_path)
        animation = unreal.load_asset(preview_animation_path)
        if not isinstance(blueprint, unreal.AnimBlueprint) or not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError("动画蓝图或预览序列无效")

        require_write_access(blueprint)

        if not unreal.BBBAnimationGraphEditorLibrary.build_sequence_crossfade_graph(blueprint, animation, [unreal.Name(name) for name in getter_names]):
            raise RuntimeError("图表结构不允许还原 尚未保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("还原图未无警告编译通过 不保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("还原动画蓝图保存失败")

        return json.dumps({"asset": asset_path, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_sequence_crossfade_blueprint(asset_path: str, parent_class_path: str, mesh_path: str, preview_animation_path: str, getter_names: list[str]) -> str:
        """
        /**
         * 创建新动画蓝图 连接标准序列求值器及布尔姿势混合并严格编译保存
         * @param asset_path			不存在的新资产路径
         * @param parent_class_path		提供线程安全查询的动画实例类
         * @param mesh_path			同骨架预览网格
         * @param preview_animation_path		同骨架预览动画
         * @param getter_names			甲乙序列 甲乙时间 乙启用 混合时间六个查询名
         * @return 新蓝图路径 生成类与编译状态
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建动画蓝图")

        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if library is None:
            raise RuntimeError("缺少原生动画图创建能力 请先编译项目编辑器模块")

        if not asset_path.startswith("/Game/") or "." in asset_path or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("目标必须为不存在的项目资产路径")

        mesh = unreal.load_asset(mesh_path)
        animation = unreal.load_asset(preview_animation_path)
        parent = unreal.load_class(None, parent_class_path)
        if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(animation, unreal.AnimSequence) or parent is None:
            raise RuntimeError("网格 预览动画或动画父类无效")

        skeleton = mesh.get_editor_property("skeleton")
        if skeleton != animation.get_editor_property("skeleton") or len(getter_names) != 6:
            raise RuntimeError("必须使用同骨架动画及六个查询")

        factory = unreal.AnimBlueprintFactory()
        factory.set_editor_property("parent_class", parent)
        factory.set_editor_property("target_skeleton", skeleton)
        factory.set_editor_property("preview_skeletal_mesh", mesh)
        directory, name = asset_path.rsplit("/", 1)
        blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.AnimBlueprint, factory)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图创建失败")

        if not library.build_sequence_crossfade_graph(blueprint, animation, [unreal.Name(name) for name in getter_names]):
            raise RuntimeError("动画图连接失败 尚未保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        status = blueprint.get_editor_property("status")
        if status != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图必须无警告编译通过 尚未保存: " + str(status))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")

        unreal.log("[BBBAnimationGraph] SAVED " + asset_path)
        return json.dumps({"asset": blueprint.get_path_name(), "generatedClass": blueprint.generated_class().get_path_name(), "status": str(status), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_actor_animation_blueprint(actor_blueprint_path: str, mesh_component_property: str, animation_blueprint_path: str) -> str:
        """
        /**
         * 在独占签出的演员蓝图默认骨骼组件上配置同骨架动画蓝图
         * @param actor_blueprint_path		明确演员蓝图
         * @param mesh_component_property		持有骨骼组件的默认对象属性
         * @param animation_blueprint_path		已编译的同骨架动画蓝图
         * @return 保存后回读的动画类与播放模式
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改演员蓝图")

        blueprint = unreal.load_asset(actor_blueprint_path)
        animation = unreal.load_asset(animation_blueprint_path)
        if not isinstance(blueprint, unreal.Blueprint) or not isinstance(animation, unreal.AnimBlueprint):
            raise RuntimeError("演员或动画蓝图无效")

        require_write_access(blueprint)

        component = unreal.get_default_object(blueprint.generated_class()).get_editor_property(mesh_component_property)
        if not isinstance(component, unreal.SkeletalMeshComponent):
            raise RuntimeError("指定属性不是骨骼网格组件")

        mesh = component.get_editor_property("skeletal_mesh_asset")
        if mesh is None or mesh.get_editor_property("skeleton") != animation.get_editor_property("target_skeleton"):
            raise RuntimeError("演员网格与动画蓝图骨架不一致")

        if animation.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图尚未无警告编译通过")

        blueprint.modify()
        component.modify()
        component.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_BLUEPRINT)
        component.set_editor_property("anim_class", animation.generated_class())
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("演员蓝图编译失败或存在警告 尚未保存")

        component = unreal.get_default_object(blueprint.generated_class()).get_editor_property(mesh_component_property)
        if component.get_editor_property("anim_class") != animation.generated_class():
            raise RuntimeError("编译后动画类回读失败 尚未保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("演员蓝图保存失败")

        unreal.log("[BBBAnimationGraph] BOUND " + actor_blueprint_path)
        return json.dumps({"asset": blueprint.get_path_name(), "component": component.get_path_name(), "animationClass": component.get_editor_property("anim_class").get_path_name(), "animationMode": str(component.get_editor_property("animation_mode")), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def bind_sequence_crossfade_getters(asset_path: str, getter_names: list[str]) -> str:
        """
        /**
         * 将标准双通道动画图输入连接到只读纯函数并编译保存
         * @param asset_path		明确独占签出或待添加的标准动画蓝图
         * @param getter_names		六个快照查询名称
         * @return 编译和保存结果
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改动画图")

        blueprint = unreal.load_asset(asset_path)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图不存在")

        require_write_access(blueprint)

        if not unreal.BBBAnimationGraphEditorLibrary.bind_sequence_crossfade_getters(blueprint, [unreal.Name(name) for name in getter_names]):
            raise RuntimeError("图表结构或快照查询不符合要求 尚未保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画图未无警告编译通过 尚未保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")

        return json.dumps({"asset": blueprint.get_path_name(), "saved": True}, ensure_ascii=False)


_registration = Registration([BBBAnimationGraphToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        """
        /**
         * 在当前调用结束后的编辑器帧重新注册工具类
         * @param delta_seconds	编辑器帧间隔
         * @return 无返回值
         */
        """
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
