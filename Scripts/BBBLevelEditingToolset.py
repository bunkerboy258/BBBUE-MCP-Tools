import json

import unreal

import toolset_registry
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBLevelEditingToolset(unreal.ToolsetDefinition):
    """提供当前关卡的项目级编辑工具"""

    @toolset_registry.tool_call
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

    @toolset_registry.tool_call
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

    @toolset_registry.tool_call
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

    @toolset_registry.tool_call
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


_registration = Registration([BBBLevelEditingToolset])


if __name__ == "__bbb_editor_script__":
    import importlib
    import BBBLevelEditingToolset as loaded_toolset

    for definition in unreal.ObjectIterator(unreal.Class):
        if (definition.get_name().split("_0x", 1)[0] == "BBBLevelEditingToolset"
                and unreal.ToolsetRegistry.is_toolset_class_registered(definition)):
            unreal.ToolsetRegistry.unregister_toolset_class(definition)
    importlib.reload(loaded_toolset)
    unreal.ToolsetRegistry.register_toolset_class(loaded_toolset.BBBLevelEditingToolset)
