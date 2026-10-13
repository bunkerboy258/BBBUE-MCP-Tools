import ast
import copy
from functools import lru_cache, wraps
import inspect
import json
from pathlib import Path
import re

from MCP.mcp_result import require_business_success, McpExecutionError
from MCP.mcp_asset_scope import asset_targets


TOOL_DOMAINS = {
    "BBBHudAssetToolset": "hud",
    "BBBTraversalToolset": "traversal",
    "BBBMeleeToolset": "melee",
    "BBBAnimationMigrationToolset": "animation",
    "BBBExternalToolset": "external",
    "BBBGenericEditorToolset": "editor",
    "BBBLevelEditingToolset": "level",
    "BBBBlueprintGraphToolset": "blueprint",
    "BBBRigidPartToolset": "rigid",
    "BBBControlRigAuthoringToolset": "control_rig",
    "BBBMcpRuntimeToolset": "runtime",
    "BBBMcpTaskToolset": None,
    "BBBAssetMaintenanceToolset": "assets",
    "BBBAnimationPreviewToolset": "preview",
    "BBBAnimationGraphToolset": "animation_graph",
    "BBBHitReactionToolset": "hit",
    "BBBSkeletalMeshImportToolset": "skeletal_import",
    "BBBRetargetAssetAuditToolset": "retarget",
    "AssetTools": "asset",
    "ObjectTools": "object",
    "BlueprintTools": "blueprint_base",
    "ControlRigTools": "control_rig_base",
    "SequencerTools": "sequencer",
    "EditorAppToolset": "app",
}
TOOLSET_ROUTES = tuple(name for name in TOOL_DOMAINS if name.startswith("BBB"))

HELPER_MODULES = (
    "BBBBlueprintLayout", "BBBBlueprintAnnotations", "BBBAnimationMotionTools",
    "BBBAnimationTrajectoryTools", "BBBArmTwistTools", "BBBWeaponHandlingTools",
    "BBBAnimationViewTools",
    "BBBSoundAssetAudit", "BBBRecoilAnimationTools", "BBBDisplayAssetCaptureTools", "BBBBlueprintMigration",
)
SCRIPTS_ROOT = Path(__file__).resolve().parent


def register_activity(identity, status, blocking=True, wait=True):
    """/** @param identity	活动唯一标识 @param status	实际状态回读函数 @param blocking	保护共享副作用 @param wait	等待完成后续跑 @return 登记完成 */"""
    import builtins
    if not hasattr(builtins, "BBB_MCP_ACTIVITIES"):
        builtins.BBB_MCP_ACTIVITIES = {}
    builtins.BBB_MCP_ACTIVITIES[identity] = (status, blocking, wait)


def active_activities():
    """/** @return 已登记活动的实际状态 */"""
    import builtins
    records = getattr(builtins, "BBB_MCP_ACTIVITIES", {})
    active = []
    for identity, (callback, blocking, wait) in list(records.items()):
        try:
            value = callback()
        except Exception:
            value = {"status": "unknown"}
        if isinstance(value, bool):
            value = {"status": "running" if value else "completed"}
        if value.get("status") in {"pending", "running", "unknown"} or value.get("running") or value.get("state") in {"waiting", "running"} or value.get("releaseError") or value.get("cleanupError"):
            item = {"id": identity, "status": value.get("status", value.get("state", "running"))}
            if not blocking:
                item["blocking"] = False
            if not wait:
                item["wait"] = False
            active.append(item)
            continue
        records.pop(identity, None)
    return sorted(active, key=lambda item: item["id"])


def start_automation_activity(test_filter):
    """/** @param test_filter 测试前缀 @return 已登记的正式测试请求 */"""
    import uuid
    import unreal
    command = unreal.SystemLibrary.get_command_line()
    match = re.search(r'(?i)(?:^|\s)-(?:abslog|log)=(?:"([^"]+)"|(\S+))', command)
    log_name = Path(unreal.Paths.get_project_file_path()).stem + ".log"
    if match is not None:
        log_name = match.group(1) or match.group(2)
    log_path = Path(log_name)
    if not log_path.is_absolute():
        log_path = Path(unreal.Paths.project_log_dir()) / log_path
    if not log_path.is_file():
        raise McpExecutionError("rejected", "AUTOMATION_LOG_REQUIRED", "测试活动需要当前宿主日志")
    state = {"status": "pending", "offset": log_path.stat().st_size, "tail": b"", "seen": False}
    marker = "BBB_MCP_AUTOMATION_" + uuid.uuid4().hex
    def status():
        with log_path.open("rb") as handle:
            handle.seek(state["offset"])
            value = state["tail"] + handle.read(65536)
            state["offset"] = handle.tell()
        if marker.encode() in value:
            state["seen"] = True
            value = value.split(marker.encode(), 1)[1]
            state["status"] = "running"
        if state["seen"] and b"Automation Test Queue Empty" in value:
            state["status"] = "completed"
        state["tail"] = value[-256:]
        return {"status": state["status"]}
    register_activity("automation:" + marker, status)
    unreal.log(marker)
    unreal.SystemLibrary.execute_console_command(None, "Automation RunTests " + test_filter)
    return {"filter": test_filter, "requested": True, "log_file": str(log_path), "log_offset": state["offset"]}


