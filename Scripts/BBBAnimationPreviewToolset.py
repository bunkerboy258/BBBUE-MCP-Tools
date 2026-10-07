import json
import os
import re
import uuid
import time
import csv

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


_transition_captures = {}
_population_runs = {}
_inspection_population = {}


@unreal.uclass()
class BBBAnimationPreviewToolset(unreal.ToolsetDefinition):
    """
    /**
     * 在临时对象上渲染明确动画的多个采样姿势 不修改源资产
     */
    """

    @mcp_tool
    @staticmethod
    def spawn_mass_inspection_population(config_paths: list[str], center: list[float], spacing: float, expected_level: str) -> str:
        """
        /**
         * 在明确关卡的 PIE 中生成每种配置一个真实实体 不修改或保存资产
         * @param config_paths		互不重复的实体配置 至多十六种
         * @param center		出生网格中心 三个厘米坐标 包含离地高度
         * @param spacing		网格间距 厘米 至少二百
         * @param expected_level		完整关卡包路径 必须与当前 PIE 关卡一致
         * @return 完整实体句柄的实际数量与快照
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("检查展示必须在 PIE 中运行")

        actual_level = re.sub(r"UEDPIE_\d+_", "", world.get_path_name().split(".")[0])
        if actual_level != expected_level or "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("当前关卡或渲染宿主与请求不一致")

        if len(center) != 3 or spacing < 200.0 or not config_paths or len(config_paths) > 16 or len(set(config_paths)) != len(config_paths):
            raise RuntimeError("出生参数无效或实体配置重复")

        if _inspection_population.get("worldIdentity") == hash(world):
            raise RuntimeError("本 PIE 已创建检查群体 禁止重复生成")

        if any(item.get("status") == "running" for item in _population_runs.values()):
            raise RuntimeError("群体性能测量期间禁止创建检查群体")

        mass = getattr(unreal, "BBBMassValidationLibrary", None)
        configs = [unreal.load_asset(path) for path in config_paths]
        if mass is None or any(not isinstance(config, unreal.MassEntityConfigAsset) for config in configs):
            raise RuntimeError("原生实体能力或配置无效")

        configs = [mass.create_actor_stress_config(world, config) for config in configs]
        if any(config is None for config in configs):
            raise RuntimeError("临时全骨骼检查配置创建失败")

        entities = []
        try:
            for index, config in enumerate(configs):
                position = unreal.Vector(center[0] + spacing * 0.5, center[1] + (index - (len(configs) - 1) * 0.5) * spacing + spacing * 0.5, center[2])
                entities.extend(mass.spawn_population(world, [config], 1, position, spacing))

            if len(entities) != len(configs):
                raise RuntimeError("检查群体实际数量与配置数量不一致")
        except Exception:
            mass.destroy_population(world, entities)
            raise

        _inspection_population.clear()
        _inspection_population.update({"world": world.get_path_name(), "worldIdentity": hash(world), "configs": configs, "entities": entities, "configPaths": list(config_paths)})
        unreal.log("Mass 检查群体已生成 数量=" + str(len(entities)) + " 关卡=" + actual_level)
        return mass.inspect_population(world, entities)

    @mcp_tool
    @staticmethod
    def inspect_mass_inspection_population(pause_game: bool = False) -> str:
        """
        /**
         * 回读本工具检查群体 可暂停游戏供用户观察 不操作其它实体
         * @param pause_game		是否暂停当前检查 PIE 用户可点击继续恢复
         * @return 实际群体快照 暂停操作失败时明确报错
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or _inspection_population.get("worldIdentity") != hash(world):
            raise RuntimeError("检查群体所在 PIE 已结束或尚未生成")

        if pause_game and not unreal.GameplayStatics.set_game_paused(world, True):
            raise RuntimeError("当前 PIE 暂停失败")

        return unreal.BBBMassValidationLibrary.inspect_population(world, _inspection_population["entities"])

    @mcp_tool
    @staticmethod
    def start_mass_population_benchmark(config_paths: list[str], counts: list[int], center: list[float], spacing: float, expected_level: str, file_prefix: str, warmup_seconds: float = 5.0, measurement_seconds: float = 10.0, force_actor_representation: bool = False) -> str:
        """
        /**
         * 在明确验收关卡的真实 PIE Mass 实体上依次测量预算关闭与开启
         * @param config_paths		实际实体配置路径
         * @param counts		递增数量 每项至多一千
         * @param center		网格出生中心 三个厘米坐标
         * @param spacing		实体出生间距 厘米
         * @param expected_level		明确的验收关卡短名 必须包含 Validation
         * @param file_prefix		唯一诊断文件前缀
         * @param warmup_seconds		每组预热秒数 至少五秒
         * @param measurement_seconds		每组测量秒数 至少十秒
         * @param force_actor_representation		使用临时全骨骼压力配置 不改正式模板
         * @return 异步运行标识 测量完成后回读结果 原始数据始终落盘
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or "Validation" not in expected_level or expected_level not in world.get_path_name():
            raise RuntimeError("必须在明确指定的验收关卡 PIE 中测量")

        if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("群体性能验收必须使用正常渲染宿主")

        if len(center) != 3 or not counts or len(counts) > 4 or counts != sorted(set(counts)) or any(value < 1 or value > 1000 for value in counts):
            raise RuntimeError("群体数量或中心无效")

        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix) or warmup_seconds < 5.0 or measurement_seconds < 10.0:
            raise RuntimeError("文件前缀或测量时长无效")

        if any(item.get("status") == "running" for item in _population_runs.values()):
            raise RuntimeError("已有群体测量正在运行")

        configs = [unreal.load_asset(path) for path in config_paths]
        if not configs or any(not isinstance(config, unreal.MassEntityConfigAsset) for config in configs):
            raise RuntimeError("实体配置无效")

        mass = getattr(unreal, "BBBMassValidationLibrary", None)
        metrics = getattr(unreal.BBBAnimationGraphEditorLibrary, "read_performance_frame_metrics", None)
        if mass is None or metrics is None:
            raise RuntimeError("请先编译群体验收原生能力")

        if force_actor_representation:
            configs = [mass.create_actor_stress_config(world, config) for config in configs]
            if any(config is None for config in configs):
                raise RuntimeError("全骨骼压力配置创建失败")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
        os.makedirs(directory, exist_ok=True)
        result_path = os.path.join(directory, file_prefix + ".json")
        csv_path = os.path.join(directory, file_prefix + ".csv")
        if os.path.exists(result_path) or os.path.exists(csv_path):
            raise RuntimeError("诊断文件已存在 请使用新前缀")

        for spawner in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.MassSpawner):
            spawner.do_despawning()

        saved = {name: unreal.SystemLibrary.get_console_variable_float_value(name) for name in ("t.MaxFPS", "r.VSync", "a.Budget.Enabled", "a.Budget.BudgetMs", "r.DontLimitOnBattery")}
        unreal.SystemLibrary.execute_console_command(world, "t.MaxFPS 0")
        unreal.SystemLibrary.execute_console_command(world, "r.VSync 0")
        unreal.SystemLibrary.execute_console_command(world, "r.DontLimitOnBattery 1")
        unreal.SystemLibrary.execute_console_command(world, "a.Budget.BudgetMs 2.0")
        run_id = str(uuid.uuid4())
        report = {"status": "running", "runId": run_id, "world": world.get_path_name(), "engine": unreal.SystemLibrary.get_engine_version(), "commandLine": unreal.SystemLibrary.get_command_line(), "configPaths": list(config_paths), "forceActorRepresentation": force_actor_representation, "warmupSeconds": warmup_seconds, "measurementSeconds": measurement_seconds, "budgetMs": 2.0, "resultPath": result_path, "csvPath": csv_path, "cases": []}
        _population_runs[run_id] = report
        output = open(csv_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(output)
        writer.writerow(["count", "budget", "frame", "game_thread_ms", "render_thread_ms", "gpu_ms", "engine_delta_ms", "slate_delta_ms"])
        state = {"case": -1, "entities": [], "phase": "next", "samples": [], "start": 0.0, "handle": None, "lastFrame": -1}
        cases = [(count, enabled) for count in counts for enabled in (False, True)]

        def save_report():
            with open(result_path, "w", encoding="utf-8") as destination:
                json.dump(report, destination, ensure_ascii=False, indent=2)
            output.flush()

        def cleanup():
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() == world and state["entities"]:
                    mass.destroy_population(world, state["entities"])
            finally:
                state["entities"] = []
                for name, value in saved.items():
                    unreal.SystemLibrary.execute_console_command(world, name + " " + str(value))
                output.close()
                if state["handle"] is not None:
                    unreal.unregister_slate_post_tick_callback(state["handle"])

        def summarize(rows, column):
            values = sorted(row[column] for row in rows)
            return {"mean": sum(values) / len(values), "p50": values[int((len(values) - 1) * 0.5)], "p95": values[int((len(values) - 1) * 0.95)], "max": values[-1]}

        def tick(delta_seconds):
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                    raise RuntimeError("验收 PIE 被外部停止")

                now = time.perf_counter()
                if state["phase"] == "next":
                    if state["entities"]:
                        mass.destroy_population(world, state["entities"])
                        state["entities"] = []
                        state["phase"] = "clear"
                        state["start"] = now
                        return

                    state["case"] += 1
                    if state["case"] >= len(cases):
                        report["status"] = "completed"
                        save_report()
                        cleanup()
                        return

                    count, enabled = cases[state["case"]]
                    unreal.SystemLibrary.execute_console_command(world, "a.Budget.Enabled " + str(int(enabled)))
                    state["entities"] = mass.spawn_population(world, configs, count, unreal.Vector(*center), spacing)
                    if len(state["entities"]) != count:
                        raise RuntimeError("实际 Mass 创建数量不匹配")

                    state["phase"] = "warmup"
                    state["start"] = now
                    report["currentCount"] = count
                    report["currentBudget"] = enabled
                    save_report()
                    return

                if state["phase"] == "clear":
                    if now - state["start"] >= 1.0:
                        state["phase"] = "next"
                    return

                if state["phase"] == "warmup":
                    if now - state["start"] >= warmup_seconds:
                        state["before"] = json.loads(mass.inspect_population(world, state["entities"]))
                        count, enabled = cases[state["case"]]
                        if force_actor_representation and state["before"].get("presentationActors") != count:
                            if now - state["start"] > 60.0:
                                raise RuntimeError("全骨骼预热超时 实际演员数量=" + str(state["before"].get("presentationActors")))
                            return
                        state["samples"] = []
                        state["start"] = now
                        state["phase"] = "measure"
                    return

                row = list(metrics()) + [float(delta_seconds) * 1000.0]
                if int(row[0]) != state["lastFrame"]:
                    state["samples"].append(row)
                    count, enabled = cases[state["case"]]
                    writer.writerow([count, int(enabled)] + row)
                    state["lastFrame"] = int(row[0])

                if now - state["start"] >= measurement_seconds:
                    count, enabled = cases[state["case"]]
                    snapshot = json.loads(mass.inspect_population(world, state["entities"]))
                    rows = state["samples"]
                    result = {"count": count, "budgetEnabled": enabled, "sampleFrames": len(rows), "measuredSeconds": now - state["start"], "before": state["before"], "after": snapshot}
                    for name, column in (("gameThreadMs", 1), ("renderThreadMs", 2), ("gpuMs", 3), ("engineDeltaMs", 4), ("slateDeltaMs", 5)):
                        result[name] = summarize(rows, column)
                    result["entityCountCorrect"] = snapshot.get("validEntities") == count
                    result["budgetMeshCoverageCorrect"] = snapshot.get("budgetMeshes") == snapshot.get("presentationActors")
                    report["cases"].append(result)
                    save_report()
                    state["phase"] = "next"
            except Exception as error:
                report["status"] = "failed"
                report["error"] = str(error)
                save_report()
                cleanup()
                unreal.log_error("[BBBPopulationBenchmark] " + str(error))

        state["handle"] = unreal.register_slate_post_tick_callback(tick)
        save_report()
        return json.dumps({"runId": run_id, "status": "running", "resultPath": result_path, "csvPath": csv_path}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_mass_population_benchmark(run_id: str) -> str:
        """
        /**
         * 读取本宿主群体验收进度 不重启测量
         * @param run_id		开始工具返回的标识
         * @return 当前阶段与结果文件路径
         */
        """
        report = _population_runs.get(run_id)
        if report is None:
            raise RuntimeError("当前宿主不存在这一测量")
        return json.dumps({key: value for key, value in report.items() if key != "cases"} | {"completedCases": len(report["cases"])}, ensure_ascii=False)

    @mcp_tool
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

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
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


    @mcp_tool
    @staticmethod
    def capture_monster_animation_transition(actor_blueprint_path: str, initial_state: int, target_state: int, initial_progress: float, target_progress: float, initial_speed: float, target_speed: float, sample_seconds: list[float], bone_names: list[str], file_prefix: str) -> str:
        """
        /**
         * 在无 Mass 实体的临时表现演员上渲染真实动画蓝图切换 不写玩法状态
         * @param actor_blueprint_path		明确表现演员蓝图
         * @param initial_state			初始表现状态 零至五
         * @param target_state			目标表现状态 零至五
         * @param initial_progress		初始非循环动作进度
         * @param target_progress			目标非循环动作进度
         * @param initial_speed			初始实际速度 厘米每秒
         * @param target_speed			目标实际速度 厘米每秒
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

        if not 0.0 <= initial_speed <= 10000.0 or not 0.0 <= target_speed <= 10000.0:
            raise RuntimeError("初始与目标实际速度必须明确且有效")

        blueprint = unreal.load_asset(actor_blueprint_path)
        if not isinstance(blueprint, unreal.Blueprint):
            raise RuntimeError("表现演员蓝图不存在")

        states = [unreal.BBBMonsterBehavior.IDLE, unreal.BBBMonsterBehavior.ALERT, unreal.BBBMonsterBehavior.PATROL, unreal.BBBMonsterBehavior.CHASE, unreal.BBBMonsterBehavior.ATTACK, unreal.BBBMonsterBehavior.DEAD]
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
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
                    presentation.call_method("ApplyPresentationState", (states[initial_state], initial_speed, 1.0, 1, initial_progress))
                    if not library.evaluate_animation_blueprint_frame(mesh, 0.001):
                        raise RuntimeError("初始动画蓝图求值失败")

                    for warmup in range(15):
                        yield
                        if not library.evaluate_animation_blueprint_frame(mesh, 1.0 / 60.0):
                            raise RuntimeError("初始姿势跨帧求值失败")

                    height = unreal.SystemLibrary.get_component_bounds(mesh)[1].z * 2.0
                    if height <= 0.001:
                        raise RuntimeError("临时表现网格包围盒高度无效")

                    preview_scale = 180.0 / height
                    actor.set_actor_scale3d(unreal.Vector(preview_scale, preview_scale, preview_scale))
                    before = {name: mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT).translation for name in bone_names}
                    yield
                    presentation.call_method("ApplyPresentationState", (states[target_state], target_speed, 2.0, 2, target_progress))
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
                    samples.append({"seconds": seconds, "animationClass": instance.get_class().get_path_name(), "bones": bones, "runtimeGraph": json.loads(unreal.BBBBlueprintEditorLibrary.probe_animation_instance_runtime(instance))})

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

    @mcp_tool
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
