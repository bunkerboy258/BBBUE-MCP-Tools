# Copyright (c) 2025 GenOrca. All Rights Reserved.

import json
import unreal

from BBBAssetWritePolicy import require_asset_write, require_write_access
from editor_toolset.toolsets.data_asset import DataAssetTools


def _new_asset(path, asset_type):
    """/** @param path 明确目标 @param asset_type 数据资产类型 @return 新资产 */"""
    if not path or unreal.EditorAssetLibrary.does_asset_exist(path):
        raise ValueError("NEW_ASSET_REQUIRED")
    require_asset_write([], destinations=[path])
    folder, name = path.rsplit("/", 1)
    return DataAssetTools.create(folder, name, asset_type.static_class())


def _save(asset):
    """/** @param asset 本次目标 @return 保存完成 */"""
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError("ASSET_SAVE_FAILED")


def ue_set_game_mode(game_mode_class_path: str = None) -> str:
    """Sets the GameMode Override on the current level's World Settings."""
    world = unreal.EditorLevelLibrary.get_editor_world()
    settings = world.get_world_settings()
    mode = unreal.load_class(None, game_mode_class_path) if game_mode_class_path else None
    if game_mode_class_path and (mode is None or not unreal.MathLibrary.class_is_child_of(mode, unreal.GameModeBase.static_class())):
        raise ValueError("GAME_MODE_CLASS_REQUIRED")
    require_write_access(settings)
    require_asset_write([settings])
    settings.modify()
    settings.set_editor_property("default_game_mode", mode)
    actual = settings.get_editor_property("default_game_mode")
    if actual != mode:
        raise RuntimeError("GAME_MODE_VERIFICATION_FAILED")
    return json.dumps({"game_mode": actual.get_path_name() if actual else None})


def ue_add_input_action(asset_path: str = None, value_type: str = "Bool") -> str:
    """Creates a new Enhanced Input Action asset."""
    types = {"Bool": unreal.InputActionValueType.BOOLEAN, "Axis1D": unreal.InputActionValueType.AXIS1D, "Axis2D": unreal.InputActionValueType.AXIS2D, "Axis3D": unreal.InputActionValueType.AXIS3D}
    if value_type not in types:
        raise ValueError("INPUT_VALUE_TYPE")
    action = _new_asset(asset_path, unreal.InputAction)
    action.set_editor_property("value_type", types[value_type])
    _save(action)
    return json.dumps({"asset_path": action.get_path_name(), "value_type": value_type})


def ue_add_input_mapping(mapping_context_path: str = None, action_path: str = None, key_name: str = None) -> str:
    """Creates/updates an InputMappingContext with a key-to-action mapping."""
    if not mapping_context_path or not action_path or not key_name:
        raise ValueError("MAPPING_PARAMETERS_REQUIRED")
    action = unreal.load_asset(action_path)
    if not isinstance(action, unreal.InputAction):
        raise ValueError("INPUT_ACTION_REQUIRED")
    key = unreal.Key()
    key.set_editor_property("key_name", key_name)
    if unreal.EditorAssetLibrary.does_asset_exist(mapping_context_path):
        context = unreal.load_asset(mapping_context_path)
        if not isinstance(context, unreal.InputMappingContext):
            raise ValueError("MAPPING_CONTEXT_REQUIRED")
        require_write_access(context)
    if not unreal.EditorAssetLibrary.does_asset_exist(mapping_context_path):
        context = _new_asset(mapping_context_path, unreal.InputMappingContext)
    context.modify()
    context.map_key(action, key)
    _save(context)
    return json.dumps({"mapping_context_path": context.get_path_name(), "action_path": action.get_path_name(), "key_name": key_name})