@lru_cache(maxsize=None)
def source_index(module_name):
    """
    /**
     * 只缓存当前加载周期的源码元数据 不缓存资产或注册状态
     * @param module_name	本仓库模块名称
     * @return 源码函数与模块导入映射
     */
    """
    path = SCRIPTS_ROOT / (module_name + ".py")
    if module_name.endswith("_actions"):
        path = SCRIPTS_ROOT / "MCP/ThirdParty/GenOrca" / (module_name + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    functions = {}
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom) and node.module in HELPER_MODULES:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
    definition = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == module_name), None)
    public = []
    if definition is not None:
        public = [node.name for node in definition.body if isinstance(node, ast.FunctionDef)
            and any(ast.unparse(decorator) in {"mcp_tool", "toolset_registry.tool_call"} for decorator in node.decorator_list)]
    return {"functions": functions, "imports": imports, "public_tools": sorted(public)}


@lru_cache(maxsize=None)
def native_requirements(module_name, function_name):
    """
    /**
     * @param module_name	源码模块
     * @param function_name	工具或辅助函数
     * @return 当前加载周期的静态原生引用 不包含宿主状态
     */
    """
    return _walk_native_requirements(module_name, function_name, set())


def _walk_native_requirements(module_name, function_name, visited):
    """
    /**
     * 追踪静态原生引用和本仓库辅助调用 动态业务条件仍由工具预检
     * @param module_name	源码模块
     * @param function_name	工具或辅助函数
     * @param visited	当前递归路径
     * @return 原生类到所需函数名称集合
     */
    """
    key = (module_name, function_name)
    if key in visited:
        return {}
    visited.add(key)
    index = source_index(module_name)
    function = index["functions"].get(function_name)
    if function is None:
        return {}
    requirements = {}
    aliases = {}
    call_targets = {id(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "unreal":
            if node.attr.startswith("BBB"):
                aliases[ast.unparse(node)] = node.attr
                requirements.setdefault(node.attr, set())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and ast.unparse(node.args[0]) == "unreal" and isinstance(node.args[1], ast.Constant):
                name = node.args[1].value
                if isinstance(name, str) and (name.startswith("BBB")):
                    aliases[ast.unparse(node)] = name
                    requirements.setdefault(name, set())
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and ast.unparse(node.value) in aliases:
            for target in node.targets:
                aliases[ast.unparse(target)] = aliases[ast.unparse(node.value)]
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and ast.unparse(node.value) in aliases:
            owner = aliases[ast.unparse(node.value)]
            if id(node) in call_targets or owner.endswith("Library"):
                requirements[owner].add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
            owner = aliases.get(ast.unparse(node.args[0]))
            if owner and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                requirements[owner].add(node.args[1].value)
        if not isinstance(node, ast.Call):
            continue
        child = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in index["functions"]:
                child = (module_name, name)
            if isinstance(index["imports"].get(name), tuple):
                child = index["imports"][name]
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            imported = index["imports"].get(node.func.value.id)
            if imported in HELPER_MODULES:
                child = (imported, node.func.attr)
        if child:
            for name, methods in _walk_native_requirements(*child, visited).items():
                requirements.setdefault(name, set()).update(methods)
    return requirements


def dependency_status(requirements, unreal_module):
    """
    /**
     * @param requirements	原生类及函数要求
     * @param unreal_module	当前宿主 API
     * @return 缺失符号与可用状态
     */
    """
    missing_classes = []
    missing_functions = []
    for name, methods in sorted(requirements.items()):
        definition = getattr(unreal_module, name, None)
        if definition is None:
            missing_classes.append(name)
            continue
        for method in sorted(methods):
            if not callable(getattr(definition, method, None)):
                missing_functions.append(name + "." + method)
    return {
        "required_native_classes": sorted(requirements),
        "required_native_functions": sorted(name + "." + method for name, methods in requirements.items() for method in methods),
        "missing_native_classes": missing_classes,
        "missing_native_functions": missing_functions,
        "native_dependencies_ready": not missing_classes and not missing_functions,
    }


def mcp_tool(method):
    """
    /**
     * 统一项目工具的原生符号与业务失败边界 保留官方注册和参数结构
     * @param method	静态公开工具
     * @return 官方可注册函数
     */
    """
    import unreal
    import toolset_registry

    function = method.__func__ if isinstance(method, staticmethod) else method
    module_name = Path(function.__code__.co_filename).stem
    requirements = native_requirements(module_name, function.__name__)

    @wraps(function)
    def invoke(*args, **kwargs):
        status = dependency_status(requirements, unreal)
        if not status["native_dependencies_ready"]:
            return json.dumps(McpExecutionError("rejected", "NATIVE_DEPENDENCY_MISSING", "原生依赖待准备", status).value, ensure_ascii=False)
        try:
            result = function(*args, **kwargs)
        except McpExecutionError as error:
            return json.dumps(error.value, ensure_ascii=False)
        require_business_success(result)
        return result

    invoke.__signature__ = inspect.signature(function)
    return toolset_registry.tool_call(staticmethod(invoke))




QUERY_TOOLS = {
    "AssetTools": {"list_folders", "exists", "find_assets", "get_asset_tags", "get_asset_class", "can_edit_asset", "is_checked_out", "is_dirty", "get_referencers", "get_dependencies"},
    "ObjectTools": {"search_subclasses", "get_class", "list_properties", "get_properties"},
    "EditorAppToolset": {"IsPIERunning", "GetSelectedActors", "GetSelectedAssets", "GetCameraTransform", "GetContentBrowserPath", "GetOpenAssets"},
    "BBBMcpRuntimeToolset": {"inspect_mcp_performance", "inspect_mcp_dependencies"},
    "BBBGenericEditorToolset": {
        "inspect_material_statistics",
        "inspect_dirty_packages", "inspect_pie_characters", "inspect_pie_player_control", "inspect_pie_actor_properties",
        "inspect_pie_actor_skeletal_bones", "inspect_pie_hand_attachments", "inspect_pie_bone_alignment", "inspect_pie_static_mesh_instances",
        "inspect_static_mesh_bounds", "inspect_animation_notifies", "inspect_animation_notify_properties", "inspect_sound_assets",
        "inspect_animation_float_curves", "inspect_animation_montage_segments", "inspect_asset_properties", "inspect_blueprint_class_defaults",
        "inspect_niagara_graphs", "inspect_pie_niagara_system", "inspect_control_rig_graphs", "get_niagara_capture_status",
        "probe_pie_character_ground_contacts",
    },
    "BBBBlueprintGraphToolset": {"inspect_blueprint_graph_logic", "inspect_blueprint_graph", "inspect_owned_objects"},
    "BBBAnimationMigrationToolset": {"get_pie_input_sequence_status", "get_pie_montage_motion_capture_status", "get_pie_character_motion_capture_status", "export_animation_blueprint_graphs", "inspect_backward_recoil_context", "inspect_animation_bone_track_keys", "inspect_pie_arm_pose", "probe_python_api", "probe_animation_assets", "probe_animation_blueprint", "probe_animation_bone_trajectories", "probe_animation_component_poses", "probe_animation_instance_runtime", "probe_animation_property_access_paths", "probe_pie_character_animation_runtime"},
    "BBBAnimationPreviewToolset": {"inspect_animation_transition_capture", "inspect_mass_population_benchmark"},
    "BBBHitReactionToolset": {"inspect_skeletal_hit_reaction_capture", "inspect_zombie_gib_presentation", "inspect_pie_audio_device", "inspect_blood_residue", "inspect_player_weapon_hit_state", "inspect_physics_asset_constraints", "inspect_skeletal_physics_state"},
    "BBBAssetMaintenanceToolset": {"inspect_external_object_package_metadata", "inspect_external_actor_package_metadata", "inspect_external_actor_packages", "inspect_physics_asset_material_bindings", "inspect_package_objects", "inspect_pose_asset_source_guids", "inspect_animation_access_errors", "inspect_content_dependency_integrity", "inspect_loaded_package_soft_paths", "inspect_native_dependency_packages", "inspect_native_package_referencers", "inspect_asset_packages", "inspect_foliage_base_cache"},
    "BBBControlRigAuthoringToolset": {"inspect_mesh_bounds", "inspect_authoring_api", "inspect_control_rig_reference", "inspect_control_rig_graph", "inspect_control_rig_controls", "inspect_sequence_bindings"},
    "BBBAnimationGraphToolset": {"inspect_mass_scene_population", "inspect_mass_variation_network"},
    "BBBMeleeToolset": {"inspect_upper_body_mask", "inspect_melee_sources"},
    "BBBRigidPartToolset": {"inspect_reference_attachment", "inspect_static_mesh_geometry"},
    "BBBTraversalToolset": {"get_pie_traversal_samples", "inspect_pie_traversal_contact_points", "inspect_traversal_montage_windows", "inspect_pie_traversal_network", "inspect_traversal_editing_schema"},
    "BBBRetargetAssetAuditToolset": {"inspect_retargeter", "inspect_animation_poses"},
}

EXTERNAL_QUERIES = {
    "animation": {"find_socket", "get_anim_sequence_info", "get_skeletal_mesh_info", "get_skeleton_info", "list_curves", "list_notifies", "list_notify_tracks", "list_sockets", "list_sync_markers"},
    "control_rig": {"get_control_rig_info"},
    "data_table": {"does_row_exist", "get_column_names", "get_row_names", "get_rows_as_json"},
    "editor": {"get_open_assets", "get_selected_assets"},
    "layer": {"get_actors_in_layer", "list_layers"},
    "level": {"get_current_level_path", "list_level_actors"},
    "level_sequence": {"get_sequence_info"},
    "retarget": {"get_ik_rig_info"},
    "util": {"is_in_pie", "get_output_log", "get_cvar", "get_project_info", "list_class_properties", "list_enum_values", "get_viewport_camera"},
}

BLOCKED_TOOLS = {
    "execute_tool_script", "execute_python_command", "execute_python_script", "execute_editor_script",
    "execute_console_command", "execute_script",
}

PIE_TOOLS = {
    "BBBAnimationMigrationToolset": {"sample_weapon_handling_runtime", "sample_backward_recoil_runtime", "start_locomotion_runtime_probe", "stop_locomotion_runtime_probe", "submit_character_diagnostic_inputs", "capture_animation_pose", "capture_backward_recoil_alpha_samples"},
    "BBBGenericEditorToolset": {"capture_niagara_preview"},
    "BBBControlRigAuthoringToolset": {"capture_attachment_pose"},
    "BBBAnimationGraphToolset": {"capture_monster_stagger_samples"},
    "BBBHitReactionToolset": {"preview_blood_residue", "spawn_inspection_projectile", "spawn_mass_hit_acceptance_population", "start_blood_residue_capture", "start_player_weapon_hit_capture", "start_skeletal_hit_reaction_capture"},
}


WRITE_TARGET_FIELDS = {
    "assets.remap_missing_soft_object_paths": ("referencer_paths",),
    "assets.fixup_redirector_references_batch": ("referencer_paths",),
    "hud.set_input_action_keys": ('mapping_context_path',),
    "traversal.configure_character_movement_input": ('main_path',),
    "traversal.configure_character_traversal_exits": ('main_path',),
    "traversal.configure_character_traversal_state": ('main_path', 'interface_path', 'base_path', 'child_paths'),
    "traversal.configure_traversal_montages": ('destination_paths',),
    "animation.bind_backward_recoil_additive_inputs": ('blueprint_path',),
    "animation.configure_weapon_recoil_animation_source": ('blueprint_path',),
    "animation.simplify_animation_data_accesses": ('blueprint_paths',),
    "animation.migrate_animation_data_accesses": ('blueprint_paths',),
    "animation.repair_raise_weapon_after_firing_transition": ('blueprint_path',),
    "animation.apply_try_weapon_animation_fallbacks": ('blueprint_paths',),
    "animation.repair_main_anim_instance_accesses": ('blueprint_path',),
    "animation.configure_character_rifle_actions": ('character_blueprint_path',),
    "animation.create_equipment_action_montages": ('target_paths',),
    "animation.configure_control_rig_anim_graph_node": ('blueprint_path',),
    "animation.add_animation_layer_boolean_input": ('blueprint_path',),
    "animation.create_control_rig_anim_graph_node": ('blueprint_path',),
    "animation.rebuild_ik_foot_tracks": ('animation_paths',),
    "animation.rewrite_animation_node_binding_paths": ('blueprint_path',),
    "animation.rewrite_animation_property_access_paths": ('blueprint_paths',),
    "animation.rename_animation_blueprint_variables": ('blueprint_path',),
    "animation.set_animation_blueprint_skeletons": ('blueprint_paths',),
    "animation.set_animation_blueprint_preview_mesh": ('blueprint_path',),
    "animation.set_animation_sequence_preview_meshes": ('animation_paths',),
    "animation.set_animation_folder_preview_meshes": ('folder_path',),
    "animation.restore_lyra_stop_pose": ('blueprint_path',),
    "animation.build_weapon_animation_graph": ('blueprint_path',),
    "animation.remap_animation_blueprint_blend_profiles": ('blueprint_path',),
    "animation.rebuild_blend_space_skeleton": ('blend_space_path',),
    "animation.copy_animation_skeleton_metadata": ('target_skeleton_path',),
    "animation.rebind_animation_blueprint_interface": ('blueprint_path',),
    "animation.remap_animation_blueprint_class_references": ('blueprint_path',),
    "animation.remap_animation_sequence_notify_classes": ('animation_path',),
    "animation.rebuild_arm_twist_tracks": ('animation_paths',),
    "animation.limit_hand_swing_tracks": ('animation_paths',),
    "animation.restore_animation_from_source": ('destination_path',),
    "animation.replace_montage_animation_references": ('montage_path',),
    "animation.hold_animation_bone_tracks": ('animation_path',),
    "animation.configure_continuous_bone_rotation": ('blueprint_path',),
    "animation.configure_weapon_handling_graphs": ('blueprint_path',),
    "animation.create_backward_additive_animation": ('destination_path',),
    "animation.create_animation_slice": ('destination_path',),
    "editor.create_primitive_texture_blend_material": ('material_path',),
    "editor.import_skeletal_animation_set": ('destination_path',),
    "editor.create_animation_set_retargeter": ('source_rig_path', 'retargeter_path'),
    "editor.create_channel_sprite_system": ('channel_path', 'system_path'),
    "editor.set_struct_array_object": ('object_path',),
    "editor.configure_persistent_projectile_tracer": ('channel_path', 'system_path'),
    "editor.configure_projectile_tracer_finish": ('channel_path', 'system_path'),
    "editor.configure_projectile_impact_system": ('channel_path', 'system_path', 'material_path'),
    "editor.create_projectile_sprite_material": ('material_path',),
    "assets.configure_monster_blood_residue": ('settings_path',),
    "assets.refresh_asset_registry_folders": ('folder_paths',),
    "assets.repair_foliage_base_cache": ('world_package',),
    "assets.create_missing_path_recovery_redirector": ('source_package',),
    "control_rig.remap_animation_bone_times": ('animation_path',),
    "control_rig.build_pose_control_keys": ('animation_path',),
    "control_rig.prepare_animation_sequence": ('sequence_path',),
    "control_rig.bake_control_rig_animation": ('animation_path',),
    "animation_graph.configure_character_continuous_locomotion": ("asset_path", "base_layer_path", "child_layer_paths", "output_directory"),
    "external.game.add_input_action": ("asset_path",),
    "external.game.add_input_mapping": ("mapping_context_path",),
    "blueprint.optimize_blueprint_node_layout": ("graph_path",),
    "blueprint.set_blueprint_node_positions": ("graph_path",),
    "blueprint.edit_blueprint_graph_comments": ("graph_path",),
    "blueprint.add_blueprint_comment_node": ("graph_path",),
    "blueprint.remove_blueprint_comment_node": ("graph_path",),
    "blueprint.annotate_blueprint_graph": ("graph_path",),
    "blueprint.write_graph": ("graph_path",),
    "blueprint.configure_control_rig_curve_alpha": ("blueprint_path",),
    "blueprint.configure_blueprint_function_thread_safety": ("blueprint_path",),
    "editor.replace_animation_float_curve": ("asset_path",),
    "editor.set_instanced_struct_array": ("asset_path",),
    "editor.create_asset_with_factory": ("asset_path",),
    "editor.reimport_texture": ("asset_path",),
    "editor.import_animation_fbx": ("asset_path",),
    "editor.remove_empty_animation_notify_track": ("asset_path",),
    "editor.resave_asset": ("asset_path",),
    "hit.normalize_zombie_gib_material_bindings": ("mesh_paths",),
    "editor.retime_single_action_montage": ("asset_path",),
    "editor.add_animation_notify_events": ("asset_path",),
    "editor.replace_animation_notify_track": ("asset_path",),
    "editor.move_animation_notify_event": ("asset_path",),
    "editor.set_asset_object_property": ("asset_path",),
    "editor.set_asset_transform_property": ("asset_path",),
    "editor.set_blueprint_class_defaults": ("asset_path",),
    "editor.frame_texture_thumbnails": ("asset_paths",),
    "editor.refresh_material_instances": ("asset_paths",),
    "editor.reload_assets_from_disk": ("asset_paths",),
    "editor.remove_input_action_mappings": ("mapping_context_path",),
    "editor.set_niagara_spawn_update_mode": ("system_path",),
    "editor.set_niagara_pin_default": ("system_path",),
    "editor.bind_niagara_channel_reader": ("system_path",),
    "editor.set_niagara_channel_reader_frame_mode": ("system_path",),
    "editor.create_static_mesh_grid_graph": ("graph_path",),
    "editor.create_static_mesh_points_graph": ("graph_path",),
    "editor.configure_static_mesh_surface_collision": ("mesh_path",),
    "assets.repair_missing_animation_skeleton": ("asset_path",),
    "assets.refresh_blueprint_reflection_metadata": ("asset_path",),
    "assets.modernize_deprecated_blueprint_nodes": ("asset_path",),
    "assets.normalize_material_auxiliary_data": ("asset_paths",),
    "assets.resave_assets": ("asset_paths",),
    "assets.delete_asset_redirectors": ("asset_paths",),
    "assets.remove_unreferenced_loaded_redirectors": ("asset_paths",),
    "assets.delete_metadata_only_package": ("package_path",),
    "assets.remap_package_metadata_owner_paths": ("package_path",),
    "control_rig.create_control_rig": ("asset_path",),
    "control_rig.configure_control_rig_graph": ("asset_path",),
    "control_rig.add_pose_controls": ("asset_path",),
    "control_rig.set_sequence_attachment_transform": ("sequence_path",),
    "control_rig.normalize_authoring_bindings": ("sequence_path",),
    "control_rig.set_sequence_spawn_range": ("sequence_path",),
    "control_rig.create_control_rig_sequence": ("sequence_path",),
    "control_rig.configure_sequence_rig": ("sequence_path",),
    "control_rig.create_sequence_attachment": ("sequence_path",),
    "control_rig.configure_sequence_attachment_animation": ("sequence_path",),
    "control_rig.convert_component_mesh_grips": ("mesh_path",),
    "control_rig.create_attachment_preview_animation": ("destination_path",),
    "control_rig.apply_baked_bone_deltas": ("baked_path",),
    "asset.save_assets": ("asset_paths",),
}

WRITE_TARGET_JSON_FIELDS = {
    "assets.repair_pose_asset_source_guids": ('expected_reports_json', 'asset'),
    "assets.update_pose_assets_from_source": ('expected_reports_json', 'asset'),
    "assets.repair_animation_property_queries": ('operations_json', 'asset'),
    "traversal.configure_traversal_contact_points": ('points_json', 'montage'),
}



def clean_schema(value, fields=False):
    """/** @param value 官方参数结构 @return 精简参数结构 */"""
    if isinstance(value, list):
        return [clean_schema(item) for item in value]
    if isinstance(value, dict):
        result = {key: clean_schema(item, key in {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"})
            for key, item in value.items() if fields or key not in {"title", "examples", "$schema"}}
        if isinstance(result.get("description"), str):
            result["description"] = result["description"][:180]
        return result
    return value


def validate_arguments(value, schema, path="arguments", root=None):
    """/** @param value 参数值 @param schema 参数结构 @param path 字段路径 @return 参数核验完成 */"""
    if root is None:
        root = schema
    if schema is True:
        return
    if schema is False:
        raise ValueError(path + ": forbidden")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/"):
            raise ValueError("LOCAL_SCHEMA_REFERENCE_REQUIRED")
        child = root
        for part in reference[2:].split("/"):
            child = child[part.replace("~1", "/").replace("~0", "~")]
        validate_arguments(value, child, path, root)
    for branch in schema.get("allOf", []):
        validate_arguments(value, branch, path, root)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            accepted = 0
            for branch in schema[keyword]:
                try:
                    validate_arguments(value, branch, path, root)
                    accepted += 1
                except ValueError:
                    pass
            if accepted == 0 or (keyword == "oneOf" and accepted != 1):
                raise ValueError(path + ": schema branch")
    expected = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float), "null": type(None)}
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        accepted = any(isinstance(value, types[item]) and not (item in {"integer", "number"} and isinstance(value, bool)) for item in options)
        if not accepted:
            raise ValueError(path + ": expected " + str(expected))
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + ": enum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(path + ": required " + ",".join(sorted(missing)))
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(path + ": additionalProperties")
        for key, item in value.items():
            child = properties.get(key)
            if child is None and isinstance(schema.get("additionalProperties"), dict):
                child = schema["additionalProperties"]
            if child is not None:
                validate_arguments(item, child, path + "." + key, root)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise ValueError(path + ": items")
        for index, item in enumerate(value):
            validate_arguments(item, schema.get("items", {}), path + "[" + str(index) + "]", root)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise ValueError(path + ": length")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValueError(path + ": pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import math
        if not math.isfinite(value) or value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError(path + ": range")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValueError(path + ": exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise ValueError(path + ": exclusiveMaximum")


def tool_contract(toolset, name, schema, description=""):
    """/** @param toolset 注册工具集 @param name 函数名称 @param schema 官方参数 @param description 原用途 @return 唯一工具契约 */"""
    definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
    domain = TOOL_DOMAINS.get(definition)
    if domain is None and not definition.startswith("BBB") and definition != "ProgrammaticToolset":
        domain = re.sub(r"(?<!^)(?=[A-Z])", "_", definition.removesuffix("Tools")).lower()
    if domain is None or name in BLOCKED_TOOLS:
        return None
    parameters = clean_schema(schema)
    parameters.setdefault("additionalProperties", False)
    if definition.startswith("BBB"):
        function = source_index(definition)["functions"].get(name)
        if function is not None:
            for argument, value in zip(function.args.args[-len(function.args.defaults):], function.args.defaults):
                try:
                    default = ast.literal_eval(value)
                except (ValueError, TypeError):
                    continue
                parameters.get("properties", {}).get(argument.arg, {}).setdefault("default", default)
    access = "read" if name in QUERY_TOOLS.get(definition, set()) else "write"
    if not definition.startswith("BBB") and (name.startswith(("get_", "list_", "find_", "is_", "has_", "search_", "read_")) or name in {"can_edit", "load_asset", "trace_world"}):
        access = "read"
    if name in {"get_actor_transform_at_frame", "get_node_type_pins"}:
        access = "write"
    world = "any" if access == "read" else "editor"
    if "pie" in name.lower().split("_") or definition == "BBBAnimationPreviewToolset" or name in PIE_TOOLS.get(definition, set()):
        world = "pie" if access == "write" else "any"
    if definition == "EditorAppToolset" and name in {"StartPIE", "StopPIE"}:
        access, world = "pie", "any"
    if definition == "BBBAnimationMigrationToolset" and name in {"start_locomotion_runtime_probe", "stop_locomotion_runtime_probe"}:
        access, world = "pie", "any"
    summary = re.sub(r"/\*\*|\*/|^\s*\*", "", description, flags=re.M).strip().split("\n")[0][:100]
    return {"id": domain + "." + name, "toolset": toolset, "name": name, "parameters": parameters,
        "summary": summary or name, "access": access, "world": world, "definition": definition}


def resolve_access(contract, arguments):
    """/** @param contract 工具契约 @param arguments 本次参数 @return 权限与世界约束 */"""
    access, world = contract["access"], contract["world"]
    if "dry_run" in contract["parameters"].get("properties", {}) and arguments.get("dry_run", contract["parameters"]["properties"]["dry_run"].get("default", False)) is True:
        access, world = "read", "any"
    if contract["definition"] == "BBBAnimationPreviewToolset" and contract["name"] == "inspect_mass_inspection_population" and arguments.get("pause_game", False) is False:
        access, world = "read", "any"
    if contract["definition"] == "BBBAnimationMigrationToolset" and contract["name"] in {"sample_weapon_handling_runtime", "sample_backward_recoil_runtime"} and arguments.get("action") == "status":
        access, world = "read", "any"
    if contract["definition"] == "BBBGenericEditorToolset" and contract["name"] == "generate_and_inspect_pcg" and arguments.get("generate", False) is False:
        access = "read"
    return access, world


def write_scope(contract, arguments, access=None, world=None):
    """/** @param contract 契约 @param arguments 本次参数 @param access 权限 @param world 世界 @return 目标字段值与范围证据 */"""
    if access is None:
        access, world = resolve_access(contract, arguments)
    json_fields = WRITE_TARGET_JSON_FIELDS.get(contract["id"])
    if json_fields is not None:
        field, key = json_fields
        rows = json.loads(arguments.get(field, "[]"))
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or not isinstance(row.get(key), str) or not asset_targets(row[key]) for row in rows):
            return [], False
        return [row[key] for row in rows], True
    fields = WRITE_TARGET_FIELDS.get(contract["id"])
    if fields is None and contract["definition"] in {"ObjectTools", "BlueprintTools", "ControlRigTools", "SequencerTools"}:
        roles = {"ObjectTools": ("instance",), "BlueprintTools": ("blueprint", "graph", "node", "nodes"), "ControlRigTools": ("control_rig",), "SequencerTools": ("sequence",)}
        fields = tuple(field for field in roles[contract["definition"]] if field in arguments)
    targets = [arguments.get(field, contract["parameters"].get("properties", {}).get(field, {}).get("default")) for field in fields or ()]
    scoped = access == "read" or world == "pie" or access == "pie" or contract["id"] == "runtime.configure_mcp_performance" or bool(fields and all(target is not None for target in targets) and asset_targets(targets))
    if access != "read" and any(":PersistentLevel." in str(target) for target in targets):
        scoped = False
    return targets, scoped


class ToolCatalog:
    """/** 注册工具的唯一精简契约目录 */"""

    def __init__(self, backend):
        """/** @param backend 官方后端 @return 实际目录 */"""
        self.backend = backend
        self.tools = {}
        for toolset, descriptors in backend.descriptors():
            for descriptor in descriptors:
                name = descriptor["name"].rsplit(".", 1)[-1]
                contract = tool_contract(toolset, name, descriptor.get("inputSchema", {"type": "object"}), descriptor.get("description", ""))
                if contract is None or contract["definition"] == "BBBExternalToolset":
                    continue
                self.add(contract)
        for contract in backend.external_contracts():
            self.add(contract)

    def add(self, contract):
        """/** @param contract 已核实契约 @return 登记完成 */"""
        if contract["id"] in self.tools:
            raise ValueError("DUPLICATE_TOOL_ID")
        self.tools[contract["id"]] = contract

    def find(self, query, limit=8):
        """/** @param query 目标关键字 @param limit 结果上限 @return 候选工具 */"""
        tokens = query.casefold().split()
        candidates = []
        for contract in self.tools.values():
            text = (contract["id"] + " " + contract["summary"]).casefold()
            score = sum(token in text for token in tokens)
            if score:
                candidates.append((score, contract["id"], contract))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [{key: item[key] for key in ("id", "summary", "access")} for score, identity, item in candidates[:limit]]

    def describe(self, identity):
        """/** @param identity 工具 ID @return 单工具契约 */"""
        item = self.tools[identity]
        result = {key: item[key] for key in ("id", "summary", "parameters", "access", "world")}
        result["environments"] = ["editor"]
        if item["access"] in {"read", "pie"} or item["world"] == "pie" or "dry_run" in item["parameters"].get("properties", {}):
            result["environments"].append("test")
        return result

    def prepare(self, operations):
        """/** @param operations 完整批次 @return 已核验操作 */"""
        if not isinstance(operations, list) or not 1 <= len(operations) <= 16:
            raise ValueError("BATCH_SIZE")
        prepared = []
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {"tool", "arguments"}:
                raise ValueError("OPERATION_SCHEMA")
            contract = self.tools.get(operation["tool"])
            if contract is None:
                raise ValueError("TOOL_UNKNOWN")
            arguments = copy.deepcopy(operation["arguments"])
            validate_arguments(arguments, contract["parameters"])
            access, world = resolve_access(contract, arguments)
            if contract["id"] == "asset.save_assets" and not arguments.get("asset_paths"):
                raise ValueError("SAVE_REQUIRES_EXPLICIT_ASSETS")
            targets, scoped = write_scope(contract, arguments, access, world)
            prepared.append({"contract": contract, "arguments": arguments, "access": access, "world": world, "targets": targets, "scoped": scoped})
        return prepared
