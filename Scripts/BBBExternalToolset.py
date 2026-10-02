import importlib
import json
import traceback

import unreal

import toolset_registry
from toolset_registry.registration import Registration


_DOMAIN_MODULES = {
    "animation": "animation_actions",
    "control_rig": "control_rig_actions",
    "data_table": "data_table_actions",
    "editor": "editor_actions",
    "game": "game_actions",
    "layer": "layer_actions",
    "level": "level_actions",
    "level_sequence": "level_sequence_actions",
    "retarget": "retarget_actions",
    "util": "util_actions",
    "vision": "vision_actions",
}


_DOMAIN_ACTIONS = {
    "animation": {
        "add_float_curve",
        "add_notify_track",
        "add_sync_marker",
        "find_socket",
        "get_anim_sequence_info",
        "get_skeletal_mesh_info",
        "get_skeleton_info",
        "list_curves",
        "list_notifies",
        "list_notify_tracks",
        "list_sockets",
        "list_sync_markers",
        "remove_curve",
        "remove_notify_track",
    },
    "control_rig": {
        "add_rig_bone",
        "add_rig_null",
        "add_unit_node",
        "create_control_rig",
        "get_control_rig_info",
        "recompile_control_rig",
    },
    "data_table": {
        "create_data_table",
        "does_row_exist",
        "export_to_csv",
        "get_column_names",
        "get_row_names",
        "get_rows_as_json",
        "remove_row",
        "set_rows_from_json",
    },
    "editor": {
        "close_asset_editor",
        "create_proxy_actor",
        "get_open_assets",
        "get_selected_assets",
        "join_actors",
        "merge_actors",
        "open_editor_for_asset",
        "replace_mesh_on_selected",
        "replace_mesh_on_specified",
        "replace_mtl_on_selected",
        "replace_mtl_on_specified",
    },
    "game": {
        "add_input_action",
        "add_input_mapping",
        "set_game_mode",
    },
    "layer": {
        "add_actor_to_layer",
        "create_layer",
        "delete_layer",
        "get_actors_in_layer",
        "list_layers",
        "remove_actor_from_layer",
    },
    "level": {
        "create_level",
        "get_current_level_path",
        "list_level_actors",
        "load_level",
        "save_all_levels",
        "save_current_level",
        "set_world_settings",
    },
    "level_sequence": {
        "add_anim_track",
        "add_camera",
        "add_possessable",
        "add_spawnable_from_class",
        "add_transform_keyframe",
        "add_transform_track",
        "close_sequencer",
        "convert_binding",
        "create_level_sequence",
        "get_sequence_info",
        "open_in_sequencer",
        "remove_binding",
        "set_playback_range",
    },
    "retarget": {
        "add_retarget_chain",
        "auto_map_chains",
        "batch_retarget",
        "create_ik_rig",
        "create_retargeter",
        "get_ik_rig_info",
        "initialize_retarget_ops",
        "set_retarget_chain_bones",
        "set_retargeter_source_ik_rig",
    },
    "util": {
        "execute_console_command",
        "get_cvar",
        "get_output_log",
        "get_project_info",
        "get_viewport_camera",
        "is_in_pie",
        "list_class_properties",
        "list_enum_values",
        "print_message",
        "save_all_dirty",
        "set_cvar",
        "set_log_verbosity",
        "set_viewport_camera",
        "start_pie",
        "stop_pie",
    },
    "vision": {
        "capture_actors",
        "capture_from",
        "capture_viewport",
    },
}


def _load_module(domain):
    module_name = _DOMAIN_MODULES.get(domain)
    if module_name is None:
        raise ValueError("不支持的外部工具领域: {}".format(domain))

    return importlib.import_module(module_name)


def _list_domain_actions(domain):
    module = _load_module(domain)
    actions = _DOMAIN_ACTIONS.get(domain)
    if actions is None:
        raise ValueError("未配置外部工具领域白名单: {}".format(domain))

    return sorted(
        action
        for action in actions
        if callable(getattr(module, "ue_" + action, None))
    )


def _decode_params(params_json):
    if not params_json:
        return {}

    params = json.loads(params_json)
    if not isinstance(params, dict):
        raise ValueError("params_json 必须编码为对象")

    return params


