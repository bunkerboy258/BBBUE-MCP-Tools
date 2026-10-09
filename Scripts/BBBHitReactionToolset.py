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
_acceptance_population = {}


@unreal.uclass()
class BBBHitReactionToolset(unreal.ToolsetDefinition):
    """/** 配置骨骼物理受击资产并移除被替换的动画偏转层 */"""

    @mcp_tool
    @staticmethod
    def inspect_pie_audio_device() -> str:
        """
        /**
         * @return 当前 PIE 音频设备 静音 总音量与非实时混音状态 不修改配置
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("音频设备诊断需要当前 PIE 世界")
        return str(unreal.BBBHitReactionEditorLibrary.inspect_audio_device(world))

    @mcp_tool
    @staticmethod
    def create_zombie_sealed_part_meshes(source_mesh_path: str, root_bone: str, output_folder: str, rebuild_existing: bool = False) -> str:
        """
        /**
         * @param source_mesh_path	只读使用的完整僵尸网格
         * @param root_bone	断开处骨骼名称
         * @param output_folder	新增封闭部件的自有目录
         * @param rebuild_existing	显式重建完整的同名自有部件 必须独占签出 不保留旧版本
         * @return 部件和封口路径及闭环诊断 不自动保存
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建断肢资产")
        if not output_folder.startswith("/Game/_Project/") or not re.fullmatch(r"/Game/_Project/[A-Za-z0-9_/]+", output_folder):
            raise RuntimeError("新增断肢必须使用明确的自有目录")
        if root_bone not in {"head", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r"}:
            raise RuntimeError("仅支持本轮五个已批准的断开部位")
        source = unreal.load_asset(source_mesh_path)
        if not isinstance(source, unreal.SkeletalMesh):
            raise RuntimeError("源资产不是完整骨骼网格")
        prefix = output_folder + "/SM_" + str(source.get_name()) + "_" + root_bone
        destinations = [prefix + "_Part", prefix + "_Cap"]
        if not isinstance(rebuild_existing, bool):
            raise RuntimeError("重建选项必须为布尔值")
        existing = [path for path in destinations if unreal.EditorAssetLibrary.does_asset_exist(path)]
        if existing and not rebuild_existing:
            raise RuntimeError("部件资产已经存在 拒绝覆盖")
        if rebuild_existing and len(existing) != 2:
            raise RuntimeError("显式重建必须有完整的同名部件和封口")
        material_path = "/Game/_Project/System/Mass/Monster/Zombie/Shared/Severing/M_BBBZombieCutSurface"
        if not unreal.EditorAssetLibrary.does_asset_exist(material_path):
            destinations.append(material_path)
        require_asset_write(existing, [path for path in destinations if path not in existing])
        result = str(unreal.BBBZombieSeveringEditorLibrary.create_sealed_part_meshes(source, root_bone, output_folder, rebuild_existing))
        if result.startswith("失败"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def configure_monster_severing_parts(definition_path: str, parts_json: str) -> str:
        """
        /**
         * @param definition_path	已独占签出的正式僵尸配置
         * @param parts_json	五个部位的 region bone part cap 数组
         * @return 读取回来的资源对应表 不自动保存
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改断肢配置")
        if not definition_path.startswith("/Game/_Project/"):
            raise RuntimeError("只修改自有僵尸配置")
        rows = json.loads(parts_json)
        expected = {1: (unreal.BBBMonsterHitRegion.HEAD, "head"),
            2: (unreal.BBBMonsterHitRegion.LEFT_ARM, "upperarm_l"),
            3: (unreal.BBBMonsterHitRegion.RIGHT_ARM, "upperarm_r"),
            4: (unreal.BBBMonsterHitRegion.LEFT_LEG, "thigh_l"),
            5: (unreal.BBBMonsterHitRegion.RIGHT_LEG, "thigh_r")}
        if not isinstance(rows, list) or len(rows) != 5 or {row.get("region") for row in rows} != set(expected):
            raise RuntimeError("五个损毁部位必须完整且不重复")
        settings = unreal.load_asset(definition_path)
        if not isinstance(settings, unreal.BBBMonsterDefinition):
            raise RuntimeError("僵尸配置无效")
        parts = []
        for row in rows:
            region, bone = expected[row["region"]]
            if row.get("bone") != bone:
                raise RuntimeError("损毁部位与断开骨骼不匹配")
            meshes = [unreal.load_asset(row.get(key, "")) for key in ("part", "cap")]
            if any(not isinstance(mesh, unreal.StaticMesh) or not str(mesh.get_path_name()).startswith("/Game/_Project/") for mesh in meshes):
                raise RuntimeError("缺少自有的封闭部件或身体封口")
            part = unreal.BBBMonsterSeveredPartDefinition()
            part.set_editor_property("region", region)
            part.set_editor_property("bone", bone)
            part.set_editor_property("detached_mesh", meshes[0])
            part.set_editor_property("cap_mesh", meshes[1])
            parts.append(part)
        require_write_access(settings)
        settings.set_editor_property("severed_parts", parts)
        return json.dumps({"definition": definition_path, "parts": rows, "saved": False}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_blood_residue_material(material_path: str, mask_path: str, noise_path: str) -> str:
        """
        /**
         * 创建不存在的自有环境血迹父材质 原包不变
         * @param material_path	新材质路径
         * @param mask_path	初始形状纹理
         * @param noise_path	细节噪声纹理
         * @return 原生创建 保存结果
         */
        """
        if not material_path.startswith("/Game/_Project/") or unreal.EditorAssetLibrary.does_asset_exist(material_path):
            raise RuntimeError("仅创建不存在的自有材质")
        if not isinstance(unreal.load_asset(mask_path), unreal.Texture) or not isinstance(unreal.load_asset(noise_path), unreal.Texture):
            raise RuntimeError("需要有效形状与噪声纹理")
        require_asset_write([], [material_path])
        result = str(unreal.BBBBloodResidueEditorLibrary.create_residue_material(material_path, mask_path, noise_path))
        if not result.startswith("OK:"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def preview_blood_residue(settings_path: str, positions_json: str, direction: list[float], normal: list[float], seed: int = 1) -> str:
        """
        /**
         * 当前 PIE 纯表现验收 使用正式配置 不修改生命和资产
         * @param settings_path	正式血效配置
         * @param positions_json	一至六十四个接触位置 JSON 数组
         * @param direction	入射方向
         * @param normal	表面外法线
         * @param seed	变化种子
         * @return 表现接触提交结果
         */
        """
        positions = json.loads(positions_json)
        if not isinstance(positions, list):
            raise RuntimeError("接触位置必须是数组")
        direction = list(direction)
        normal = list(normal)
        vectors = [*positions, direction, normal]
        if not positions or len(positions) > 64 or any(not isinstance(value, list) or len(value) != 3 or not all(isinstance(item, (int, float)) and math.isfinite(item) for item in value) for value in vectors):
            raise RuntimeError("需要有限且有效的三维接触输入")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("表现验收需要带渲染的 PIE")
        result = str(unreal.BBBBloodResidueEditorLibrary.preview_residue(world, settings_path,
            [unreal.Vector(*value) for value in positions], unreal.Vector(*direction), unreal.Vector(*normal), seed))
        if not result.startswith("OK:"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def inspect_blood_residue() -> str:
        """/** @return 当前 PIE 血迹数量 有效形状 方向 寿命与处理预算 */"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("需要当前 PIE")
        return str(unreal.BBBBloodResidueEditorLibrary.inspect_residue(world))

    @mcp_tool
    @staticmethod
    def start_blood_residue_capture(settings_path: str, scenario: str, file_prefix: str, seed: int = 1, duration_seconds: float = 4.0, aging_time_scale: float = 1.0) -> str:
        """
        /**
         * 创建短时隔离平台并采集环境血迹 不保存关卡
         * @param settings_path	正式血效配置
         * @param scenario	floor wall slope edge accumulation 四类表面或连续命中
         * @param file_prefix	Saved/temp 下的任务目录名
         * @param seed	变化种子
         * @param duration_seconds	四至一百三十秒实际游戏时间
         * @param aging_time_scale	落定六秒后寿命验收时间倍率 一至二十 完成时还原
         * @return 采样编号 使用 inspect_skeletal_hit_reaction_capture 查询
         */
        """
        if scenario not in {"floor", "wall", "slope", "edge", "accumulation"} or not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix):
            raise RuntimeError("场景或任务目录无效")
        if not math.isfinite(duration_seconds) or not 4.0 <= duration_seconds <= 130.0:
            raise RuntimeError("寿命采样需要四至一百三十秒")
        if not math.isfinite(aging_time_scale) or not 1.0 <= aging_time_scale <= 20.0:
            raise RuntimeError("寿命验收倍率需要一至二十")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("环境画面采集需要带渲染的 PIE")
        if any(item["status"] == "pending" for item in _captures.values()):
            raise RuntimeError("已有采样尚未完成")
        settings = unreal.load_asset(settings_path)
        if not isinstance(settings, unreal.BBBMonsterBloodPresentationDefinition):
            raise RuntimeError("正式血效配置无效")
        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
        neutral = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
        identifier = str(uuid.uuid4())
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix, identifier))
        os.makedirs(directory, exist_ok=False)
        actors = []

        def spawn(kind, location, rotation=unreal.Rotator(), scale=unreal.Vector(1, 1, 1)):
            """/** @return 仅存在本次 PIE 的验收演员 */"""
            actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, kind, unreal.Transform(location=location, rotation=rotation, scale=scale))
            if actor is None:
                raise RuntimeError("短时验收演员创建失败")
            actors.append(actor)
            return actor

        record = {"status": "pending", "captureId": identifier, "scenario": scenario, "imagePaths": [], "samples": [],
                  "durationSeconds": duration_seconds, "agingTimeScale": aging_time_scale, "maxTraceCount": 0, "maxAdvanceMilliseconds": 0.0}
        data = {"handle": None, "lastImage": -1.0, "burst": 0, "finishing": False, "closeFocus": None,
                "originalTimeScale": unreal.GameplayStatics.get_global_time_dilation(world), "accelerated": False}
        try:
            floor = spawn(unreal.StaticMeshActor, unreal.Vector(0, 0, 19990), scale=unreal.Vector(40, 40, .2))
            floor.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
            floor.static_mesh_component.set_static_mesh(cube)
            floor.static_mesh_component.set_material(0, neutral)
            floor.static_mesh_component.set_collision_profile_name("BlockAll")
            floor.static_mesh_component.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
            if scenario == "slope":
                floor.set_actor_rotation(unreal.Rotator(pitch=20, yaw=0, roll=0), True)
            if scenario == "edge":
                floor.set_actor_scale3d(unreal.Vector(12, 40, .2))
            if scenario == "wall":
                wall = spawn(unreal.StaticMeshActor, unreal.Vector(750, 0, 20200), scale=unreal.Vector(.2, 40, 4))
                wall.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                wall.static_mesh_component.set_static_mesh(cube)
                wall.static_mesh_component.set_material(0, neutral)
                wall.static_mesh_component.set_collision_profile_name("BlockAll")
                wall.static_mesh_component.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
            light = spawn(unreal.PointLight, unreal.Vector(-400, -500, 21500))
            light_component = light.get_component_by_class(unreal.PointLightComponent)
            light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
            light_component.set_intensity(1600000.0)
            light_component.set_attenuation_radius(7000.0)
            camera_location = unreal.Vector(-1600, -2000, 22000)
            if scenario == "wall":
                camera_location = unreal.Vector(-1400, -1700, 21200)
            camera = spawn(unreal.SceneCapture2D, camera_location,
                unreal.MathLibrary.find_look_at_rotation(camera_location, unreal.Vector(0, 0, 20100)))
            target = unreal.RenderingLibrary.create_render_target2d(world, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property("texture_target", target)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("capture_every_frame", False)
            capture.set_editor_property("capture_on_movement", False)
            exposure = unreal.PostProcessSettings()
            exposure.set_editor_property("override_auto_exposure_method", True)
            exposure.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
            exposure.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
            exposure.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
            capture.set_editor_property("post_process_settings", exposure)
            options = unreal.ImageWriteOptions()
            options.set_editor_property("format", unreal.DesiredImageFormat.PNG)
            options.set_editor_property("overwrite_file", False)
            options.set_editor_property("compression_quality", 0)
            positions = [[-500.0, (index - 2) * 350.0, 20100.0] for index in range(5)]
            if scenario == "wall":
                positions = [[500.0, (index - 2) * 350.0, 20200.0] for index in range(5)]
            if scenario == "slope":
                positions = [[-400.0, (index - 2) * 350.0, 20220.0] for index in range(5)]
            if scenario == "edge":
                positions = [[0.0, (index - 2) * 350.0, 20100.0] for index in range(5)]
            if scenario == "accumulation":
                positions = [[-400.0, 0.0, 20100.0]] * 8
            data["start"] = unreal.GameplayStatics.get_time_seconds(world)
            BBBHitReactionToolset.preview_blood_residue(settings_path, json.dumps(positions), [1, 0, 0], [1, 0, 0], seed)
        except Exception:
            for actor in actors:
                actor.destroy_actor()
            raise
        _captures[identifier] = record

        def complete(error=None):
            """/** @return 结束采样并销毁全部短时演员 */"""
            unreal.unregister_slate_post_tick_callback(data["handle"])
            if data["accelerated"] and unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() == world:
                unreal.GameplayStatics.set_global_time_dilation(world, data["originalTimeScale"])
            for actor in actors:
                actor.destroy_actor()
            record["temporaryActorsDestroyed"] = True
            record["status"] = "failed" if error else "completed"
            if error:
                record["error"] = str(error)
            report = os.path.join(directory, "capture.json")
            with open(report, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
            record["reportPath"] = report
            record["sampleFrames"] = len(record["samples"])
            record.pop("samples")

        def tick(delta_seconds):
            """/** @return 按真实游戏时间采集落地与连续命中 */"""
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                    raise RuntimeError("采样期间 PIE 已结束")
                elapsed = unreal.GameplayStatics.get_time_seconds(world) - data["start"]
                residue = json.loads(unreal.BBBBloodResidueEditorLibrary.inspect_residue(world))
                record["maxTraceCount"] = max(record["maxTraceCount"], residue["lastTraceCount"])
                record["maxAdvanceMilliseconds"] = max(record["maxAdvanceMilliseconds"], residue["lastAdvanceMilliseconds"])
                if elapsed >= 6.0 and aging_time_scale > 1.0 and not data["accelerated"] and residue["activeFlights"] == 0:
                    unreal.GameplayStatics.set_global_time_dilation(world, aging_time_scale)
                    data["accelerated"] = True
                if scenario == "accumulation" and data["burst"] < 8 and elapsed >= (data["burst"] + 1) * .3:
                    data["burst"] += 1
                    BBBHitReactionToolset.preview_blood_residue(settings_path, json.dumps(positions), [1, 0, 0], [1, 0, 0], seed + data["burst"] * 31)
                interval = .2 if elapsed < 4.0 else 10.0
                if not data["finishing"] and (elapsed - data["lastImage"] >= interval or elapsed >= duration_seconds):
                    if elapsed >= 1.8:
                        close_focus = unreal.Vector(350, 0, 20000)
                        if elapsed < 4.0 and residue["visibleResidues"]:
                            points = [list(map(float, re.findall(r"[XYZ]=(-?\d+(?:\.\d+)?)", item["position"]))) for item in residue["visibleResidues"]]
                            if all(len(point) == 3 for point in points):
                                data["closeFocus"] = unreal.Vector(*[sum(point[axis] for point in points) / len(points) for axis in range(3)])
                        if data["closeFocus"] is not None:
                            close_focus = data["closeFocus"]
                        close_location = close_focus + unreal.Vector(-450, -600, 1000)
                        if scenario == "wall":
                            close_location = unreal.Vector(-300, -800, 20700)
                            close_focus = unreal.Vector(740, 0, 20200)
                        camera.set_actor_location_and_rotation(close_location,
                            unreal.MathLibrary.find_look_at_rotation(close_location, close_focus), False, True)
                        capture.set_editor_property("fov_angle", 50.0)
                    capture.capture_scene()
                    path = os.path.join(directory, "frame_" + str(len(record["imagePaths"])).zfill(3) + ".png")
                    unreal.ImageWriteBlueprintLibrary.export_to_disk(target, path, options)
                    record["imagePaths"].append(path)
                    record["samples"].append({"seconds": elapsed,
                        "residue": residue,
                        "performance": list(unreal.BBBAnimationGraphEditorLibrary.read_performance_frame_metrics())})
                    data["lastImage"] = elapsed
                    data["finishing"] = elapsed >= duration_seconds
                if elapsed >= duration_seconds:
                    if not all(os.path.isfile(path) and os.path.getsize(path) >= 1024 for path in record["imagePaths"]):
                        if elapsed > duration_seconds + 5.0:
                            raise RuntimeError("画面导出超时")
                        return
                    complete()
            except Exception as error:
                complete(error)

        try:
            data["handle"] = unreal.register_slate_post_tick_callback(tick)
        except Exception:
            for actor in actors:
                actor.destroy_actor()
            _captures.pop(identifier)
            raise
        return json.dumps({"captureId": identifier, "status": "pending", "directory": directory}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def spawn_mass_hit_acceptance_population(config_paths: list[str], center: list[float], spacing: float = 200.0) -> str:
        """
        /**
         * 使用正式配置与正式 LOD 生成受击验收实体 每种一个 不修改资产
         * @param config_paths	互不重复的正式配置 最多十六种
         * @param center	出生行中心 三个厘米坐标
         * @param spacing	相邻实体距离 至少二百厘米
         * @return 实际创建实体的只读快照
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or not config_paths or len(config_paths) > 16 or len(set(config_paths)) != len(config_paths):
            raise RuntimeError("需要当前 PIE 和明确的正式实体配置")
        if len(center) != 3 or not all(math.isfinite(value) for value in center) or not math.isfinite(spacing) or spacing < 200.0:
            raise RuntimeError("验收出生位置或间距无效")
        previous_world = _acceptance_population.get("worldObject")
        try:
            same_world = previous_world is not None and unreal.SystemLibrary.is_valid(previous_world) and previous_world == world
        except (TypeError, ReferenceError):
            same_world = False
        if same_world:
            raise RuntimeError("本 PIE 已创建正式受击验收群体")
        configs = [unreal.load_asset(path) for path in config_paths]
        if any(not isinstance(config, unreal.MassEntityConfigAsset) for config in configs):
            raise RuntimeError("正式 Mass 配置不存在")
        entities = []
        try:
            for index, config in enumerate(configs):
                location = unreal.Vector(center[0] + spacing * 0.5,
                    center[1] + (index - (len(configs) - 1) * 0.5) * spacing + spacing * 0.5, center[2])
                entities.extend(unreal.BBBMassValidationLibrary.spawn_population(world, [config], 1, location, spacing))
            if len(entities) != len(configs):
                raise RuntimeError("正式验收实体创建数量不一致")
        except Exception:
            unreal.BBBMassValidationLibrary.destroy_population(world, entities)
            raise
        _acceptance_population.clear()
        _acceptance_population.update({"worldObject": world, "configs": configs, "entities": entities})
        return str(unreal.BBBMassValidationLibrary.inspect_population(world, entities))

    @mcp_tool
    @staticmethod
    def inspect_player_weapon_hit_state() -> str:
        """
        /**
         * 只读检查玩家武器伤害权限 弹量与枪口方向
         * @return 当前 PIE 玩家与步枪事实
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("需要当前 PIE 世界")
        return str(unreal.BBBHitReactionEditorLibrary.inspect_player_weapon_hit_state(world))

    @mcp_tool
    @staticmethod
    def start_player_weapon_hit_capture(file_prefix: str, duration_seconds: float = 3.0, width: int = 960, height: int = 540, blood_system_path: str = "") -> str:
        """
        /**
         * 跨真实游戏帧采集玩家视点及真实实体状态 不生成子弹或修改伤害
         * @param file_prefix Saved/temp 下的任务目录名
         * @param duration_seconds 游戏时间采样秒数 零点五至十二
         * @param width 图像宽度 三百二十至一千九百二十
         * @param height 图像高度 一百八十至一千零八十
         * @param blood_system_path	可选血效系统 同帧记录真实粒子状态
         * @return 采样编号 用 inspect_skeletal_hit_reaction_capture 查询
         */
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_prefix) or not math.isfinite(duration_seconds) or not 0.5 <= duration_seconds <= 12.0:
            raise RuntimeError("任务目录或采样时长无效")
        if not 320 <= width <= 1920 or not 180 <= height <= 1080:
            raise RuntimeError("玩家截图尺寸无效")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise RuntimeError("玩家视点采样需要带渲染的 PIE")
        if any(item["status"] == "pending" for item in _captures.values()):
            raise RuntimeError("已有受击采样尚未完成")
        manager = unreal.GameplayStatics.get_player_camera_manager(world, 0)
        if manager is None:
            raise RuntimeError("本地玩家相机不存在")
        blood_system = unreal.load_asset(blood_system_path) if blood_system_path else None
        if blood_system_path and not isinstance(blood_system, unreal.NiagaraSystem):
            raise RuntimeError("血效采样目标不是 Niagara 系统")
        identifier = str(uuid.uuid4())
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix, identifier))
        os.makedirs(directory, exist_ok=False)
        camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, unreal.SceneCapture2D, unreal.Transform())
        if camera is None:
            raise RuntimeError("玩家采样相机创建失败")
        try:
            target = unreal.RenderingLibrary.create_render_target2d(world, width, height, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property("texture_target", target)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("capture_every_frame", False)
            capture.set_editor_property("capture_on_movement", False)
            write_options = unreal.ImageWriteOptions()
            write_options.set_editor_property("format", unreal.DesiredImageFormat.PNG)
            write_options.set_editor_property("overwrite_file", False)
            write_options.set_editor_property("compression_quality", 0)
        except Exception:
            camera.destroy_actor()
            raise
        record = {"status": "pending", "captureId": identifier, "playerView": True, "includesUI": False,
                  "imagePaths": [], "imageSeconds": [], "samples": [], "durationSeconds": duration_seconds}
        _captures[identifier] = record
        data = {"start": unreal.GameplayStatics.get_time_seconds(world), "last": -1.0, "lastImage": -1.0, "handle": None}

        def complete(error=None):
            """/** @return 销毁相机并保存完整采样 失败时保留诊断 */"""
            unreal.unregister_slate_post_tick_callback(data["handle"])
            camera.destroy_actor()
            record["temporaryActorsDestroyed"] = True
            record["status"] = "failed" if error else "completed"
            if error:
                record["error"] = str(error)
            report = os.path.join(directory, "capture.json")
            with open(report, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
            record["reportPath"] = report
            record["sampleFrames"] = len(record["samples"])
            record.pop("samples")

        def tick(delta_seconds):
            """/** @return 依据实际游戏时间采样 不使用截图数量推算时长 */"""
            try:
                if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                    raise RuntimeError("玩家采样期间 PIE 已结束")
                now = unreal.GameplayStatics.get_time_seconds(world)
                if now == data["last"]:
                    return
                data["last"] = now
                elapsed = now - data["start"]
                if elapsed < duration_seconds and elapsed - data["lastImage"] >= 1.0 / 60.0 - 0.0001:
                    camera.set_actor_location_and_rotation(manager.get_camera_location(), manager.get_camera_rotation(), False, True)
                    capture.set_editor_property("fov_angle", manager.get_fov_angle())
                    capture.capture_scene()
                    filename = "frame_" + str(len(record["imagePaths"])).zfill(4) + ".png"
                    path = os.path.join(directory, filename)
                    unreal.ImageWriteBlueprintLibrary.export_to_disk(target, path, write_options)
                    record["imagePaths"].append(path)
                    record["imageSeconds"].append(elapsed)
                    record["samples"].append({"seconds": elapsed,
                        "bloodRuntime": str(unreal.BBBNiagaraEditorLibrary.inspect_pie_system(blood_system.get_path_name())) if blood_system else "",
                        "weapon": json.loads(unreal.BBBHitReactionEditorLibrary.inspect_player_weapon_hit_state(world)),
                        "population": json.loads(unreal.BBBMassValidationLibrary.inspect_population(world, [])),
                        "performance": list(unreal.BBBAnimationGraphEditorLibrary.read_performance_frame_metrics())})
                    data["lastImage"] = elapsed
                if elapsed >= duration_seconds:
                    if not all(os.path.isfile(path) and os.path.getsize(path) >= 1024 for path in record["imagePaths"]):
                        if elapsed > duration_seconds + 5.0:
                            raise RuntimeError("玩家画面异步导出超时")
                        return
                    complete()
            except Exception as error:
                complete(error)

        try:
            data["handle"] = unreal.register_slate_post_tick_callback(tick)
        except Exception:
            camera.destroy_actor()
            _captures.pop(identifier)
            raise
        return json.dumps({"captureId": identifier, "status": "pending", "playerView": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def normalize_hit_reaction_arm_bodies(asset_path: str, mesh_path: str) -> str:
        """
        /**
         * 统一自有手臂刚体绑定 保持参考姿势下的形状与约束 不保存
         * @param asset_path	已独占签出的物理资产
         * @param mesh_path	参考骨骼网格
         * @return 实际改绑数量
         */
        """
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("改绑物理资产前需要结束 PIE")
        asset = unreal.load_asset(asset_path)
        mesh = unreal.load_asset(mesh_path)
        if not isinstance(asset, unreal.PhysicsAsset) or not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("需要物理资产和参考骨骼网格")
        require_write_access(asset)
        count = unreal.BBBHitReactionEditorLibrary.normalize_arm_bodies(asset, mesh)
        if count < 0:
            raise RuntimeError("手臂刚体或参考姿势不满足完整改绑条件")
        return json.dumps({"asset": asset.get_path_name(), "normalizedBodies": count}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def rebuild_monster_blood_system(channel_path: str, system_path: str, spray_material_path: str, splash_material_path: str, mist_material_path: str) -> str:
        """
        /**
         * 使用指定现有材质重建并保存批量僵尸血效
         * @param channel_path	已独占签出的自有数据通道
         * @param system_path	已独占签出的自有 Niagara 系统
         * @param spray_material_path	方向血滴材质
         * @param splash_material_path	单张喷溅材质
         * @param mist_material_path	八乘八血雾序列材质
         * @return 原生构建结果
         */
        """
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("重建血效资产前需要结束 PIE")
        for path, asset_type in ((channel_path, unreal.NiagaraDataChannelAsset), (system_path, unreal.NiagaraSystem)):
            asset = unreal.load_asset(path)
            if not isinstance(asset, asset_type) or not path.startswith("/Game/_Project/"):
                raise RuntimeError("重建目标必须是现有自有血效资产")
            require_write_access(asset)
        for path in (spray_material_path, splash_material_path, mist_material_path):
            if not isinstance(unreal.load_asset(path), unreal.MaterialInterface):
                raise RuntimeError("血效材质不存在")
        result = unreal.BBBNiagaraEditorLibrary.configure_monster_blood_impact_system(
            channel_path, system_path, spray_material_path, splash_material_path, mist_material_path)
        if str(result).startswith("失败"):
            raise RuntimeError(str(result))
        return str(result)

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
    def configure_corpse_physics_asset(asset_path: str, total_mass_kg: float = 75.0) -> str:
        """
        /**
         * @param asset_path	已独占签出的自有物理资产
         * @param total_mass_kg	完整身体质量 三十五至一百五十千克
         * @return 当前刚体质量和 BBBCorpse 约束 不自动保存
         */
        """
        if not math.isfinite(total_mass_kg) or not 35.0 <= total_mass_kg <= 150.0:
            raise RuntimeError("尸体质量无效")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改物理资产")
        if not asset_path.startswith("/Game/_Project/"):
            raise RuntimeError("只修改自有物理资产")
        asset = unreal.load_asset(asset_path)
        if not isinstance(asset, unreal.PhysicsAsset):
            raise RuntimeError("物理资产不存在")
        require_write_access(asset)
        result = str(unreal.BBBHitReactionEditorLibrary.configure_corpse_physics(asset, total_mass_kg))
        if result.startswith("失败"):
            raise RuntimeError(result)
        return result

    @mcp_tool
    @staticmethod
    def inspect_physics_asset_constraints(asset_path: str) -> str:
        """
        /**
         * @param asset_path	明确的物理资产
         * @return 刚体质量和全部约束的当前值 不修改资产
         */
        """
        asset = unreal.load_asset(asset_path)
        if not isinstance(asset, unreal.PhysicsAsset):
            raise RuntimeError("物理资产不存在")
        return str(unreal.BBBHitReactionEditorLibrary.inspect_physics_asset(asset))

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
        mesh.set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
        presentation = actor.get_monster_presentation()
        state = unreal.BBBMonsterBehavior.CHASE if speed > 0.0 else unreal.BBBMonsterBehavior.IDLE
        presentation.call_method("ApplyPresentationState", (state, speed, 1.0, 1, 0.0))
        library.set_preview_hit_facts(mesh, region, unreal.Vector(*direction), 10.0)
        actors = [actor]
        subjects = [actor]
        for index in range(1, actor_count):
            subject = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, blueprint.generated_class(), unreal.Transform(location=unreal.Vector((index % 8) * 150.0, (index // 8) * 150.0, 20090.0), rotation=unreal.Rotator(yaw=180.0)))
            actors.append(subject)
            subjects.append(subject)
            subject.set_actor_enable_collision(True)
            subject.get_monster_mesh().set_forced_lod(1)
            subject.get_monster_mesh().set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
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
            write_options = unreal.ImageWriteOptions()
            write_options.set_editor_property("format", unreal.DesiredImageFormat.PNG)
            write_options.set_editor_property("overwrite_file", False)
            write_options.set_editor_property("compression_quality", 0)
            settings = unreal.PostProcessSettings()
            settings.set_editor_property("override_auto_exposure_method", True)
            settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
            settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
            settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
            capture.set_editor_property("post_process_settings", settings)
        bones = ["head", "spine_03", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r", "hand_l", "hand_r", "foot_l", "foot_r"]
        start_time = unreal.GameplayStatics.get_time_seconds(world)
        data = {"baseline": None, "start": None, "last": -1.0, "shots": 0, "samples": [], "images": [], "imageSeconds": [], "handle": None, "interrupted": False, "lastImage": -1.0}

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
                        before = data["baseline"][name]
                        current = sample["pose"][name]
                        dot = abs(sum(a * b for a, b in zip(before["rotation"], current["rotation"])))
                        peak_angles[name] = max(peak_angles[name], math.degrees(2.0 * math.acos(min(1.0, dot))))
                        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(before["position"], current["position"])))
                        peak_distances[name] = max(peak_distances[name], distance)
                rows = [sample["performance"] for sample in data["samples"] if 0.05 <= sample["seconds"] <= max(1.1, (shots - 1) * interval_seconds)]
                times = sorted(row[1] for row in rows)
                record["gameThreadMs"] = {"mean": sum(times) / len(times), "p95": times[int((len(times) - 1) * 0.95)], "samples": len(times)}
                record["peakAnglesDegrees"] = peak_angles
                record["peakDisplacementCm"] = peak_distances
                report_path = os.path.join(directory, identifier + ".json")
                with open(report_path, "w", encoding="utf-8") as stream:
                    json.dump({**record, "baseline": data["baseline"], "samples": data["samples"]}, stream, ensure_ascii=False)
                record["reportPath"] = report_path
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
                if now - start_time < (2.0 if actor_count > 1 else 0.5):
                    return
                if data["start"] is None:
                    frozen_pose = speed == 0.0 and actor_count == 1 and interrupt == "none"
                    if frozen_pose:
                        mesh.set_editor_property("pause_anims", True)
                    record["animationPausedForMeasurement"] = frozen_pose
                    data["baseline"] = pose()
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
                data["samples"].append(sample)
                if camera is not None and elapsed - data["lastImage"] >= 1.0 / 60.0 - 0.0001 and elapsed < (shots - 1) * interval_seconds + 0.8:
                    camera.capture_component2d.capture_scene()
                    filename = identifier + "_" + str(len(data["images"])).zfill(3) + ".png"
                    unreal.ImageWriteBlueprintLibrary.export_to_disk(target, os.path.join(directory, filename), write_options)
                    data["images"].append(os.path.join(directory, filename))
                    data["imageSeconds"].append(elapsed)
                    data["lastImage"] = elapsed
                if elapsed >= (shots - 1) * interval_seconds + 2.0:
                    if not all(os.path.isfile(path) and os.path.getsize(path) >= 1024 for path in data["images"]):
                        if elapsed > (shots - 1) * interval_seconds + 7.0:
                            raise RuntimeError("部位画面异步导出超时")
                        return
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
