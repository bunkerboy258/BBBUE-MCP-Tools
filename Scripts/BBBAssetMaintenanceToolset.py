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


def _move_dirty_packages():
    """
    /** @return 当前所有项目脏包 防止原生重命名顺带保存其它会话的修改 */
    """
    packages = list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
    packages.extend(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
    return sorted({package.get_path_name() for package in packages if package.get_path_name().startswith("/Game/")})


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
        data = list(registry.get_assets_by_package_name(source))
        folder_data = list(registry.get_assets_by_path(source, recursive=True))
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
            class_path = str(asset_data.asset_class_path)
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
            if len(registry.get_assets_by_package_name(package)) != 1:
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
    return {
        "requested_count": len(requests),
        "asset_count": len(assets),
        "moves": roots,
        "assets": assets,
        "referencer_packages": sorted(referencers),
        "blockers": blockers,
        "can_execute_after_checkout": not blockers,
        "checkout_checked": False,
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


@unreal.uclass()
class BBBAssetMaintenanceToolset(unreal.ToolsetDefinition):
    """提供精确限定资产范围的维护工具"""

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
            if str(asset.get_class().get_class_path_name()) != item["class_path"]:
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
            target_data = list(registry.get_assets_by_package_name(destination))
            old_data = list(registry.get_assets_by_package_name(source))
            destination_object = destination + "." + destination.rsplit("/", 1)[-1]
            target_valid = (
                len(target_data) == 1
                and str(target_data[0].asset_class_path) == expected_class
                and str(target_data[0].asset_name) == destination.rsplit("/", 1)[-1]
            )
            redirectors = [data for data in old_data if str(data.asset_class_path) == "/Script/CoreUObject.ObjectRedirector"]
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
            if len(old_data) == 1 and len(redirectors) == 1:
                old_state_valid = old_file_exists and redirector_targets == [destination_object]
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


_registration = Registration([BBBAssetMaintenanceToolset])
_registration.unregister()
_registration.register()
