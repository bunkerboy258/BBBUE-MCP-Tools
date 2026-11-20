import importlib
import json
import os

import unreal

import BBBAssetMaintenanceToolset as maintenance
from MCP.mcp_result import McpExecutionError


def _object_path(package):
    """/** @param package	已核验的包路径 @return 主资产对象路径 */"""
    return package + "." + package.rsplit("/", 1)[-1]


def _inspect_sources(assets, registry, scope):
    """
    /**
     * 核对已保存目标并区分旧副本 重定向器和已清理路径
     * @param assets	原批次已改名的映射
     * @param registry	已扫描的资产注册表
     * @param scope	原批次明确的写入范围
     * @return 待合并副本 已登记重定向器和真正空的原包
     */
    """
    copies = {}
    redirectors = []
    empty = []
    for item in assets:
        source = item["source"]
        destination = item["destination"]
        target = list(maintenance._move_primary_assets(registry.get_assets_by_package_name(destination)))
        if (not os.path.isfile(maintenance._move_filename(destination)) or len(target) != 1
                or str(target[0].asset_name) != destination.rsplit("/", 1)[-1]
                or maintenance._move_class_path(target[0].asset_class_path) != item["class_path"]):
            raise McpExecutionError("rejected", "MOVE_TARGET_CHANGED", "正式目标路径或类型变化", {"package": destination})
        refs = set(maintenance._move_referencers(registry, source))
        if refs - scope:
            raise McpExecutionError("rejected", "MOVE_REFERENCER_REQUIRED", "旧包出现原批次范围外引用", {"package": source, "referencers": sorted(refs - scope)})
        records = list(registry.get_assets_by_package_name(source))
        filename = maintenance._move_filename(source)
        if not os.path.isfile(filename):
            if records or refs:
                raise McpExecutionError("rejected", "MOVE_SOURCE_STATE_REQUIRED", "缺失旧文件仍有注册对象或引用", {"package": source})
            continue
        if records and all(maintenance._move_class_path(row.asset_class_path) == "/Script/CoreUObject.ObjectRedirector" for row in records):
            for row in records:
                tag = str(row.get_tag_value("DestinationObject") or "")
                actual = tag.split("'", 1)[1].rstrip("'") if "'" in tag else tag
                expected = destination + "." + str(row.asset_name)
                if actual.casefold() != expected.casefold():
                    raise McpExecutionError("rejected", "MOVE_SOURCE_CHANGED", "旧重定向器不指向正式目标对象", {"package": source})
                if expected != item["destination_object"]:
                    blueprint = unreal.load_object(None, item["destination_object"], follow_redirectors=False)
                    generated = blueprint.generated_class() if isinstance(blueprint, unreal.Blueprint) else None
                    default = unreal.get_default_object(generated) if generated is not None else None
                    if expected.casefold() not in {obj.get_path_name().casefold() for obj in (generated, default) if obj is not None}:
                        raise McpExecutionError("rejected", "MOVE_SOURCE_CHANGED", "重定向器的蓝图子对象身份不符", {"package": source})
            redirectors.append(source)
            continue
        if maintenance._move_file_sha256(filename) != item["source_sha256"]:
            raise McpExecutionError("rejected", "MOVE_SOURCE_CHANGED", "旧副本摘要与原批次不符", {"package": source})
        primary = list(maintenance._move_primary_assets(records))
        if not records:
            empty.append(source)
            continue
        if (len(primary) != 1 or str(primary[0].asset_name) != source.rsplit("/", 1)[-1]
                or maintenance._move_class_path(primary[0].asset_class_path) != item["class_path"]
                or item["class_path"] in {"/Script/Engine.World", "/Script/Engine.MapBuildDataRegistry"}):
            raise McpExecutionError("rejected", "MOVE_SOURCE_STATE_REQUIRED", "旧副本对象身份不符", {"package": source})
        copies[source] = (item, refs)
    return copies, redirectors, empty


def _consolidation_order(copies):
    """/** @param copies	已核验副本与引用者 @return 优先处理依赖旧包的副本 */"""
    remaining = set(copies)
    while remaining:
        package = min(remaining, key=lambda path: (len((copies[path][1] & remaining) - {path}), path))
        remaining.remove(package)
        yield copies[package][0]


