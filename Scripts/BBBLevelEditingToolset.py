import json

import unreal

import toolset_registry
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBLevelEditingToolset(unreal.ToolsetDefinition):
    """提供当前关卡的项目级编辑工具"""

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
        if not unreal.GameplayStatics.set_game_paused(world, paused):
            raise RuntimeError("设置 PIE 暂停状态失败")
        return json.dumps({"world": world.get_path_name(), "paused": unreal.GameplayStatics.is_game_paused(world)})

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
