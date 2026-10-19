import json
import math

import unreal

from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
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
        """在已签出关卡中保存十种配置各一只的 Mass 展示生成器。"""
        if expected_level != "/Game/_Project/Maps/BBBTest":
            raise RuntimeError("仅允许配置 BBBTest 展示关卡")
        if len(config_paths) != 10 or len(set(config_paths)) != 10:
            raise RuntimeError("必须提供十个互不重复的实体配置")
        if len(center) != 3 or not all(isinstance(value, (int, float)) for value in center):
            raise RuntimeError("展示中心必须为三个坐标值")
        if not 100 <= spacing <= 500 or not 0 <= radius <= 100:
            raise RuntimeError("展示间距或随机半径超出允许范围")
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("配置持久关卡前必须停止 PIE")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None or world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("当前编辑器关卡与预期关卡不符")
        source = unreal.find_object(None, source_spawner_path)
        if not isinstance(source, unreal.MassSpawner) or source.get_world() != world:
            raise RuntimeError("源 MassSpawner 不属于当前编辑器关卡")
        existing_labels = {actor.get_actor_label() for actor in
                           unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()}
        names = [path.rsplit("/", 1)[-1].removeprefix("MEC_BBBZombie") for path in config_paths]
        labels = ["BBB_Showcase_Zombie_" + name for name in names]
        if any(label in existing_labels for label in labels):
            raise RuntimeError("展示生成器标签已存在，拒绝重复创建")

        assets = [unreal.load_asset(path) for path in config_paths]
        if any(not isinstance(asset, unreal.MassEntityConfigAsset) for asset in assets):
            raise RuntimeError("输入包含无效 MassEntityConfigAsset")
        source_generators = source.get_editor_property("spawn_data_generators")
        if len(source_generators) != 1:
            raise RuntimeError("源生成器必须恰好包含一个出生数据生成器")
        source_generator = source_generators[0].get_editor_property("generator_instance")
        if not isinstance(source_generator, unreal.BBBMonsterSpawnGenerator):
            raise RuntimeError("源生成器必须使用 BBBMonsterSpawnGenerator")

        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        original_types = list(source.get_editor_property("entity_types"))
        original_count = source.get_editor_property("count")
        original_radius = source_generator.get_editor_property("spawn_radius")
        original_location = source.get_actor_location()
        original_label = source.get_actor_label()
        created = []
        try:
            for _ in range(9):
                duplicated = subsystem.duplicate_actors([source], world, unreal.Vector(0.0, 0.0, 0.0))
                if len(duplicated) != 1 or not isinstance(duplicated[0], unreal.MassSpawner):
                    raise RuntimeError("复制 MassSpawner 失败")
                created.append(duplicated[0])

            spawners = [source] + created
            generators = []
            for spawner in spawners:
                entries = spawner.get_editor_property("spawn_data_generators")
                if len(entries) != 1:
                    raise RuntimeError("复制后的出生生成器数量不符")
                generator = entries[0].get_editor_property("generator_instance")
                if not isinstance(generator, unreal.BBBMonsterSpawnGenerator):
                    raise RuntimeError("复制后的出生生成器类型不符")
                generators.append(generator)
            if len({generator.get_path_name() for generator in generators}) != 10:
                raise RuntimeError("出生生成器实例没有独立复制")

            for index, (spawner, generator, asset, label) in enumerate(zip(spawners, generators, assets, labels)):
                y = center[1] + (index - 4.5) * spacing
                spawner.set_editor_property("entity_types", [unreal.MassSpawnedEntityType(entity_config=asset, proportion=1.0)])
                spawner.set_editor_property("count", 1)
                generator.set_editor_property("spawn_radius", radius)
                spawner.set_actor_location(unreal.Vector(center[0], y, center[2]), False, True)
                spawner.set_actor_label(label)

            if not unreal.EditorLevelLibrary.save_current_level():
                raise RuntimeError("保存 BBBTest 关卡失败")
        except Exception:
            source.set_editor_property("entity_types", original_types)
            source.set_editor_property("count", original_count)
            source_generator.set_editor_property("spawn_radius", original_radius)
            source.set_actor_location(original_location, False, True)
            source.set_actor_label(original_label)
            for actor in created:
                subsystem.destroy_actor(actor)
            raise

        return json.dumps({"level": expected_level, "count": len(spawners),
                           "spawners": [{"actor": actor.get_path_name(), "label": label,
                                         "config": path, "location": [center[0], center[1] + (index - 4.5) * spacing, center[2]]}
                                        for index, (actor, label, path) in enumerate(zip(spawners, labels, config_paths))],
                           "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def spawn_pie_mass_display(
        spawner_path: str,
        config_paths: list[str],
        center: list[float],
        radius: float,
    ) -> str:
        """仅在 PIE 中用指定 Mass 配置各生成一只展示实体，不保存关卡。"""
        if len(config_paths) < 1 or len(config_paths) > 20 or len(set(config_paths)) != len(config_paths):
            raise RuntimeError("配置数量须为一至二十且不可重复")
        if len(center) != 3 or not all(isinstance(value, (int, float)) for value in center):
            raise RuntimeError("出生中心必须为三个坐标值")
        if not 0 <= radius <= 2000:
            raise RuntimeError("生成半径须在零至二千厘米之间")

        spawner = unreal.find_object(None, spawner_path)
        pie_worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
        if not isinstance(spawner, unreal.MassSpawner) or spawner.get_world() not in pie_worlds:
            raise RuntimeError("目标必须是当前 PIE 世界中的 MassSpawner")
        generators = spawner.get_editor_property("spawn_data_generators")
        if len(generators) != 1:
            raise RuntimeError("展示生成器必须恰好一个")
        generator = generators[0].get_editor_property("generator_instance")
        if not isinstance(generator, unreal.BBBMonsterSpawnGenerator):
            raise RuntimeError("展示生成器不是 BBBMonsterSpawnGenerator")

        assets = [unreal.load_asset(path) for path in config_paths]
        invalid_paths = [path for path, asset in zip(config_paths, assets)
                         if not isinstance(asset, unreal.MassEntityConfigAsset)]
        if invalid_paths:
            raise RuntimeError("以下路径不是 MassEntityConfigAsset: " + ", ".join(invalid_paths))
        entity_types = [unreal.MassSpawnedEntityType(entity_config=asset, proportion=1.0) for asset in assets]

        original_types = list(spawner.get_editor_property("entity_types"))
        original_count = spawner.get_editor_property("count")
        original_radius = generator.get_editor_property("spawn_radius")
        original_location = spawner.get_actor_location()
        try:
            spawner.set_editor_property("entity_types", entity_types)
            spawner.set_editor_property("count", len(entity_types))
            generator.set_editor_property("spawn_radius", radius)
            spawner.set_actor_location(unreal.Vector(*center), False, True)
            spawner.do_spawning()
        except Exception:
            spawner.do_despawning()
            spawner.set_editor_property("entity_types", original_types)
            spawner.set_editor_property("count", original_count)
            generator.set_editor_property("spawn_radius", original_radius)
            spawner.set_actor_location(original_location, False, True)
            raise
        return json.dumps({"world": spawner.get_world().get_path_name(),
                           "spawner": spawner_path, "requested": len(entity_types),
                           "configs": list(config_paths), "center": list(center), "radius": radius}, ensure_ascii=False)

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


_registration = Registration([BBBLevelEditingToolset])
