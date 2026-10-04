import hashlib
import json
import os
import re

import unreal
import toolset_registry
from toolset_registry.registration import Registration


def _move_path(value):
    """
    /**
     * 校验本项目包路径 防止对象后缀和文件系统路径混入移动请求
     * @param value	待校验路径
     * @return 不带结尾斜线的 /Game 子路径
     */
    """
    if not isinstance(value, str):
        raise RuntimeError("移动路径必须是字符串")
    path = value.rstrip("/")
    if not path.startswith("/Game/"):
        raise RuntimeError("仅允许 /Game 下的明确子路径: " + path)
    segments = path.split("/")[2:]
    if any(not re.fullmatch(r"[\w\-]+", segment) for segment in segments):
        raise RuntimeError("路径包含无效片段或对象后缀: " + path)
    if {segment.casefold() for segment in segments}.intersection({"__externalactors__", "__externalobjects__"}):
        raise RuntimeError("关卡外部数据必须使用专用迁移流程: " + path)
    return path


def _external_package_path(value, root_name):
    """
    /**
     * 校验关卡外部包的精确路径和磁盘文件
     * @param value	待核验的包路径
     * @param root_name	外部 Actor 或外部 Object 的固定根名称
     * @return 未加载的合法外部包路径
     */
    """
    if root_name not in {"__ExternalActors__", "__ExternalObjects__"}:
        raise RuntimeError("关卡外部根名称无效")
    if not isinstance(value, str):
        raise RuntimeError("关卡外部包路径必须是字符串")
    path = value.rstrip("/")
    segments = path.split("/")[2:]
    if not path.startswith("/Game/" + root_name + "/") or len(segments) < 4:
        raise RuntimeError("仅允许明确的 Game 关卡外部 包: " + path)
    if any(not re.fullmatch(r"[\w\-]+", segment) for segment in segments):
        raise RuntimeError("关卡外部包路径包含无效片段或对象后缀: " + path)
    if not os.path.isfile(_move_filename(path)):
        raise RuntimeError("关卡外部包文件不存在: " + path)
    return path


def _external_actor_package_path(value):
    """
    /**
     * 校验一个精确的 World Partition 外部 Actor 包路径
     * @param value	待校验的包路径
     * @return 合法的 /Game/__ExternalActors__ 包路径
     */
    """
    return _external_package_path(value, "__ExternalActors__")


def _external_object_package_path(value):
    """/** @return 校验后的精确关卡外部 Object 包路径 */"""
    return _external_package_path(value, "__ExternalObjects__")


def _require_external_actor_world_owners(registry, packages):
    """
    /**
     * 保存或迁移外部 Actor 前确认所属关卡真实存在 不加载遗留副本
     * @param registry	项目资产注册表
     * @param packages	需要修改的精确外部 Actor 包列表
     * @return 已核验的所属关卡路径
     */
    """
    owners = sorted({"/Game/" + "/".join(path.split("/")[3:-3]) for path in packages})
    for owner in owners:
        records = registry.get_assets_by_package_name(owner)
        if not os.path.isfile(_move_filename(owner, ".umap")) or len(records) != 1 or _move_class_path(records[0].asset_class_path) != "/Script/Engine.World":
            raise RuntimeError("外部 Actor 所属关卡缺失或不是实际 World 必须先核对历史副本 不加载或保存: " + owner)
    return owners


def _delete_ownerless_external_packages(package_paths, backup_directory, dry_run, path_validator):
    """
    /**
     * 核对归属与引用后备份并原生清理明确历史外部包
     * @param package_paths	需要核验的精确外部包
     * @param backup_directory	永久原件备份目录
     * @param dry_run	是否仅执行前置核验
     * @param path_validator	与外部包类型对应的路径校验函数
     * @return 原件哈希和原生删除核验结果
     */
    """
    import hashlib
    import shutil

    if not package_paths or len(package_paths) > 2048 or len(set(package_paths)) != len(package_paths):
        raise RuntimeError("必须提供 1 至 2048 个不重复历史外部包")
    if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
        raise RuntimeError("存在脏包或 PIE 拒绝清理历史外部包")
    if not unreal.SourceControl.is_enabled() or not unreal.SourceControl.is_available() or unreal.SourceControl.current_provider() != "Perforce":
        raise RuntimeError("历史外部包清理必须使用可用的 Perforce")
    content = os.path.realpath(unreal.Paths.project_content_dir())
    backup_root = os.path.realpath(backup_directory)
    if not os.path.isabs(backup_directory) or os.path.commonpath([content, backup_root]) == content:
        raise RuntimeError("永久备份必须使用 Content 外的绝对目录")
    registry = _move_registry()
    selected = [path_validator(path) for path in package_paths]
    selected_set = set(selected)
    owners = sorted({"/Game/" + "/".join(path.split("/")[3:-3]) for path in selected})
    for owner in owners:
        records = registry.get_assets_by_package_name(owner)
        if os.path.isfile(_move_filename(owner, ".umap")) or any(_move_class_path(record.asset_class_path) == "/Script/Engine.World" for record in records):
            raise RuntimeError("所属关卡仍存在 拒绝历史包清理: " + owner)
    for path in selected:
        outside = set(_move_referencers(registry, path)) - selected_set
        if outside:
            raise RuntimeError("历史外部包仍有组外引用 拒绝清理: " + path + " " + str(sorted(outside)))
    states = unreal.SourceControl.query_file_states(selected, silent=True, use_source_control_state_cache=False)
    if len(states) != len(selected):
        raise RuntimeError("历史外部包 Perforce 状态不完整")
    for path, state in zip(selected, states):
        if not state.is_valid or state.is_unknown or state.is_checked_out_other or state.is_conflicted or state.is_deleted:
            raise RuntimeError("历史外部包 Perforce 状态不安全: " + path)
        if state.is_source_controlled and not state.is_added and not state.is_current:
            raise RuntimeError("历史外部包不是当前仓库版本: " + path)
    report = {"dry_run": dry_run, "owners": owners, "package_count": len(selected), "backups": [], "success": False}
    if dry_run:
        report["success"] = True
        return json.dumps(report, ensure_ascii=False)
    for path in selected:
        source = _move_filename(path)
        backup = os.path.join(backup_root, path[6:] + ".uasset")
        with open(source, "rb") as source_stream:
            digest = hashlib.sha256(source_stream.read()).hexdigest()
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        if not os.path.exists(backup):
            shutil.copy2(source, backup)
        with open(backup, "rb") as backup_stream:
            backup_digest = hashlib.sha256(backup_stream.read()).hexdigest()
        if backup_digest != digest:
            raise RuntimeError("历史外部包原件备份不匹配 拒绝删除: " + path)
        report["backups"].append({"package": path, "source": source, "backup": backup, "sha256": digest})
    filenames = [_move_filename(path) for path in selected]
    report["engine_success"] = bool(unreal.SourceControl.mark_files_for_delete(filenames, silent=True))
    report["remaining_files"] = [path for path, filename in zip(selected, filenames) if os.path.isfile(filename)]
    report["dirty_packages"] = _move_dirty_packages()
    report["success"] = report["engine_success"] and not report["remaining_files"] and not report["dirty_packages"]
    unreal.log("[BBBOwnerlessExternalDelete]{} {} 个包 原件永久保留 删除后须重启宿主刷新注册表".format("PASS" if report["success"] else "FAIL", len(selected)))
    return json.dumps(report, ensure_ascii=False)


def _move_requests(moves_json):
    """
    /**
     * 读取明确映射 拒绝空请求和过大的批次
     * @param moves_json	源路径与目标路径组成的 JSON 数组
     * @return 规范化的移动映射
     */
    """
    try:
        requests = json.loads(moves_json)
    except (ValueError, TypeError) as error:
        raise RuntimeError("moves_json 不是有效 JSON: " + str(error)) from error
    if not isinstance(requests, list) or not requests or len(requests) > 5000:
        raise RuntimeError("必须提供 1 至 5000 项明确映射")
    result = []
    for entry in requests:
        if not isinstance(entry, dict):
            raise RuntimeError("每项映射必须包含 source 和 destination")
        source = _move_path(entry.get("source"))
        destination = _move_path(entry.get("destination"))
        if source.casefold() == destination.casefold():
            raise RuntimeError("源和目标不能相同 也不支持仅大小写改名: " + source)
        result.append(dict(entry, source=source, destination=destination))
    return result


def _move_registry():
    """
    /** @return 已完成扫描的资产注册表 扫描期间拒绝生成不完整计划 */
    """
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    if registry.is_loading_assets():
        raise RuntimeError("资产注册表仍在扫描 请完成扫描后重试")
    return registry


def _move_filename(package, extension=".uasset"):
    """
    /**
     * 计算磁盘落点并校验解析后的路径仍位于项目 Content 内
     * @param package	明确的 /Game 包路径
     * @param extension	包文件扩展名
     * @return 解析后的绝对文件路径
     */
    """
    content = os.path.realpath(unreal.Paths.project_content_dir())
    filename = os.path.realpath(os.path.join(content, package[len("/Game/"):] + extension))
    if os.path.commonpath([content, filename]) != content:
        raise RuntimeError("包文件落点越出项目 Content: " + package)
    return filename


def _move_referencers(registry, package):
    """
    /**
     * 查询注册表中的硬引用和软引用 不加载引用者
     * @param registry	资产注册表
     * @param package	被引用的包路径
     * @return 排序去重后的引用者包路径
     */
    """
    options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=False,
        include_soft_management_references=False,
        include_hard_management_references=False,
    )
    return sorted({str(name) for name in registry.get_referencers(package, options) or []})


def _move_native_dependency_report(registry, packages):
    """
    /**
     * 沿内容包依赖核对已加载的原生脚本包 不加载或保存资产
     * @param registry	已扫描的资产注册表
     * @param packages	本批源资产与受影响引用者
     * @return 遍历数量 原生脚本包与缺失依赖
     */
    """
    options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=False,
        include_soft_management_references=False,
        include_hard_management_references=False,
    )
    pending = list(set(packages))
    visited = set()
    script_packages = set()
    while pending:
        package = pending.pop()
        if package in visited:
            continue
        visited.add(package)
        if len(visited) > 100000:
            raise RuntimeError("依赖闭包超过安全核验容量 拒绝不完整预检")
        for name in registry.get_dependencies(package, options) or []:
            dependency = str(name)
            if dependency.startswith("/Script/"):
                script_packages.add(dependency)
                continue
            if dependency.startswith("/Game/") or dependency.startswith("/Engine/"):
                pending.append(dependency)
    missing = sorted(package for package in script_packages if unreal.find_object(None, package) is None)
    return {"visited_package_count": len(visited), "script_packages": sorted(script_packages), "missing_script_packages": missing}


