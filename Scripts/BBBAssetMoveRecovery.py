"""Recover a recorded native asset move after its editor host has restarted."""

import json
import os
import importlib

import unreal

import BBBAssetMaintenanceToolset as maintenance
from MCP.mcp_result import McpExecutionError


def finish_redirectors(report):
    """
    /**
     * 接续原生合并产生的精确重定向器清理阶段
     * @param report	原批次迁移映射与执行证据
     * @return 已完成结果 或尚未进入此阶段时返回空值
     */
    """
    registry = maintenance._move_registry()
    sources = []
    for item in report['assets']:
        records = registry.get_assets_by_package_name(item['source'])
        if not records or any(maintenance._move_class_path(row.asset_class_path) != '/Script/CoreUObject.ObjectRedirector' for row in records):
            return None
        for row in records:
            target = str(row.get_tag_value('DestinationObject') or '')
            if "'" in target:
                target = target.split("'", 1)[1].rstrip("'")
            if target != item['destination_object']:
                raise McpExecutionError('rejected', 'MOVE_REDIRECTOR_TARGET_CHANGED', '旧包重定向目标不符合原迁移映射')
        sources.append(item['source'])
    rows = json.dumps(report['assets'])
    before = json.loads(maintenance._verify_asset_moves_json(rows))
    unsaved = {path for row in before['results'] for path in row.get('unsaved_packages', [])}
    destinations = {item['destination'] for item in report['assets']}
    if unsaved - destinations:
        raise McpExecutionError('rejected', 'MOVE_UNEXPECTED_DIRTY_PACKAGE', '迁移收尾包含目标以外的未保存包')
    if unsaved:
        maintenance.require_asset_write(unsaved)
        for path in sorted(unsaved):
            package = unreal.find_object(None, path, follow_redirectors=False)
            if package is None or package.get_path_name() != path or not unreal.EditorLoadingAndSavingUtils.save_packages([package], False):
                raise McpExecutionError('rejected', 'MOVE_TARGET_SAVE_FAILED', '正式目标保存失败')
        before = json.loads(maintenance._verify_asset_moves_json(rows))
    if not all(row['success'] and not row['old_referencers'] for row in before['results']):
        raise McpExecutionError('rejected', 'MOVE_REDIRECTOR_REFERENCES', '正式目标或旧路径引用尚未核验通过')
    maintenance.BBBAssetMaintenanceToolset.delete_asset_redirectors(sources, True)
    cleanup = json.loads(maintenance.BBBAssetMaintenanceToolset.delete_asset_redirectors(sources, False))
    verification = json.loads(maintenance._verify_asset_moves_json(rows))
    current = {**report, 'redirector_cleanup': cleanup, 'verification': verification}
    current['success'] = cleanup.get('success') is True and verification.get('success') is True
    if not current['success']:
        raise McpExecutionError('partial', 'ASSET_MOVE_INCOMPLETE', '重定向器清理未完成', {'recovery': current})
    return current


def resume(report):
    """Use verified native consolidation if both original and renamed assets remain on disk."""
    global maintenance
    maintenance = importlib.reload(maintenance)
    assets = report['assets']
    renamed = {row['source'] for row in report['object_results'] if row['renamed']}
    if not assets or len(assets) > 64 or len(renamed) != len(assets):
        return maintenance._resume_asset_moves(report)
    finished = finish_redirectors(report)
    if finished is not None:
        return finished
    registry = maintenance._move_registry()
    for item in assets:
        source = item['source']
        target = item['destination']
        old_records = maintenance._move_primary_assets(registry.get_assets_by_package_name(source))
        target_records = maintenance._move_primary_assets(registry.get_assets_by_package_name(target))
        if not (len(old_records) == len(target_records) == 1
                and maintenance._move_class_path(old_records[0].asset_class_path) == item['class_path']
                and maintenance._move_class_path(target_records[0].asset_class_path) == item['class_path']
                and os.path.isfile(maintenance._move_filename(source))
                and os.path.isfile(maintenance._move_filename(target))
                and maintenance._move_file_sha256(maintenance._move_filename(source)) == item['source_sha256']):
            return maintenance._resume_asset_moves(report)
    # Both complete, registered copies exist after a host restart.  The original
    # bytes still match the move's pre-write evidence; reject dirty packages and
    # let UE's native consolidation replace references, never delete files directly.
    rows = json.dumps(assets, ensure_ascii=False)
    preview = json.loads(maintenance.BBBAssetMaintenanceToolset.consolidate_verified_asset_copies(rows, True))
    if preview.get('count') != len(assets):
        raise McpExecutionError('rejected', 'MOVE_CONSOLIDATION_PREFLIGHT', '旧包合并预检未通过')
    result = json.loads(maintenance.BBBAssetMaintenanceToolset.consolidate_verified_asset_copies(rows, False))
    if result.get('success') is True:
        finished = finish_redirectors({**report, 'consolidation': result})
        if finished is not None:
            return finished
    verification = json.loads(maintenance._verify_asset_moves_json(rows))
    current = {**report, 'consolidation': result, 'verification': verification}
    current['success'] = result.get('success') is True and verification.get('success') is True
    if not current['success']:
        raise McpExecutionError('partial', 'ASSET_MOVE_INCOMPLETE', '原生合并未完成，保留批次占用', {'recovery': current})
    return current
