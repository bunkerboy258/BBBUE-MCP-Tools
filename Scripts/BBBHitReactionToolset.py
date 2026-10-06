import json
import math
import os
import re
import uuid

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration
from BBBAssetWritePolicy import require_asset_write, require_write_access


_captures = {}


@unreal.uclass()
class BBBHitReactionToolset(unreal.ToolsetDefinition):
    """/** 配置骨骼物理受击资产并移除被替换的动画偏转层 */"""

    @mcp_tool
    @staticmethod
    def spawn_inspection_projectile(projectile_definition_path: str, start: list[float], end: list[float], damage: float = 0.0) -> str:
        """
        /**
         * 使用正式子弹配置验证移动 碰撞 命中输入和受击表现 不直接提交命中
         * @param projectile_definition_path\t明确的正式子弹配置
         * @param start\t子弹出生位置 三个厘米坐标
         * @param end\t确定飞行方向的目标位置 三个厘米坐标
         * @param damage\t本次验证伤害 零表示仅验证表现
         * @return 子弹出生输入提交结果
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or len(start) != 3 or len(end) != 3 or not all(math.isfinite(value) for value in list(start) + list(end)) or not math.isfinite(damage) or not 0.0 <= damage <= 10000.0:
            raise RuntimeError("需要当前 PIE 世界和有效子弹坐标")
        definition = unreal.load_asset(projectile_definition_path)
        if not isinstance(definition, unreal.BBBProjectileDefinition):
            raise RuntimeError("目标不是正式子弹配置")
        submitted = unreal.BBBMassValidationLibrary.spawn_inspection_projectile(world, definition, unreal.Vector(*start), unreal.Vector(*end), damage)
        if not submitted:
            raise RuntimeError("正式子弹出生输入提交失败")
        return json.dumps({"submitted": True, "definition": definition.get_path_name(), "start": list(start), "end": list(end), "damage": damage}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_hit_reaction_physics_asset(asset_path: str, orientation_strength: float = 200.0, angular_velocity_strength: float = 12.0) -> str:
        """
        /**
         * 修改已经独占签出的自有物理资产 不保存
         * @param asset_path\t明确的自有物理资产
         * @param orientation_strength\t角度恢复强度
         * @param angular_velocity_strength\t角速度恢复强度
         * @return 刚体与约束配置报告
         */
        """
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.PhysicsAsset) or not asset_path.startswith("/Game/_Project/"):
            raise RuntimeError("需要明确的自有物理资产")
        require_write_access(asset)
        result = unreal.BBBHitReactionEditorLibrary.configure_physics_asset(asset, orientation_strength, angular_velocity_strength)
        if str(result).startswith("失败"):
            raise RuntimeError(str(result))
        return str(result)

    @mcp_tool
    @staticmethod
    def create_hit_reaction_profile(asset_path: str, region: int) -> str:
        """
        /**
         * 创建并保存不存在的物理受击配置 调用方负责新增文件版本控制
         * @param asset_path\t自有配置包路径
         * @param region\t零躯干 一头部 二手臂 三腿部
         * @return 保存的配置路径
         */
        """
        if not asset_path.startswith("/Game/_Project/") or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("配置目标必须是不存在的自有路径")
        require_asset_write([], [asset_path])
        asset = unreal.BBBHitReactionEditorLibrary.create_reaction_profile(asset_path, region)
        if asset is None or not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("物理受击配置创建或保存失败")
        return json.dumps({"asset": asset.get_path_name(), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def remove_fact_hit_bone_layer(asset_path: str) -> str:
        """
        /**
         * 删除旧普通受击偏转链 严格编译成功后保存
         * @param asset_path\t已独占签出的目标动画蓝图
         * @return 删除数量与编译保存结果
         */
        """
        blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("目标不是动画蓝图")
        require_write_access(blueprint)
        count = unreal.BBBHitReactionEditorLibrary.remove_hit_bone_layer(blueprint)
        if count < 0:
            raise RuntimeError("目标动画偏转链不符合已知结构 禁止保存")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图未严格编译通过 禁止保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")
        return json.dumps({"asset": asset_path, "removedBoneControls": count, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_skeletal_physics_state(component_path: str) -> str:
        """
        /**
         * 只读检查已经加载的运行时骨骼对象 不创建或修改资产
         * @param component_path\t当前骨骼组件对象路径
         * @return 受击状态与刚体混合权重
         */
        """
        component = unreal.find_object(None, component_path)
        if not isinstance(component, unreal.SkeletalMeshComponent):
            raise RuntimeError("运行时骨骼组件不存在")
        return str(unreal.BBBHitReactionEditorLibrary.inspect_physics_state(component))

    @mcp_tool
    @staticmethod
    def start_skeletal_hit_reaction_capture(actor_blueprint_path: str, region: int, direction: list[float], file_prefix: str, shots: int = 1, interval_seconds: float = 0.1, speed: float = 0.0, capture_images: bool = False, interrupt: str = "none", actor_count: int = 1) -> str:
        """
        /**
         * 在临时表现对象上跨真实游戏帧验证局部物理回弹 不产生玩法伤害
         * @param actor_blueprint_path\t明确的表现演员蓝图
         * @param region\t零至五的命中部位
         * @param direction\t世界受力方向 三个分量
         * @param file_prefix\tSaved/temp 下的安全输出目录名
         * @param shots\t连续命中次数 零至十二 零用于基线
         * @param interval_seconds\t命中间隔秒数
         * @param speed\t临时演员前进速度 厘米每秒
         * @param capture_images\t是否输出真实渲染帧
         * @param interrupt\t无中断 死亡或隐藏 none dead hidden
         * @param actor_count	临时全骨骼表现数量 一至六十四
         * @return 跨帧诊断编号
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or region not in range(6) or len(direction) != 3 or not all(math.isfinite(value) for value in direction):
            raise RuntimeError("需要运行中的 PIE 和有效受击参数")
        if sum(value * value for value in direction) < 0.001 or not 0 <= shots <= 12 or not 1 <= actor_count <= 64 or not 0.05 <= interval_seconds <= 0.5 or not 0.0 <= speed <= 300.0:
            raise RuntimeError("受击方向 次数 间隔或移动速度无效")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix) or interrupt not in {"none", "dead", "hidden"}:
            raise RuntimeError("输出目录名或中断类型无效")
        if any(value["status"] == "pending" for value in _captures.values()):
            raise RuntimeError("已有受击采样正在执行")
        if capture_images and "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("真实渲染采样需要渲染宿主")
        blueprint = unreal.load_asset(actor_blueprint_path)
        if not isinstance(blueprint, unreal.Blueprint) or blueprint.generated_class() is None:
            raise RuntimeError("表现蓝图不存在或未编译")
        identifier = str(uuid.uuid4())
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix))
        os.makedirs(directory, exist_ok=True)
        record = {"status": "pending", "captureId": identifier, "blueprint": actor_blueprint_path, "region": region, "shots": shots, "speed": speed, "interrupt": interrupt, "actorCount": actor_count}
        _captures[identifier] = record
        library = unreal.BBBAnimationGraphEditorLibrary
        physics = unreal.BBBHitReactionEditorLibrary
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector(0.0, 0.0, 20090.0), rotation=unreal.Rotator(yaw=180.0)))
        if actor is None:
            record["status"] = "failed"
            raise RuntimeError("临时表现演员创建失败")
        actor.set_actor_enable_collision(True)
        mesh = actor.get_monster_mesh()
        mesh.set_forced_lod(1)
        presentation = actor.get_monster_presentation()
        state = unreal.BBBMonsterBehavior.CHASE if speed > 0.0 else unreal.BBBMonsterBehavior.IDLE
        presentation.call_method("ApplyPresentationState", (state, speed, 1.0, 1, 0.0))
        library.set_preview_hit_facts(mesh, region, unreal.Vector(*direction), 10.0)
        actors = [actor]
        subjects = [actor]
        control = None
        if shots > 0 and actor_count == 1 and interrupt == "none":
            control = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector(0.0, 150.0, 20090.0), rotation=unreal.Rotator(yaw=180.0)))
            actors.append(control)
            control.get_monster_mesh().set_forced_lod(1)
            control.get_monster_mesh().get_anim_instance().set_editor_property("presentation_id_fact", mesh.get_anim_instance().get_editor_property("presentation_id_fact"))
            control.get_monster_presentation().call_method("ApplyPresentationState", (state, speed, 1.0, 1, 0.0))
            control.get_monster_mesh().set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
        for index in range(1, actor_count):
            subject = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector((index % 8) * 150.0, (index // 8) * 150.0, 20090.0), rotation=unreal.Rotator(yaw=180.0)))
            actors.append(subject)
            subjects.append(subject)
            subject.set_actor_enable_collision(True)
            subject.get_monster_mesh().set_forced_lod(1)
            subject.get_monster_presentation().call_method("ApplyPresentationState", (state, speed, 1.0, 1, 0.0))
            library.set_preview_hit_facts(subject.get_monster_mesh(), region, unreal.Vector(*direction), 10.0)
        camera = None
        target = None
        if capture_images:
            focus = mesh.get_socket_location("pelvis") + unreal.Vector(0.0, 0.0, 15.0)
            location = focus + unreal.Vector(-330.0, -270.0, 20.0)
            camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=unreal.MathLibrary.find_look_at_rotation(location, focus)))
            light = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.PointLight, unreal.Transform(location=location))
            if camera is None or light is None:
                actor.destroy_actor()
                raise RuntimeError("临时采样相机或灯光创建失败")
            actors.extend([camera, light])
            light_component = light.get_component_by_class(unreal.PointLightComponent)
            light_component.set_intensity(300000.0)
            light_component.set_attenuation_radius(1400.0)
            target = unreal.RenderingLibrary.create_render_target2d(world, 640, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property("texture_target", target)
            capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.show_only_actor_components(actor)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("fov_angle", 35.0)
            capture.set_editor_property("capture_every_frame", False)
            capture.set_editor_property("capture_on_movement", False)
            settings = unreal.PostProcessSettings()
            settings.set_editor_property("override_auto_exposure_method", True)
            settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
            settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
            settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
            capture.set_editor_property("post_process_settings", settings)
        if control is not None:
            unreal.AnimationBudget.enable_animation_budget(world, False)
            for subject in (actor, control):
                subject.get_monster_presentation().call_method("ApplyPresentationState", (unreal.BBBMonsterBehavior.ALERT, 0.0, 0.0, 1, 0.0))
        bones = ["head", "spine_03", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r", "hand_l", "hand_r", "foot_l", "foot_r"]
        start_time = unreal.GameplayStatics.get_time_seconds(world)
        data = {"baseline": None, "start": None, "last": -1.0, "shots": 0, "samples": [], "images": [], "imageSeconds": [], "handle": None, "interrupted": False, "lastImage": -1.0, "synchronized": control is None}

        def pose(component=mesh):
            result = {}
            for name in bones:
                transform = component.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT)
                position = transform.translation
                rotation = transform.rotation
                result[name] = {"position": [position.x, position.y, position.z], "rotation": [rotation.x, rotation.y, rotation.z, rotation.w]}
            return result

        def complete(error=None):
            unreal.unregister_slate_post_tick_callback(data["handle"])
            if error is not None:
                record.update({"status": "failed", "error": str(error)})
            if error is None:
                record.update({"status": "completed", "sampleFrames": len(data["samples"]), "imagePaths": data["images"], "imageSeconds": data["imageSeconds"], "lastPhysics": json.loads(physics.inspect_physics_state(mesh)), "remainingActiveActors": sum(json.loads(physics.inspect_physics_state(item.get_monster_mesh()))["activeBlends"] > 0 for item in subjects)})
                peak_angles = {name: 0.0 for name in bones}
                peak_distances = {name: 0.0 for name in bones}
                for sample in data["samples"]:
                    for name in bones:
                        before = sample["controlPose"][name] if control is not None and record.get("initialControlErrorCm", 100.0) <= 0.25 else data["baseline"][name]
                        current = sample["pose"][name]
                        dot = abs(sum(a * b for a, b in zip(before["rotation"], current["rotation"])))
                        peak_angles[name] = max(peak_angles[name], math.degrees(2.0 * math.acos(min(1.0, dot))))
                        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(before["position"], current["position"])))
                        peak_distances[name] = max(peak_distances[name], distance)
                record["matchedAnimationControl"] = control is not None and record.get("initialControlErrorCm", 100.0) <= 0.25
                rows = [sample["performance"] for sample in data["samples"] if 0.05 <= sample["seconds"] <= max(1.1, (shots - 1) * interval_seconds)]
                times = sorted(row[1] for row in rows)
                record["gameThreadMs"] = {"mean": sum(times) / len(times), "p95": times[int((len(times) - 1) * 0.95)], "samples": len(times)}
                record["peakAnglesDegrees"] = peak_angles
                record["peakDisplacementCm"] = peak_distances
                report_path = os.path.join(directory, identifier + ".json")
                with open(report_path, "w", encoding="utf-8") as stream:
                    json.dump({**record, "baseline": data["baseline"], "samples": data["samples"]}, stream, ensure_ascii=False)
                record["reportPath"] = report_path
            if control is not None:
                unreal.AnimationBudget.enable_animation_budget(world, True)
            for item in reversed(actors):
                if unreal.SystemLibrary.is_valid(item):
                    item.destroy_actor()
            record["temporaryActorsDestroyed"] = True

        def tick(delta_seconds):
            try:
                if not unreal.SystemLibrary.is_valid(actor):
                    raise RuntimeError("PIE 或临时表现对象已退出")
                now = unreal.GameplayStatics.get_time_seconds(world)
                if now == data["last"]:
                    return
                data["last"] = now
                if not data["synchronized"] and now - start_time >= 0.1:
                    for subject in (actor, control):
                        subject.get_monster_presentation().call_method("ApplyPresentationState", (state, speed, 1.0, 1, 0.0))
                    data["synchronized"] = True
                if now - start_time < (2.0 if actor_count > 1 else 0.5):
                    return
                if data["start"] is None:
                    data["baseline"] = pose()
                    if control is not None:
                        reference = pose(control.get_monster_mesh())
                        record["initialControlErrorCm"] = max(math.sqrt(sum((x - y) ** 2 for x, y in zip(data["baseline"][name]["position"], reference[name]["position"]))) for name in bones)
                    data["start"] = now
                elapsed = now - data["start"]
                if speed > 0.0:
                    actor.set_actor_location(unreal.Vector(-speed * elapsed, 0.0, 20090.0), False, True)
                if data["shots"] < shots and elapsed >= data["shots"] * interval_seconds:
                    for subject in subjects:
                        if not library.set_preview_hit_facts(subject.get_monster_mesh(), region, unreal.Vector(*direction), 0.0):
                            raise RuntimeError("受击事实写入失败")
                    data["shots"] += 1
                if interrupt != "none" and elapsed >= 0.15 and not data["interrupted"]:
                    if interrupt == "dead":
                        presentation.call_method("ApplyPresentationState", (unreal.BBBMonsterBehavior.DEAD, 0.0, now, 2, 0.0))
                        library.set_preview_hit_facts(mesh, region, unreal.Vector(*direction), 10.0)
                    if interrupt == "hidden":
                        actor.set_actor_hidden_in_game(True)
                    data["interrupted"] = True
                physics_state = json.loads(physics.inspect_physics_state(mesh))
                sample = {"seconds": elapsed, "pose": pose(), "physics": physics_state, "performance": list(library.read_performance_frame_metrics())}
                if control is not None:
                    sample["controlPose"] = pose(control.get_monster_mesh())
                data["samples"].append(sample)
                if camera is not None and elapsed - data["lastImage"] >= 0.04 and elapsed < (shots - 1) * interval_seconds + 0.8:
                    camera.capture_component2d.capture_scene()
                    filename = identifier + "_" + str(len(data["images"])).zfill(3) + ".png"
                    unreal.RenderingLibrary.export_render_target(world, target, directory, filename)
                    data["images"].append(os.path.join(directory, filename))
                    data["imageSeconds"].append(elapsed)
                    data["lastImage"] = elapsed
                if elapsed >= (shots - 1) * interval_seconds + 2.0:
                    complete()
            except Exception as error:
                complete(error)

        data["handle"] = unreal.register_slate_post_tick_callback(tick)
        return json.dumps(record, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def run_monster_hit_reaction_regressions() -> str:
        """
        /**
         * 在无 PIE 的宿主排队运行现有僵尸自动化回归 通过结果须回读引擎日志
         * @return 排队的测试筛选条件 不代表测试通过
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止执行编辑器自动化回归")
        unreal.SystemLibrary.execute_console_command(None, "Automation RunTests UBBB.Mass.Zombie")
        return json.dumps({"queued": True, "filter": "UBBB.Mass.Zombie"})

    @mcp_tool
    @staticmethod
    def inspect_skeletal_hit_reaction_capture(capture_id: str) -> str:
        """
        /**
         * 读取跨帧物理受击诊断 完整逐帧数据位于返回的报告路径
         * @param capture_id\t开始采样返回的编号
         * @return 采样状态与峰值摘要
         */
        """
        if capture_id not in _captures:
            raise RuntimeError("物理受击采样编号不存在")
        return json.dumps(_captures[capture_id], ensure_ascii=False)


_registration = Registration([BBBHitReactionToolset])