def _move_dirty_packages():
    """
    /** @return 当前所有项目脏包 防止原生重命名顺带保存其它会话的修改 */
    """
    packages = list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
    packages.extend(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
    return sorted({package.get_path_name() for package in packages if package.get_path_name().startswith("/Game/")})


def _move_blocking_blueprint_errors(existing_errors, current_errors, selected_packages):
    existing = set(existing_errors)
    selected = set(selected_packages)
    blocking = set(current_errors) - existing
    for error in current_errors:
        package_path = error.split(".", 1)[0]
        if package_path in selected:
            blocking.add(error)
    return sorted(blocking)


def _move_primary_assets(asset_data):
    """
    /**
     * 只保留包内主资产 蓝图生成类与默认对象由引擎随主资产维护
     * @param asset_data	注册表返回的包内或目录对象
     * @return 可独立迁移的主资产列表
     */
    """
    return [item for item in asset_data if item.is_u_asset()]


def _move_class_path(path):
    """
    /**
     * 从类型路径字段生成稳定名称 不使用包含内存地址的结构调试文本
     * @param path	UE 顶层资产类型路径
     * @return 完整类型路径
     */
    """
    return str(path.package_name) + "." + str(path.asset_name)


def _plan_asset_moves(requests, registry):
    """
    /**
     * 将目录映射展开为精确资产映射 只读检查引用和磁盘冲突
     * @param requests	目录和资产移动请求
     * @param registry	已完成扫描的资产注册表
     * @return 完整映射及阻断原因
     */
    """
    if len(requests) > 1000:
        raise RuntimeError("单批最多 1000 项目录或资产请求")
    assets = []
    blockers = []
    roots = []
    source_keys = set()
    destination_keys = set()
    referencers = set()
    known_sources = {item["source"].casefold() for item in requests}
    if len(known_sources) != len(requests):
        raise RuntimeError("批次包含重复源路径")

    for request in requests:
        source = request["source"]
        destination = request["destination"]
        data = _move_primary_assets(registry.get_assets_by_package_name(source))
        folder_data = _move_primary_assets(registry.get_assets_by_path(source, recursive=True))
        is_directory = bool(folder_data) or unreal.EditorAssetLibrary.does_directory_exist(source)
        if bool(data) == is_directory:
            raise RuntimeError("源路径不存在或资产与目录类型不明确: " + source)
        if is_directory:
            for other in requests:
                other_source = other["source"].casefold()
                if other_source.startswith(source.casefold() + "/"):
                    raise RuntimeError("不能同时移动父目录和子项: " + source)
                if other["destination"].casefold() == source.casefold() or other["destination"].casefold().startswith(source.casefold() + "/"):
                    raise RuntimeError("目标不能位于本批次正在移动的源目录内: " + source)
            data = folder_data
        if not data:
            raise RuntimeError("空目录无需资产迁移 请使用目录管理工具: " + source)
        roots.append({"source": source, "destination": destination, "kind": "directory" if is_directory else "asset"})

        for asset_data in sorted(data, key=lambda item: str(item.package_name)):
            package = _move_path(str(asset_data.package_name))
            target = destination
            if is_directory:
                target += package[len(source):]
            target = _move_path(target)
            class_path = _move_class_path(asset_data.asset_class_path)
            object_path = package + "." + str(asset_data.asset_name)
            target_object = target + "." + target.rsplit("/", 1)[-1]
            if package.casefold() in source_keys or target.casefold() in destination_keys:
                raise RuntimeError("展开后的源资产或目标资产重复: " + package + " -> " + target)
            if target.casefold() in known_sources:
                raise RuntimeError("目标不能同时作为另一项源路径: " + target)
            source_keys.add(package.casefold())
            destination_keys.add(target.casefold())

            if class_path in {"/Script/CoreUObject.ObjectRedirector", "/Script/Engine.World", "/Script/Engine.MapBuildDataRegistry"}:
                blockers.append({"package": package, "reason": "重定向器和关卡数据不属于通用资产移动范围"})
            if len(_move_primary_assets(registry.get_assets_by_package_name(package))) != 1:
                blockers.append({"package": package, "reason": "包内存在多个资产 需专用迁移"})
            if registry.get_assets_by_package_name(target) or unreal.EditorAssetLibrary.does_directory_exist(target):
                blockers.append({"package": target, "reason": "目标包或同名目录已存在"})
            parent = target.rsplit("/", 1)[0]
            while parent != "/Game":
                if registry.get_assets_by_package_name(parent):
                    blockers.append({"package": parent, "reason": "目标父路径被资产占用"})
                parent = parent.rsplit("/", 1)[0]

            source_file = _move_filename(package)
            target_file = _move_filename(target)
            if not os.path.isfile(source_file):
                blockers.append({"package": package, "reason": "源资产尚未保存到磁盘"})
            for extension in (".uasset", ".umap", ".uexp", ".ubulk", ".uptnl"):
                if os.path.exists(_move_filename(target, extension)):
                    blockers.append({"package": target, "reason": "目标磁盘文件已存在: " + extension})
            references = _move_referencers(registry, package)
            referencers.update(name for name in references if name != package)
            assets.append({
                "source": package,
                "destination": target,
                "source_folder": source if is_directory else package.rsplit("/", 1)[0],
                "source_object": object_path,
                "destination_object": target_object,
                "class_path": class_path,
                "source_file": source_file,
                "destination_file": target_file,
                "referencers": references,
            })
            if len(assets) > 5000:
                raise RuntimeError("展开资产数超过 5000 请拆分批次")

    if source_keys.intersection(destination_keys):
        raise RuntimeError("批次包含循环或链式移动 请拆分批次")
    for target in destination_keys:
        parent = target.rsplit("/", 1)[0]
        while parent != "/game":
            if parent in destination_keys:
                raise RuntimeError("目标资产不能同时作为另一个目标的父目录: " + target)
            parent = parent.rsplit("/", 1)[0]
    for package in sorted(referencers):
        try:
            _move_path(package)
        except RuntimeError:
            blockers.append({"package": package, "reason": "存在项目外或关卡外部数据引用者 需专用迁移"})
    dirty_packages = _move_dirty_packages()
    if dirty_packages:
        blockers.append({"packages": dirty_packages, "reason": "项目存在未保存修改 原生移动可能触及脏包"})
    native_dependencies = _move_native_dependency_report(registry, referencers | {item["source"] for item in assets})
    if native_dependencies["missing_script_packages"]:
        blockers.append({"script_packages": native_dependencies["missing_script_packages"], "reason": "原生依赖未加载 拒绝重存可能丢失类型数据的资产"})
    return {
        "requested_count": len(requests),
        "asset_count": len(assets),
        "moves": roots,
        "assets": assets,
        "referencer_packages": sorted(referencers),
        "blockers": blockers,
        "can_execute_after_checkout": not blockers,
        "checkout_checked": False,
        "native_dependencies": native_dependencies,
    }


def _require_move_checkout(packages, destinations):
    """
    /**
     * 检查现有包独占签出和目标仓库冲突 不主动办理签出
     * @param packages	源资产和所有注册表引用者
     * @param destinations	新资产包路径
     * @return 无返回值 不满足条件直接拒绝
     */
    """
    if not unreal.SourceControl.is_enabled() or not unreal.SourceControl.is_available():
        raise RuntimeError("执行移动前必须启用并连接 Perforce")
    if unreal.SourceControl.current_provider() != "Perforce":
        raise RuntimeError("本项目二进制资产必须由 Perforce 管理")
    names = sorted(set(packages))
    states = unreal.SourceControl.query_file_states(names, silent=True, use_source_control_state_cache=False)
    if len(states) != len(names):
        raise RuntimeError("无法获得完整 Perforce 状态")
    for package, state in zip(names, states):
        if not state.is_valid or state.is_unknown or state.is_checked_out_other or state.is_conflicted or state.is_deleted:
            raise RuntimeError("Perforce 状态无效或存在冲突: " + package)
        if not state.can_edit or not (state.is_checked_out or state.is_added):
            raise RuntimeError("必须先独占签出或待添加源资产与引用者: " + package)
        if state.is_source_controlled and not state.is_added and not state.is_current:
            raise RuntimeError("包不是仓库最新版本 请由用户处理: " + package)
    targets = sorted(set(destinations))
    target_states = unreal.SourceControl.query_file_states(targets, silent=True, use_source_control_state_cache=False)
    if len(target_states) != len(targets):
        raise RuntimeError("无法获得完整目标 Perforce 状态")
    for package, state in zip(targets, target_states):
        if not state.is_valid or state.is_unknown or state.is_source_controlled or state.is_added or state.is_checked_out_other or state.is_deleted or not state.can_add:
            raise RuntimeError("目标存在仓库冲突或不在可添加映射内: " + package)


def _permit_external_actor_move_references(report):
    """
    /**
     * 为普通资产的原生移动允许明确外部 Actor 引用 保留其它预检阻断
     * @param report	完整的普通资产移动预检报告
     * @return 增补外部引用清单的预检报告
     */
    """
    if report["asset_count"] > 64:
        raise RuntimeError("保留外部 Actor 引用的单批移动最多 64 个普通资产")
    permitted = []
    blockers = []
    for blocker in report["blockers"]:
        package = blocker.get("package", "")
        if package.startswith("/Game/__ExternalActors__/") and blocker.get("reason") == "存在项目外或关卡外部数据引用者 需专用迁移":
            permitted.append(_external_actor_package_path(package))
            continue
        blockers.append(blocker)
    report["external_actor_referencers"] = sorted(set(permitted))
    report["blockers"] = blockers
    report["can_execute_after_checkout"] = not blockers
    return report


def _execute_asset_moves(report):
    """
    /**
     * 执行通过预检的原生资产移动 保留逐对象结果与部分失败证据
     * @param report	已通过策略预检的明确映射报告
     * @return 完整执行与磁盘核验结果
     */
    """
    external_referencers = [path for path in report["referencer_packages"] if path.startswith("/Game/__ExternalActors__/")]
    if external_referencers:
        _require_external_actor_world_owners(_move_registry(), external_referencers)
    affected = set(report["referencer_packages"])
    affected.update(item["source"] for item in report["assets"])
    _require_move_checkout(affected, [item["destination"] for item in report["assets"]])
    report["checkout_checked"] = True
    renames = []
    loaded_assets = []
    for item in report["assets"]:
        asset = unreal.EditorAssetLibrary.load_asset(item["source_object"])
        if asset is None or asset.get_path_name() != item["source_object"]:
            raise RuntimeError("源对象不存在或通过重定向加载了其它资产: " + item["source_object"])
        if _move_class_path(asset.get_class().get_class_path_name()) != item["class_path"]:
            raise RuntimeError("源资产类型与预检不一致: " + item["source"])
        loaded_assets.append(asset)
        renames.append(unreal.AssetRenameData(
            asset=asset,
            new_package_path=item["destination"].rsplit("/", 1)[0],
            new_name=item["destination"].rsplit("/", 1)[-1],
        ))
    if _move_dirty_packages():
        raise RuntimeError("加载后出现脏包 已中止移动 请先检查并保存")

    unreal.log("[BBBAssetMove]开始原生批量移动 {} 个资产".format(len(renames)))
    report["executed"] = True
    try:
        report["engine_success"] = bool(unreal.AssetToolsHelpers.get_asset_tools().rename_assets(renames))
    except Exception as error:
        report["engine_success"] = False
        report["engine_error"] = str(error)
    report["object_results"] = [
        {
            "source": item["source"],
            "destination": item["destination"],
            "actual_object": asset.get_path_name(),
            "renamed": asset.get_path_name() == item["destination_object"],
        }
        for item, asset in zip(report["assets"], loaded_assets)
    ]
    try:
        report["verification"] = json.loads(BBBAssetMaintenanceToolset.verify_asset_moves(json.dumps(report["assets"])))
    except Exception as error:
        report["verification"] = {"success": False, "error": str(error)}
    report["success"] = (
        report["engine_success"]
        and report["verification"]["success"]
        and all(item["renamed"] for item in report["object_results"])
    )
    report["partial"] = not report["success"] and any(item["renamed"] for item in report["object_results"])
    if not report["success"]:
        unreal.log_error("[BBBAssetMove]移动或核验未完整通过 必须检查逐项结果 禁止直接重试整批")
    if report["success"]:
        unreal.log("[BBBAssetMove]PASS {} 个资产 已核验磁盘与注册表".format(len(renames)))
    return json.dumps(report, ensure_ascii=False)


@unreal.uclass()
class BBBAssetMaintenanceToolset(unreal.ToolsetDefinition):
    """提供精确限定资产范围的维护工具"""

    @toolset_registry.tool_call
    @staticmethod
    def delete_ownerless_external_actor_packages(package_paths: list[str], backup_directory: str, dry_run: bool = True) -> str:
        """
        /**
         * 备份后原生清理所属关卡缺失且没有组外引用的外部 Actor 历史文件
         * @param package_paths	已核对历史归属的精确外部包 单批最多 2048 项
         * @param backup_directory	项目 Content 外永久保留原件的目录
         * @param dry_run	默认只核验 不加载对象或删除文件
         * @return 原件哈希 原生删除结果和剩余文件
         */
        """
        return _delete_ownerless_external_packages(package_paths, backup_directory, dry_run, _external_actor_package_path)

    @toolset_registry.tool_call
    @staticmethod
    def delete_ownerless_external_object_packages(package_paths: list[str], backup_directory: str, dry_run: bool = True) -> str:
        """
        /**
         * 备份后原生清理所属关卡缺失且没有组外引用的外部 Object 历史文件
         * @param package_paths	已核对历史归属的精确外部包 单批最多 2048 项
         * @param backup_directory	项目 Content 外永久保留原件的目录
         * @param dry_run	默认只核验 不加载对象或删除文件
         * @return 原件哈希 原生删除结果和剩余文件
         */
        """
        return _delete_ownerless_external_packages(package_paths, backup_directory, dry_run, _external_object_package_path)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_external_object_package_metadata(package_paths: list[str]) -> str:
        """
        /**
         * 只读核对外部 Object 的注册信息与引用 不加载对象
         * @param package_paths	需要核验的精确外部 Object 包 单批最多 64 项
         * @return 注册对象 类型和硬软包引用
         */
        """
        if not package_paths or len(package_paths) > 64 or len(set(package_paths)) != len(package_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复外部 Object 包")
        registry = _move_registry()
        rows = []
        for requested in package_paths:
            path = _external_object_package_path(requested)
            records = [{"object": path + "." + str(record.asset_name), "class_path": _move_class_path(record.asset_class_path)} for record in registry.get_assets_by_package_name(path)]
            rows.append({"package": path, "records": records, "referencers": _move_referencers(registry, path)})
        return json.dumps({"read_only": True, "packages": rows}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_external_actor_package_metadata(package_paths: list[str]) -> str:
        """
        /**
         * 只读核对外部 Actor 包注册信息与引用 不加载缺失所属关卡的对象
         * @param package_paths	需要核验的精确外部 Actor 包 单批最多 64 项
         * @return 注册对象 类型和硬软包引用
         */
        """
        if not package_paths or len(package_paths) > 64 or len(set(package_paths)) != len(package_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复外部 Actor 包")
        registry = _move_registry()
        rows = []
        for requested in package_paths:
            path = _external_actor_package_path(requested)
            records = [{"object": path + "." + str(record.asset_name), "class_path": _move_class_path(record.asset_class_path)} for record in registry.get_assets_by_package_name(path)]
            rows.append({"package": path, "records": records, "referencers": _move_referencers(registry, path)})
        report = {"read_only": True, "packages": rows}
        unreal.log("[BBBExternalActorMetadata]核对 {} 个外部包 不加载对象".format(len(rows)))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_external_actor_packages(package_paths: list[str]) -> str:
        """
        /**
         * 读取明确外部 Actor 的实际身份与父级连接 不保存或修改包
         * @param package_paths	需要核验的精确外部 Actor 包 单批最多 64 项
         * @return 注册对象 实际 GUID 父级连接与脏包状态
         */
        """
        if not package_paths or len(package_paths) > 64 or len(set(package_paths)) != len(package_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复外部 Actor 包")
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("存在脏包或 PIE 拒绝加载外部 Actor 核验")
        registry = _move_registry()
        rows = []
        for requested in package_paths:
            path = _external_actor_package_path(requested)
            records = list(registry.get_assets_by_package_name(path))
            actors = []
            for record in records:
                actor = record.get_asset()
                if not isinstance(actor, unreal.Actor):
                    raise RuntimeError("外部包注册对象不是可加载的 Actor: " + path)
                parent = actor.get_attach_parent_actor()
                identity = {
                    "object": actor.get_path_name(),
                    "class_path": actor.get_class().get_path_name(),
                    "actor_guid": actor.get_editor_property("actor_guid").to_string(),
                    "attach_parent_actor": parent.get_path_name() if parent is not None else "",
                }
                niagara_class = getattr(unreal, "NiagaraActor", None)
                if niagara_class is not None and isinstance(actor, niagara_class):
                    identity["destroy_on_system_finish"] = actor.get_destroy_on_system_finish()
                actors.append(identity)
            rows.append({"package": path, "actors": actors, "referencers": _move_referencers(registry, path)})
        dirty = _move_dirty_packages()
        report = {"read_only": True, "packages": rows, "dirty_packages": dirty, "success": not dirty}
        unreal.log("[BBBExternalActorInspect]核验 {} 个外部包 {}".format(len(rows), "PASS" if report["success"] else "FAIL"))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_physics_asset_material_bindings(package_path: str) -> str:
        """
        /**
         * 原生读取物理资产的刚体材质绑定与碰撞形状 不执行保存
         * @param package_path	需要核验的精确物理资产包路径
         * @return 逐骨骼材质绑定 碰撞形状数量与脏包状态
         */
        """
        return unreal.BBBAssetRepairEditorLibrary.inspect_physics_asset_material_bindings(_move_path(package_path))

    @toolset_registry.tool_call
    @staticmethod
    def delete_metadata_only_package(package_path: str, dry_run: bool = True) -> str:
        """
        /**
         * 仅清理无引用且只有一个旧版元数据导出的精确包
         * @param package_path	已备份的精确包路径
         * @param dry_run	默认只核验导出与引用
         * @return 前置条件与引擎清理后的磁盘结果
         */
        """
        package = _move_path(package_path)
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("存在脏包或 PIE 拒绝清理元数据包")
        registry = _move_registry()
        if registry.get_assets_by_package_name(package) or _move_referencers(registry, package):
            raise RuntimeError("包存在注册资产或引用者 拒绝清理")
        report = json.loads(unreal.BBBAssetRepairEditorLibrary.inspect_package_objects(package))
        objects = report.get("objects", [])
        if not report.get("success") or report.get("export_count") != 1 or len(objects) != 1:
            raise RuntimeError("文件导出不符合元数据空包条件")
        if objects[0].get("is_asset") or objects[0].get("class") != "/Script/CoreUObject.MetaData":
            raise RuntimeError("包包含真实对象 拒绝清理")
        report["package"] = package
        report["dry_run"] = dry_run
        if not dry_run:
            _require_move_checkout([package], [])
            report["success"] = bool(unreal.BBBAssetRepairEditorLibrary.delete_metadata_only_package(package))
            if not report["success"]:
                unreal.log_error("[BBBMetadataCleanup]引擎未完成空包清理 " + package)
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_package_objects(package_path: str) -> str:
        """
        /**
         * 核验未注册包或非主资产包的实际导出 不执行保存
         * @param package_path	需要加载核验的精确项目包
         * @return 文件导出数量和所有包内对象
         */
        """
        return unreal.BBBAssetRepairEditorLibrary.inspect_package_objects(_move_path(package_path))

    @toolset_registry.tool_call
    @staticmethod
    def repair_missing_animation_skeleton(asset_path: str, skeleton_path: str) -> str:
        """
        /**
         * 为已备份且独占签出的无骨架动画恢复同资源包骨架
         * @param asset_path	无骨架动画的明确包路径
         * @param skeleton_path	经归属核验的目标骨架包路径
         * @return 轨道兼容性 修复结果和保存结果
         */
        """
        asset_path = _move_path(asset_path)
        skeleton_path = _move_path(skeleton_path)
        if _move_dirty_packages():
            raise RuntimeError("存在脏包 拒绝修复动画骨架")
        _require_move_checkout([asset_path], [])
        try:
            result = json.loads(unreal.BBBAssetRepairEditorLibrary.repair_missing_animation_skeleton(asset_path, skeleton_path))
        except Exception as error:
            asset = unreal.find_object(None, asset_path + "." + asset_path.rsplit("/", 1)[-1])
            target = unreal.find_object(None, skeleton_path + "." + skeleton_path.rsplit("/", 1)[-1])
            if not isinstance(asset, unreal.AnimSequence) or target is None or asset.get_skeleton() != target:
                raise RuntimeError("加载错误后未完成骨架恢复 不保存: " + str(error))
            result = {"success": True, "recovered_after_initial_load_error": str(error)}
        if not result.get("success"):
            raise RuntimeError("动画已有骨架或轨道不兼容 拒绝修复: " + json.dumps(result))
        result["saved"] = bool(unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False))
        result["success"] = result["success"] and result["saved"] and not _move_dirty_packages()
        unreal.log("[BBBAnimationSkeletonRepair]修复结果 " + json.dumps(result))
        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pose_asset_source_guids(asset_paths: list[str]) -> str:
        """
        /**
         * 只读比较姿势源的新旧 GUID 算法和持久化载荷
         * @param asset_paths\t明确姿势包路径 最多 64 项
         * @return 每项姿势的源 GUID 匹配情况和载荷指纹
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复姿势包")
        native = getattr(unreal, "BBBAssetRepairEditorLibrary", None)
        if native is None:
            raise RuntimeError("宿主缺少 BBBAssetRepairEditorLibrary 原生校验能力")
        results = []
        for path in asset_paths:
            asset = unreal.EditorAssetLibrary.load_asset(_move_path(path))
            if not isinstance(asset, unreal.PoseAsset):
                raise RuntimeError("目标不是姿势资产: " + path)
            report = native.inspect_pose_source(asset)
            if not report:
                raise RuntimeError("无法校验姿势源: " + path)
            results.append(json.loads(report))
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def repair_pose_asset_source_guids(expected_reports_json: str, dry_run: bool = True, allow_verified_samples: bool = False) -> str:
        """
        /**
         * 仅修复通过 GUID 或逐键校验的姿势缓存 全批预检且不重新生成姿势
         * @param expected_reports_json\t检查工具的完整报告 JSON
         * @param dry_run\t默认只预检 执行前必须备份并独占签出
         * @param allow_verified_samples\t显式允许固定精度的逐键校验 默认禁用
         * @return 保存后重新检查的报告
         */
        """
        expected = json.loads(expected_reports_json)
        if not isinstance(expected, list) or not expected or len(expected) > 64:
            raise RuntimeError("必须提供 1 至 64 项检查报告")
        paths = [_move_path(item["asset"].split(".")[0]) for item in expected]
        current = json.loads(BBBAssetMaintenanceToolset.inspect_pose_asset_source_guids(paths))
        for before, item in zip(expected, current):
            verified = item["legacy_matches"] or (allow_verified_samples and item.get("samples_match", False))
            if before != item or not verified or item["current_matches"]:
                raise RuntimeError("报告发生变化或不属于已证明的 GUID 算法升级: " + item["asset"])
        if dry_run:
            return json.dumps(current, ensure_ascii=False)
        if _move_dirty_packages():
            raise RuntimeError("存在脏包 拒绝开始姿势缓存维护")
        _require_move_checkout(paths, [])
        results = []
        for path, before in zip(paths, current):
            asset = unreal.EditorAssetLibrary.load_asset(path)
            raw = unreal.BBBAssetRepairEditorLibrary.repair_pose_source_guid(asset, before["stored_guid"], allow_verified_samples)
            if not raw:
                raise RuntimeError("姿势缓存修复失败 未保存: " + path)
            after = json.loads(raw)
            if not after["current_matches"] or before["payload_hash"] != after["payload_hash"]:
                raise RuntimeError("姿势缓存修复后校验失败 未保存: " + path)
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                raise RuntimeError("姿势缓存保存失败: " + path)
            results.append(after)
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_access_errors(asset_paths: list[str]) -> str:
        """
        /**
         * 只读检查动画属性访问节点的路径和编译错误
         * @param asset_paths\t明确动画蓝图包路径 最多 16 项
         * @return 按蓝图分组的节点诊断
         */
        """
        if not asset_paths or len(asset_paths) > 16:
            raise RuntimeError("动画蓝图批次必须为 1 至 16 项")
        results = {}
        for path in asset_paths:
            asset = unreal.EditorAssetLibrary.load_asset(_move_path(path))
            if not isinstance(asset, unreal.AnimBlueprint):
                raise RuntimeError("目标不是动画蓝图: " + path)
            results[path] = json.loads(unreal.BBBAssetRepairEditorLibrary.inspect_access_errors(asset))
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def repair_animation_property_queries(operations_json: str, save: bool = False) -> str:
        """
        /**
         * 按显式计划创建安全标量查询并修复指定节点 最终编译通过后才允许保存
         * @param operations_json\t每个蓝图的 guarded_queries weights paths calls 计划
         * @param save\t默认仅修改内存并编译 保存前须备份和独占签出
         * @return 每项蓝图的编译和保存结果 失败保留内存便于检查
         */
        """
        plans = json.loads(operations_json)
        if not isinstance(plans, list) or not plans or len(plans) > 16:
            raise RuntimeError("必须提供 1 至 16 项蓝图修复计划")
        for item in plans:
            if not isinstance(item, dict) or set(item) - {"asset", "guarded_queries", "weights", "paths", "calls"}:
                raise RuntimeError("蓝图计划存在未知操作或格式错误")
        paths = [_move_path(item["asset"]) for item in plans]
        if len(set(paths)) != len(paths):
            raise RuntimeError("蓝图计划不得重复")
        _require_move_checkout(paths, [])
        assets = [unreal.EditorAssetLibrary.load_asset(path) for path in paths]
        if any(not isinstance(asset, unreal.AnimBlueprint) for asset in assets):
            raise RuntimeError("计划包含非动画蓝图")
        native = unreal.BBBAssetRepairEditorLibrary
        for plan, asset in zip(plans, assets):
            for item in plan.get("guarded_queries", []):
                target = unreal.load_class(None, item["class"])
                fallback = str(item["fallback"]).lower()
                if not native.create_guarded_value_query(asset, item["name"], item["object_getter"], target, item["value_getter"], fallback):
                    raise RuntimeError("安全查询创建失败 未保存: " + plan["asset"])
            for item in plan.get("weights", []):
                if not native.append_smoothed_bool_weight(asset, item["update"], item["variable"], item["boolean_getter"], item["object_getter"], item["speed"]):
                    raise RuntimeError("平滑权重创建失败 未保存: " + plan["asset"])
            for item in plan.get("paths", []):
                node = unreal.find_object(None, item["node"])
                if node is None or node.get_outermost() != asset.get_outermost():
                    raise RuntimeError("目标节点不属于指定蓝图")
                old = list(unreal.BBBBlueprintEditorLibrary.get_property_access_path(node))
                if old != item["old"]:
                    raise RuntimeError("目标属性路径发生漂移")
                if not unreal.BBBBlueprintEditorLibrary.set_property_access_path(node, item["new"]):
                    raise RuntimeError("属性路径修复失败 未保存")
            for item in plan.get("calls", []):
                if not native.replace_access_with_query(asset, item["node"], item["old"], item["query"]):
                    raise RuntimeError("属性节点替换失败 未保存: " + plan["asset"])
        results = []
        for path, asset in zip(paths, assets):
            unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            status = asset.get_editor_property("status")
            results.append({"asset": path, "status": str(status), "saved": False})
        if any(asset.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE for asset in assets):
            raise RuntimeError("编译未通过 整批未保存: " + json.dumps(results, ensure_ascii=False))
        if save:
            for asset, result in zip(assets, results):
                if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                    raise RuntimeError("编译通过但保存失败: " + result["asset"])
                result["saved"] = True
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_content_dependency_integrity(asset_paths: list[str]) -> str:
        """
        /**
         * 只读核验资产注册表中的项目硬软包引用是否存在于物理目录
         * @param asset_paths	明确包路径列表 最多 5000 项
         * @return 缺失包与实际引用者 不加载或保存资产
         */
        """
        if not asset_paths or len(asset_paths) > 5000 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 5000 个不重复包路径")

        packages = []
        for path in asset_paths:
            if path.startswith("/Game/__ExternalActors__/"):
                packages.append(_external_actor_package_path(path))
                continue

            if path.startswith("/Game/__ExternalObjects__/"):
                packages.append(_external_object_package_path(path))
                continue

            packages.append(_move_path(path))
        registry = _move_registry()
        hard_options = unreal.AssetRegistryDependencyOptions(
            include_soft_package_references=False,
            include_hard_package_references=True,
            include_searchable_names=False,
            include_soft_management_references=False,
            include_hard_management_references=False,
        )
        soft_options = unreal.AssetRegistryDependencyOptions(
            include_soft_package_references=True,
            include_hard_package_references=False,
            include_searchable_names=False,
            include_soft_management_references=False,
            include_hard_management_references=False,
        )
        existence = {}
        missing_packages = set()
        referencers = []
        for package in packages:
            missing = set()
            hard = {str(name) for name in registry.get_dependencies(package, hard_options) or []}
            soft = {str(name) for name in registry.get_dependencies(package, soft_options) or []}
            for dependency in hard | soft:
                if not dependency.startswith("/Game/"):
                    continue

                if dependency not in existence:
                    existence[dependency] = any(os.path.isfile(_move_filename(dependency, extension)) for extension in (".uasset", ".umap"))

                if not existence[dependency]:
                    missing.add(dependency)

            if missing:
                missing_packages.update(missing)
                referencers.append({"package": package, "missing_dependencies": sorted(missing), "missing_hard_dependencies": sorted(missing.intersection(hard)), "missing_soft_dependencies": sorted(missing.intersection(soft))})

        return json.dumps({"read_only": True, "checked_count": len(packages), "missing_packages": sorted(missing_packages), "referencers": referencers, "success": not missing_packages}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def normalize_material_auxiliary_data(asset_paths: list[str], clear_missing_preview: bool = False, dry_run: bool = True) -> str:
        """
        /**
         * 按原生烘焙规则清理材质旧辅助缓存 保留实际纹理绑定
         * @param asset_paths	明确材质包 最多 64 项
         * @param clear_missing_preview	是否清理已缺失的可选预览网格
         * @param dry_run	只读预检
         * @return 每个材质的缓存前后和实际绑定证明
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("需要 1 至 64 个明确不重复材质包")

        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝材质缓存整理")

        paths = [_move_path(path) for path in asset_paths]
        registry = _move_registry()
        for path in paths:
            records = _move_primary_assets(registry.get_assets_by_package_name(path))
            if len(records) != 1 or _move_class_path(records[0].asset_class_path) not in ["/Script/Engine.Material", "/Script/Engine.MaterialInstanceConstant"]:
                raise RuntimeError("只能整理唯一真实材质资产")

        integrity = json.loads(BBBAssetMaintenanceToolset.inspect_content_dependency_integrity(paths))
        if any(row["missing_hard_dependencies"] for row in integrity["referencers"]):
            raise RuntimeError("存在缺失硬引用 不允许加载后保存")

        report = {"dry_run": dry_run, "success": dry_run, "materials": []}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        _require_move_checkout(paths, [])
        for path in paths:
            asset = unreal.load_object(None, path + "." + path.rsplit("/", 1)[-1], follow_redirectors=False)
            row = json.loads(unreal.BBBAssetRepairEditorLibrary.normalize_material_auxiliary_data(asset, clear_missing_preview))
            row["package"] = path
            report["materials"].append(row)
            if not row["success"] or not unreal.EditorLoadingAndSavingUtils.save_packages([asset.get_outermost()], False):
                return json.dumps(report, ensure_ascii=False)

        registry.scan_paths_synchronous(sorted({path.rsplit("/", 1)[0] for path in paths}), force_rescan=True)
        report["success"] = not _move_dirty_packages()
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def refresh_blueprint_reflection_metadata(asset_path: str) -> str:
        """
        /**
         * 对明确蓝图或关卡执行原生反射节点刷新 不保存
         * @param asset_path	已备份并签出的明确包
         * @return 节点连线数量及蓝图对象路径
         */
        """
        path = _move_path(asset_path)
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝刷新")

        _require_move_checkout([path], [])
        asset = unreal.load_object(None, path + "." + path.rsplit("/", 1)[-1], follow_redirectors=False)
        return unreal.BBBAssetRepairEditorLibrary.refresh_blueprint_reflection_metadata(asset)

    @toolset_registry.tool_call
    @staticmethod
    def remap_package_metadata_owner_paths(package_path: str, old_package_path: str, dry_run: bool = True) -> str:
        """
        /**
         * 归并包元数据旧所属路径 保留全部原值 冲突时不改动
         * @param package_path	已备份的当前真实包
         * @param old_package_path	明确旧所属包
         * @param dry_run	只读预检
         * @return 元数据映射和保存结果
         */
        """
        path = _move_path(package_path)
        old = _move_path(old_package_path)
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝元数据归并")

        if not dry_run:
            _require_move_checkout([path], [])

        package = unreal.load_package(path)
        if package is None or package.get_path_name() != path:
            raise RuntimeError("目标包加载不完整")

        report = json.loads(unreal.BBBAssetRepairEditorLibrary.remap_package_metadata_owner_paths(path, old, dry_run))
        if report["success"] and not dry_run:
            report["success"] = unreal.EditorLoadingAndSavingUtils.save_packages([package], False)
            _move_registry().scan_paths_synchronous([path.rsplit("/", 1)[0]], force_rescan=True)

        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_loaded_package_soft_paths(package_path: str) -> str:
        """
        /**
         * 只读检查已经加载包的精确软对象路径
         * @param package_path	明确已加载包
         * @return 原生路径清单 不加载或保存
         */
        """
        return unreal.BBBAssetRepairEditorLibrary.inspect_loaded_package_soft_paths(_move_path(package_path))

    @toolset_registry.tool_call
    @staticmethod
    def create_missing_path_recovery_redirector(source_package: str, destination_package: str, dry_run: bool = True) -> str:
        """
        /**
         * 为真实缺失旧包建立暂时重定向 用原生加载保留硬引用
         * @param source_package	缺失的旧包
         * @param destination_package	已核对的真实目标包
         * @param dry_run	只读预检
         * @return 创建结果 验收后须原生清理临时包
         */
        """
        source = _move_path(source_package)
        destination = _move_path(destination_package)
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝恢复引用")

        if source == destination or any(os.path.isfile(_move_filename(source, extension)) for extension in (".uasset", ".umap")):
            raise RuntimeError("旧包存在或目标未变化")

        registry = _move_registry()
        records = _move_primary_assets(registry.get_assets_by_package_name(destination))
        if len(records) != 1 or _move_class_path(records[0].asset_class_path) == "/Script/CoreUObject.ObjectRedirector":
            raise RuntimeError("目标必须是唯一真实主资产")

        report = {"source": source, "destination": destination, "dry_run": dry_run, "success": dry_run}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        asset = unreal.load_object(None, destination + "." + str(records[0].asset_name), follow_redirectors=False)
        if asset is None or asset.get_outermost().get_path_name() != destination:
            raise RuntimeError("目标加载失败或发生漂移")

        report["success"] = unreal.BBBAssetRepairEditorLibrary.create_missing_path_recovery_redirector(source, asset)
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def remap_missing_soft_object_paths(referencer_paths: list[str], replacements_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 将已缺失包的硬编码软对象路径归入已核对的真实目标 保留子对象路径
         * @param referencer_paths	已备份的明确引用者包 最多 64 项
         * @param replacements_json	明确 source 与 destination 软对象路径映射
         * @param dry_run	仅预检 不加载或保存包
         * @return 保存包 旧引用残留与拒绝原因
         */
        """
        if not referencer_paths or len(referencer_paths) > 64 or len(set(referencer_paths)) != len(referencer_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复引用者包")

        replacements = json.loads(replacements_json)
        if not isinstance(replacements, list) or not replacements or len(replacements) > 2000:
            raise RuntimeError("必须提供 1 至 2000 个明确软路径映射")

        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝软路径修复")

        registry = _move_registry()
        redirect_map = {}
        seen_sources = set()
        sources = set()
        references = set()
        for item in replacements:
            source = item.get("source", "")
            destination = item.get("destination", "")
            if not source.startswith("/Game/") or not destination.startswith("/Game/") or "." not in source or "." not in destination or ":" in source or ":" in destination:
                raise RuntimeError("必须使用明确项目顶层对象路径")

            source_package, source_name = source.split(".", 1)
            target_package, target_name = destination.split(".", 1)
            _move_path(source_package)
            _move_path(target_package)
            if source in seen_sources or source == destination or any(os.path.isfile(_move_filename(source_package, extension)) for extension in (".uasset", ".umap")):
                raise RuntimeError("源路径重复 已存在或未变化 拒绝修复: " + source)

            records = _move_primary_assets(registry.get_assets_by_package_name(target_package))
            if len(records) != 1 or _move_class_path(records[0].asset_class_path) == "/Script/CoreUObject.ObjectRedirector":
                raise RuntimeError("目标不是唯一真实主资产: " + destination)

            name = str(records[0].asset_name)
            allowed_names = {name}
            if _move_class_path(records[0].asset_class_path).endswith("Blueprint"):
                allowed_names.update((name + "_C", "Default__" + name + "_C"))

            if target_name not in allowed_names or not any(os.path.isfile(_move_filename(target_package, extension)) for extension in (".uasset", ".umap")):
                raise RuntimeError("目标对象名或物理文件不符: " + destination)

            redirect_map[unreal.SoftObjectPath(source)] = unreal.SoftObjectPath(destination)
            seen_sources.add(source)
            sources.add(source_package)
            references.update(_move_referencers(registry, source_package))

        selected = [_move_path(path) for path in referencer_paths]
        if not set(selected).issubset(references):
            raise RuntimeError("明确包不是当前缺失路径的引用者")

        primary = {}
        for path in selected:
            records = _move_primary_assets(registry.get_assets_by_package_name(path))
            if len(records) != 1 or _move_class_path(records[0].asset_class_path) == "/Script/CoreUObject.ObjectRedirector":
                raise RuntimeError("只允许唯一主资产引用者: " + path)

            primary[path] = records[0]

        report = {"dry_run": dry_run, "referencers": selected, "replacements": replacements, "saved": [], "success": False}
        if dry_run:
            report["success"] = True
            return json.dumps(report, ensure_ascii=False)

        hard_options = unreal.AssetRegistryDependencyOptions(include_hard_package_references=True, include_soft_package_references=False, include_searchable_names=False, include_soft_management_references=False, include_hard_management_references=False)
        missing_hard = {}
        for path in selected:
            missing = [str(name) for name in registry.get_dependencies(path, hard_options) or [] if str(name).startswith("/Game/") and not any(os.path.isfile(_move_filename(str(name), extension)) for extension in (".uasset", ".umap"))]
            if missing:
                missing_hard[path] = missing

        if missing_hard:
            raise RuntimeError("引用者存在缺失硬依赖 拒绝加载后保存: " + json.dumps(missing_hard, ensure_ascii=False))

        _require_move_checkout(selected, [])
        existing_errors = {obj.get_path_name() for obj in unreal.ObjectIterator() if isinstance(obj, unreal.Blueprint) and obj.get_path_name().startswith("/Game/") and obj.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR}
        packages = []
        for path in selected:
            package = unreal.load_package(path)
            asset = unreal.load_object(None, path + "." + str(primary[path].asset_name), follow_redirectors=False)
            if package is None or asset is None or package.get_path_name() != path or asset.get_outermost() != package or _move_class_path(asset.get_class().get_class_path_name()) != _move_class_path(primary[path].asset_class_path):
                raise RuntimeError("引用者加载不完整或类型改变: " + path)

            packages.append(package)

        current_errors = {obj.get_path_name() for obj in unreal.ObjectIterator() if isinstance(obj, unreal.Blueprint) and obj.get_path_name().startswith("/Game/") and obj.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR}
        blocking = _move_blocking_blueprint_errors(existing_errors, current_errors, selected)
        if blocking or _move_dirty_packages():
            report["blocked"] = "加载后出现蓝图错误或脏包 不保存"
            report["blueprint_errors"] = sorted(blocking)
            report["dirty_packages"] = _move_dirty_packages()
            return json.dumps(report, ensure_ascii=False)

        unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, redirect_map)
        for package in packages:
            if not unreal.EditorLoadingAndSavingUtils.save_packages([package], False):
                report["blocked"] = "保存失败 保留已完成清单 不自动重试"
                return json.dumps(report, ensure_ascii=False)

            report["saved"].append(package.get_path_name())

        registry.scan_paths_synchronous(sorted({path.rsplit("/", 1)[0] for path in selected}), force_rescan=True)
        report["remaining_selected"] = {path: sorted(set(_move_referencers(registry, path)).intersection(selected)) for path in sorted(sources)}
        report["dirty_packages"] = _move_dirty_packages()
        report["success"] = not report["dirty_packages"] and not any(report["remaining_selected"].values())
        unreal.log("[BBBMissingSoftPathRepair]{} 保存 {} 个包".format("PASS" if report["success"] else "FAIL", len(report["saved"])))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_native_dependency_packages(asset_paths: list[str]) -> str:
        """
        /**
         * 只读核对明确内容包的原生依赖闭包 不加载资产
         * @param asset_paths	需要核验的内容包路径 单批最多 5000 项
         * @return 原生脚本包 缺失依赖和遍历数量
         */
        """
        if not asset_paths or len(asset_paths) > 5000 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 5000 个不重复包路径")
        packages = [_move_path(path) for path in asset_paths]
        return json.dumps(_move_native_dependency_report(_move_registry(), packages), ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_asset_packages(asset_paths: list[str]) -> str:
        """
        /**
         * 只读检查明确包的注册对象与已加载对象 不跟随重定向加载目标
         * @param asset_paths	明确包路径列表
         * @return 注册类型 重定向目标 引用者 磁盘与脏包状态
         */
        """
        if not asset_paths or len(asset_paths) > 5000 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 5000 个不重复包路径")
        registry = _move_registry()
        dirty = set(_move_dirty_packages())
        results = []
        loaded_children = {path: [] for path in asset_paths}
        for obj in unreal.ObjectIterator():
            outer = obj.get_outermost().get_name()
            if outer in loaded_children:
                loaded_children[outer].append(obj.get_path_name())
        for requested in asset_paths:
            package = _move_path(requested)
            name = package.rsplit("/", 1)[-1]
            loaded = []
            for object_path in (package + "." + name, package + "." + name + "_C", package + ".Default__" + name + "_C"):
                asset = unreal.find_object(None, object_path, follow_redirectors=False)
                if asset is not None:
                    loaded.append({"path": asset.get_path_name(), "class_path": _move_class_path(asset.get_class().get_class_path_name())})
            records = []
            for data in registry.get_assets_by_package_name(package):
                records.append({
                    "object": package + "." + str(data.asset_name),
                    "class_path": _move_class_path(data.asset_class_path),
                    "primary": data.is_u_asset(),
                    "destination": str(data.get_tag_value("DestinationObject") or ""),
                })
            results.append({
                "package": package,
                "records": records,
                "loaded": loaded,
                "loaded_child_count": len(loaded_children[package]),
                "loaded_children": sorted(loaded_children[package])[:64],
                "referencers": _move_referencers(registry, package),
                "dirty": package in dirty,
                "file_exists": any(os.path.isfile(_move_filename(package, extension)) for extension in (".uasset", ".umap")),
            })
        return json.dumps({"read_only": True, "packages": results}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def refresh_asset_registry_folders(folder_paths: list[str]) -> str:
        """
        /**
         * 按明确目录从磁盘刷新注册表 不加载 修改或删除资产文件
         * @param folder_paths	明确的项目内容子目录
         * @return 刷新目录及各目录主资产数量
         */
        """
        if not folder_paths or len(folder_paths) > 64 or len(set(folder_paths)) != len(folder_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复子目录")
        paths = [_move_path(path) for path in folder_paths]
        if _move_dirty_packages():
            raise RuntimeError("存在脏包时拒绝用磁盘状态覆盖注册表")
        registry = _move_registry()
        registry.scan_paths_synchronous(paths, force_rescan=True)
        return json.dumps({"folders": [{"path": path, "asset_count": len(_move_primary_assets(registry.get_assets_by_path(path, recursive=True)))} for path in paths]}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def consolidate_verified_asset_copies(moves_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 将已校验的旧副本引用归入明确目标 使用原生合并而非删除磁盘文件
         * @param moves_json	含 source destination class_path source_sha256 的精确清单
         * @param dry_run	仅预检开关
         * @return 合并进度和结果 失败时不自动回滚
         */
        """
        requests = _move_requests(moves_json)
        if len(requests) > 64:
            raise RuntimeError("副本合并单批最多 64 项")
        registry = _move_registry()
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝合并")
        pairs = []
        affected = set()
        seen = set()
        for item in requests:
            source = item["source"]
            destination = item["destination"]
            if source in seen or destination in seen:
                raise RuntimeError("合并不允许重复或链式路径")
            seen.update((source, destination))
            expected_hash = item.get("source_sha256", "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
                raise RuntimeError("必须提供经备份核验的源 SHA256: " + source)
            with open(_move_filename(source), "rb") as stream:
                actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual_hash.casefold() != expected_hash.casefold():
                raise RuntimeError("源副本已变化 拒绝合并: " + source)
            objects = []
            for path in (source, destination):
                records = _move_primary_assets(registry.get_assets_by_package_name(path))
                if len(records) != 1 or _move_class_path(records[0].asset_class_path) != item.get("class_path"):
                    raise RuntimeError("包类型与清单不符: " + path)
                if item["class_path"] in {"/Script/CoreUObject.ObjectRedirector", "/Script/Engine.World", "/Script/Engine.MapBuildDataRegistry"}:
                    raise RuntimeError("不支持合并重定向器或关卡数据")
                object_path = path + "." + path.rsplit("/", 1)[-1]
                obj = unreal.load_asset(object_path, follow_redirectors=False)
                if obj is None or obj.get_path_name() != object_path:
                    raise RuntimeError("未加载精确对象: " + object_path)
                objects.append(obj)
            affected.update((source, destination))
            affected.update(_move_referencers(registry, source))
            pairs.append((item, objects[0], objects[1]))
        if _move_dirty_packages():
            raise RuntimeError("预检加载产生脏包 拒绝合并")
        report = {"dry_run": dry_run, "count": len(pairs), "affected": sorted(affected), "completed": []}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(affected, [])
        for item, source, destination in pairs:
            if not unreal.EditorAssetLibrary.consolidate_assets(destination, [source]):
                unreal.log_error("[BBBAssetConsolidate]原生合并未通过 必须检查部分结果")
                report["success"] = False
                report["failed_source"] = item["source"]
                return json.dumps(report, ensure_ascii=False)
            report["completed"].append(item["source"])
        report["success"] = not _move_dirty_packages()
        unreal.log("[BBBAssetConsolidate]完成 {} 个旧副本".format(len(report["completed"])))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def fixup_redirector_references(asset_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 只修明确重定向器的项目包引用 保留重定向器本身
         * @param asset_paths	已备份的重定向器包路径
         * @param dry_run	仅预检 不加载或保存引用者
         * @return 引用者清单 保存结果及剩余旧引用
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复重定向包")
        registry = _move_registry()
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝修复引用")
        references = set()
        redirect_map = {}
        for requested in asset_paths:
            path = _move_path(requested)
            records = registry.get_assets_by_package_name(path)
            if not records or any(_move_class_path(data.asset_class_path) != "/Script/CoreUObject.ObjectRedirector" for data in records):
                raise RuntimeError("包不完全由重定向器组成: " + path)
            for data in records:
                target = str(data.get_tag_value("DestinationObject") or "")
                if "'" in target:
                    target = target.split("'", 1)[1].rstrip("'")
                if not target.startswith("/Game/") or "." not in target:
                    raise RuntimeError("重定向目标不明确: " + path)
                if unreal.load_object(None, target) is None:
                    raise RuntimeError("重定向目标无法加载: " + target)
                redirect_map[unreal.SoftObjectPath(path + "." + str(data.asset_name))] = unreal.SoftObjectPath(target)
            references.update(_move_referencers(registry, path))
        for path in references:
            _move_path(path)
        report = {"dry_run": dry_run, "redirectors": list(asset_paths), "referencers": sorted(references)}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(set(asset_paths) | references, [])
        packages = []
        for path in sorted(references):
            package = unreal.load_package(path)
            if package is None or package.get_path_name() != path:
                raise RuntimeError("无法加载精确引用者包: " + path)
            packages.append(package)
        if _move_dirty_packages():
            raise RuntimeError("加载引用者产生脏包 拒绝保存 请先检查")
        if packages:
            unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, redirect_map)
            if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, False):
                raise RuntimeError("引用者保存失败 请核对已保存包 不自动重试")
        report["remaining"] = {path: _move_referencers(registry, path) for path in asset_paths}
        report["success"] = not any(report["remaining"].values()) and not _move_dirty_packages()
        unreal.log("[BBBRedirectorReferences]引用修复 {}".format("PASS" if report["success"] else "FAIL"))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def fixup_external_actor_redirector_references(asset_paths: list[str], referencer_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 修复明确外部 Actor 包对资产重定向器的引用并保留重定向器
         * @param asset_paths	已备份的重定向包路径 单批最多 64 项
         * @param referencer_paths	已备份且已由当前用户独占签出的外部 Actor 包 单批最多 32 项
         * @param dry_run	仅检查注册表和磁盘 不加载或保存包
         * @return 本批已保存包和仍引用旧路径的结果
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复重定向包")
        if not referencer_paths or len(referencer_paths) > 32 or len(set(referencer_paths)) != len(referencer_paths):
            raise RuntimeError("必须提供 1 至 32 个不重复外部 Actor 包")
        registry = _move_registry()
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝修复外部 Actor 引用")
        references = set()
        redirect_map = {}
        targets = set()
        for requested in asset_paths:
            path = _move_path(requested)
            records = registry.get_assets_by_package_name(path)
            if not records or any(_move_class_path(data.asset_class_path) != "/Script/CoreUObject.ObjectRedirector" for data in records):
                raise RuntimeError("包不完全由重定向器组成: " + path)
            for data in records:
                target = str(data.get_tag_value("DestinationObject") or "")
                if "'" in target:
                    target = target.split("'", 1)[1].rstrip("'")
                if not target.startswith("/Game/") or "." not in target:
                    raise RuntimeError("重定向目标不明确: " + path)
                target_package, target_name = target.split(".", 1)
                target_package = _move_path(target_package)
                redirect_map[unreal.SoftObjectPath(path + "." + str(data.asset_name))] = unreal.SoftObjectPath(target)
                targets.add(target)
                target_records = _move_primary_assets(registry.get_assets_by_package_name(target_package))
                if len(target_records) != 1 or _move_class_path(target_records[0].asset_class_path) == "/Script/CoreUObject.ObjectRedirector":
                    raise RuntimeError("重定向目标主资产缺失或不唯一: " + target)
                if str(target_records[0].asset_name) == target_name and _move_class_path(target_records[0].asset_class_path) == "/Script/Engine.Blueprint":
                    old_asset_path = path + "." + str(data.asset_name)
                    generated_target = str(target_records[0].get_tag_value("GeneratedClass") or target + "_C")
                    if "'" in generated_target:
                        generated_target = generated_target.split("'", 1)[1].rstrip("'")
                    if not generated_target.startswith(target_package + "."):
                        raise RuntimeError("蓝图生成类不属于精确目标包: " + generated_target)
                    default_target = target_package + ".Default__" + generated_target.split(".", 1)[1]
                    redirect_map[unreal.SoftObjectPath(old_asset_path + "_C")] = unreal.SoftObjectPath(generated_target)
                    redirect_map[unreal.SoftObjectPath(path + ".Default__" + str(data.asset_name) + "_C")] = unreal.SoftObjectPath(default_target)
                    targets.add(generated_target)
                    targets.add(default_target)
            references.update(_move_referencers(registry, path))
        selected = [_external_actor_package_path(path) for path in referencer_paths]
        _require_external_actor_world_owners(registry, selected)
        if not set(selected).issubset(references):
            raise RuntimeError("本批包含不是当前重定向器引用者的外部 Actor 包")
        report = {"dry_run": dry_run, "redirectors": list(asset_paths), "referencers": selected, "saved": [], "success": False}
        if dry_run:
            report["success"] = True
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(selected, [])
        packages = []
        for target_path in targets:
            target_object = unreal.load_object(None, target_path, follow_redirectors=False)
            if target_object is None or target_object.get_path_name() != target_path:
                raise RuntimeError("无法加载精确重定向目标对象: " + target_path)
            if _move_class_path(target_object.get_class().get_class_path_name()) == "/Script/CoreUObject.ObjectRedirector":
                raise RuntimeError("重定向目标仍是重定向器: " + target_path)
        for path in selected:
            package = unreal.load_package(path)
            if package is None or package.get_path_name() != path:
                raise RuntimeError("无法加载精确外部 Actor 包: " + path)
            records = registry.get_assets_by_package_name(path)
            if not records or any(not isinstance(record.get_asset(), unreal.Actor) for record in records):
                raise RuntimeError("外部包未完整加载实际 Actor 拒绝保存: " + path)
            packages.append(package)
        if _move_dirty_packages():
            raise RuntimeError("加载外部 Actor 包产生脏包 拒绝保存 请先检查")
        unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, redirect_map)
        for package in packages:
            path = package.get_path_name()
            if not unreal.EditorLoadingAndSavingUtils.save_packages([package], False):
                report["blocked"] = "保存失败 请核对已保存包 不自动重试: " + path
                report["dirty_packages"] = _move_dirty_packages()
                unreal.log_error("[BBBExternalActorRedirectorFixup]保存失败 不自动重试")
                return json.dumps(report, ensure_ascii=False)
            report["saved"].append(path)
        actor_folders = sorted({path.rsplit("/", 1)[0] for path in selected})
        registry.scan_paths_synchronous(actor_folders, force_rescan=True)
        for path in asset_paths:
            remaining = set(_move_referencers(registry, path))
            report.setdefault("remaining_selected", {})[path] = sorted(remaining.intersection(selected))
        report["dirty_packages"] = _move_dirty_packages()
        report["success"] = not report["dirty_packages"] and not any(report["remaining_selected"].values())
        unreal.log("[BBBExternalActorRedirectorFixup]{} 保存 {} 个外部 Actor 包".format("PASS" if report["success"] else "FAIL", len(report["saved"])))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def fixup_redirector_references_batch(asset_paths: list[str], referencer_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 分批修复明确引用者 保留重定向器 遇到加载或蓝图错误立即停止保存
         * @param asset_paths	已备份的重定向包路径
         * @param referencer_paths	已备份的引用者包路径 单批最多 32 项
         * @param dry_run	仅检查注册表 不加载对象或保存
         * @return 本批保存结果 剩余引用及阻止保存的原因
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复重定向包")
        if not referencer_paths or len(referencer_paths) > 32 or len(set(referencer_paths)) != len(referencer_paths):
            raise RuntimeError("必须提供 1 至 32 个不重复引用者包")
        registry = _move_registry()
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝修复引用")
        references = set()
        redirect_map = {}
        targets = []
        for requested in asset_paths:
            path = _move_path(requested)
            records = registry.get_assets_by_package_name(path)
            if not records or any(_move_class_path(data.asset_class_path) != "/Script/CoreUObject.ObjectRedirector" for data in records):
                raise RuntimeError("包不完全由重定向器组成: " + path)
            for data in records:
                target = str(data.get_tag_value("DestinationObject") or "")
                if "'" in target:
                    target = target.split("'", 1)[1].rstrip("'")
                if not target.startswith("/Game/") or "." not in target:
                    raise RuntimeError("重定向目标不明确: " + path)
                _move_path(target.split(".", 1)[0])
                redirect_map[unreal.SoftObjectPath(path + "." + str(data.asset_name))] = unreal.SoftObjectPath(target)
                targets.append(target)
            references.update(_move_referencers(registry, path))
        selected = [_move_path(path) for path in referencer_paths]
        if not set(selected).issubset(references):
            raise RuntimeError("本批包含不是当前引用者的包")
        primary = {}
        for path in selected:
            records = _move_primary_assets(registry.get_assets_by_package_name(path))
            if len(records) != 1 or _move_class_path(records[0].asset_class_path) == "/Script/CoreUObject.ObjectRedirector":
                raise RuntimeError("仅支持单主资产内容包: " + path)
            primary[path] = records[0]
        report = {"dry_run": dry_run, "referencers": selected, "saved": [], "success": False}
        if dry_run:
            report["success"] = True
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(selected, [])
        existing_errors = []
        for obj in unreal.ObjectIterator():
            if isinstance(obj, unreal.Blueprint) and obj.get_path_name().startswith("/Game/"):
                if obj.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
                    existing_errors.append(obj.get_path_name())
        packages = []
        for target in targets:
            if unreal.load_object(None, target) is None:
                report["blocked"] = "重定向目标无法加载: " + target
                return json.dumps(report, ensure_ascii=False)
        for path in selected:
            package = unreal.load_package(path)
            asset = unreal.load_object(None, path + "." + str(primary[path].asset_name), follow_redirectors=False)
            if package is None or asset is None or package.get_path_name() != path or asset.get_outermost() != package:
                report["blocked"] = "引用者加载不完整: " + path
                return json.dumps(report, ensure_ascii=False)
            if _move_class_path(asset.get_class().get_class_path_name()) != _move_class_path(primary[path].asset_class_path):
                report["blocked"] = "引用者加载类型与注册表不符: " + path
                return json.dumps(report, ensure_ascii=False)
            packages.append(package)
        errors = []
        for obj in unreal.ObjectIterator():
            if isinstance(obj, unreal.Blueprint) and obj.get_path_name().startswith("/Game/"):
                if obj.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
                    errors.append(obj.get_path_name())
        dirty = _move_dirty_packages()
        blocking_errors = _move_blocking_blueprint_errors(existing_errors, errors, selected)
        if blocking_errors or dirty:
            report["blocked"] = "加载产生蓝图错误或脏包 拒绝保存"
            report["blueprint_errors"] = sorted(errors)
            report["blocking_blueprint_errors"] = blocking_errors
            report["dirty_packages"] = dirty
            unreal.log_error("[BBBRedirectorBatch]拒绝保存 加载检查未通过")
            return json.dumps(report, ensure_ascii=False)
        unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, redirect_map)
        for package in packages:
            path = package.get_path_name()
            if not unreal.EditorLoadingAndSavingUtils.save_packages([package], False):
                report["blocked"] = "保存失败 请核对部分进度: " + path
                unreal.log_error("[BBBRedirectorBatch]保存失败 不自动重试")
                return json.dumps(report, ensure_ascii=False)
            report["saved"].append(path)
        referencer_folders = sorted({path.rsplit("/", 1)[0] for path in selected})
        registry.scan_paths_synchronous(referencer_folders, force_rescan=True)
        report["remaining"] = {path: _move_referencers(registry, path) for path in asset_paths}
        report["remaining_selected"] = {
            path: sorted(set(referencers).intersection(selected))
            for path, referencers in report["remaining"].items()
        }
        report["dirty_packages"] = _move_dirty_packages()
        report["success"] = not report["dirty_packages"] and not any(report["remaining_selected"].values())
        unreal.log("[BBBRedirectorBatch]本批保存 {} 个引用者".format(len(report["saved"])))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def delete_asset_redirectors(asset_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 仅删除明确的无引用重定向包 不跟随重定向 不删除目标
         * @param asset_paths	已备份的精确重定向包列表
         * @param dry_run	仅预检 不加载或删除对象
         * @return 删除结果及剩余磁盘文件
         */
        """
        if not asset_paths or len(asset_paths) > 5000 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 5000 个不重复包")
        registry = _move_registry()
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝删除")
        object_paths = []
        for requested in asset_paths:
            path = _move_path(requested)
            records = registry.get_assets_by_package_name(path)
            if not records or any(_move_class_path(data.asset_class_path) != "/Script/CoreUObject.ObjectRedirector" for data in records):
                raise RuntimeError("包不完全由重定向器组成: " + path)
            if _move_referencers(registry, path):
                raise RuntimeError("重定向包仍有引用: " + path)
            object_paths.extend(path + "." + str(data.asset_name) for data in records)
        report = {"dry_run": dry_run, "package_count": len(asset_paths), "object_count": len(object_paths)}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(asset_paths, [])
        objects = []
        for path in object_paths:
            obj = unreal.load_object(None, path, follow_redirectors=False)
            if obj is None or obj.get_path_name() != path or obj.get_class().get_name() != "ObjectRedirector":
                raise RuntimeError("不是精确重定向对象: " + path)
            objects.append(obj)
        if _move_dirty_packages() or any(_move_referencers(registry, path) for path in asset_paths):
            raise RuntimeError("加载后出现脏包或新增引用 拒绝删除")
        native = getattr(unreal, "BBBAssetRepairEditorLibrary", None)
        if native is None:
            raise RuntimeError("宿主缺少原包重定向清理能力 必须先编译 BBBAssetRepairEditorLibrary")
        report["engine_success"] = bool(native.delete_redirector_packages(objects))
        report["remaining_files"] = [path for path in asset_paths if any(os.path.isfile(_move_filename(path, extension)) for extension in (".uasset", ".umap"))]
        report["remaining_packages"] = [path for path in asset_paths if registry.get_assets_by_package_name(path)]
        report["unsaved_packages"] = _move_dirty_packages()
        report["success"] = report["engine_success"] and not report["remaining_files"] and not report["remaining_packages"] and not report["unsaved_packages"]
        unreal.log("[BBBRedirectorDelete]{} {} 个包".format("PASS" if report["success"] else "FAIL", len(asset_paths)))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def audit_asset_folder_move(source_folder: str, destination_folder: str) -> str:
        """只读检查目录迁移的目标冲突和目录外引用"""
        source = source_folder.rstrip("/")
        destination = destination_folder.rstrip("/")
        protected_segments = {"__ExternalActors__", "__ExternalObjects__"}
        if not source.startswith("/Game/") or not destination.startswith("/Game/"):
            raise RuntimeError("源目录和目标目录必须位于 /Game 下")
        if source == destination or source.startswith(destination + "/") or destination.startswith(source + "/"):
            raise RuntimeError("源目录与目标目录不能相同或互相嵌套")
        if protected_segments.intersection(source.split("/")) or protected_segments.intersection(destination.split("/")):
            raise RuntimeError("不允许迁移关卡外部 Actor 或对象目录")

        assets = unreal.EditorAssetLibrary.list_assets(source, recursive=True, include_folder=False)
        if not assets:
            raise RuntimeError("源目录没有可审计的资产: " + source)

        collisions = []
        external_assets = []
        referencer_counts = {}
        referencer_packages = set()
        for listed_path in assets:
            leaf = listed_path.rsplit("/", 1)[-1]
            package_path = listed_path.rsplit(".", 1)[0] if "." in leaf else listed_path
            relative_path = package_path[len(source):].lstrip("/")
            target_package = destination + "/" + relative_path
            target_name = target_package.rsplit("/", 1)[-1]
            target_object = target_package + "." + target_name
            if unreal.EditorAssetLibrary.does_asset_exist(target_object):
                collisions.append(target_object)

            referencers = unreal.EditorAssetLibrary.find_package_referencers_for_asset(package_path, False)
            external_referencers = []
            for referencer in referencers:
                referencer_leaf = referencer.rsplit("/", 1)[-1]
                referencer_package = referencer.rsplit(".", 1)[0] if "." in referencer_leaf else referencer
                if referencer_package == package_path or referencer_package.startswith(source + "/"):
                    continue
                external_referencers.append(referencer_package)
                referencer_packages.add(referencer_package)
                parts = referencer_package.split("/")
                root = "/".join(parts[:3]) if len(parts) > 2 else referencer_package
                referencer_counts[root] = referencer_counts.get(root, 0) + 1

            if external_referencers:
                external_assets.append({"asset": package_path, "referencers": external_referencers})

        report = {
            "source_folder": source,
            "destination_folder": destination,
            "asset_count": len(assets),
            "target_collision_count": len(collisions),
            "target_collision_examples": collisions[:30],
            "assets_with_external_referencers": len(external_assets),
            "external_referencer_package_count": len(referencer_packages),
            "external_referencer_counts_by_root": referencer_counts,
            "external_reference_examples": external_assets[:30],
            "read_only": True,
            "perforce_checkout_check_required": True
        }
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def move_assets_batch(moves_json: str, dry_run: bool = True) -> str:
        """预检并按给定顺序批量移动资产或目录"""
        registry = _move_registry()
        report = _plan_asset_moves(_move_requests(moves_json), registry)
        report["dry_run"] = dry_run
        report["executed"] = False
        if dry_run:
            unreal.log("[BBBAssetMove]预览 {} 个资产 {} 个阻断项".format(report["asset_count"], len(report["blockers"])))
            return json.dumps(report, ensure_ascii=False)
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("PIE 期间不允许资产移动")
        if report["blockers"]:
            unreal.log_error("[BBBAssetMove]预检拒绝 " + json.dumps(report["blockers"], ensure_ascii=False))
            return json.dumps(report, ensure_ascii=False)

        return _execute_asset_moves(report)

    @toolset_registry.tool_call
    @staticmethod
    def move_partitioned_world(source_package: str, destination_package: str, dry_run: bool = True) -> str:
        """
        /**
         * 使用原生分区构建器迁移明确关卡并核验外部包数量
         * @param source_package		已备份的源关卡包
         * @param destination_package	不存在的目标关卡包
         * @param dry_run			仅预检 不加载或移动关卡
         * @return 原生执行与外部包磁盘核验结果
         */
        """
        source = _move_path(source_package)
        destination = _move_path(destination_package)
        if source.casefold() == destination.casefold():
            raise RuntimeError("源和目标关卡不能相同")
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝迁移关卡")
        registry = _move_registry()
        records = _move_primary_assets(registry.get_assets_by_package_name(source))
        if len(records) != 1 or _move_class_path(records[0].asset_class_path) != "/Script/Engine.World" or str(records[0].get_tag_value("LevelIsPartitioned") or "") != "1":
            raise RuntimeError("源不是唯一的分区关卡主资产")
        source_file = _move_filename(source, ".umap")
        if not os.path.isfile(source_file):
            raise RuntimeError("源关卡文件不存在")
        if registry.get_assets_by_package_name(destination):
            raise RuntimeError("目标包已经注册")
        for extension in (".umap", ".uasset", ".ini"):
            if os.path.exists(_move_filename(destination, extension)):
                raise RuntimeError("目标磁盘文件已存在")
        external = {}
        scan_folders = [source.rsplit("/", 1)[0], destination.rsplit("/", 1)[0]]
        packages = {source}
        packages.update(_move_referencers(registry, source))
        for anchor in ("__ExternalActors__", "__ExternalObjects__"):
            old_folder = "/Game/" + anchor + source[len("/Game"):]
            new_folder = "/Game/" + anchor + destination[len("/Game"):]
            old_directory = os.path.dirname(_move_filename(old_folder + "/__FolderProbe"))
            new_directory = os.path.dirname(_move_filename(new_folder + "/__FolderProbe"))
            files = []
            for root, directories, names in os.walk(old_directory, followlinks=False):
                if any(os.path.islink(os.path.join(root, name)) for name in directories):
                    raise RuntimeError("外部包目录包含链接")
                files.extend(os.path.join(root, name) for name in names if name.endswith(".uasset"))
            if os.path.isdir(new_directory) and any(names for root, directories, names in os.walk(new_directory, followlinks=False)):
                raise RuntimeError("目标外部包目录非空")
            for filename in files:
                relative = os.path.relpath(filename, unreal.Paths.project_content_dir()).replace(os.sep, "/")
                packages.add("/Game/" + relative[:-len(".uasset")])
            external[anchor] = {"source_folder": old_folder, "destination_folder": new_folder, "source_directory": old_directory, "destination_directory": new_directory, "source_files": sorted(files)}
            scan_folders.extend([old_folder, new_folder])
        built_data = source + "_BuiltData"
        if os.path.isfile(_move_filename(built_data)):
            packages.add(built_data)
        report = {"dry_run": dry_run, "source": source, "destination": destination, "source_file": source_file, "destination_file": _move_filename(destination, ".umap"), "affected_packages": sorted(packages), "external": external, "executed": False}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        _require_move_checkout(packages, [destination])
        report["native"] = json.loads(unreal.BBBAssetRepairEditorLibrary.move_partitioned_world(source, destination))
        report["executed"] = report["native"].get("executed", False)
        registry.scan_paths_synchronous(scan_folders, force_rescan=True)
        targets = _move_primary_assets(registry.get_assets_by_package_name(destination))
        report["destination_registered"] = len(targets) == 1 and _move_class_path(targets[0].asset_class_path) == "/Script/Engine.World"
        report["destination_file_exists"] = os.path.isfile(report["destination_file"])
        for entry in external.values():
            entry["remaining_source_files"] = sorted(os.path.join(root, name) for root, directories, names in os.walk(entry["source_directory"], followlinks=False) for name in names if name.endswith(".uasset"))
            entry["destination_files"] = sorted(os.path.join(root, name) for root, directories, names in os.walk(entry["destination_directory"], followlinks=False) for name in names if name.endswith(".uasset"))
            entry["counts_match"] = len(entry["source_files"]) == len(entry["destination_files"]) and not entry["remaining_source_files"]
        report["dirty_packages"] = _move_dirty_packages()
        report["success"] = report["native"].get("success", False) and report["destination_registered"] and report["destination_file_exists"] and all(entry["counts_match"] for entry in external.values()) and not report["dirty_packages"]
        if not report["success"]:
            unreal.log_error("[BBBWorldMove]磁盘或外部包核验未完整通过 必须检查结果 禁止盲重试")
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def move_assets_preserving_external_actor_references(moves_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 原生批量移动普通资产 为明确外部 Actor 引用保留旧路径重定向
         * @param moves_json	精确源目标映射 单批最多 64 个普通资产
         * @param dry_run	仅预检 不加载或移动资产
         * @return 执行结果及仍需修复的引用清单
         */
        """
        registry = _move_registry()
        report = _permit_external_actor_move_references(_plan_asset_moves(_move_requests(moves_json), registry))
        report["dry_run"] = dry_run
        report["executed"] = False
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        if report["blockers"]:
            unreal.log_error("[BBBAssetMoveExternalActors]预检拒绝 " + json.dumps(report["blockers"], ensure_ascii=False))
            return json.dumps(report, ensure_ascii=False)
        unreal.log("[BBBAssetMoveExternalActors]保留 {} 个外部 Actor 引用者的旧路径重定向".format(len(report["external_actor_referencers"])))
        return _execute_asset_moves(report)

    @toolset_registry.tool_call
    @staticmethod
    def verify_asset_moves(moves_json: str) -> str:
        """
        /**
         * 只读核验预览清单中的精确资产映射 不通过旧路径加载目标
         * @param moves_json	move_assets_batch 返回的 assets 数组序列化结果
         * @return JSON 核验结果 包括旧引用与阻止目录清理的剩余文件
         */
        """
        registry = _move_registry()
        requests = _move_requests(moves_json)
        results = []
        dirty = set(_move_dirty_packages())
        source_folders = set()
        seen_sources = set()
        seen_destinations = set()
        for item in requests:
            source = item["source"]
            destination = item["destination"]
            if source.casefold() in seen_sources or destination.casefold() in seen_destinations:
                raise RuntimeError("核验清单包含重复源或目标")
            seen_sources.add(source.casefold())
            seen_destinations.add(destination.casefold())
            expected_class = item.get("class_path")
            if not isinstance(expected_class, str) or not expected_class.startswith("/") or "." not in expected_class:
                raise RuntimeError("必须使用预览返回的精确 assets 清单 含 class_path")
            target_data = _move_primary_assets(registry.get_assets_by_package_name(destination))
            old_data = list(registry.get_assets_by_package_name(source))
            destination_object = destination + "." + destination.rsplit("/", 1)[-1]
            target_valid = (
                len(target_data) == 1
                and _move_class_path(target_data[0].asset_class_path) == expected_class
                and str(target_data[0].asset_name) == destination.rsplit("/", 1)[-1]
            )
            redirectors = [data for data in old_data if _move_class_path(data.asset_class_path) == "/Script/CoreUObject.ObjectRedirector"]
            redirector_targets = []
            for data in redirectors:
                exported_target = str(data.get_tag_value("DestinationObject") or "")
                object_target = exported_target
                if "'" in exported_target:
                    object_target = exported_target.split("'", 1)[1].rstrip("'")
                redirector_targets.append(object_target)
            old_references = _move_referencers(registry, source)
            target_exists = os.path.isfile(_move_filename(destination))
            old_file_exists = os.path.isfile(_move_filename(source))
            old_state_valid = not old_data and not old_file_exists and not old_references
            if old_data and len(old_data) == len(redirectors):
                old_state_valid = (
                    old_file_exists
                    and destination_object in redirector_targets
                    and all(
                        target in {destination_object, destination + "." + str(data.asset_name)}
                        for data, target in zip(redirectors, redirector_targets)
                    )
                )
            pending = sorted(set(item.get("referencers", [])) | {source, destination})
            unsaved = sorted(dirty.intersection(pending))
            success = target_valid and target_exists and old_state_valid and not unsaved
            results.append({
                "source": source,
                "destination": destination,
                "destination_registered": target_valid,
                "destination_file_exists": target_exists,
                "old_file_exists": old_file_exists,
                "redirector_targets": redirector_targets,
                "old_referencers": old_references,
                "unsaved_packages": unsaved,
                "success": success,
            })
            source_folder = item.get("source_folder", source.rsplit("/", 1)[0])
            if source_folder != "/Game":
                source_folder = _move_path(source_folder)
            if not source.casefold().startswith(source_folder.casefold() + "/"):
                raise RuntimeError("清单的 source_folder 不是源资产父目录: " + source)
            source_folders.add(source_folder)

        folders = []
        for folder in sorted(source_folders):
            if any(folder.casefold().startswith(other.casefold() + "/") for other in source_folders if other != folder):
                continue
            directory = os.path.dirname(_move_filename(folder + "/__FolderProbe"))
            remaining_files = []
            if os.path.isdir(directory):
                for root, directories, files in os.walk(directory, followlinks=False):
                    remaining_files.extend(os.path.join(root, name) for name in files)
                    remaining_files.extend(os.path.join(root, name) for name in directories if os.path.islink(os.path.join(root, name)))
            registered = [str(data.package_name) for data in registry.get_assets_by_path(folder, recursive=True)]
            folders.append({
                "folder": folder,
                "remaining_files": sorted(remaining_files),
                "remaining_packages": sorted(set(registered)),
                "empty_on_disk_and_registry": not remaining_files and not registered,
            })
        report = {
            "read_only": True,
            "asset_count": len(results),
            "success": all(item["success"] for item in results),
            "results": results,
            "source_folders": folders,
        }
        unreal.log("[BBBAssetMoveVerify]{} {} 个资产".format("PASS" if report["success"] else "FAIL", len(results)))
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def resave_assets(asset_paths: list[str]) -> str:
        """校验精确资产路径与可编辑状态后强制重存指定资产"""
        from toolset_registry.helpers import require_editable

        if not asset_paths or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供非空且不重复的精确资产路径")

        assets = []
        for path in asset_paths:
            if not path.startswith("/Game/") or "." in path:
                raise RuntimeError("必须提供 Game 下不带对象后缀的包路径")
            object_path = path + "." + path.rsplit("/", 1)[-1]
            asset = unreal.EditorAssetLibrary.load_asset(object_path)
            if asset is None:
                raise RuntimeError("无法加载精确资产: " + object_path)
            require_editable(asset)
            assets.append(asset)

        saved = []
        for asset in assets:
            asset_path = asset.get_path_name()
            if not unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False):
                raise RuntimeError("资产重存失败 已成功重存列表: " + json.dumps(saved))
            saved.append(asset.get_outermost().get_name())

        return json.dumps({"resaved": saved}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def make_current_editor_level_explicit(expected_package: str) -> str:
        """校验活动层包名后显式同步编辑器放置目标层"""
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if subsystem.is_in_play_in_editor():
            raise RuntimeError("PIE 期间不允许切换放置层")
        level = subsystem.get_current_level()
        if level is None or level.get_outermost().get_name() != expected_package:
            raise RuntimeError("活动层不匹配 不切换也不载入其它关卡")
        if not subsystem.set_current_level_by_name(expected_package.rsplit("/", 1)[-1]):
            raise RuntimeError("设置已加载目标层失败")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return json.dumps({"level": level.get_path_name(), "world": world.get_path_name()}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def remove_unreferenced_loaded_redirectors(asset_paths: list[str]) -> str:
        """仅删除已加载且无包引用的重定向对象 拒绝删除普通资产"""
        from toolset_registry.helpers import require_editable

        if not asset_paths or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供非空且不重复的精确资产路径")

        validated = []
        for path in asset_paths:
            if not path.startswith("/Game/") or "." in path:
                raise RuntimeError("必须提供 Game 下不带对象后缀的包路径")
            object_path = path + "." + path.rsplit("/", 1)[-1]
            candidates = []
            default_path = path + ".Default__" + path.rsplit("/", 1)[-1] + "_C"
            for candidate_path in (object_path, object_path + "_C", default_path):
                asset = unreal.find_object(None, candidate_path, follow_redirectors=False)
                if asset is None:
                    continue
                if asset.get_path_name() != candidate_path or asset.get_class().get_name() != "ObjectRedirector":
                    raise RuntimeError("拒绝删除非重定向对象: " + candidate_path)
                require_editable(asset)
                candidates.append(asset)
            if not candidates:
                raise RuntimeError("未找到精确的已加载重定向对象: " + object_path)
            references = unreal.EditorAssetLibrary.find_package_referencers_for_asset(path, True)
            if references:
                raise RuntimeError("重定向仍有引用: {} {}".format(path, references))
            validated.append((path, candidates))

        removed = []
        for path, candidates in validated:
            if not unreal.EditorAssetLibrary.delete_loaded_assets(candidates):
                raise RuntimeError("重定向删除失败 已删除列表: " + json.dumps(removed))
            unreal.log("已清理无引用重定向: " + path)
            removed.append(path)
        return json.dumps({"removed": removed}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def clean_unreferenced_redirectors_in_folder(folder_path: str, dry_run: bool = True) -> str:
        """检查或清理指定目录内无引用且可编辑的重定向器"""
        from toolset_registry.helpers import require_editable

        folder = folder_path.rstrip("/")
        if not folder.startswith("/Game/") or folder.count("/") < 2:
            raise RuntimeError("只允许处理 /Game 下的精确子目录")

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        redirector_class = unreal.load_class(None, "/Script/CoreUObject.ObjectRedirector")
        if redirector_class is None:
            raise RuntimeError("无法解析 UE ObjectRedirector 类型")
        asset_filter = unreal.ARFilter(
            package_paths=[folder],
            recursive_paths=True,
            class_paths=[redirector_class.get_class_path_name()],
            recursive_classes=True
        )
        redirector_data = registry.get_assets(asset_filter)
        redirectors = []
        referenced = []
        uneditable = []
        invalid_assets = []
        for asset_data in redirector_data:
            package_path = str(asset_data.package_name)
            if package_path != folder and not package_path.startswith(folder + "/"):
                continue

            asset_name = str(asset_data.asset_name)
            asset = unreal.EditorAssetLibrary.load_asset(package_path + "." + asset_name)
            if asset is None:
                invalid_assets.append(package_path)
                continue
            if asset.get_class().get_name() != "ObjectRedirector":
                invalid_assets.append(package_path)
                continue

            redirectors.append((package_path, asset))
            if unreal.EditorAssetLibrary.find_package_referencers_for_asset(package_path, True):
                referenced.append(package_path)
            try:
                require_editable(asset)
            except Exception:
                uneditable.append(package_path)

        report = {
            "folder": folder,
            "redirector_count": len(redirectors),
            "referenced_count": len(referenced),
            "referenced_examples": referenced[:30],
            "uneditable_count": len(uneditable),
            "uneditable_examples": uneditable[:30],
            "non_redirector_or_unloadable_count": len(invalid_assets),
            "non_redirector_or_unloadable_examples": invalid_assets[:30],
            "dry_run": dry_run
        }
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        if invalid_assets:
            raise RuntimeError("目录内存在非重定向器或无法加载资产 拒绝批量删除: " + json.dumps(report, ensure_ascii=False))
        if referenced:
            raise RuntimeError("仍有引用的重定向器必须先修复引用 拒绝删除: " + json.dumps(report, ensure_ascii=False))
        if uneditable:
            raise RuntimeError("存在不可编辑的重定向器 拒绝批量删除: " + json.dumps(report, ensure_ascii=False))
        if not redirectors:
            return json.dumps(report, ensure_ascii=False)

        assets = [asset for package_path, asset in redirectors]
        if not unreal.EditorAssetLibrary.delete_loaded_assets(assets):
            raise RuntimeError("批量删除重定向器失败 已完成状态需在内容浏览器复核")

        report["removed_count"] = len(redirectors)
        report["dry_run"] = False
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def modernize_deprecated_blueprint_nodes(asset_path: str) -> str:
        """
        /**
         * 将明确弃用的骨骼网格查询和实例添加节点替换为当前接口
         * @param asset_path	已经备份的真实蓝图包
         * @return 替换数量和成功状态 不编译或保存
         */
        """
        path = _move_path(asset_path)
        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝接口更新")

        _require_move_checkout([path], [])
        asset = unreal.load_object(None, path + "." + path.rsplit("/", 1)[-1], follow_redirectors=False)
        if asset is None or asset.get_class().get_name() not in ["Blueprint", "AnimBlueprint"]:
            raise RuntimeError("目标不是明确蓝图")

        return unreal.BBBAssetRepairEditorLibrary.modernize_deprecated_blueprint_nodes(asset)

    @toolset_registry.tool_call
    @staticmethod
    def rebuild_loaded_actor_construction(actor_paths: list[str]) -> str:
        """
        /**
         * 重建明确非分区角色的构造组件 保留样条点和角色身份
         * @param actor_paths	当前编辑器世界中的精确角色对象路径
         * @return 样条段前后数量和身份校验结果 不保存
         */
        """
        if not actor_paths or len(actor_paths) > 128 or len(set(actor_paths)) != len(actor_paths):
            raise RuntimeError("必须提供 1 至 128 个不重复角色路径")

        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝构造重建")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        package = world.get_outermost().get_path_name() if world is not None else ""
        _move_path(package)
        if any(not path.startswith(package + ".") for path in actor_paths):
            raise RuntimeError("角色不属于当前编辑器世界")

        _require_move_checkout([package], [])
        return unreal.BBBAssetRepairEditorLibrary.rebuild_loaded_actor_construction(actor_paths)

    @toolset_registry.tool_call
    @staticmethod
    def update_pose_assets_from_source(expected_reports_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 使用引擎正式接口更新已有姿势 保留姿势名称和加法基准
         * @param expected_reports_json	检查工具的完整源报告
         * @param dry_run	只预检 调用方执行前必须备份
         * @return 源一致性和姿势名称保留结果 不修改源动画
         */
        """
        expected = json.loads(expected_reports_json)
        if not isinstance(expected, list) or not expected or len(expected) > 64:
            raise RuntimeError("必须提供 1 至 64 项源检查报告")

        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝姿势更新")

        paths = [_move_path(row["asset"].split(".")[0]) for row in expected]
        current = json.loads(BBBAssetMaintenanceToolset.inspect_pose_asset_source_guids(paths))
        if current != expected or any(row["structural_mismatch_count"] or row["curve_mismatch_count"] for row in current):
            raise RuntimeError("源报告变化或姿势结构不一致 拒绝更新")

        if dry_run:
            return json.dumps(current, ensure_ascii=False)

        _require_move_checkout(paths, [])
        results = []
        for row in current:
            asset = unreal.load_object(None, row["asset"], follow_redirectors=False)
            source = unreal.load_object(None, row["source"], follow_redirectors=False)
            if asset.get_editor_property("skeleton") != source.get_editor_property("skeleton"):
                raise RuntimeError("姿势与源动画骨架不同 拒绝更新")

            names = [str(name) for name in asset.get_pose_names()]
            base = str(asset.get_base_pose_name())
            asset.modify()
            asset.update_pose_from_animation(source)
            after = json.loads(unreal.BBBAssetRepairEditorLibrary.inspect_pose_source(asset))
            preserved = names == [str(name) for name in asset.get_pose_names()] and base == str(asset.get_base_pose_name())
            if not preserved or not after["current_matches"] or after["structural_mismatch_count"] or after["curve_mismatch_count"]:
                raise RuntimeError("更新后的姿势名称 基准或源校验失败 未保存")

            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                raise RuntimeError("姿势更新保存失败")

            results.append({"before": row, "after": after, "pose_names": names, "base_pose": base, "names_and_base_preserved": preserved})
        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def delete_unreferenced_asset_packages(asset_paths: list[str], backup_directory: str, dry_run: bool = True) -> str:
        """
        /**
         * 在永久备份哈希和组外引用核验后原生删除明确资产
         * @param asset_paths	需要隔离的真实资产包 最多 64 项
         * @param backup_directory	已有永久备份绝对目录 保留 Content 相对层级
         * @param dry_run	默认只核验
         * @return 每个原生删除结果和磁盘文件不存在的复核
         */
        """
        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供 1 至 64 个不重复包")

        if _move_dirty_packages() or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            raise RuntimeError("脏包或 PIE 期间拒绝资产隔离")

        paths = [_move_path(path) for path in asset_paths]
        registry = _move_registry()
        content = os.path.realpath(unreal.Paths.project_content_dir())
        backup_root = os.path.realpath(backup_directory)
        if not os.path.isabs(backup_directory) or os.path.commonpath([content, backup_root]) == content:
            raise RuntimeError("备份必须位于 Content 外的绝对目录")

        files = []
        for path in paths:
            outside = set(_move_referencers(registry, path)) - set(paths)
            if outside:
                raise RuntimeError("仍有组外引用 拒绝删除: " + path + " " + str(sorted(outside)))

            source = os.path.realpath(_move_filename(path))
            if os.path.commonpath([content, source]) != content:
                raise RuntimeError("资产文件必须位于项目 Content 内")

            if not os.path.isfile(source):
                raise RuntimeError("目标真实资产文件缺失")

            backup = os.path.realpath(os.path.join(backup_root, os.path.relpath(source, content)))
            if os.path.commonpath([backup_root, backup]) != backup_root:
                raise RuntimeError("备份文件必须位于指定永久备份目录内")
            if not os.path.isfile(backup):
                raise RuntimeError("永久备份文件缺失")

            with open(source, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            with open(backup, "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() != digest:
                    raise RuntimeError("原件与永久备份哈希不同 拒绝删除")
            files.append({"package": path, "file": source, "backup": backup, "sha256": digest})

        if dry_run:
            return json.dumps({"dry_run": True, "files": files}, ensure_ascii=False)

        _require_move_checkout(paths, [])
        for row in files:
            object_path = row["package"] + "." + row["package"].rsplit("/", 1)[-1]
            asset = unreal.load_object(None, object_path, follow_redirectors=False)
            row["native_deleted"] = unreal.BBBAssetRepairEditorLibrary.delete_asset_packages([asset])
            row["physical_file_absent"] = not os.path.exists(row["file"])
            if not row["native_deleted"] or not row["physical_file_absent"]:
                unreal.log_error("[BBB][AssetIsolation]原生删除或物理核验失败 " + object_path)
                return json.dumps({"success": False, "files": files}, ensure_ascii=False)

        return json.dumps({"success": True, "files": files}, ensure_ascii=False)


_registration = Registration([BBBAssetMaintenanceToolset])
_registration.unregister()
_registration.register()