def _dispatch(domain, action, params_json):
    if not action:
        raise ValueError("动作名不能为空")

    if action.startswith("ue_"):
        raise ValueError("动作名不需要包含 ue_ 前缀")

    actions = _DOMAIN_ACTIONS.get(domain)
    if actions is None:
        raise ValueError("未配置外部工具领域白名单: {}".format(domain))
    if action not in actions:
        raise ValueError("{} 领域动作未通过白名单校验: {}".format(domain, action))

    module = _load_module(domain)
    function = getattr(module, "ue_" + action, None)
    if not callable(function):
        raise ValueError("{} 领域不存在动作: {}".format(domain, action))

    result = function(**_decode_params(params_json))
    if isinstance(result, str):
        return result

    return json.dumps(result, ensure_ascii=False)


def _run(domain, action, params_json):
    try:
        return _dispatch(domain, action, params_json)
    except Exception as error:
        unreal.log_error("[BBBExternal] {}.{} 执行失败: {}".format(domain, action, error))
        return json.dumps(
            {
                "success": False,
                "domain": domain,
                "action": action,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


@unreal.uclass()
class BBBExternalToolset(unreal.ToolsetDefinition):
    """移植 GenOrca Unreal MCP 中当前官方工具集缺少的 UE Python 工具"""

    @toolset_registry.tool_call
    @staticmethod
    def list_available_actions() -> str:
        """列出已移植的 GenOrca 工具领域和动作"""
        return json.dumps(
            {
                "source": "GenOrca/unreal-mcp",
                "sourceRevision": "f7986db239516aa4299ddc6f54d713253bd82631",
                "license": "Apache-2.0",
                "domains": {
                    domain: _list_domain_actions(domain)
                    for domain in sorted(_DOMAIN_MODULES)
                },
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def animation(action: str, params_json: str = "{}") -> str:
        """执行动画序列、Notify、Sync Marker、曲线和骨骼查询动作"""
        return _run("animation", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def control_rig(action: str, params_json: str = "{}") -> str:
        """执行 Control Rig 创建、骨骼、Null、节点和重编译动作"""
        return _run("control_rig", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def data_table(action: str, params_json: str = "{}") -> str:
        """执行 DataTable 行列查询、导出和 JSON 写入动作"""
        return _run("data_table", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def editor(action: str, params_json: str = "{}") -> str:
        """执行资产编辑器和选中 Actor 的批处理动作"""
        return _run("editor", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def level(action: str, params_json: str = "{}") -> str:
        """执行关卡创建、加载、World Settings 和保存动作"""
        return _run("level", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def retarget(action: str, params_json: str = "{}") -> str:
        """执行 IK Rig、IK Retargeter、链映射和批量重定向动作"""
        return _run("retarget", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def level_sequence(action: str, params_json: str = "{}") -> str:
        """执行 Level Sequence 创建、绑定、轨道和关键帧动作"""
        return _run("level_sequence", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def layer(action: str, params_json: str = "{}") -> str:
        """执行关卡 Layer 查询、创建、删除和 Actor 管理动作"""
        return _run("layer", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def game(action: str, params_json: str = "{}") -> str:
        """执行 GameMode 和 Enhanced Input 配置动作"""
        return _run("game", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def vision(action: str, params_json: str = "{}") -> str:
        """执行视口、指定姿态和 Actor 截图动作"""
        return _run("vision", action, params_json)

    @toolset_registry.tool_call
    @staticmethod
    def util(action: str, params_json: str = "{}") -> str:
        """执行日志、CVar、视口、PIE 和项目状态动作"""
        return _run("util", action, params_json)


_registration = Registration([BBBExternalToolset])


if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        """
        /**
         * 等待工具类重实例化后替换原注册 不重启编辑器
         * @param delta_seconds	本帧时间间隔
         * @return 无返回值
         */
        """
        try:
            _registration.unregister()
            if not _registration.register():
                raise RuntimeError("外部工具注册表不可用")
            unreal.log("[BBBExternal]工具类更新后已替换注册 请重新发现并验证调用")
        except Exception as error:
            unreal.log_error("[BBBExternal]工具类更新后注册失败 {}".format(error))
        finally:
            unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
