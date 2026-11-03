import json
import math

import unreal

from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
    'inspect_static_lighting': {'center': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3}, 'extent': {'type': 'array', 'items': {'type': 'number', 'minimum': 0}, 'minItems': 3, 'maxItems': 3}},
    'build_gpu_lightmass': {
        'action': {'type': 'string', 'enum': ['start', 'status'], 'default': 'status'},
        'gi_samples': {'type': 'integer', 'minimum': 32, 'maximum': 8192, 'default': 512},
        'shadow_samples': {'type': 'integer', 'minimum': 32, 'maximum': 8192, 'default': 128},
        'tile_pool_size': {'type': 'integer', 'minimum': 16, 'maximum': 128, 'default': 32},
        'workload_factor': {'type': 'integer', 'minimum': 1, 'maximum': 8, 'default': 2},
    },
    'build_static_lighting': {'action': {'type': 'string', 'enum': ['start', 'status', 'cancel'], 'default': 'status'}, 'quality': {'type': 'integer', 'minimum': 0, 'maximum': 3, 'default': 0}, 'actor_paths_json': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'uniqueItems': True, 'default': []}},
    'inspect_navigation_route': {'points_json': {
        'type': 'array', 'minItems': 2, 'maxItems': 256,
        'items': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
    }},
    'set_static_mesh_nanite_settings': {'settings_json': {
        'type': 'object', 'minProperties': 1, 'additionalProperties': False,
        'properties': {
            'bEnabled': {'type': 'boolean'},
            'bExplicitTangents': {'type': 'boolean'},
            'positionPrecision': {'type': 'integer'},
            'normalPrecision': {'type': 'integer', 'minimum': -1, 'maximum': 16},
            'tangentPrecision': {'type': 'integer', 'minimum': -1, 'maximum': 16},
            'keepPercentTriangles': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'trimRelativeError': {'type': 'number', 'minimum': 0, 'maximum': 1000},
            'fallbackTarget': {'type': 'string', 'enum': ['Auto', 'PercentTriangles', 'RelativeError']},
            'fallbackPercentTriangles': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'fallbackRelativeError': {'type': 'number', 'minimum': 0, 'maximum': 1000},
            'shapePreservation': {'type': 'string', 'enum': ['None', 'PreserveArea', 'Voxelize']},
        },
    }},
}