def resume(report):
    """
    /**
     * 使用原批次证据接续保存失败的混合迁移
     * @param report	所属批次的已执行映射与原始摘要
     * @return 正式目标和旧路径均已核验的实际结果
     */
    """
    global maintenance
    maintenance = importlib.reload(maintenance)
    renamed = {row["source"] for row in report["object_results"] if row["renamed"]}
    assets = [item for item in report["assets"] if item["source"] in renamed]
    if not assets or len(assets) > 5000:
        return maintenance._resume_asset_moves(report)

    scope = {maintenance._move_path(p) for p in report["referencer_packages"]}
    sources = set()
    destinations = set()
    for item in assets:
        source = maintenance._move_path(item["source"])
        destination = maintenance._move_path(item["destination"])
        if (item["source_object"] != _object_path(source) or item["destination_object"] != _object_path(destination)
                or source.casefold() in sources or destination.casefold() in destinations):
            raise McpExecutionError("rejected", "MOVE_RECOVERY_INVALID", "迁移对象身份或映射不符", {"package": source})
        sources.add(source.casefold())
        destinations.add(destination.casefold())
        scope.update((source, destination))
    if sources & destinations:
        raise McpExecutionError("rejected", "MOVE_RECOVERY_INVALID", "迁移源和目标包重叠")

    registry = maintenance._move_registry()
    copies, redirectors, empty = _inspect_sources(assets, registry, scope)
    if not copies and not redirectors:
        return maintenance._resume_asset_moves(report)
    if empty:
        raise McpExecutionError("rejected", "MOVE_SOURCE_STATE_REQUIRED", "混合批次发现未注册的旧文件", {"packages": empty})
    if maintenance._move_dirty_packages():
        raise McpExecutionError("rejected", "MOVE_RECOVERY_GUARD", "原生合并前编辑器仍有未保存的项目包")
    maintenance.require_asset_write(scope)

    pairs = []
    for item in _consolidation_order(copies):
        original = unreal.load_object(None, item["source_object"], follow_redirectors=False)
        target = unreal.load_object(None, item["destination_object"], follow_redirectors=False)
        if (original is None or original.get_path_name() != item["source_object"]
                or target is None or target.get_path_name().casefold() != item["destination_object"].casefold()):
            raise McpExecutionError("rejected", "MOVE_SOURCE_STATE_REQUIRED", "无法加载精确的副本与目标", {"package": item["source"]})
        pairs.append((item, original, target))
    if maintenance._move_dirty_packages():
        raise McpExecutionError("rejected", "MOVE_RECOVERY_GUARD", "加载副本产生脏包")

    completed = []
    try:
        for item, original, target in pairs:
            if not unreal.EditorAssetLibrary.consolidate_assets(target, [original]):
                raise RuntimeError("原生合并失败: " + item["source"])
            completed.append(item["source"])
        registry.scan_paths_synchronous(sorted({path.rsplit("/", 1)[0] for path in scope}), force_rescan=True)
        remaining, redirectors, empty = _inspect_sources(assets, registry, scope)
        if remaining or empty or maintenance._move_dirty_packages():
            raise RuntimeError("合并后仍有副本、未知文件或未保存的项目包")
        for start in range(0, len(redirectors), 64):
            group = redirectors[start:start + 64]
            if any(maintenance._move_referencers(registry, path) for path in group):
                maintenance.BBBAssetMaintenanceToolset.fixup_redirector_references(group, False)
        registry.scan_paths_synchronous(sorted({path.rsplit("/", 1)[0] for path in scope}), force_rescan=True)
        if redirectors:
            cleanup = json.loads(maintenance.BBBAssetMaintenanceToolset.delete_asset_redirectors(redirectors, False))
            if not cleanup.get("success"):
                raise RuntimeError("原生重定向器清理失败")
        verification = json.loads(maintenance._verify_asset_moves_json(json.dumps(assets)))
        if not verification["success"] or any(row["old_file_exists"] or row["old_referencers"] for row in verification["results"]):
            raise RuntimeError("旧包磁盘状态或引用回读失败")
    except Exception as error:
        unreal.log_error("[BBBAssetMoveRecovery] 已合并 {} 个旧包: {}".format(len(completed), error))
        raise McpExecutionError("partial", "MOVE_RECOVERY_GUARD", str(error), {"completed": completed}) from error

    unreal.log("[BBBAssetMoveRecovery] 核验 {} 个目标并清除旧包".format(len(assets)))
    return {"success": True, "verification": verification, "consolidated": completed}
