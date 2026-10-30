import json
import math
import os
import re
import time
import uuid

import unreal


def start_capture(world, version_path, region, direction, file_prefix, shots, interval_seconds,
                  capture_images, actor_count, distance_cm, view_yaw, captures, projectile_path="", animation_path="", wound_strength=1.0, allow_severing=False):
    """
    /**
     * @param world	当前模拟世界
     * @param version_path	正式僵尸模板
     * @param region	零至五的命中部位
     * @param direction	世界受力方向
     * @param file_prefix	任务临时目录名
     * @param shots	每个靶的命中次数 零表示性能基线
     * @param interval_seconds	真实游戏时间的命中间隔
     * @param capture_images	是否采集真实渲染帧
     * @param actor_count	同时受击的固定靶数量
     * @param distance_cm	相机至中心靶的水平距离
     * @param view_yaw	相机绕中心靶的角度
     * @param captures	所属工具集的采样状态
     * @param projectile_path	可选正式子弹配置 留空使用点命中指令
     * @param animation_path	可选兼容动画序列 用于行走 跑步与攻击联检
     * @param wound_strength	大于零且不超过十的创口累计强度 不改变物理冲量
     * @param allow_severing	是否允许本次预览触发正式断离表现
     * @return 独立机位及中性照明的临时场景采样编号
     */
    """
    if world is None or region not in range(6) or len(direction) != 3 or not all(math.isfinite(value) for value in direction):
        raise RuntimeError("需要模拟世界及有效命中部位与方向")
    if sum(value * value for value in direction) < .001 or not 0 <= shots <= 12 or not 1 <= actor_count <= 64:
        raise RuntimeError("命中次数 数量或方向无效")
    if not math.isfinite(interval_seconds) or not .05 <= interval_seconds <= .5:
        raise RuntimeError("命中间隔需要零点零五至零点五秒")
    if not math.isfinite(distance_cm) or not 250 <= distance_cm <= 2500 or not math.isfinite(view_yaw):
        raise RuntimeError("机位距离需要二点五至二十五米")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix) or any(item["status"] == "pending" for item in captures.values()):
        raise RuntimeError("任务目录无效或已有采样尚未结束")
    if capture_images and "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
        raise RuntimeError("画面采样需要渲染宿主")
    version = unreal.load_asset(version_path)
    if not isinstance(version, unreal.MassEntityConfigAsset):
        raise RuntimeError("需要正式僵尸实体模板")
    if not isinstance(wound_strength, (int, float)) or not math.isfinite(wound_strength) or not 0 < wound_strength <= 10:
        raise RuntimeError("创口强度需要大于零且不超过十的有限数值")
    animation = unreal.load_asset(animation_path) if animation_path else None
    if animation_path and not isinstance(animation, unreal.AnimSequence):
        raise RuntimeError("测试动画需要有效动画序列")
    projectile = unreal.load_asset(projectile_path) if projectile_path else None
    if projectile_path and not isinstance(projectile, unreal.BBBProjectileDefinition):
        raise RuntimeError("子弹预览需要正式子弹配置")
    controller = unreal.GameplayStatics.get_player_controller(world, 0)
    if controller is None:
        raise RuntimeError("需要模拟世界的本地相机控制器")
    identifier = str(uuid.uuid4())
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix, identifier))
    os.makedirs(directory, exist_ok=False)
    actors = []
    restored_lights = []
    original_view = controller.get_view_target()
    record = {"status": "pending", "captureId": identifier, "version": version_path, "region": region,
              "direction": list(direction), "shots": shots, "actorCount": actor_count, "distanceCm": distance_cm,
              "viewYaw": view_yaw, "imagePaths": [], "imageSeconds": [], "imagePhases": [], "samples": [], "shotSeconds": [],
              "lighting": "neutral_key_fill_rim_front_area_gray_ambient_manual_exposure", "usesGameplayCharacter": False,
              "projectile": projectile_path, "timeDilation": unreal.GameplayStatics.get_global_time_dilation(world),
              "wallSeconds": [], "infection": 255, "animation": animation_path, "woundStrength": wound_strength, "allowSevering": allow_severing}
    data = {"handle": None, "start": None, "last": -1.0, "shot": 0, "lastImage": -1.0,
            "prewarmed": False, "reset": False, "initialHits": [], "groundView": False}

    def spawn(kind, location, rotation=unreal.Rotator(), scale=unreal.Vector(1, 1, 1)):
        """/** @return 只存在当前模拟世界的对象 */"""
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, kind,
            unreal.Transform(location=location, rotation=rotation, scale=scale))
        if actor is None:
            raise RuntimeError("临时场景对象创建失败")
        actors.append(actor)
        return actor

    def cleanup():
        """/** @return 恢复当前模拟世界并销毁本次所有临时对象 */"""
        same_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() == world
        if same_world:
            if unreal.SystemLibrary.is_valid(original_view):
                controller.set_view_target_with_blend(original_view, 0.0)
            for component, visible in restored_lights:
                if unreal.SystemLibrary.is_valid(component):
                    component.set_visibility(visible)
            for actor in reversed(actors):
                if unreal.SystemLibrary.is_valid(actor):
                    actor.destroy_actor()
        record["temporaryActorsDestroyed"] = True

    try:
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Light):
            for component in actor.get_components_by_class(unreal.LightComponent):
                restored_lights.append((component, component.is_visible()))
                component.set_visibility(False)
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkyLight):
            component = actor.get_component_by_class(unreal.SkyLightComponent)
            restored_lights.append((component, component.is_visible()))
            component.set_visibility(False)
        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
        neutral = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
        for location, scale in [(unreal.Vector(0, 0, 19990), unreal.Vector(70, 70, .2)),
                                (unreal.Vector(1500, 0, 20500), unreal.Vector(.2, 70, 10))]:
            surface = spawn(unreal.StaticMeshActor, location, scale=scale).static_mesh_component
            surface.set_mobility(unreal.ComponentMobility.MOVABLE)
            surface.set_static_mesh(cube)
            gray = surface.create_dynamic_material_instance(0, neutral)
            gray.set_vector_parameter_value("Color", unreal.LinearColor(.18, .18, .18, 1))
            gray.set_scalar_parameter_value("Roughness", .85)
            surface.set_collision_profile_name("BlockAll")
            surface.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
        for location, intensity in [(unreal.Vector(-250, -350, 20450), 30000),
                                    (unreal.Vector(-200, 400, 20250), 12000),
                                    (unreal.Vector(300, 0, 20400), 18000)]:
            light = spawn(unreal.PointLight, location).get_component_by_class(unreal.PointLightComponent)
            light.set_mobility(unreal.ComponentMobility.MOVABLE)
            light.set_intensity(intensity)
            light.set_attenuation_radius(3000.0)
            light.set_editor_property("source_radius", 80.0)
        for rotation, intensity in [(unreal.Rotator(pitch=-35, yaw=25), 10.0),
                                    (unreal.Rotator(pitch=-20, yaw=-55), 4.0)]:
            light = spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 20500), rotation).get_component_by_class(unreal.DirectionalLightComponent)
            light.set_mobility(unreal.ComponentMobility.MOVABLE)
            light.set_intensity(intensity)
            light.set_cast_shadows(intensity > 5.0)
            light.set_editor_property("light_source_angle", 4.0)
        ambient = spawn(unreal.SkyLight, unreal.Vector(0, 0, 20500)).get_component_by_class(unreal.SkyLightComponent)
        ambient.set_mobility(unreal.ComponentMobility.MOVABLE)
        ambient.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
        ambient.set_cubemap(unreal.load_asset("/Engine/EngineResources/GrayTextureCube"))
        ambient.set_intensity(1.0)
        front_location = unreal.Vector(-350.0 * math.cos(math.radians(view_yaw)),
                                       -350.0 * math.sin(math.radians(view_yaw)), 20200.0)
        front_rotation = unreal.MathLibrary.find_look_at_rotation(front_location, unreal.Vector(0, 0, 20120))
        front = spawn(unreal.RectLight, front_location, front_rotation).get_component_by_class(unreal.RectLightComponent)
        front.set_mobility(unreal.ComponentMobility.MOVABLE)
        front.set_intensity(20000.0)
        front.set_attenuation_radius(3000.0)
        front.set_editor_property("source_width", 120.0)
        front.set_editor_property("source_height", 90.0)
        front.set_cast_shadows(False)
        subjects = []
        for index in range(actor_count):
            y = 0.0 if actor_count == 1 else ((index % 8) - 3.5) * 100.0
            transform = unreal.Transform(location=unreal.Vector((index // 8) * 100, y, 20000), rotation=unreal.Rotator(yaw=180))
            subject = unreal.BBBBlueprintEditorLibrary.begin_transient_pie_actor(world, unreal.BBBZombieHitReactionTarget, transform)
            if subject is None:
                raise RuntimeError("固定受击靶创建失败")
            actors.append(subject)
            subject.set_editor_property("zombie_version", version)
            subject.gore_preview.set_editor_property("reset_interval", 0.0)
            subject.gore_preview.set_editor_property("allow_severing", allow_severing)
            if animation:
                subject.set_editor_property("test_animation", animation)
            subject = unreal.BBBBlueprintEditorLibrary.finish_transient_pie_actor(subject, transform)
            if subject is None or not subject.get_editor_property("configuration_ready"):
                raise RuntimeError("固定靶配置失败")
            subject.target_mesh.set_custom_primitive_data_float(0, 1.0)
            subjects.append(subject)
        yaw = math.radians(view_yaw)
        location = unreal.Vector(-distance_cm * math.cos(yaw), -distance_cm * math.sin(yaw), 20130)
        focus = unreal.Vector(0, 0, 20105)
        rotation = unreal.MathLibrary.find_look_at_rotation(location, focus)
        view = spawn(unreal.CameraActor, location, rotation)
        view.get_component_by_class(unreal.CameraComponent).set_field_of_view(80.0)
        controller.set_view_target_with_blend(view, 0.0)
        camera = spawn(unreal.SceneCapture2D, location, rotation)
        target = unreal.RenderingLibrary.create_render_target2d(world, 960, 540, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        capture = camera.capture_component2d
        capture.set_editor_property("texture_target", target)
        capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        capture.set_editor_property("capture_every_frame", not capture_images)
        capture.set_editor_property("capture_on_movement", False)
        capture.set_editor_property("fov_angle", 80.0)
        exposure = unreal.PostProcessSettings()
        exposure.set_editor_property("override_auto_exposure_method", True)
        exposure.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        exposure.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        exposure.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        capture.set_editor_property("post_process_settings", exposure)
        options = None
        if capture_images:
            options = unreal.ImageWriteOptions()
            options.set_editor_property("format", unreal.DesiredImageFormat.PNG)
            options.set_editor_property("overwrite_file", False)
            options.set_editor_property("compression_quality", 0)
        record["renderResolution"] = [960, 540]
        record["performanceRendering"] = "independent_scene_capture"
        record["targetPaths"] = [subject.get_path_name() for subject in subjects]
        warmup = unreal.GameplayStatics.get_time_seconds(world)
    except Exception:
        cleanup()
        raise

    def complete(error=None):
        """/** @return 保存实际帧时间与粒子状态并完成资源回收 */"""
        if record["status"] != "pending":
            return
        unreal.unregister_slate_post_tick_callback(data["handle"])
        record["status"] = "failed" if error else "completed"
        if error:
            record["error"] = str(error)
        record["consumedHits"] = [subject.get_editor_property("hit_count") - before
                                  for subject, before in zip(subjects, data["initialHits"])] if not error else []
        regions = (unreal.BBBMonsterHitRegion.TORSO, unreal.BBBMonsterHitRegion.HEAD,
                   unreal.BBBMonsterHitRegion.LEFT_ARM, unreal.BBBMonsterHitRegion.RIGHT_ARM,
                   unreal.BBBMonsterHitRegion.LEFT_LEG, unreal.BBBMonsterHitRegion.RIGHT_LEG)
        record["regionsMatch"] = [subject.get_editor_property("last_hit_region") == regions[region]
                                  for subject in subjects] if not error and shots > 0 else []
        if not error and any(count != shots for count in record["consumedHits"]):
            record["status"] = "failed"
            record["error"] = "指令命中消费次数与请求不符"
        if not error and shots > 0 and not all(record["regionsMatch"]):
            record["status"] = "failed"
            record["error"] = "实际命中部位与请求不符"
        cleanup()
        rows = [sample["performance"] for sample in record["samples"] if .2 <= sample["seconds"] <= 2.5]
        record["performance"] = {}
        for index, name in [(4, "frameMs"), (1, "gameThreadMs"), (2, "renderThreadMs"), (3, "gpuMs")]:
            values = sorted(row[index] for row in rows)
            if values:
                record["performance"][name] = {"mean": sum(values) / len(values), "p95": values[int((len(values) - 1) * .95)]}
        record["sampleFrames"] = len(record["samples"])
        path = os.path.join(directory, "capture.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
        record["reportPath"] = path
        record.pop("samples")

    def tick(delta_seconds):
        """/** @return 以游戏时钟定时触发命中并采样 独立于角色输入 */"""
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError("临时场景采样期间模拟世界已结束")
            now = unreal.GameplayStatics.get_time_seconds(world)
            if now == data["last"]:
                return
            data["last"] = now
            if now - warmup >= .25 and not data["prewarmed"]:
                for subject in subjects:
                    if not subject.preview_hit(region, unreal.Vector(*direction), 1.0):
                        raise RuntimeError("命中预热失败")
                data["prewarmed"] = True
            if now - warmup >= 1.5 and not data["reset"]:
                for subject in subjects:
                    subject.gore_preview.reset_target()
                data["initialHits"] = [subject.get_editor_property("hit_count") for subject in subjects]
                data["reset"] = True
                record["prewarmed"] = True
            if now - warmup < 2.0:
                return
            if data["start"] is None:
                data["start"] = now
                data["wallStart"] = time.monotonic()
            elapsed = now - data["start"]
            if data["shot"] < shots and elapsed >= .25 + data["shot"] * interval_seconds:
                for subject in subjects:
                    if projectile:
                        bone = ("spine_01", "head", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r")[region]
                        center = subject.target_mesh.get_socket_location(bone)
                        axis = unreal.Vector(*direction).normal()
                        if not unreal.BBBMassValidationLibrary.spawn_inspection_projectile(world, projectile,
                                center - axis * 200, center + axis * 50, 10.0):
                            raise RuntimeError("正式子弹出生输入失败")
                        continue
                    if not subject.preview_hit(region, unreal.Vector(*direction), wound_strength):
                        raise RuntimeError("标准点命中入口拒绝预览指令")
                record["shotSeconds"].append(elapsed)
                data["shot"] += 1
            sample = {"seconds": elapsed, "performance": list(unreal.BBBAnimationGraphEditorLibrary.read_performance_frame_metrics())}
            tail = .25 + max(0, shots - 1) * interval_seconds
            if capture_images and camera and elapsed >= tail + 1.5 and not data["groundView"]:
                residue = json.loads(unreal.BBBBloodResidueEditorLibrary.inspect_residue(world))
                surfaces = residue["visibleResidues"]
                if surfaces:
                    largest = max(surfaces, key=lambda item: math.prod(float(value) for value in re.findall(r"[YZ]=(-?\d+(?:\.\d+)?)", item["size"])))
                    coordinates = [float(value) for value in re.findall(r"[XYZ]=(-?\d+(?:\.\d+)?)", largest["position"])]
                    if len(coordinates) == 3:
                        focus = unreal.Vector(*coordinates)
                        location = focus + unreal.Vector(-180, -240, 400)
                        camera.set_actor_location_and_rotation(location, unreal.MathLibrary.find_look_at_rotation(location, focus), False, True)
                        capture.set_editor_property("fov_angle", 50.0)
                        record["groundResidue"] = residue
                        data["groundView"] = True
            if capture_images and camera and elapsed < tail + 2.75:
                actual_view = unreal.GameplayStatics.get_player_camera_manager(world, 0).get_camera_location()
                sample["viewLocation"] = [actual_view.x, actual_view.y, actual_view.z]
                if elapsed - data["lastImage"] >= 1.0 / 60.0 - .0001:
                    capture.capture_scene()
                    path = os.path.join(directory, "frame_" + str(len(record["imagePaths"])).zfill(4) + ".png")
                    unreal.ImageWriteBlueprintLibrary.export_to_disk(target, path, options)
                    record["imagePaths"].append(path)
                    record["imageSeconds"].append(elapsed)
                    record["wallSeconds"].append(time.monotonic() - data["wallStart"])
                    record["imagePhases"].append("ground" if data["groundView"] else "impact")
                    data["lastImage"] = elapsed
                sample["bloodRuntime"] = str(unreal.BBBNiagaraEditorLibrary.inspect_pie_system(
                    "/Game/_Project/Mass/Monster/Zombie/Effects/NS_BBBZombieBloodImpact"))
                sample["physics"] = json.loads(unreal.BBBHitReactionEditorLibrary.inspect_physics_state(subjects[0].target_mesh))
            record["samples"].append(sample)
            end = .25 + max(0, shots - 1) * interval_seconds + 3.0
            if elapsed >= end:
                if not all(os.path.isfile(path) and os.path.getsize(path) > 1024 for path in record["imagePaths"]):
                    if elapsed > end + 5.0:
                        raise RuntimeError("采样图像导出超时")
                    return
                complete()
        except Exception as error:
            complete(error)

    captures[identifier] = record
    from BBBMcpCapabilities import register_activity
    register_activity("hit:" + identifier, lambda: record, blocking=False, wait=False)
    try:
        data["handle"] = unreal.register_slate_post_tick_callback(tick)
    except Exception:
        cleanup()
        captures.pop(identifier)
        raise
    return json.dumps({"captureId": identifier, "status": "pending", "temporaryScene": True}, ensure_ascii=False)
