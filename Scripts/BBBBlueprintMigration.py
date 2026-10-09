import json

import unreal

from BBBAssetWritePolicy import require_asset_write


def _dirty_content():
    """/** @return 尚未保存的持久内容包 不包含其它测试的临时世界 */"""
    from BBBAssetMaintenanceToolset import _move_dirty_packages
    return [path for path in _move_dirty_packages() if path.startswith("/Game/")]


def _value(value):
    """/** @return 将显式对象引用和数组转换为编辑器属性值 */"""
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict) and set(value) == {"refPath"}:
        path = value["refPath"]
        loaded = unreal.load_object(None, path) if path else None
        if path and loaded is None:
            raise RuntimeError("引用对象不存在: " + path)
        return loaded
    return value


def migrate_blueprint(source_path, destination_path, parent_class_path, defaults_json, level_paths, dry_run):
    """
    /**
     * 在明确关卡范围内迁移演员蓝图身份和父类 最终删除旧跳转
     * @param source_path	原演员蓝图包
     * @param destination_path	不存在的新蓝图包
     * @param parent_class_path	已编译的目标演员父类
     * @param defaults_json	目标父类属性值 显式对象引用使用 refPath
     * @param level_paths	包含全部引用者的非分区关卡包
     * @param dry_run	只核对引用者与配置 不修改
     * @return 实际父类 关卡演员和旧路径清理结果
     */
    """
    from BBBAssetMaintenanceToolset import _move_path, _move_referencers, _move_dirty_packages

    source = _move_path(source_path)
    destination = _move_path(destination_path)
    levels = [_move_path(path) for path in level_paths]
    if source == destination or not levels or len(set(levels)) != len(levels):
        raise RuntimeError("必须提供不同的源目标和不重复关卡")
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if editor.is_in_play_in_editor() or _dirty_content():
        raise RuntimeError("PIE 或脏包期间禁止迁移蓝图")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    references = _move_referencers(registry, source)
    if set(references) != set(levels):
        raise RuntimeError("关卡清单必须完整匹配引用者: " + str(references))
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        raise RuntimeError("目标已存在 拒绝覆盖")
    blueprint = unreal.load_asset(source)
    parent = unreal.load_class(None, parent_class_path)
    if not isinstance(blueprint, unreal.Blueprint) or not parent or not unreal.MathLibrary.class_is_child_of(parent, unreal.Actor.static_class()):
        raise RuntimeError("源蓝图或目标演员父类无效")
    values = json.loads(defaults_json)
    if not isinstance(values, dict) or not values:
        raise RuntimeError("必须提供明确的目标默认值")
    resolved = {name: _value(value) for name, value in values.items()}
    parent_default = unreal.get_default_object(parent)
    for name in resolved:
        parent_default.get_editor_property(name)
    report = {"source": source, "destination": destination, "parent": parent_class_path,
              "referencers": references, "dry_run": dry_run, "actors": []}
    if dry_run:
        return json.dumps(report, ensure_ascii=False)
    require_asset_write([source] + levels, [destination])
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for path in levels:
        current = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if current.get_outermost().get_path_name() in _move_dirty_packages():
            raise RuntimeError("当前关卡尚未保存 禁止切换")
        if not editor.load_level(path):
            raise RuntimeError("关卡加载失败: " + path)
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        sources = [actor for actor in actors.get_all_level_actors() if actor.get_class() == blueprint.generated_class()]
        if not sources or any(actor.get_outermost() != world.get_outermost() for actor in sources):
            raise RuntimeError("引用关卡没有内部目标演员 外部演员需要专用迁移流程")
        if _dirty_content():
            raise RuntimeError("加载引用关卡产生脏包 禁止迁移")
    unreal.BlueprintEditorLibrary.reparent_blueprint(blueprint, parent)
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("重挂父类后蓝图未无警告编译通过")
    default = unreal.get_default_object(blueprint.generated_class())
    for name, value in resolved.items():
        default.set_editor_property(name, value)
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("配置后蓝图编译失败")
    if not unreal.EditorAssetLibrary.rename_asset(source, destination):
        raise RuntimeError("蓝图身份迁移失败")
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError("新蓝图保存失败")
    source_object = source + "." + source.rsplit("/", 1)[1]
    destination_object = destination + "." + destination.rsplit("/", 1)[1]
    redirects = {unreal.SoftObjectPath(source_object + suffix): unreal.SoftObjectPath(destination_object + suffix)
                 for suffix in ("", "_C")}
    for path in levels:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_outermost().get_path_name() != path and not editor.load_level(path):
            raise RuntimeError("引用关卡重新加载失败: " + path)
        for actor in actors.get_all_level_actors():
            if actor.get_class() == blueprint.generated_class():
                actor.modify()
                for name, value in resolved.items():
                    actor.set_editor_property(name, value)
                actor.set_actor_label(destination.rsplit("/", 1)[1])
                report["actors"].append(actor.get_path_name())
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths([world.get_outermost()], redirects)
        if not editor.save_current_level():
            raise RuntimeError("引用关卡保存失败: " + path)
    registry.scan_paths_synchronous([source.rsplit("/", 1)[0], destination.rsplit("/", 1)[0]]
                                    + [path.rsplit("/", 1)[0] for path in levels], force_rescan=True)
    remaining = _move_referencers(registry, source)
    if remaining:
        raise RuntimeError("旧路径仍有引用 不删除跳转: " + str(remaining))
    if unreal.EditorAssetLibrary.does_asset_exist(source):
        redirector_path = source + "." + source.rsplit("/", 1)[1]
        redirector = unreal.load_object(None, redirector_path, follow_redirectors=False)
        if not isinstance(redirector, unreal.ObjectRedirector) or redirector.get_path_name() != redirector_path:
            raise RuntimeError("旧路径不是精确跳转 拒绝删除")
        require_asset_write([source])
        if _dirty_content() or _move_referencers(registry, source):
            raise RuntimeError("清理前出现未保存内容或新增引用")
        if not unreal.BBBAssetRepairEditorLibrary.delete_redirector_packages([redirector]):
            raise RuntimeError("旧跳转清理失败")
    report["saved"] = True
    report["old_path_exists"] = unreal.EditorAssetLibrary.does_asset_exist(source)
    report["dirty_packages"] = _dirty_content()
    return json.dumps(report, ensure_ascii=False)


if __name__ == "__bbb_editor_script__":
    import importlib
    import BBBBlueprintMigration
    importlib.reload(BBBBlueprintMigration)
    print("演员蓝图迁移模块已刷新")
