"""Recover a recorded native asset move after its editor host has restarted."""

import json
import os

import unreal

import BBBAssetMaintenanceToolset as maintenance
from MCP.mcp_result import McpExecutionError


def resume(report):
    """Use verified native consolidation if both original and renamed assets remain on disk."""
    assets = report['assets']
    renamed = {row['source'] for row in report['object_results'] if row['renamed']}
    if not assets or len(assets) > 64 or len(renamed) != len(assets):
        return maintenance._resume_asset_moves(report)
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
    verification = json.loads(maintenance._verify_asset_moves_json(rows))
    current = {**report, 'consolidation': result, 'verification': verification}
    current['success'] = result.get('success') is True and verification.get('success') is True
    if not current['success']:
        raise McpExecutionError('partial', 'ASSET_MOVE_INCOMPLETE', '原生合并未完成，保留批次占用', {'recovery': current})
    return current