@unreal.uclass()
class BBBLevelEditingToolset(unreal.ToolsetDefinition):
    """提供当前关卡的项目级编辑工具"""

    @mcp_tool
    @staticmethod
    def inspect_static_lighting(expected_level: str, center: list[float], extent: list[float]) -> str:
        """
        /**
         * 只读检查当前关卡包围盒内网格的光照 UV 与 Nanite 信息
         * @param expected_level\t明确的当前关卡包路径
         * @param center\t包围盒中心厘米 三个有限数值
         * @param extent\t包围盒半尺寸厘米 全零读取整个世界
         * @return 原生网格检查与组件清单
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("当前关卡与检查目标不匹配")
        for values in (center, extent):
            if len(values) != 3 or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                raise RuntimeError("包围盒必须为有限三元数组")
        if any(value < 0 for value in extent):
            raise RuntimeError("包围盒半尺寸不能为负")
        result = json.loads(str(unreal.BBBStaticLightingEditorLibrary.inspect_static_lighting(
            world, unreal.Vector(*center), unreal.Vector(*extent))))
        if not result.get('success'):
            raise RuntimeError(result.get('error', '原生光照检查失败'))
        return json.dumps(result, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def build_static_lighting(expected_level: str, build_data_path: str, action: str = 'status', quality: int = 0,
                              actor_paths_json: str = '[]') -> str:
        """
        /**
         * 启动 查询或取消本工具持有的原生 CPU 光照构建 完成后需显式保存关卡与构建数据
         * @param expected_level\t明确的当前关卡包路径
         * @param build_data_path\t当前关卡对应的独立 BuiltData 包路径
         * @param action\tstart 或 status 或 cancel
         * @param quality\t零至三 对应预览 中 高 正式
         * @param actor_paths_json\t明确接收烘焙的演员 空数组构建整个当前关卡
         * @return 原生运行 成功与结果采用状态 不将启动成功当作构建完成
         */
        """
        from BBBAssetWritePolicy import require_write_access
        from BBBMcpCapabilities import register_activity

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("当前关卡与构建目标不匹配")
        if action not in ('start', 'status', 'cancel') or type(quality) is not int or not 0 <= quality <= 3:
            raise RuntimeError("光照动作或质量无效")
        actor_paths = json.loads(actor_paths_json)
        if not isinstance(actor_paths, list) or any(not isinstance(path, str) or not path for path in actor_paths):
            raise RuntimeError("烘焙目标必须为有效路径数组")
        if len(set(actor_paths)) != len(actor_paths):
            raise RuntimeError("烘焙演员不能重复")
        if action == 'start':
            if build_data_path != expected_level + '_BuiltData':
                raise RuntimeError("构建数据路径必须属于目标关卡")
            require_write_access(world)
            require_write_access(build_data_path)

        def status():
            result = json.loads(str(unreal.BBBStaticLightingEditorLibrary.build_static_lighting(
                world, 'status', 0, [])))
            if not result.get('success'):
                raise RuntimeError(result.get('error', '原生光照状态查询失败'))
            return result

        result = json.loads(str(unreal.BBBStaticLightingEditorLibrary.build_static_lighting(
            world, action, quality, actor_paths)))
        if not result.get('success'):
            raise RuntimeError(result.get('error', '原生光照构建失败'))
        if result.get('running'):
            register_activity('lighting:' + result['id'], status)
        return json.dumps(result, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def reuse_authored_lighting(expected_level: str, source_level: str, source_build_data_path: str,
                               dry_run: bool = True) -> str:
        """
        /**
         * 核对原作者光照映射并绑定到几何一致的当前项目关卡 来源只读
         * @param expected_level	明确的当前项目关卡包路径
         * @param source_level	只读原作者地图包路径
         * @param source_build_data_path	只读原作者构建数据包路径
         * @param dry_run	为真时不修改当前关卡
         * @return 原生匹配覆盖与实际绑定结果 不触发烘焙
         */
        """
        from BBBAssetWritePolicy import require_write_access
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("当前关卡与原作者光照复用目标不匹配")
        if not dry_run:
            require_write_access(world)
        result = json.loads(str(unreal.BBBStaticLightingEditorLibrary.reuse_authored_lighting(
            world, source_level, source_build_data_path, dry_run)))
        if not result.get('success'):
            raise RuntimeError(result.get('error', '原作者光照核对失败'))
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def build_gpu_lightmass(expected_level: str, build_data_path: str, action: str = 'status',
                            gi_samples: int = 512, shadow_samples: int = 128,
                            tile_pool_size: int = 32, workload_factor: int = 2) -> str:
        """
        /**
         * 使用引擎 GPU Lightmass 整图烘焙 并登记实际运行状态
         * @param expected_level	明确的当前关卡包路径
         * @param build_data_path	目标关卡独立构建数据包
         * @param action	start 或 status
         * @param gi_samples	每纹素间接光采样数
         * @param shadow_samples	静止灯光阴影采样数
         * @param tile_pool_size	显存瓦片池边长
         * @param workload_factor	关闭实时视口后的工作负载倍率
         * @return 原生运行状态与进度 停止不单独证明结果成功
         */
        """
        from BBBAssetWritePolicy import require_write_access
        from BBBMcpCapabilities import register_activity

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("当前关卡与 GPU 烘焙目标不匹配")
        if build_data_path != expected_level + '_BuiltData' or action not in ('start', 'status'):
            raise RuntimeError("GPU 烘焙动作或独立构建数据路径无效")
        if not hasattr(unreal, 'GPULightmassSubsystem'):
            raise RuntimeError("未启用 GPU Lightmass 插件 需要启用后重启编辑器")
        library = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.SubsystemBlueprintLibrary"))
        subsystem = library.call_method("GetWorldSubsystem", (world, unreal.GPULightmassSubsystem))
        if subsystem is None:
            raise RuntimeError("当前世界没有 GPU Lightmass 子系统")

        def status():
            running = bool(subsystem.is_running())
            percent = int(subsystem.get_percentage())
            return {'status': 'running' if running else 'completed', 'running': running,
                    'percentage': percent, 'backend': 'GPU Lightmass',
                    'result_requires_completion_log': True, 'level': expected_level}

        if action == 'status':
            return json.dumps(status(), ensure_ascii=False)
        require_write_access(world)
        require_write_access(build_data_path)
        if subsystem.is_running() or unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("GPU 烘焙已运行或当前处于 PIE")
        for value, lower, upper in ((gi_samples, 32, 8192), (shadow_samples, 32, 8192),
                                    (tile_pool_size, 16, 128), (workload_factor, 1, 8)):
            if type(value) is not int or not lower <= value <= upper:
                raise RuntimeError("GPU 烘焙参数越界")
        settings = subsystem.get_settings()
        values = {'mode': unreal.GPULightmassMode.FULL_BAKE,
                  'gi_samples': gi_samples, 'stationary_light_shadow_samples': shadow_samples,
                  'lightmap_tile_pool_size': tile_pool_size,
                  'tile_passes_in_slow_mode': 1, 'tile_passes_in_full_speed_mode': workload_factor,
                  'use_irradiance_caching': False, 'use_first_bounce_ray_guiding': False,
                  'compress_lightmaps': True,
                  'denoising_options': unreal.GPULightmassDenoisingOptions.ON_COMPLETION,
                  'volumetric_lightmap_quality_multiplier': 2,
                  'volumetric_lightmap_detail_cell_size': 200}
        for name, value in values.items():
            settings.set_editor_property(name, value)
        subsystem.set_realtime(False)
        subsystem.launch()
        result = status()
        if not result['running']:
            raise RuntimeError("GPU Lightmass 未能启动 请检查 DX12 光追与显存日志")
        register_activity('gpu_lighting:' + world.get_path_name(), status)
        unreal.log('[BBBGpuLightmass] FullBake started ' + json.dumps(result, ensure_ascii=False))
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def place_actor_from_class(asset_path: str, class_path: str, label: str,
                               location: list[float], rotation: list[float]) -> str:
        """
        /**
         * 在明确的当前关卡创建并保存一个独立演员 拒绝重复标签
         * @param asset_path	预期当前关卡的包路径
         * @param class_path	原生类或蓝图生成类完整路径
         * @param label	关卡内唯一标签
         * @param location	世界位置厘米 三个有限数值
         * @param rotation	俯仰 偏航 滚转角度 三个有限数值
         * @return 已保存对象路径与实际变换
         */
        """
        from BBBAssetWritePolicy import require_write_access

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止放置关卡演员")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not asset_path.startswith("/Game/") or world.get_path_name().split(".", 1)[0] != asset_path:
            raise RuntimeError("活动关卡与明确目标不匹配")
        for values in (location, rotation):
            if len(values) != 3 or not all(isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value) for value in values):
                raise RuntimeError("变换必须为三个有限数值")
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if not label.strip() or any(actor.get_actor_label() == label for actor in subsystem.get_all_level_actors()):
            raise RuntimeError("演员标签为空或重复")
        actor_class = unreal.load_class(None, class_path)
        if actor_class is None or not isinstance(unreal.get_default_object(actor_class), unreal.Actor):
            raise RuntimeError("目标不是有效演员类")
        require_write_access(world)
        actor = subsystem.spawn_actor_from_class(actor_class, unreal.Vector(*location),
            unreal.Rotator(pitch=rotation[0], yaw=rotation[1], roll=rotation[2]))
        if actor is None:
            raise RuntimeError("演员创建失败")
        actor.set_actor_label(label)
        if actor.get_world() != world or actor.get_outer().get_path_name() != world.get_path_name() + ":PersistentLevel":
            unreal.log_error("[BBBLevel]对象不在目标持久关卡 " + actor.get_path_name())
            raise RuntimeError("创建结果不在目标持久关卡 禁止盲目重放")
        if not unreal.EditorLoadingAndSavingUtils.save_map(world, asset_path):
            unreal.log_error("[BBBLevel]已创建但保存失败 " + actor.get_path_name())
            raise RuntimeError("关卡保存失败 对象已创建 禁止盲目重放")
        actual = actor.get_actor_location()
        unreal.log("[BBBLevel]已保存关卡演员 " + actor.get_path_name())
        return json.dumps({"actor": actor.get_path_name(), "level": asset_path, "saved": True,
            "location": [actual.x, actual.y, actual.z], "rotation": list(rotation)}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_mass_display_spawners(
        expected_level: str,
        source_spawner_path: str,
        config_paths: list[str],
        center: list[float],
        spacing: float,
        radius: float,
    ) -> str:
        """
        /**
         * 在 BBBTest 保存十种出生配置各一只的统一生成入口
         * @param expected_level\t明确的 BBBTest 包路径
         * @param source_spawner_path\t当前关卡的统一生成入口
         * @param config_paths\t十个独立 BBBMonsterSpawnDefinition 资产
         * @param center\t展示中心的有限坐标
         * @param spacing\t展示间距厘米
         * @param radius\t每个入口的候选圆盘半径
         * @return 已保存入口路径 不修改出生规则资产
         */
        """
        from BBBAssetWritePolicy import require_write_access
        require_write_access()
        if expected_level != "/Game/_Project/Maps/BBBTest":
            raise RuntimeError("仅允许配置 BBBTest")
        if len(config_paths) != 10 or len(set(config_paths)) != 10:
            raise RuntimeError("必须提供十个互不重复的出生配置")
        if len(center) != 3 or any(not math.isfinite(value) for value in center):
            raise RuntimeError("展示中心无效")
        if not 100 <= spacing <= 500 or not 0 <= radius <= 100:
            raise RuntimeError("展示间距或半径超出范围")
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("持久关卡编辑必须停止 PIE")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        source = unreal.find_object(None, source_spawner_path)
        if world is None or world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("当前地图不匹配")
        if not isinstance(source, unreal.BBBMonsterSpawnerPresentationActor) or source.get_world() != world:
            raise RuntimeError("源对象不是当前地图的统一生成入口")
        assets = [unreal.load_asset(path) for path in config_paths]
        if any(not isinstance(asset, unreal.BBBMonsterSpawnDefinition) for asset in assets):
            raise RuntimeError("必须使用统一出生配置资产")
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        created = []
        for index, asset in enumerate(assets):
            duplicates = subsystem.duplicate_actors([source], world, unreal.Vector(0.0, 0.0, 0.0))
            if len(duplicates) != 1:
                raise RuntimeError("创建统一生成入口失败")
            actor = duplicates[0]
            created.append(actor)
            actor.set_editor_property("Definition", asset)
            actor.set_editor_property("Count", 1)
            region = actor.get_editor_property("Region")
            region.set_editor_property("Shape", unreal.BBBMonsterSpawnRegionShape.DISK)
            region.set_editor_property("Extent", unreal.Vector(max(1.0, radius), max(1.0, radius), 600.0))
            actor.set_editor_property("Region", region)
            actor.set_actor_location(unreal.Vector(center[0], center[1] + (index - 4.5) * spacing, center[2]), False, True)
            actor.set_actor_label("BBB_Showcase_Zombie_" + asset.get_name().removeprefix("DA_BBBMonsterSpawn_"))
        if not unreal.EditorLevelLibrary.save_current_level():
            raise RuntimeError("保存展示入口失败 已建立对象保持可检查")
        return json.dumps({"level": expected_level, "spawners": [actor.get_path_name() for actor in created], "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def spawn_pie_mass_display(
        spawner_path: str,
        config_paths: list[str],
        center: list[float],
        radius: float,
    ) -> str:
        """
        /**
         * 在房主 PIE 通过统一出生处理各提交一只临时展示小怪
         * @param spawner_path\t当前 PIE 的统一生成入口 用于确定世界与请求模板
         * @param config_paths\t一至二十个独立 BBBMonsterSpawnDefinition 资产
         * @param center\t展示圆周的有限世界中心
         * @param radius\t圆周半径 多只展示至少一百厘米
         * @return 已提交请求入口 实际数量须读取 ReadCreatedCount 不保存资产
         */
        """
        if not 1 <= len(config_paths) <= 20 or len(set(config_paths)) != len(config_paths):
            raise RuntimeError("必须提供一至二十个互不重复的出生配置")
        if len(center) != 3 or any(not math.isfinite(value) for value in center):
            raise RuntimeError("展示中心无效")
        if not math.isfinite(radius) or not 0 <= radius <= 2000 or (len(config_paths) > 1 and radius < 100):
            raise RuntimeError("展示圆周半径无效")
        source = unreal.find_object(None, spawner_path)
        if not isinstance(source, unreal.BBBMonsterSpawnerPresentationActor) or source.get_world() not in unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("目标必须是当前 PIE 的统一生成入口")
        if not source.has_authority():
            raise RuntimeError("展示请求必须投给房主")
        assets = [unreal.load_asset(path) for path in config_paths]
        if any(not isinstance(asset, unreal.BBBMonsterSpawnDefinition) for asset in assets):
            raise RuntimeError("必须使用统一出生配置资产")
        world = source.get_world()
        created = []
        fields = ("Pool", "CandidateCount", "CandidatesPerFrame", "CreatesPerFrame", "MaxObservers",
                  "MinPlayerDistance", "MinSpacing", "GroundTraceDistance", "bRequirePath", "bAvoidVisible",
                  "Seed", "bRandomYaw", "FixedYaw")
        try:
            for index, asset in enumerate(assets):
                angle = index * math.tau / len(assets)
                location = unreal.Vector(center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius, center[2])
                transform = unreal.Transform(location=location)
                actor = unreal.BBBBlueprintEditorLibrary.begin_transient_pie_actor(world, unreal.BBBMonsterSpawnerPresentationActor.static_class(), transform)
                if actor is None:
                    raise RuntimeError("临时展示入口创建失败")
                created.append(actor)
                settings = unreal.new_object(unreal.BBBMonsterSpawnDefinition, outer=actor)
                for name in fields:
                    settings.set_editor_property(name, asset.get_editor_property(name))
                settings.set_editor_property("bAvoidVisible", False)
                settings.set_editor_property("MinPlayerDistance", 0.0)
                settings.set_editor_property("Seed", 12345 + index)
                actor.set_editor_property("Definition", settings)
                actor.set_editor_property("EntityConfig", source.get_editor_property("EntityConfig"))
                actor.set_editor_property("Count", 1)
                actor.set_editor_property("bAutoStart", False)
                region = actor.get_editor_property("Region")
                region.set_editor_property("Shape", unreal.BBBMonsterSpawnRegionShape.DISK)
                region.set_editor_property("Extent", unreal.Vector(20.0, 20.0, 600.0))
                actor.set_editor_property("Region", region)
                unreal.BBBBlueprintEditorLibrary.finish_transient_pie_actor(actor, transform)
                if not actor.start_spawning():
                    raise RuntimeError("临时展示请求未提交")
        except Exception:
            for actor in created:
                actor.destroy_actor()
            raise
        return json.dumps({"world": world.get_path_name(), "requested": len(assets),
                           "spawners": [actor.get_path_name() for actor in created],
                           "note": "仅临时展示规则关闭可见性和安全距离 仍检查导航 地面 空间 间距与路径 不修改正式资产"}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def set_pie_paused(paused: bool) -> str:
        """暂停或继续唯一的 PIE 世界，便于检查临时 Mass 展示。"""
        worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
        if len(worlds) != 1:
            raise RuntimeError("必须恰好有一个 PIE 世界")
        world = worlds[0]
        if unreal.GameplayStatics.is_game_paused(world) != paused:
            unreal.GameplayStatics.set_game_paused(world, paused)
        actual = unreal.GameplayStatics.is_game_paused(world)
        if actual != paused:
            raise RuntimeError("设置 PIE 暂停状态失败")
        return json.dumps({"world": world.get_path_name(), "paused": actual})

    @mcp_tool
    @staticmethod
    def break_level_instance_to_current_level(
        level_instance_path: str,
        keep_folders: bool = True,
    ) -> str:
        """将指定关卡实例拆解为当前持久关卡中的独立对象"""
        if not level_instance_path:
            raise RuntimeError("关卡实例路径不能为空")

        level_instance = unreal.find_object(None, level_instance_path)

        if level_instance is None:
            raise RuntimeError("关卡实例对象不存在: {}".format(level_instance_path))

        if not isinstance(level_instance, unreal.LevelInstance):
            raise RuntimeError("目标对象不是 LevelInstance: {}".format(level_instance_path))

        result = unreal.BBBBlueprintEditorLibrary.break_level_instance_to_current_level(
            level_instance,
            keep_folders,
        )
        report = json.loads(result)

        if not report.get("success", False):
            raise RuntimeError(report.get("error", "关卡实例拆解失败"))

        return json.dumps(report, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def audit_static_scene_components(expected_level: str, actor_paths: list[str]) -> str:
        """
        /**
         * 只读统计明确演员的静态网格组件和实例 不运行构造脚本
         * @param expected_level\t预期编辑器主世界的关卡包路径
         * @param actor_paths\t一至一百二十八个当前世界演员路径
         * @return 组件网格 材质 碰撞 实例数量与三角形估计
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().rsplit(".", 1)[0] != expected_level:
            raise RuntimeError("场景审计世界不匹配")
        if not 1 <= len(actor_paths) <= 128 or len(set(actor_paths)) != len(actor_paths):
            raise RuntimeError("场景审计需要一至一百二十八个不重复演员")

        targets = []
        for path in actor_paths:
            actor = unreal.find_object(None, path)
            if not isinstance(actor, unreal.Actor) or actor.get_world() != world:
                raise RuntimeError("场景审计演员不属于当前世界 " + path)
            targets.append(actor)

        tags = {}
        rows = []
        total_instances = 0
        total_triangles = 0
        for actor in targets:
            components = []
            for component in sorted(actor.get_components_by_class(unreal.StaticMeshComponent), key=lambda value: value.get_path_name()):
                mesh = component.get_editor_property("static_mesh")
                if mesh is None:
                    continue
                mesh_path = mesh.get_path_name()
                if mesh_path not in tags:
                    data = unreal.EditorAssetLibrary.find_asset_data(mesh_path)
                    triangles = data.get_tag_value("Triangles")
                    tags[mesh_path] = int(triangles) if triangles else None

                count = 1
                if isinstance(component, unreal.InstancedStaticMeshComponent):
                    count = component.get_instance_count()
                materials = []
                for index in range(component.get_num_materials()):
                    material = component.get_material(index)
                    materials.append(material.get_path_name() if material else None)
                position = component.get_world_location()
                components.append({
                    "path": component.get_path_name(),
                    "class": component.get_class().get_path_name(),
                    "mesh": mesh_path,
                    "instances": count,
                    "lod0_triangles": tags[mesh_path],
                    "materials": materials,
                    "mobility": str(component.get_editor_property("mobility")),
                    "collision": str(component.get_collision_enabled()),
                    "collision_profile": str(component.get_collision_profile_name()),
                    "simulate_physics": component.is_simulating_physics(),
                    "visible": component.is_visible(),
                    "hidden_in_game": component.get_editor_property("hidden_in_game"),
                    "cast_shadow": component.get_editor_property("cast_shadow"),
                    "position": [position.x, position.y, position.z],
                })
                total_instances += count
                if tags[mesh_path] is not None:
                    total_triangles += count * tags[mesh_path]

            rows.append({"actor": actor.get_path_name(), "class": actor.get_class().get_path_name(),
                         "components": components,
                         "instances": sum(value["instances"] for value in components)})

        return json.dumps({"world": world.get_path_name(), "actors": rows,
                           "actor_count": len(rows), "instance_count": total_instances,
                           "lod0_triangles_estimate": total_triangles}, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def create_static_actor_mesh(actor_path: str, asset_path: str, nanite_enabled: bool = False) -> str:
        """
        /**
         * 将明确演员的静态组件合并到新网格 保留原演员供独立验收
         * @param actor_path\t当前编辑器世界的明确来源演员
         * @param asset_path\t尚不存在的新网格包路径
         * @param nanite_enabled\t创建时生成精确 Nanite 保留完整源三角形和回退网格
         * @return 原材质 原几何 LOD 合并结果与枢轴
         */
        """
        from BBBAssetWritePolicy import require_write_access

        actor = unreal.find_object(None, actor_path)
        if not isinstance(actor, unreal.Actor):
            raise RuntimeError("明确来源演员不存在")
        if not asset_path.startswith("/Game/") or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("新网格目标包不合法或已存在")
        expected_materials = set()
        for component in actor.get_components_by_class(unreal.StaticMeshComponent):
            if component.get_editor_property("static_mesh") is None:
                continue
            if isinstance(component, unreal.InstancedStaticMeshComponent) and component.get_instance_count() == 0:
                continue
            for index in range(component.get_num_materials()):
                material = component.get_material(index)
                if material is not None:
                    expected_materials.add(material.get_path_name())
        require_write_access(asset_path)
        report = json.loads(unreal.BBBSceneGeometryEditorLibrary.create_static_actor_mesh(actor, asset_path, nanite_enabled))
        if not report.get("success", False):
            raise RuntimeError(report.get("error", "静态场景合并失败"))
        mesh = unreal.load_object(None, report["mesh"])
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError("合并结果不是静态网格 禁止重放")
        actual_materials = {slot.material_interface.get_path_name() for slot in mesh.get_editor_property("static_materials") if slot.material_interface is not None}
        if mesh.get_outermost().get_path_name() != asset_path or actual_materials != expected_materials or report["source_lod0_triangles"] != report["merged_lod0_triangles"]:
            report["expected_materials"] = sorted(expected_materials)
            report["actual_materials"] = sorted(actual_materials)
            removed = unreal.EditorAssetLibrary.delete_loaded_asset(mesh)
            raise RuntimeError("合并不一致 已撤销新建网格 " + str(removed) + " " + json.dumps(report, ensure_ascii=False))
        report["materials"] = sorted(actual_materials)
        if not unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False):
            raise RuntimeError("合并网格保存失败 禁止重放")
        return json.dumps(report, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def set_static_mesh_nanite_settings(asset_path: str, settings_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 一次性提交静态网格 Nanite 几何和精度设置 只触发一次网格重建
         * @param asset_path\t明确的已有静态网格资产
         * @param settings_json\t明确设置字段 其它 Nanite 字段保留
         * @param dry_run\t只核验字段并返回前后值 不重建或保存
         * @return 前后设置 保存与独立子系统回读证据
         */
        """
        from BBBAssetWritePolicy import require_write_access

        level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if level_subsystem is None or level_subsystem.is_in_play_in_editor():
            raise RuntimeError("Nanite 设置需要非 PIE 的编辑宿主")
        patch = json.loads(settings_json)
        schema = MCP_INPUTS['set_static_mesh_nanite_settings']['settings_json']['properties']
        if not isinstance(patch, dict) or not patch or set(patch) - set(schema):
            raise RuntimeError("需要明确且受支持的 Nanite 设置字段")
        properties = {
            'bEnabled': 'enabled', 'bExplicitTangents': 'explicit_tangents',
            'positionPrecision': 'position_precision', 'normalPrecision': 'normal_precision',
            'tangentPrecision': 'tangent_precision', 'keepPercentTriangles': 'keep_percent_triangles',
            'trimRelativeError': 'trim_relative_error', 'fallbackTarget': 'fallback_target',
            'fallbackPercentTriangles': 'fallback_percent_triangles',
            'fallbackRelativeError': 'fallback_relative_error', 'shapePreservation': 'shape_preservation',
        }
        enums = {
            'fallbackTarget': {'Auto': unreal.NaniteFallbackTarget.AUTO,
                               'PercentTriangles': unreal.NaniteFallbackTarget.PERCENT_TRIANGLES,
                               'RelativeError': unreal.NaniteFallbackTarget.RELATIVE_ERROR},
            'shapePreservation': {'None': unreal.NaniteShapePreservation.NONE,
                                  'PreserveArea': unreal.NaniteShapePreservation.PRESERVE_AREA,
                                  'Voxelize': unreal.NaniteShapePreservation.VOXELIZE},
        }
        for key, value in patch.items():
            rule = schema[key]
            if rule['type'] == 'boolean' and type(value) is not bool:
                raise RuntimeError("Nanite 布尔设置类型错误 " + key)
            if rule['type'] in ('number', 'integer'):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise RuntimeError("Nanite 数值设置类型错误 " + key)
                if rule['type'] == 'integer' and type(value) is not int:
                    raise RuntimeError("Nanite 整数设置类型错误 " + key)
                if value < rule.get('minimum', value) or value > rule.get('maximum', value):
                    raise RuntimeError("Nanite 数值设置超出范围 " + key)
            if key in enums and value not in enums[key]:
                raise RuntimeError("Nanite 枚举设置无效 " + key)
            if key == 'positionPrecision' and value != -2147483648 and not -6 <= value <= 13:
                raise RuntimeError("Nanite 位置精度超出范围")
        mesh = unreal.load_object(None, asset_path)
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError("明确目标不是静态网格")
        subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        settings = subsystem.get_nanite_settings(mesh)

        def geometry():
            return {'lod_count': subsystem.get_lod_count(mesh),
                    'lod0_triangles': mesh.get_num_triangles(0),
                    'nanite_triangles': mesh.get_num_nanite_triangles()}

        def read(current):
            values = {}
            for key, prop in properties.items():
                value = current.get_editor_property(prop)
                if key in enums:
                    value = next(name for name, item in enums[key].items() if value == item)
                values[key] = value
            return values

        before = read(settings)
        geometry_before = geometry()
        for key, value in patch.items():
            settings.set_editor_property(properties[key], enums[key][value] if key in enums else value)
        expected = read(settings)
        if dry_run:
            return json.dumps({'dry_run': True, 'mesh': mesh.get_path_name(), 'before': before,
                               'expected': expected, 'geometry_before': geometry_before}, ensure_ascii=False)
        require_write_access(mesh)
        subsystem.set_nanite_settings(mesh, settings, True)
        after = read(subsystem.get_nanite_settings(mesh))
        if after != expected:
            raise RuntimeError("Nanite 重建后设置不一致 禁止重放")
        if not unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False):
            raise RuntimeError("Nanite 网格保存失败 禁止重放")
        return json.dumps({'success': True, 'mesh': mesh.get_path_name(), 'before': before,
                           'after': after, 'geometry_before': geometry_before,
                           'geometry_after': geometry(), 'saved': True}, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def audit_static_actor_collision(source_actor_path: str, candidate_actor_path: str,
                                     grid_size: int = 5, tolerance_cm: float = 0.5) -> str:
        """
        /**
         * 对来源和候选演员分别采样简单与复杂碰撞 不改变碰撞或可见性
         * @param source_actor_path\t明确来源演员路径
         * @param candidate_actor_path\t明确候选演员路径
         * @param grid_size\t六向采样网格边长 二至九
         * @param tolerance_cm\t命中距离允许误差厘米 零至五
         * @return 命中与差异统计和有限样例 采样不能证明全表面完全一致
         */
        """
        source = unreal.find_object(None, source_actor_path)
        candidate = unreal.find_object(None, candidate_actor_path)
        if not isinstance(source, unreal.Actor) or not isinstance(candidate, unreal.Actor):
            raise RuntimeError("碰撞比较的明确演员不存在")
        report = json.loads(unreal.BBBSceneGeometryEditorLibrary.audit_static_actor_collision(source, candidate, grid_size, tolerance_cm))
        if not report.get("success", False):
            raise RuntimeError(report.get("error", "静态场景碰撞审计失败"))
        return json.dumps(report, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def refresh_navigation_bounds(expected_level: str, volume_paths: list[str]) -> str:
        """
        /**
         * 通知当前导航系统重新处理明确导航体积 不将请求当作构建完成
         * @param expected_level\t当前编辑器关卡包路径
         * @param volume_paths\t当前世界中已配置的导航体积路径
         * @return 体积实际范围与构建状态 后续必须查询完整路径
         */
        """
        from BBBAssetWritePolicy import require_write_access

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if unreal.EditorLevelLibrary.get_pie_worlds(False) or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("需要匹配的非 PIE 编辑器世界")
        if not 1 <= len(volume_paths) <= 64 or len(set(volume_paths)) != len(volume_paths):
            raise RuntimeError("需要一至六十四个不重复导航体积")
        navigation = unreal.NavigationSystemV1.get_navigation_system(world)
        if navigation is None:
            raise RuntimeError("当前世界没有导航系统 请先检查世界导航配置")
        volumes = []
        for path in volume_paths:
            volume = unreal.find_object(None, path)
            if not isinstance(volume, unreal.NavMeshBoundsVolume) or volume.get_world() != world:
                raise RuntimeError("明确目标不是当前世界导航体积 " + path)
            origin, extent = volume.get_actor_bounds(False)
            if min(extent.x, extent.y, extent.z) <= 0:
                raise RuntimeError("导航体积刷体为空 " + path)
            volumes.append(volume)
        require_write_access(world)
        result = []
        for volume in volumes:
            navigation.on_navigation_bounds_updated(volume)
            origin, extent = volume.get_actor_bounds(False)
            result.append({'volume': volume.get_path_name(), 'center_cm': [origin.x, origin.y, origin.z],
                           'extent_cm': [extent.x, extent.y, extent.z]})
        unreal.log("[BBBLevelNavigation]已提交边界刷新 " + str(len(result)))
        return json.dumps({'world': world.get_path_name(), 'volumes': result, 'requested': True,
                           'building_or_locked': unreal.NavigationSystemV1.is_navigation_being_built_or_locked(world)}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_navigation_route(expected_level: str, points_json: str,
                                 context_actor_path: str = '', endpoint_tolerance_cm: float = 100.0) -> str:
        """
        /**
         * 依次查询必经点之间的导航路径并拒绝将局部路径计为通过
         * @param expected_level\t当前编辑器关卡包路径
         * @param points_json\t二至二百五十六个必经世界坐标 厘米
         * @param context_actor_path\t明确导航数据或 Pawn 路径 空值使用世界默认代理
         * @param endpoint_tolerance_cm\t首尾路径点相对请求点的三维容差厘米
         * @return 各段有效性 局部标记 实际长度和路径点 不证明真实玩家通行
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if unreal.EditorLevelLibrary.get_pie_worlds(False) or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("需要匹配的非 PIE 编辑器世界")
        points = json.loads(points_json)
        if not isinstance(points, list) or not 2 <= len(points) <= 256:
            raise RuntimeError("路线需要二至二百五十六个必经点")
        for point in points:
            if not isinstance(point, list) or len(point) != 3 or not all(type(v) in (int, float) and math.isfinite(v) for v in point):
                raise RuntimeError("必经点必须是三个有限厘米数值")
        if not math.isfinite(endpoint_tolerance_cm) or not 1 <= endpoint_tolerance_cm <= 200:
            raise RuntimeError("路径端点容差须为一至二百厘米")
        context = None
        if context_actor_path:
            context = unreal.find_object(None, context_actor_path)
            if not isinstance(context, (unreal.NavigationData, unreal.Pawn, unreal.Controller)) or context.get_world() != world:
                raise RuntimeError("导航上下文不是当前世界的导航数据 Pawn 或 Controller")
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        nav_data = []
        for actor in actors:
            if isinstance(actor, unreal.RecastNavMesh):
                nav_data.append({'path': actor.get_path_name(), 'radius_cm': actor.get_editor_property('agent_radius'),
                                 'height_cm': actor.get_editor_property('agent_height')})
        navigation = unreal.NavigationSystemV1.get_navigation_system(world)
        building = unreal.NavigationSystemV1.is_navigation_being_built_or_locked(world)
        if navigation is None or building or not nav_data:
            return json.dumps({'world': world.get_path_name(), 'ready': False, 'building_or_locked': building,
                               'navigation_system': navigation is not None, 'nav_data': nav_data,
                               'all_segments_valid': False, 'segments': []}, ensure_ascii=False)
        segments = []
        for index in range(len(points) - 1):
            start, end = points[index:index + 2]
            path = unreal.NavigationSystemV1.find_path_to_location_synchronously(
                world, unreal.Vector(*start), unreal.Vector(*end), context)
            valid = path is not None and path.is_valid()
            partial = path is not None and path.is_partial()
            path_points = []
            length = 0.0
            if path is not None:
                path_points = [[p.x, p.y, p.z] for p in path.path_points]
                length = path.get_path_length()
            start_error = None
            end_error = None
            if path_points:
                start_error = math.dist(start, path_points[0])
                end_error = math.dist(end, path_points[-1])
            passed = bool(valid and not partial and len(path_points) >= 2 and math.isfinite(length)
                          and length > 0 and start_error <= endpoint_tolerance_cm and end_error <= endpoint_tolerance_cm)
            segments.append({'index': index, 'valid': valid, 'partial': partial, 'passed': passed,
                             'requested_start_cm': start, 'requested_end_cm': end, 'length_m': length / 100.0,
                             'start_error_cm': start_error, 'end_error_cm': end_error, 'path_points_cm': path_points})
        passed = all(segment['passed'] for segment in segments)
        if not passed:
            unreal.log_warning("[BBBLevelNavigation]路线包含未通过段 " + str([s['index'] for s in segments if not s['passed']]))
        return json.dumps({'world': world.get_path_name(), 'ready': True, 'building_or_locked': False,
                           'context': context_actor_path or 'world_default', 'nav_data': nav_data,
                           'all_segments_valid': passed, 'length_m': sum(s['length_m'] for s in segments),
                           'segments': segments}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def set_review_view(expected_level: str, camera_actor_path: str, location: list[float],
                        rotation: list[float], ortho_width_cm: float = 0.0, view_mode: str = 'Lit') -> str:
        """
        /**
         * 用明确相机驾驶前台视口并切换真实着色模式 供 Slate 截图验收
         * @param expected_level\t当前编辑器关卡包路径
         * @param camera_actor_path\t当前世界明确 CameraActor 路径
         * @param location\t世界位置厘米
         * @param rotation\t俯仰 偏航 滚转角度 顶视使用俯仰负九十度
         * @param ortho_width_cm\t正值开启相机正交投影 零使用透视
         * @param view_mode\tLit Unlit 或 PlayerCollision
         * @return 相机投影与实际视口着色模式 必须另取真实视口截图
         */
        """
        from BBBAssetWritePolicy import require_write_access

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if unreal.EditorLevelLibrary.get_pie_worlds(False) or world.get_path_name().split('.', 1)[0] != expected_level:
            raise RuntimeError("需要匹配的非 PIE 编辑器世界")
        for values in (location, rotation):
            if len(values) != 3 or not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                raise RuntimeError("机位必须为有限三元数组")
        if not math.isfinite(ortho_width_cm) or not 0 <= ortho_width_cm <= 200000:
            raise RuntimeError("正交宽度必须为零至二十万厘米")
        modes = {'Lit': unreal.ViewModeIndex.VMI_LIT, 'Unlit': unreal.ViewModeIndex.VMI_UNLIT,
                 'PlayerCollision': unreal.ViewModeIndex.VMI_COLLISION_PAWN}
        if view_mode not in modes:
            raise RuntimeError("不支持的审查视图模式")
        actor = unreal.find_object(None, camera_actor_path)
        if not isinstance(actor, unreal.CameraActor) or actor.get_world() != world:
            raise RuntimeError("明确目标不是当前世界 CameraActor")
        require_write_access(actor)
        actor.modify()
        component = actor.get_editor_property('camera_component')
        component.modify()
        actor.set_actor_location(unreal.Vector(*location), False, True)
        actor.set_actor_rotation(unreal.Rotator(pitch=rotation[0], yaw=rotation[1], roll=rotation[2]), True)
        projection = unreal.CameraProjectionMode.PERSPECTIVE
        if ortho_width_cm > 0:
            projection = unreal.CameraProjectionMode.ORTHOGRAPHIC
            component.set_editor_property('ortho_width', ortho_width_cm)
        component.set_editor_property('projection_mode', projection)
        actor.set_editor_property('is_editor_only_actor', True)
        level = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        key = level.get_active_viewport_config_key()
        level.pilot_level_actor(actor, key)
        level.set_exact_camera_view(True, key)
        unreal.AutomationLibrary.set_editor_active_viewport_view_mode(modes[view_mode])
        level.editor_invalidate_viewports()
        actual = unreal.AutomationLibrary.get_editor_active_viewport_view_mode()
        if actual != modes[view_mode] or level.get_pilot_level_actor(key) != actor:
            raise RuntimeError("前台视口模式或驾驶相机回读不匹配")
        unreal.log("[BBBLevelReview]前台视口 " + view_mode + " " + str(projection))
        return json.dumps({'world': world.get_path_name(), 'camera': actor.get_path_name(),
                           'projection': str(component.get_editor_property('projection_mode')),
                           'ortho_width_cm': component.get_editor_property('ortho_width'),
                           'view_mode': str(actual), 'location_cm': list(location), 'rotation_deg': list(rotation),
                           'exact_camera_view': level.get_exact_camera_view(key)}, ensure_ascii=False)


_registration = Registration([BBBLevelEditingToolset])
