import re


READ_TOOLS = {
    "EditorAppToolset": {"IsPIERunning", "GetSelectedActors", "GetSelectedAssets", "GetCameraTransform", "GetContentBrowserPath", "GetOpenAssets"},
    "AssetTools": {"list_folders", "exists", "find_assets", "get_asset_tags", "get_asset_class"},
    "ObjectTools": {"search_subclasses", "get_class", "list_properties", "get_properties"},
    "BBBMcpTaskToolset": {"inspect_editor_activity"},
    "BBBMcpRuntimeToolset": {"inspect_mcp_performance", "get_mcp_usage_guide", "inspect_mcp_dependencies"},
    "BBBGenericEditorToolset": {
        "inspect_dirty_packages", "inspect_pie_characters", "inspect_pie_player_control",
        "inspect_pie_actor_properties", "inspect_pie_actor_skeletal_bones",
        "inspect_pie_hand_attachments", "inspect_pie_bone_alignment",
        "inspect_pie_static_mesh_instances", "inspect_static_mesh_bounds",
        "inspect_animation_notifies", "inspect_animation_notify_properties",
    },
    "BBBAnimationMigrationToolset": {
        "get_pie_input_sequence_status", "get_pie_montage_motion_capture_status",
        "export_animation_blueprint_graphs",
    },
    "BBBAnimationPreviewToolset": {"inspect_animation_transition_capture", "inspect_mass_population_benchmark"},
    "BBBHitReactionToolset": {"inspect_skeletal_hit_reaction_capture"},
    "BBBBlueprintGraphToolset": {"inspect_blueprint_graph_logic", "inspect_blueprint_graph"},
}
READ_ACTIONS = {
    "is_in_pie", "get_output_log", "get_cvar", "get_project_info",
    "list_class_properties", "list_enum_values", "get_viewport_camera",
}
OPAQUE_TOOLS = {
    "execute_tool_script", "execute_python_command", "execute_python_script",
    "execute_editor_script", "execute_console_command", "execute_script",
}


def tool_identity(params):
    """
    /**
     * 解析实际调用目标
     * @param params	协议工具参数
     * @return 工具集 函数与业务参数
     */
    """
    name = params.get("name", "")
    arguments = params.get("arguments", {})
    if name == "call_tool":
        return arguments.get("toolset_name", ""), arguments.get("tool_name", ""), arguments.get("arguments", {})
    if "." in name:
        toolset, name = name.rsplit(".", 1)
        return toolset, name, arguments
    return "", name, arguments


def tool_access(toolset, name, arguments=None):
    """
    /**
     * 统一维护经过源码审查的操作权限
     * @param toolset	实际工具集
     * @param name	工具名称
     * @param arguments	业务参数 发现阶段为空
     * @return shared_read editor_write pie_write conditional 或 blocked
     */
    """
    definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
    if name.replace("_", "").lower() in {value.replace("_", "").lower() for value in OPAQUE_TOOLS}:
        return "blocked"
    if not toolset and name in {"list_toolsets", "describe_toolset"}:
        return "shared_read"
    if name in READ_TOOLS.get(definition, set()):
        return "shared_read"
    if definition == "BBBExternalToolset" and name == "util":
        if arguments is None:
            return "conditional"
        action = arguments.get("action")
        if action == "execute_console_command":
            return "blocked"
        if action in READ_ACTIONS:
            return "shared_read"
        if action in {"start_pie", "stop_pie"}:
            return "pie_write"
    if definition == "BBBAnimationPreviewToolset" and name == "inspect_mass_inspection_population":
        if arguments is None:
            return "conditional"
        if arguments.get("pause_game", False) is False:
            return "shared_read"
    if definition == "BBBGenericEditorToolset" and name == "generate_and_inspect_pcg":
        if arguments is None:
            return "conditional"
        if arguments.get("generate", False):
            return "blocked"
    if definition == "EditorAppToolset" and name in {"StartPIE", "StopPIE"}:
        return "pie_write"
    return "editor_write"


def is_read_call(params):
    """
    /**
     * @param params	协议工具参数
     * @return 是否属于共享查询
     */
    """
    return tool_access(*tool_identity(params)) == "shared_read"


def access_catalog():
    """
    /**
     * @return AI 可复用的共享查询与参数条件
     */
    """
    return {
        "shared_read_tools": {name: sorted(tools) for name, tools in READ_TOOLS.items()},
        "external_read_actions": sorted(READ_ACTIONS),
        "conditional_rules": {
            "BBBExternalToolset.util": "按 action 分类",
            "BBBAnimationPreviewToolset.inspect_mass_inspection_population": "pause_game=false 可共享查询",
            "BBBGenericEditorToolset.generate_and_inspect_pcg": "generate=false 使用编辑阶段 generate=true 等待活动跟踪能力",
        },
        "default_access": "editor_write",
    }
