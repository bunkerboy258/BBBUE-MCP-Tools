import builtins
import contextlib
import io
import json
import math
import os
import runpy
import time

import unreal

import toolset_registry
from editor_toolset.toolsets.blueprint import BlueprintTools
from toolset_registry.registration import Registration


def _path(value):
    if value is None:
        return None

    return value.get_path_name()


def _read_property(value, property_name):
    try:
        property_value = value.get_editor_property(property_name)
    except Exception as error:
        return {"error": str(error)}

    if isinstance(property_value, unreal.Object):
        return _path(property_value)

    return str(property_value)


def _read_pin(pin):
    linked_to = []
    for linked_pin in list(pin.linked_to):
        owner = linked_pin.owning_node
        linked_to.append(
            {
                "node": owner.get_name() if owner else None,
                "pin": str(linked_pin.pin_name),
            }
        )

    return {
        "default": str(pin.default_value),
        "direction": str(pin.direction),
        "linkedTo": linked_to,
        "name": str(pin.pin_name),
    }


def _read_node(node):
    properties = {}
    for property_name in (
        "blend_space",
        "sequence",
        "state_machine_name",
        "sync_group_name",
        "group_role",
        "method",
    ):
        properties[property_name] = _read_property(node, property_name)

    try:
        anim_node = node.get_editor_property("node")
    except Exception:
        anim_node = None

    if anim_node is not None:
        for property_name in (
            "blend_space",
            "sequence",
            "state_machine_name",
            "sync_group_name",
            "group_role",
            "method",
        ):
            properties["node." + property_name] = _read_property(anim_node, property_name)

    pins = []
    for pin in list(node.pins):
        pins.append(_read_pin(pin))

    return {
        "class": node.get_class().get_name(),
        "name": node.get_name(),
        "pins": pins,
        "properties": properties,
        "title": node.get_node_title(),
    }


def _list_animation_sequences(root_path):
    result = []
    for asset_path in unreal.EditorAssetLibrary.list_assets(root_path, True, False):
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if asset is None:
            continue

        if asset.get_class().get_name() != "AnimSequence":
            continue

        result.append(asset_path)

    return result


def _index_assets_by_name(asset_paths):
    result = {}
    for asset_path in asset_paths:
        asset_name = asset_path.rsplit("/", 1)[-1].split(".", 1)[0]
        result.setdefault(asset_name, []).append(asset_path)

    return result


def _transform_to_dict(transform):
    translation = transform.translation
    rotation = transform.rotation.rotator()
    scale = transform.scale3d

    return {
        "translation": {
            "x": translation.x,
            "y": translation.y,
            "z": translation.z,
        },
        "rotation": {
            "pitch": rotation.pitch,
            "yaw": rotation.yaw,
            "roll": rotation.roll,
        },
        "scale": {
            "x": scale.x,
            "y": scale.y,
            "z": scale.z,
        },
    }


def _write_diagnostic_report(file_name, data):
    report_directory = os.path.join(
        unreal.Paths.project_saved_dir(),
        "Diagnostics",
    )
    os.makedirs(report_directory, exist_ok=True)

    report_path = os.path.join(report_directory, file_name)
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(data, report_file, ensure_ascii=False, indent=4)

    return report_path


def _vector_distance(first, second):
    difference = first - second

    return difference.length()


def _create_action_montage(source_path, target_path, slot_name):
    source_animation = unreal.EditorAssetLibrary.load_asset(source_path)
    if source_animation is None:
        raise RuntimeError("动作源动画不存在: {}".format(source_path))

    if source_animation.get_class().get_name() != "AnimSequence":
        raise RuntimeError("动作源资产不是 AnimSequence: {}".format(source_path))

    if unreal.EditorAssetLibrary.does_asset_exist(target_path):
        raise RuntimeError("目标动作蒙太奇已存在: {}".format(target_path))

    package_path, asset_name = target_path.rsplit("/", 1)
    unreal.EditorAssetLibrary.make_directory(package_path)

    factory = unreal.AnimMontageFactory()
    factory.set_editor_property("source_animation", source_animation)
    montage = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        package_path,
        unreal.AnimMontage,
        factory,
    )
    if montage is None:
        raise RuntimeError("创建动作蒙太奇失败: {}".format(target_path))

    slot_tracks = list(montage.get_editor_property("slot_anim_tracks"))
    if len(slot_tracks) != 1:
        raise RuntimeError("动作蒙太奇插槽轨道数量异常: {}".format(target_path))

    slot_track = slot_tracks[0]
    slot_track.set_editor_property("slot_name", unreal.Name(slot_name))
    montage.set_editor_property("slot_anim_tracks", slot_tracks)

    if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
        raise RuntimeError("保存动作蒙太奇失败: {}".format(target_path))

    return {
        "montage": target_path,
        "slot": slot_name,
        "source": source_path,
    }


def _append_action_montage_track(montage, source_path, slot_name):
    source_animation = unreal.EditorAssetLibrary.load_asset(source_path)
    if source_animation is None:
        raise RuntimeError("动作附加动画不存在: {}".format(source_path))

    segment = unreal.AnimSegment()
    segment.set_editor_properties(
        {
            "anim_reference": source_animation,
            "anim_start_time": 0.0,
            "anim_end_time": source_animation.get_play_length(),
            "anim_play_rate": 1.0,
            "looping_count": 1,
        }
    )

    anim_track = unreal.AnimTrack()
    anim_track.set_editor_property("anim_segments", [segment])

    slot_track = unreal.SlotAnimationTrack()
    slot_track.set_editor_properties(
        {
            "slot_name": unreal.Name(slot_name),
            "anim_track": anim_track,
        }
    )

    slot_tracks = list(montage.get_editor_property("slot_anim_tracks"))
    slot_tracks.append(slot_track)
    montage.set_editor_property("slot_anim_tracks", slot_tracks)


def _create_lyra_character_action_montage(
    base_source_path,
    target_path,
    base_slot_name,
    additive_source_path=None,
    additive_slot_name=None,
    blend_option=unreal.AlphaBlendOption.HERMITE_CUBIC,
):
    result = _create_action_montage(
        base_source_path,
        target_path,
        base_slot_name,
    )
    montage = unreal.EditorAssetLibrary.load_asset(target_path)
    if montage is None:
        raise RuntimeError("Lyra人物动作蒙太奇加载失败: {}".format(target_path))

    if additive_source_path:
        if not additive_slot_name:
            raise RuntimeError("Lyra人物动作附加轨道缺少插槽名: {}".format(target_path))

        _append_action_montage_track(
            montage,
            additive_source_path,
            additive_slot_name,
        )

    blend_in = montage.get_editor_property("blend_in")
    blend_in.set_editor_property("blend_option", blend_option)
    montage.set_editor_property("blend_in", blend_in)

    blend_out = montage.get_editor_property("blend_out")
    blend_out.set_editor_property("blend_option", blend_option)
    montage.set_editor_property("blend_out", blend_out)

    if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
        raise RuntimeError("保存Lyra人物动作蒙太奇失败: {}".format(target_path))

    result["additiveSlot"] = additive_slot_name
    result["additiveSource"] = additive_source_path

    return result


def _audit_ik_foot_tracks(animation, mesh):
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = True
    model = animation.data_model_interface
    number_of_keys = model.get_number_of_keys()
    additive_type = animation.get_editor_property("additive_anim_type")
    track_names = {
        str(track_name).casefold()
        for track_name in model.get_bone_track_names()
    }
    bone_names = {
        str(bone_name).casefold()
        for bone_name in animation.get_anim_pose_at_frame(0, options).get_bone_names()
    }
    pairs = (
        ("foot_l", "ik_foot_l"),
        ("foot_r", "ik_foot_r"),
    )
    result = {
        "additiveType": str(additive_type),
        "asset": _path(animation),
        "numberOfKeys": number_of_keys,
        "pairs": {},
        "repairSupported": additive_type == unreal.AdditiveAnimationType.AAT_NONE,
        "requiresRepair": False,
    }

    for source_bone, target_bone in pairs:
        pair_result = {
            "averageComponentError": None,
            "maximumComponentError": None,
            "sourceBone": source_bone,
            "sourceBoneExists": source_bone in bone_names,
            "targetBone": target_bone,
            "targetBoneExists": target_bone in bone_names,
            "targetTrackExists": target_bone in track_names,
        }
        result["pairs"][target_bone] = pair_result

        if source_bone not in bone_names or target_bone not in bone_names:
            result["requiresRepair"] = True
            continue

        errors = []
        for key_index in range(number_of_keys):
            pose = animation.get_anim_pose_at_frame(key_index, options)
            source_transform = pose.get_bone_pose(
                source_bone,
                unreal.AnimPoseSpaces.WORLD,
            )
            target_transform = pose.get_bone_pose(
                target_bone,
                unreal.AnimPoseSpaces.WORLD,
            )
            errors.append(
                _vector_distance(
                    source_transform.translation,
                    target_transform.translation,
                )
            )

        pair_result["averageComponentError"] = sum(errors) / len(errors)
        pair_result["maximumComponentError"] = max(errors)

        if target_bone not in track_names or max(errors) > 1.0:
            result["requiresRepair"] = True

    return result


def _sample_ik_foot_tracks(animation, mesh, sample_count):
    """按采样帧读取动画左右脚与 IK 脚的组件空间误差"""
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = True
    model = animation.data_model_interface
    number_of_keys = model.get_number_of_keys()
    frames = sorted(
        {
            round(index * (number_of_keys - 1) / max(1, sample_count - 1))
            for index in range(sample_count)
        }
    )
    track_names = {
        str(track_name).casefold()
        for track_name in model.get_bone_track_names()
    }
    bone_names = {
        str(bone_name).casefold()
        for bone_name in animation.get_anim_pose_at_frame(0, options).get_bone_names()
    }
    result = {
        "asset": _path(animation),
        "numberOfKeys": number_of_keys,
        "pairs": {},
        "repairSupported": animation.get_editor_property("additive_anim_type") == unreal.AdditiveAnimationType.AAT_NONE,
    }
    for source_bone, target_bone in (("foot_l", "ik_foot_l"), ("foot_r", "ik_foot_r")):
        pair_result = {
            "averageComponentError": None,
            "maximumComponentError": None,
            "sourceBoneExists": source_bone in bone_names,
            "targetBoneExists": target_bone in bone_names,
            "targetTrackExists": target_bone in track_names,
        }
        result["pairs"][target_bone] = pair_result
        if source_bone not in bone_names or target_bone not in bone_names:
            continue
        errors = []
        for frame in frames:
            pose = animation.get_anim_pose_at_frame(frame, options)
            source_transform = pose.get_bone_pose(source_bone, unreal.AnimPoseSpaces.WORLD)
            target_transform = pose.get_bone_pose(target_bone, unreal.AnimPoseSpaces.WORLD)
            errors.append(
                _vector_distance(
                    source_transform.translation,
                    target_transform.translation,
                )
            )
        pair_result["averageComponentError"] = sum(errors) / len(errors)
        pair_result["maximumComponentError"] = max(errors)
    return result


def _build_ik_foot_track_data(animation, mesh):
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = True
    model = animation.data_model_interface
    number_of_keys = model.get_number_of_keys()
    bone_names = {
        str(bone_name).casefold()
        for bone_name in animation.get_anim_pose_at_frame(0, options).get_bone_names()
    }
    pairs = (
        ("foot_l", "ik_foot_l"),
        ("foot_r", "ik_foot_r"),
    )
    result = {}

    for source_bone, target_bone in pairs:
        if source_bone not in bone_names:
            raise RuntimeError(
                "动画缺少源脚骨骼 {}: {}".format(
                    source_bone,
                    _path(animation),
                )
            )

        if target_bone not in bone_names:
            raise RuntimeError(
                "动画骨架缺少 IK 脚骨骼 {}: {}".format(
                    target_bone,
                    _path(animation),
                )
            )

        positions = []
        rotations = []
        scales = []
        parent_bone = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem).get_bone_parent(mesh, target_bone)
        if str(parent_bone).casefold() not in bone_names:
            raise RuntimeError("IK 脚的父骨骼不在采样姿势中: {} {}".format(_path(animation), parent_bone))

        for key_index in range(number_of_keys):
            pose = animation.get_anim_pose_at_frame(key_index, options)
            source_transform = pose.get_bone_pose(
                source_bone,
                unreal.AnimPoseSpaces.WORLD,
            )
            parent_transform = pose.get_bone_pose(
                parent_bone,
                unreal.AnimPoseSpaces.WORLD,
            )
            target_local_transform = unreal.MathLibrary.make_relative_transform(source_transform, parent_transform)

            positions.append(target_local_transform.translation)
            rotations.append(target_local_transform.rotation)
            scales.append(target_local_transform.scale3d)

        result[target_bone] = {
            "positions": positions,
            "rotations": rotations,
            "scales": scales,
        }

    return result


@unreal.uclass()
class BBBAnimationMigrationToolset(unreal.ToolsetDefinition):
    """为 BBB 动画迁移提供官方 MCP 探针和编辑入口"""

    @toolset_registry.tool_call
    @staticmethod
    def simplify_animation_data_accesses(
        blueprint_paths: list[str],
        node_class_path: str,
        removed_input_pins: list[str],
        removed_access_paths: list[str],
        direct_access_paths: list[str],
    ) -> str:
        """删除动画节点旧输入及无用纯节点，将指定属性路径恢复为直接数据访问"""
        results = []
        for blueprint_path in blueprint_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
            if not isinstance(blueprint, unreal.AnimBlueprint):
                raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

            changed_count = unreal.BBBBlueprintEditorLibrary.simplify_animation_data_accesses(
                blueprint,
                node_class_path,
                [unreal.Name(name) for name in removed_input_pins],
                removed_access_paths,
                direct_access_paths,
            )
            if changed_count < 0:
                raise RuntimeError("动画数据简化失败，未保存: {}".format(blueprint_path))

            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            status = blueprint.get_editor_property("status")
            if status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("动画数据简化编译未通过，未保存: {} {}".format(blueprint_path, status))

            if changed_count > 0 and not unreal.EditorAssetLibrary.save_asset(blueprint_path, only_if_is_dirty=False):
                raise RuntimeError("动画数据简化保存失败: {}".format(blueprint_path))

            results.append({"blueprint": blueprint_path, "changedNodeCount": changed_count, "status": str(status)})

        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def migrate_animation_data_accesses(
        blueprint_paths: list[str],
        getter_paths_json: str,
        duration_query: str,
        elapsed_path: list[str],
        removed_functions: list[str],
        nullable_object_getter: str,
        missing_value_defaults_json: str,
    ) -> str:
        """将动画查询迁移为属性访问，保留时长输入并为可空对象链添加默认值选择"""
        getter_paths = json.loads(getter_paths_json)
        missing_value_defaults = json.loads(missing_value_defaults_json)
        results = []
        for blueprint_path in blueprint_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
            if not isinstance(blueprint, unreal.AnimBlueprint):
                raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

            changed_count = unreal.BBBBlueprintEditorLibrary.migrate_animation_data_accesses(
                blueprint,
                getter_paths,
                unreal.Name(duration_query),
                elapsed_path,
                [unreal.Name(name) for name in removed_functions],
                unreal.Name(nullable_object_getter),
                missing_value_defaults,
            )
            if changed_count < 0:
                raise RuntimeError("动画属性访问迁移失败，未保存: {}".format(blueprint_path))

            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            compile_status = blueprint.get_editor_property("status")
            if compile_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("动画属性访问编译未通过，未保存: {} {}".format(blueprint_path, compile_status))

            if not unreal.EditorAssetLibrary.save_asset(blueprint_path, only_if_is_dirty=False):
                raise RuntimeError("动画属性访问保存失败: {}".format(blueprint_path))

            results.append({
                "blueprint": blueprint_path,
                "changedNodeCount": changed_count,
                "status": str(compile_status),
            })

        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def repair_raise_weapon_after_firing_transition(blueprint_path: str) -> str:
        """将失效的开火标签转换绑定替换为当前动画事实查询"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        changed_count = unreal.BBBBlueprintEditorLibrary.repair_raise_weapon_after_firing_transition(
            blueprint
        )
        if changed_count < 0:
            raise RuntimeError("开火后举枪转换修复失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        compile_status = blueprint.get_editor_property("status")
        if compile_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError(
                "开火后举枪转换编译未通过: {} {}".format(
                    blueprint_path,
                    compile_status,
                )
            )

        if not unreal.EditorAssetLibrary.save_asset(blueprint_path, only_if_is_dirty=False):
            raise RuntimeError("开火后举枪转换保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "changedNodeCount": changed_count,
                "status": str(compile_status),
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def apply_try_weapon_animation_fallbacks(
        blueprint_paths: list[str],
    ) -> str:
        """将 Base 与主动画蓝图的可空武器属性链改为 C++ Try 安全访问"""
        if not blueprint_paths:
            raise RuntimeError("至少需要一个动画蓝图")

        forbidden_names = ("_Rifle", "_Unarmed")
        results = []
        blueprints = []

        for blueprint_path in blueprint_paths:
            if any(name in blueprint_path for name in forbidden_names):
                raise RuntimeError(
                    "具体动画层不得重写 Base 武器逻辑: {}".format(blueprint_path)
                )

            blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
            if not isinstance(blueprint, unreal.AnimBlueprint):
                raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

            changed_count = unreal.BBBBlueprintEditorLibrary.apply_try_weapon_animation_fallbacks(
                blueprint
            )
            if changed_count < 0:
                raise RuntimeError("Try 武器动画回退失败: {}".format(blueprint_path))

            blueprints.append(blueprint)
            results.append(
                {
                    "blueprint": blueprint_path,
                    "changedCount": changed_count,
                }
            )

        for blueprint in blueprints:
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            compile_status = blueprint.get_editor_property("status")
            if compile_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError(
                    "Try 武器动画回退编译未通过: {} {}".format(
                        blueprint.get_path_name(),
                        compile_status,
                    )
                )

        for blueprint in blueprints:
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                raise RuntimeError("动画蓝图保存失败: {}".format(blueprint.get_path_name()))

        return json.dumps({"results": results}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def repair_main_anim_instance_accesses(blueprint_path: str) -> str:
        """将主动画实例包装访问统一替换为原生线程安全入口"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        changed_count = unreal.BBBBlueprintEditorLibrary.repair_main_anim_instance_accesses(
            blueprint
        )
        if changed_count < 0:
            raise RuntimeError("主动画实例访问修复失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        compile_status = blueprint.get_editor_property("status")
        if compile_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError(
                "主动画实例访问编译未通过: {} {}".format(
                    blueprint_path,
                    compile_status,
                )
            )

        if not unreal.EditorAssetLibrary.save_asset(blueprint_path, only_if_is_dirty=False):
            raise RuntimeError("主动画实例访问保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "changedNodeCount": changed_count,
                "status": str(compile_status),
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def configure_character_rifle_actions(
        character_blueprint_path: str,
        equip_montage_path: str,
        reload_montage_path: str,
        fire_montage_path: str,
    ) -> str:
        """将角色动画配置切换到人物侧步枪动作蒙太奇"""
        character_blueprint = unreal.EditorAssetLibrary.load_asset(
            character_blueprint_path
        )
        if character_blueprint is None:
            raise RuntimeError("角色蓝图不存在: {}".format(character_blueprint_path))

        generated_class = character_blueprint.generated_class()
        if generated_class is None:
            raise RuntimeError("角色蓝图生成类不存在: {}".format(character_blueprint_path))

        character_default = unreal.get_default_object(generated_class)
        character_config = character_default.get_editor_property("character_config")
        animation_config = character_config.get_editor_property("animation")
        weapon_config = animation_config.get_editor_property("weapon")

        montage_paths = {
            "equip_montage": equip_montage_path,
            "reload_montage": reload_montage_path,
            "fire_montage": fire_montage_path,
        }
        for property_name, montage_path in montage_paths.items():
            montage = unreal.EditorAssetLibrary.load_asset(montage_path)
            if montage is None:
                raise RuntimeError("人物动作蒙太奇不存在: {}".format(montage_path))

            weapon_config.set_editor_property(property_name, montage)

        animation_config.set_editor_property("weapon", weapon_config)
        character_config.set_editor_property("animation", animation_config)
        character_default.set_editor_property("character_config", character_config)

        if not unreal.EditorAssetLibrary.save_loaded_asset(character_blueprint, False):
            raise RuntimeError("保存角色蓝图失败: {}".format(character_blueprint_path))

        return json.dumps(
            {
                "character": character_blueprint_path,
                "equip": equip_montage_path,
                "reload": reload_montage_path,
                "fire": fire_montage_path,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def create_equipment_action_montages(
        source_paths: list[str],
        target_paths: list[str],
        slot_name: str,
    ) -> str:
        """从指定动画序列重建角色装备动作蒙太奇"""
        if len(source_paths) != len(target_paths):
            raise RuntimeError("动作源路径与目标路径数量不一致")

        if not source_paths:
            raise RuntimeError("动作源路径不能为空")

        created = []
        for source_path, target_path in zip(source_paths, target_paths):
            created.append(
                _create_action_montage(
                    source_path,
                    target_path,
                    slot_name,
                )
            )

        return json.dumps({"created": created}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def create_rifle_magazine_reload_animation(
        source_path: str,
        animation_path: str,
        montage_path: str,
        definition_path: str,
        magazine_mesh_path: str,
    ) -> str:
        """
        /**
         * 从武器骨架基准姿势新建与人物换弹同步的弹匣动作
         * @param source_path		武器原始动画路径
         * @param animation_path	新动画序列路径
         * @param montage_path		新武器蒙太奇路径
         * @param definition_path	步枪配置路径
         * @param magazine_mesh_path	独立弹匣网格路径
         * @return 新动画与配置的校验摘要
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建步枪换弹资产")

        source = unreal.EditorAssetLibrary.load_asset(source_path)
        definition = unreal.EditorAssetLibrary.load_asset(definition_path)
        magazine_mesh = unreal.EditorAssetLibrary.load_asset(magazine_mesh_path)
        if not isinstance(source, unreal.AnimSequence) or definition is None or not isinstance(magazine_mesh, unreal.StaticMesh):
            raise RuntimeError("步枪换弹源动画 配置或弹匣网格无效")

        require_editable(definition)
        if unreal.EditorAssetLibrary.does_asset_exist(animation_path) or unreal.EditorAssetLibrary.does_asset_exist(montage_path):
            raise RuntimeError("新动画或蒙太奇路径已存在")

        model = source.data_model_interface
        source_frames = model.get_number_of_frames()
        source_length = model.get_play_length()
        if source_frames < 1 or source_length <= 0.0:
            raise RuntimeError("原始动画帧率无效")

        frame_count = round(source_frames * 2.2 / source_length)
        target_length = frame_count * source_length / source_frames
        if abs(target_length - 2.2) > 0.001:
            raise RuntimeError("原始动画帧率无法精确表达 2.2 秒")

        options = unreal.AnimPoseEvaluationOptions()
        first_pose = source.get_anim_pose_at_frame(0, options)
        track_names = [str(name) for name in model.get_bone_track_names()]
        if "magazine_joint" not in track_names:
            raise RuntimeError("原始动画缺少 magazine_joint 轨道 实际轨道 " + str(track_names))

        unreal.EditorAssetLibrary.make_directory(animation_path.rsplit("/", 1)[0])
        package_path, asset_name = animation_path.rsplit("/", 1)
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", source.get_skeleton())
        animation = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name,
            package_path,
            unreal.AnimSequence,
            factory,
        )
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError("新建武器动画序列失败")

        controller = animation.controller
        controller.open_bracket("重建步枪弹匣换弹动作", False)
        try:
            controller.set_frame_rate(model.get_frame_rate(), False)
            controller.set_number_of_frames(unreal.FrameNumber(frame_count), False)
            for bone in track_names:
                if not controller.add_bone_track(bone, False):
                    raise RuntimeError("创建新武器骨骼轨道失败 " + bone)
                transform = first_pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
                positions = []
                rotations = []
                scales = []
                for frame in range(frame_count):
                    time_seconds = frame * 2.2 / frame_count
                    travel = 0.0
                    if bone == "magazine_joint" and 0.30 < time_seconds <= 0.40:
                        alpha = (time_seconds - 0.30) / 0.10
                        travel = 8.0 * alpha * alpha * (3.0 - 2.0 * alpha)
                    if bone == "magazine_joint" and 0.40 < time_seconds < 0.55:
                        alpha = (time_seconds - 0.40) / 0.15
                        travel = 8.0 * (1.0 - alpha * alpha * (3.0 - 2.0 * alpha))
                    positions.append(unreal.Vector(
                        transform.translation.x,
                        transform.translation.y + travel,
                        transform.translation.z,
                    ))
                    rotations.append(unreal.Quat(
                        transform.rotation.x,
                        transform.rotation.y,
                        transform.rotation.z,
                        transform.rotation.w,
                    ))
                    scales.append(unreal.Vector(
                        transform.scale3d.x,
                        transform.scale3d.y,
                        transform.scale3d.z,
                    ))
                if not controller.set_bone_track_keys(bone, positions, rotations, scales, False):
                    raise RuntimeError("写入新武器轨道失败 " + bone)
        finally:
            controller.close_bracket(False)

        if abs(animation.get_play_length() - 2.2) > 0.04:
            raise RuntimeError("新武器动画长度不符合人物换弹蒙太奇")
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError("保存新武器动画序列失败")

        montage = _create_action_montage(animation_path, montage_path, "DefaultSlot")
        definition.set_editor_property("equipment_reload_montage", unreal.EditorAssetLibrary.load_asset(montage_path))
        definition.set_editor_property("magazine_mesh", magazine_mesh)
        if not unreal.EditorAssetLibrary.save_loaded_asset(definition, False):
            raise RuntimeError("保存步枪配置失败")

        return json.dumps({
            "animation": animation_path,
            "montage": montage,
            "definition": definition_path,
            "length": animation.get_play_length(),
            "tracks": track_names,
            "magazineMesh": magazine_mesh_path,
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_bone_track_keys(asset_path: str, bone_name: str, sample_count: int = 12) -> str:
        """
        /**
         * 从动画数据模型读取指定骨骼的原始关键帧
         * @param asset_path	动画序列路径
         * @param bone_name	骨骼轨道名称
         * @param sample_count	输出采样数量
         * @return 轨道帧数与采样位移
         */
        """
        animation = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(animation, unreal.AnimSequence) or sample_count < 2:
            raise RuntimeError("动画序列或采样数量无效")

        names = [str(name) for name in animation.data_model_interface.get_bone_track_names()]
        matching = next((name for name in names if name.casefold() == bone_name.casefold()), None)
        if matching is None:
            raise RuntimeError("动画缺少目标骨骼轨道")

        transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, unreal.Name(matching))
        if not transforms:
            raise RuntimeError("动画骨骼原始轨道读取失败")

        indices = sorted({round(index * (len(transforms) - 1) / (sample_count - 1)) for index in range(sample_count)})
        return json.dumps({
            "asset": asset_path,
            "bone": matching,
            "keys": len(transforms),
            "length": animation.get_play_length(),
            "samples": [{
                "frame": index,
                "time": index * animation.get_play_length() / max(1, len(transforms) - 1),
                "location": [transforms[index].translation.x, transforms[index].translation.y, transforms[index].translation.z],
            } for index in indices],
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def create_lyra_rifle_character_montages(
        source_root: str,
        target_root: str,
    ) -> str:
        """使用重定向人物序列重建Lyra步枪人物侧蒙太奇"""
        specs = (
            {
                "base": "MM_Rifle_Equip",
                "baseSlot": "UpperBody",
                "additive": "MM_Rifle_Equip_Additive",
                "additiveSlot": "UpperBodyAdditive",
                "blendOption": unreal.AlphaBlendOption.HERMITE_CUBIC,
                "target": "AM_MM_Rifle_Equip",
            },
            {
                "base": "MM_Rifle_Reload",
                "baseSlot": "UpperBody",
                "additive": "MM_Rifle_Reload_Additive",
                "additiveSlot": "UpperBodyAdditive",
                "blendOption": unreal.AlphaBlendOption.HERMITE_CUBIC,
                "target": "AM_MM_Rifle_Reload",
            },
            {
                "base": "MM_Rifle_Fire",
                "baseSlot": "FullBodyAdditivePreAim",
                "additive": None,
                "additiveSlot": None,
                "blendOption": unreal.AlphaBlendOption.CUBIC,
                "target": "AM_MM_Rifle_Fire",
            },
        )

        created = []
        for spec in specs:
            created.append(
                _create_lyra_character_action_montage(
                    "{}/{}".format(source_root.rstrip("/"), spec["base"]),
                    "{}/{}".format(target_root.rstrip("/"), spec["target"]),
                    spec["baseSlot"],
                    "{}/{}".format(source_root.rstrip("/"), spec["additive"])
                    if spec["additive"]
                    else None,
                    spec["additiveSlot"],
                    spec["blendOption"],
                )
            )

        return json.dumps({"created": created}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_python_api(type_names: list[str]) -> str:
        """探测指定 Unreal Python 类型当前实际暴露的接口"""
        result = {}
        for type_name in type_names:
            value = getattr(unreal, type_name, None)
            if value is None:
                result[type_name] = []
                continue

            result[type_name] = sorted(
                name
                for name in dir(value)
                if not name.startswith("__")
            )

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def configure_control_rig_anim_graph_node(
        blueprint_path: str,
        node_path: str,
        rig_asset_path: str,
        exposed_input_names: list[str],
    ) -> str:
        """为指定动画图控制绑定节点设置 Rig 并暴露输入引脚 不编译或保存"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        node = unreal.load_object(None, node_path)
        rig_blueprint = unreal.EditorAssetLibrary.load_asset(rig_asset_path)

        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        if not isinstance(node, unreal.AnimGraphNode_ControlRig):
            raise RuntimeError("控制绑定动画图节点不存在: {}".format(node_path))

        if not isinstance(rig_blueprint, unreal.ControlRigBlueprint):
            raise RuntimeError("控制绑定资产不存在: {}".format(rig_asset_path))

        configured = unreal.BBBBlueprintEditorLibrary.configure_control_rig_anim_graph_node(
            blueprint,
            node,
            rig_blueprint,
            [unreal.Name(name) for name in exposed_input_names],
        )

        if not configured:
            raise RuntimeError("控制绑定动画图节点配置失败: {}".format(node_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "node": node_path,
                "rig": rig_asset_path,
                "exposedInputs": [str(name) for name in exposed_input_names],
                "compiled": False,
                "saved": False,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def add_animation_layer_boolean_input(
        blueprint_path: str,
        graph_name: str,
        pose_name: str,
        input_name: str,
    ) -> str:
        """为动画层接口的输入姿势增加布尔参数 编译并保存接口"""
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改动画层接口")

        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        with unreal.ScopedEditorTransaction("添加动画层布尔输入"):
            blueprint.modify()
            changed = unreal.BBBBlueprintEditorLibrary.add_animation_layer_boolean_input(
                blueprint,
                unreal.Name(graph_name),
                unreal.Name(pose_name),
                unreal.Name(input_name),
            )

        if changed < 0:
            raise RuntimeError("动画层布尔输入创建失败: {}".format(blueprint_path))

        if changed == 0:
            return json.dumps(
                {
                    "blueprint": blueprint_path,
                    "graph": graph_name,
                    "pose": pose_name,
                    "input": input_name,
                    "changed": False,
                    "compiled": False,
                    "saved": False,
                },
                ensure_ascii=False,
            )

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            unreal.log_error("动画层接口编译失败 不保存 {}".format(blueprint_path))
            raise RuntimeError("动画层接口编译失败: {}".format(blueprint_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画层接口保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "graph": graph_name,
                "pose": pose_name,
                "input": input_name,
                "changed": True,
                "compiled": True,
                "saved": True,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def configure_recoil_animation_graphs(
        interface_blueprint_path: str,
        base_blueprint_path: str,
        main_blueprint_path: str,
        magnitude_property_name: str,
    ) -> str:
        """配置后坐力动画层 递增触发重播并编译保存三个动画蓝图"""
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改后坐力动画图")

        layer_name = "FullBodyRecoil"
        pose_name = "RecoilParameters"
        state_machine_name = "Recoil_SM"
        animation_variable_name = "RecoilAdditiveAnimation"
        previous_magnitude_variable_name = "WasRecoilMagnitudeLastUpdate"
        trigger_variable_name = "bRecoilMagnitudeIncreasedThisUpdate"
        asset_paths = [interface_blueprint_path, base_blueprint_path, main_blueprint_path]
        blueprints = []

        for asset_path in asset_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
            if not isinstance(blueprint, unreal.AnimBlueprint):
                raise RuntimeError("动画蓝图不存在: {}".format(asset_path))

            blueprints.append(blueprint)

        interface_blueprint, base_blueprint, main_blueprint = blueprints
        with unreal.ScopedEditorTransaction("配置角色后坐力动画层"):
            interface_blueprint.modify()
            interface_changed = unreal.BBBBlueprintEditorLibrary.ensure_animation_layer_interface_function(
                interface_blueprint,
                unreal.Name(layer_name),
                unreal.Name(pose_name),
                unreal.Name(),
            )
            if interface_changed < 0:
                raise RuntimeError("后坐力动画层接口创建失败: {}".format(interface_blueprint_path))

            unreal.BlueprintEditorLibrary.compile_blueprint(interface_blueprint)
            interface_status = interface_blueprint.get_editor_property("status")
            if interface_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("后坐力动画层接口编译未通过: {} {}".format(interface_blueprint_path, interface_status))

            unreal.BlueprintEditorLibrary.compile_blueprint(base_blueprint)
            base_status_before = base_blueprint.get_editor_property("status")
            if base_status_before != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("基础动画层接口刷新编译未通过: {} {}".format(base_blueprint_path, base_status_before))

            base_blueprint.modify()
            base_changed = unreal.BBBBlueprintEditorLibrary.configure_recoil_additive_layer(
                base_blueprint,
                interface_blueprint,
                unreal.Name(layer_name),
                unreal.Name(state_machine_name),
                unreal.Name(animation_variable_name),
                unreal.Name(trigger_variable_name),
            )
            if base_changed < 0:
                raise RuntimeError("基础动画层后坐力状态机配置失败: {}".format(base_blueprint_path))

            unreal.BlueprintEditorLibrary.compile_blueprint(base_blueprint)
            base_status = base_blueprint.get_editor_property("status")
            if base_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("基础动画层后坐力状态机编译未通过: {} {}".format(base_blueprint_path, base_status))

            unreal.BlueprintEditorLibrary.compile_blueprint(main_blueprint)
            main_status_before = main_blueprint.get_editor_property("status")
            if main_status_before != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("主动画层接口刷新编译未通过: {} {}".format(main_blueprint_path, main_status_before))

            main_blueprint.modify()
            main_changed = unreal.BBBBlueprintEditorLibrary.configure_recoil_main_animation_graph(
                main_blueprint,
                interface_blueprint,
                unreal.Name(layer_name),
                unreal.Name(previous_magnitude_variable_name),
                unreal.Name(trigger_variable_name),
                unreal.Name(magnitude_property_name),
            )
            if main_changed < 0:
                raise RuntimeError("主动画图后坐力触发与叠加配置失败: {}".format(main_blueprint_path))

            unreal.BlueprintEditorLibrary.compile_blueprint(main_blueprint)
            main_status = main_blueprint.get_editor_property("status")
            if main_status != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("主动画图后坐力触发编译未通过: {} {}".format(main_blueprint_path, main_status))

        changed_blueprints = []
        if interface_changed > 0:
            changed_blueprints.append(interface_blueprint)

        if base_changed > 0:
            changed_blueprints.append(base_blueprint)

        if main_changed > 0:
            changed_blueprints.append(main_blueprint)

        for blueprint in changed_blueprints:
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                raise RuntimeError("后坐力动画蓝图保存失败: {}".format(blueprint.get_path_name()))

        return json.dumps(
            {
                "interface": interface_blueprint_path,
                "base": base_blueprint_path,
                "main": main_blueprint_path,
                "layer": layer_name,
                "stateMachine": state_machine_name,
                "animationVariable": animation_variable_name,
                "triggerVariable": trigger_variable_name,
                "magnitudeProperty": magnitude_property_name,
                "changed": {
                    "interface": interface_changed,
                    "base": base_changed,
                    "main": main_changed,
                },
                "compiled": {
                    "interface": str(interface_status),
                    "base": str(base_status),
                    "main": str(main_status),
                },
                "saved": [blueprint.get_path_name() for blueprint in changed_blueprints],
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def create_control_rig_anim_graph_node(
        blueprint_path: str,
        graph_path: str,
        rig_asset_path: str,
        exposed_input_names: list[str],
        position_x: int,
        position_y: int,
    ) -> str:
        """在动画图中创建并配置控制绑定节点 不连接 不编译 不保存"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        graph = unreal.load_object(None, graph_path)
        rig_blueprint = unreal.EditorAssetLibrary.load_asset(rig_asset_path)

        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        if graph is None:
            raise RuntimeError("动画图不存在: {}".format(graph_path))

        if not isinstance(rig_blueprint, unreal.ControlRigBlueprint):
            raise RuntimeError("控制绑定资产不存在: {}".format(rig_asset_path))

        node_path = unreal.BBBBlueprintEditorLibrary.create_control_rig_anim_graph_node(
            blueprint,
            graph,
            rig_blueprint,
            [unreal.Name(name) for name in exposed_input_names],
            position_x,
            position_y,
        )

        if not node_path:
            raise RuntimeError("控制绑定动画图节点创建或配置失败: {}".format(graph_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "graph": graph_path,
                "node": node_path,
                "rig": rig_asset_path,
                "exposedInputs": [str(name) for name in exposed_input_names],
                "connected": False,
                "compiled": False,
                "saved": False,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def audit_ik_foot_tracks(root_path: str, mesh_path: str) -> str:
        """审计动画中供 Stride Warping 使用的左右 IK 脚轨道"""
        assets = []
        repair_assets = []
        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("IK 审计网格不存在: {}".format(mesh_path))

        for asset_path in _list_animation_sequences(root_path):
            animation = unreal.EditorAssetLibrary.load_asset(asset_path)
            if animation.get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
                raise RuntimeError("IK 审计动画与网格骨架不一致: {}".format(asset_path))

            asset_result = _audit_ik_foot_tracks(animation, mesh)
            assets.append(asset_result)

            if asset_result["requiresRepair"]:
                repair_assets.append(asset_path)

        result = {
            "animationCount": len(assets),
            "assets": assets,
            "repairAssetCount": len(repair_assets),
            "repairAssets": repair_assets,
            "rootPath": root_path,
        }
        result["reportPath"] = _write_diagnostic_report(
            "BBBAnimationIKTrackAudit.json",
            result,
        )

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def audit_ik_foot_tracks_against_reference(
        current_root_path: str,
        reference_root_path: str,
        current_mesh_path: str,
        reference_mesh_path: str,
        sample_count: int = 9,
    ) -> str:
        """按同相对路径和各自网格对照当前动画与原版 IK 脚轨道"""
        if sample_count < 2:
            raise RuntimeError("IK 对照采样数量至少为 2")

        current_mesh = unreal.load_asset(current_mesh_path)
        reference_mesh = unreal.load_asset(reference_mesh_path)
        if not isinstance(current_mesh, unreal.SkeletalMesh):
            raise RuntimeError("当前 IK 对照网格不存在: {}".format(current_mesh_path))

        if not isinstance(reference_mesh, unreal.SkeletalMesh):
            raise RuntimeError("原版 IK 对照网格不存在: {}".format(reference_mesh_path))

        current_assets = _list_animation_sequences(current_root_path)
        results = []
        candidates = []
        missing_reference = []
        for current_path in current_assets:
            relative_path = current_path[len(current_root_path.rstrip("/")):]
            reference_path = reference_root_path.rstrip("/") + relative_path
            current_animation = unreal.EditorAssetLibrary.load_asset(current_path)
            reference_animation = unreal.EditorAssetLibrary.load_asset(reference_path)
            entry = {
                "current": current_path,
                "reference": reference_path,
                "referenceExists": isinstance(reference_animation, unreal.AnimSequence),
            }
            if not isinstance(reference_animation, unreal.AnimSequence):
                missing_reference.append(current_path)
                results.append(entry)
                continue

            if current_animation.get_editor_property("skeleton") != current_mesh.get_editor_property("skeleton"):
                raise RuntimeError("当前 IK 对照动画与网格骨架不一致: {}".format(current_path))

            if reference_animation.get_editor_property("skeleton") != reference_mesh.get_editor_property("skeleton"):
                raise RuntimeError("原版 IK 对照动画与网格骨架不一致: {}".format(reference_path))

            current_result = _sample_ik_foot_tracks(current_animation, current_mesh, sample_count)
            reference_result = _sample_ik_foot_tracks(reference_animation, reference_mesh, sample_count)
            entry["current"] = current_result
            entry["referenceData"] = reference_result
            current_bad = any(
                pair["maximumComponentError"] is None or pair["maximumComponentError"] > 1.0
                for pair in current_result["pairs"].values()
            )
            reference_healthy = all(
                pair["maximumComponentError"] is not None
                and pair["maximumComponentError"] <= 1.0
                and pair["targetTrackExists"]
                for pair in reference_result["pairs"].values()
            )
            entry["referenceHealthy"] = reference_healthy
            entry["repairCandidate"] = current_bad and reference_healthy and current_result["repairSupported"]
            if entry["repairCandidate"]:
                candidates.append(current_path)
            results.append(entry)

        result = {
            "currentRootPath": current_root_path,
            "referenceRootPath": reference_root_path,
            "currentMeshPath": current_mesh_path,
            "referenceMeshPath": reference_mesh_path,
            "sampleCount": sample_count,
            "currentAnimationCount": len(current_assets),
            "referenceMissingCount": len(missing_reference),
            "repairCandidateCount": len(candidates),
            "repairCandidates": candidates,
            "missingReference": missing_reference,
            "assets": results,
        }
        result["reportPath"] = _write_diagnostic_report(
            "BBBAllRoleAnimationIKAudit.json",
            result,
        )
        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def rebuild_ik_foot_tracks(animation_paths: list[str], mesh_path: str) -> str:
        """原位重建指定动画供 Stride Warping 使用的左右 IK 脚轨道"""
        prepared_assets = []
        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("IK 重建网格不存在: {}".format(mesh_path))

        for animation_path in animation_paths:
            animation = unreal.EditorAssetLibrary.load_asset(animation_path)
            if animation is None:
                raise RuntimeError("待修复动画不存在: {}".format(animation_path))

            additive_type = animation.get_editor_property(
                "additive_anim_type"
            )
            if animation.get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
                raise RuntimeError("IK 重建动画与网格骨架不一致: {}".format(animation_path))
            if additive_type != unreal.AdditiveAnimationType.AAT_NONE:
                raise RuntimeError(
                    "禁止直接重建加法动画的 IK 脚轨道: {} ({})".format(
                        animation_path,
                        str(additive_type),
                    )
                )

            prepared_assets.append(
                {
                    "animation": animation,
                    "path": animation_path,
                    "tracks": _build_ik_foot_track_data(animation, mesh),
                }
            )

        repaired_assets = []
        for prepared_asset in prepared_assets:
            animation = prepared_asset["animation"]
            model = animation.data_model_interface
            controller = animation.controller
            track_names = {
                str(track_name).casefold()
                for track_name in model.get_bone_track_names()
            }

            controller.open_bracket("重建 IK 脚动画轨道", False)
            try:
                for target_bone, track_data in prepared_asset["tracks"].items():
                    if target_bone not in track_names:
                        if not controller.add_bone_track(target_bone, False):
                            raise RuntimeError(
                                "新增 IK 脚轨道失败: {} {}".format(
                                    prepared_asset["path"],
                                    target_bone,
                                )
                            )

                    if not controller.set_bone_track_keys(
                        target_bone,
                        track_data["positions"],
                        track_data["rotations"],
                        track_data["scales"],
                        False,
                    ):
                        raise RuntimeError(
                            "写入 IK 脚轨道失败: {} {}".format(
                                prepared_asset["path"],
                                target_bone,
                            )
                        )
            finally:
                controller.close_bracket(False)

            verification_result = _audit_ik_foot_tracks(animation, mesh)
            if verification_result["requiresRepair"]:
                raise RuntimeError("IK 脚轨道写入后验证失败，未保存: {}".format(prepared_asset["path"]))

            if not unreal.EditorAssetLibrary.save_asset(
                prepared_asset["path"],
                False,
            ):
                raise RuntimeError(
                    "保存 IK 脚轨道失败: {}".format(
                        prepared_asset["path"],
                    )
                )

            repaired_assets.append(prepared_asset["path"])

        verification = []
        for repaired_asset in prepared_assets:
            verification.append(
                _audit_ik_foot_tracks(repaired_asset["animation"], mesh)
            )

        failed_verification = [
            item["asset"]
            for item in verification
            if item["requiresRepair"]
        ]
        result = {
            "failedVerification": failed_verification,
            "repairedAssetCount": len(repaired_assets),
            "repairedAssets": repaired_assets,
            "verification": verification,
        }
        result["reportPath"] = _write_diagnostic_report(
            "BBBAnimationIKTrackRepair.json",
            result,
        )

        if failed_verification:
            raise RuntimeError(
                "IK 脚轨道写入后验证失败: {}".format(
                    ", ".join(failed_verification),
                )
            )

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def start_locomotion_runtime_probe() -> str:
        """启动只读 PIE 移动动画、同步播放器和最终脚部姿势探针"""
        script_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "ProbeScripts",
            "probe_locomotion_sync_runtime.py",
        )
        if not os.path.isfile(script_path):
            raise RuntimeError("移动动画运行时探针不存在: {}".format(script_path))

        runpy.run_path(
            script_path,
            run_name="__bbb_locomotion_runtime_probe__",
        )

        return json.dumps(
            {
                "runtimeReport": os.path.join(
                    unreal.Paths.project_saved_dir(),
                    "Diagnostics",
                    "BBBLocomotionRuntime.jsonl",
                ),
                "feetReport": os.path.join(
                    unreal.Paths.project_saved_dir(),
                    "Diagnostics",
                    "BBBLocomotionFeet.csv",
                ),
                "started": True,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def run_editor_script(script_path: str) -> str:
        """在编辑器内执行项目 Scripts 目录下的 Python 脚本并返回其标准输出"""
        scripts_root = os.path.realpath(
            os.path.join(unreal.Paths.project_dir(), "Scripts")
        )
        repository_scripts_root = os.path.dirname(os.path.realpath(__file__))
        target = os.path.realpath(script_path)
        allowed_roots = (scripts_root, repository_scripts_root)
        if not any(os.path.commonpath((target, root)) == root for root in allowed_roots if os.path.splitdrive(target)[0].lower() == os.path.splitdrive(root)[0].lower()):
            raise RuntimeError(
                "仅允许执行当前项目或 MCP 仓库 Scripts 目录内的脚本: {}".format(script_path)
            )
        if not os.path.isfile(target):
            raise RuntimeError("脚本不存在: {}".format(target))

        buffer = io.StringIO()
        error = None
        with contextlib.redirect_stdout(buffer):
            try:
                runpy.run_path(target, run_name="__bbb_editor_script__")
            except Exception as err:  # 保证异常时也能拿回已打印的输出
                error = "{}: {}".format(type(err).__name__, err)

        return json.dumps(
            {"script": target, "output": buffer.getvalue(), "error": error},
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def stop_locomotion_runtime_probe() -> str:
        """停止 PIE 移动动画探针并关闭报告文件"""
        probe = getattr(builtins, "BBB_LOCOMOTION_SYNC_PROBE", None)
        if probe is None:
            return json.dumps({"stopped": False}, ensure_ascii=False)

        probe.stop()
        builtins.BBB_LOCOMOTION_SYNC_PROBE = None

        return json.dumps({"stopped": True}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_blueprint(asset_path: str) -> str:
        """读取动画蓝图的图表、节点、骨架和父类"""
        blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(asset_path))

        graphs = []
        for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
            nodes = []
            try:
                graph_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
                nodes = [
                    _read_node(node)
                    for node in list(graph_editor.list_all_nodes())
                ]
            except Exception:
                nodes = []

            graphs.append(
                {
                    "class": graph.get_class().get_name(),
                    "name": graph.get_name(),
                    "nodes": nodes,
                    "path": graph.get_path_name(),
                }
            )

        result = {
            "asset": asset_path,
            "generatedClass": _path(blueprint.generated_class()),
            "graphs": graphs,
            "parentClass": _path(blueprint.get_blueprint_parent_class()),
            "targetSkeleton": _path(blueprint.get_editor_property("target_skeleton")),
        }

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_property_access_paths(asset_paths: list[str]) -> str:
        """读取动画蓝图中属性存取节点隐藏的完整属性路径"""
        result = {}

        for asset_path in asset_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
            if blueprint is None:
                result[asset_path] = {"error": "动画蓝图不存在"}
                continue

            accesses = []
            for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
                try:
                    graph_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
                    nodes = list(graph_editor.list_all_nodes())
                except Exception:
                    continue

                for node in nodes:
                    if node.get_class().get_name() != "K2Node_PropertyAccess":
                        continue

                    property_path = [
                        str(path_part)
                        for path_part in unreal.BBBBlueprintEditorLibrary.get_property_access_path(
                            node
                        )
                    ]

                    accesses.append(
                        {
                            "graph": graph.get_path_name(),
                            "node": node.get_path_name(),
                            "path": property_path,
                            "title": node.get_node_title(),
                        }
                    )

            result[asset_path] = {
                "accessCount": len(accesses),
                "accesses": accesses,
            }

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def rewrite_animation_property_access_paths(
        blueprint_paths: list[str],
        path_replacements_json: str,
    ) -> str:
        """按完整路径精确重写动画蓝图属性存取节点"""
        path_replacements = json.loads(path_replacements_json)
        replacements = {
            tuple(item["oldPath"]): list(item["newPath"])
            for item in path_replacements
        }
        updated = []

        for blueprint_path in blueprint_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
            if blueprint is None:
                raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

            blueprint_updates = []
            for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
                try:
                    graph_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
                    nodes = list(graph_editor.list_all_nodes())
                except Exception:
                    continue

                for node in nodes:
                    if node.get_class().get_name() != "K2Node_PropertyAccess":
                        continue

                    old_path = tuple(
                        str(path_part)
                        for path_part in unreal.BBBBlueprintEditorLibrary.get_property_access_path(
                            node
                        )
                    )
                    new_path = replacements.get(old_path)
                    if new_path is None:
                        continue

                    if not unreal.BBBBlueprintEditorLibrary.set_property_access_path(
                        node,
                        new_path,
                    ):
                        raise RuntimeError(
                            "属性路径重写失败: {} {}".format(
                                node.get_path_name(),
                                new_path,
                            )
                        )

                    blueprint_updates.append(
                        {
                            "graph": graph.get_name(),
                            "node": node.get_name(),
                            "oldPath": list(old_path),
                            "newPath": new_path,
                        }
                    )

            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                raise RuntimeError("动画蓝图保存失败: {}".format(blueprint_path))

            updated.append(
                {
                    "blueprint": blueprint_path,
                    "updates": blueprint_updates,
                }
            )

        return json.dumps({"updated": updated}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def rename_animation_blueprint_variables(
        blueprint_path: str,
        variable_names: dict[str, str],
    ) -> str:
        """重命名动画蓝图变量并同步修正全部节点引用"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        renamed = []
        for old_name, new_name in variable_names.items():
            if not unreal.BBBBlueprintEditorLibrary.rename_blueprint_variable(
                blueprint,
                old_name,
                new_name,
            ):
                raise RuntimeError(
                    "变量重命名失败: {} -> {}".format(old_name, new_name)
                )

            renamed.append(
                {
                    "oldName": old_name,
                    "newName": new_name,
                }
            )

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败: {}".format(blueprint_path))

        return json.dumps({"renamed": renamed}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_assets(asset_paths: list[str]) -> str:
        """读取动画序列的骨架、长度、根运动、曲线、通知和同步标记"""
        result = {}
        for asset_path in asset_paths:
            animation = unreal.EditorAssetLibrary.load_asset(asset_path)
            if animation is None:
                result[asset_path] = {"error": "资产不存在"}
                continue

            if animation.get_class().get_name() != "AnimSequence":
                result[asset_path] = {"error": "资产不是 AnimSequence"}
                continue

            curves = []
            try:
                curves = [
                    str(name)
                    for name in unreal.AnimationLibrary.get_animation_curve_names(
                        animation,
                        unreal.RawCurveTrackTypes.RCT_FLOAT,
                    )
                ]
            except Exception:
                curves = []

            notifies = []
            try:
                for event in unreal.AnimationLibrary.get_animation_notify_events(animation):
                    notifies.append(
                        {
                            "name": str(event.get_editor_property("notify_name")),
                            "duration": unreal.AnimationLibrary.get_anim_notify_event_duration(
                                event,
                            ),
                            "notify": _path(event.get_editor_property("notify")),
                            "notifyState": _path(
                                event.get_editor_property("notify_state_class"),
                            ),
                            "time": unreal.AnimationLibrary.get_anim_notify_event_trigger_time(
                                event,
                            ),
                        }
                    )
            except Exception:
                notifies = []

            markers = []
            try:
                for marker in unreal.AnimationLibrary.get_animation_sync_markers(animation):
                    markers.append(
                        {
                            "name": str(marker.get_editor_property("marker_name")),
                            "time": marker.get_editor_property("time"),
                        }
                    )
            except Exception:
                markers = []

            result[asset_path] = {
                "additiveType": _read_property(animation, "additive_anim_type"),
                "curves": curves,
                "enableRootMotion": _read_property(animation, "enable_root_motion"),
                "length": animation.get_play_length(),
                "markers": markers,
                "notifies": notifies,
                "rateScale": _read_property(animation, "rate_scale"),
                "skeleton": _path(animation.get_editor_property("skeleton")),
            }

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_component_poses(
        asset_paths: list[str],
        mesh_path: str,
        bone_names: list[str],
        sample_count: int = 9,
        incorporate_root_motion: bool = False,
        should_retarget: bool = True,
    ) -> str:
        """使用明确网格采样组件空间姿势，审计根运动和左右脚 IK 的位置与旋转误差"""
        if sample_count < 2:
            raise RuntimeError("姿势采样数量至少为 2")

        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("姿势采样网格不存在: {}".format(mesh_path))

        options = unreal.AnimPoseEvaluationOptions()
        options.optional_skeletal_mesh = mesh
        options.evaluation_type = unreal.AnimDataEvalType.RAW
        options.should_retarget = should_retarget
        options.incorporate_root_motion_into_pose = incorporate_root_motion
        results = []
        for asset_path in asset_paths:
            animation = unreal.load_asset(asset_path)
            if not isinstance(animation, unreal.AnimSequence):
                raise RuntimeError("姿势采样动画不存在: {}".format(asset_path))

            if animation.get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
                raise RuntimeError("姿势采样骨架不一致: {}".format(asset_path))

            key_count = animation.data_model_interface.get_number_of_keys()
            samples = []
            frames = sorted({round(index * (key_count - 1) / (sample_count - 1)) for index in range(sample_count)})
            for frame in frames:
                pose = animation.get_anim_pose_at_frame(frame, options)
                available = {str(name).casefold() for name in pose.get_bone_names()}
                missing = {name for name in bone_names if name.casefold() not in available}
                if missing:
                    raise RuntimeError("采样姿势缺少骨骼: {} {}".format(asset_path, sorted(missing)))

                bones = {}
                for bone_name in bone_names:
                    transform = pose.get_bone_pose(bone_name, unreal.AnimPoseSpaces.WORLD)
                    rotation = transform.rotation
                    bones[bone_name] = _transform_to_dict(transform)
                    bones[bone_name]["quaternion"] = [rotation.x, rotation.y, rotation.z, rotation.w]

                pairs = {}
                for side in ("l", "r"):
                    fk_name = "foot_" + side
                    ik_name = "ik_foot_" + side
                    if fk_name not in available or ik_name not in available:
                        continue

                    fk = pose.get_bone_pose(fk_name, unreal.AnimPoseSpaces.WORLD)
                    ik = pose.get_bone_pose(ik_name, unreal.AnimPoseSpaces.WORLD)
                    dot = abs(fk.rotation.x * ik.rotation.x + fk.rotation.y * ik.rotation.y + fk.rotation.z * ik.rotation.z + fk.rotation.w * ik.rotation.w)
                    pairs[side] = {
                        "positionError": _vector_distance(fk.translation, ik.translation),
                        "rotationErrorDegrees": math.degrees(2.0 * math.acos(min(1.0, dot))),
                    }

                samples.append({"frame": frame, "bones": bones, "footPairs": pairs})

            results.append({"asset": asset_path, "keys": key_count, "samples": samples})

        report = {"mesh": mesh_path, "incorporateRootMotion": incorporate_root_motion, "assets": results}
        report["reportPath"] = _write_diagnostic_report("BBBAnimationComponentPoses.json", report)
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_bone_trajectories(
        asset_paths: list[str],
        bone_names: list[str],
        sample_count: int = 9,
    ) -> str:
        """按归一化时间读取动画根轨迹与指定骨骼轨迹"""
        if sample_count < 2:
            raise RuntimeError("采样数量至少为 2")

        result = {}
        for asset_path in asset_paths:
            animation = unreal.EditorAssetLibrary.load_asset(asset_path)
            if animation is None:
                result[asset_path] = {"error": "资产不存在"}
                continue

            if animation.get_class().get_name() != "AnimSequence":
                result[asset_path] = {"error": "资产不是 AnimSequence"}
                continue

            length = animation.get_play_length()
            samples = []
            for sample_index in range(sample_count):
                normalized_time = sample_index / float(sample_count - 1)
                sample_time = length * normalized_time
                root_track = unreal.AnimationLibrary.extract_root_track_transform(
                    animation,
                    sample_time,
                )
                bones = {}
                for bone_name in bone_names:
                    bone_pose = unreal.AnimationLibrary.get_bone_pose_for_time(
                        animation,
                        bone_name,
                        sample_time,
                        False,
                    )
                    bones[bone_name] = _transform_to_dict(bone_pose)

                samples.append(
                    {
                        "bones": bones,
                        "normalizedTime": normalized_time,
                        "rootTrack": _transform_to_dict(root_track),
                        "time": sample_time,
                    }
                )

            result[asset_path] = {
                "length": length,
                "samples": samples,
                "skeleton": _path(animation.get_editor_property("skeleton")),
            }

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def audit_animation_dependencies(
        root_path: str,
        dependency_prefixes: list[str],
    ) -> str:
        """汇总动画目录对指定路径前缀的直接资产依赖"""
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = unreal.EditorAssetLibrary.list_assets(root_path, True, False)
        matches = {}
        dependencies = set()

        for asset_path in assets:
            package_name = asset_path.split(".", 1)[0]
            package_dependencies = registry.get_dependencies(
                package_name,
                unreal.AssetRegistryDependencyOptions(True, True, True, True),
            )
            filtered = sorted(
                str(dependency)
                for dependency in package_dependencies
                if any(
                    str(dependency).startswith(prefix)
                    for prefix in dependency_prefixes
                )
            )
            if not filtered:
                continue

            matches[asset_path] = filtered
            dependencies.update(filtered)

        return json.dumps(
            {
                "assetCount": len(assets),
                "assetsWithMatches": len(matches),
                "dependencies": sorted(dependencies),
                "matches": matches,
                "rootPath": root_path,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def audit_animation_migration_metadata(root_path: str) -> str:
        """汇总正式动画仍携带的编辑器修改器、压缩设置、加法基准和通知引用"""
        result = {}

        for asset_path in _list_animation_sequences(root_path):
            animation = unreal.EditorAssetLibrary.load_asset(asset_path)
            metadata = {
                "appliedModifiers": [],
                "curveCompressionSettings": _read_property(
                    animation,
                    "curve_compression_settings",
                ),
                "modifierInstances": [],
                "notifies": [],
                "referencePoseSequence": _read_property(
                    animation,
                    "ref_pose_seq",
                ),
            }

            modifier_data = animation.get_asset_user_data_of_class(
                unreal.AnimationModifiersAssetUserData,
            )
            if modifier_data is not None:
                metadata["modifierInstances"] = [
                    _path(modifier)
                    for modifier in list(
                        modifier_data.get_editor_property(
                            "animation_modifier_instances",
                        )
                    )
                    if modifier is not None
                ]
                metadata["appliedModifiers"] = [
                    str(path)
                    for path in modifier_data.get_editor_property(
                        "applied_modifiers",
                    ).keys()
                ]

            notify_events = unreal.AnimationLibrary.get_animation_notify_events(
                animation,
            )

            for event in notify_events:
                notify = event.get_editor_property("notify")
                notify_state = event.get_editor_property("notify_state_class")
                metadata["notifies"].append(
                    {
                        "name": str(event.get_editor_property("notify_name")),
                        "notify": _path(notify),
                        "notifyState": _path(notify_state),
                    }
                )

            if any(
                (
                    metadata["appliedModifiers"],
                    metadata["modifierInstances"],
                    metadata["notifies"],
                    isinstance(metadata["curveCompressionSettings"], str),
                    isinstance(metadata["referencePoseSequence"], str),
                )
            ):
                result[asset_path] = metadata

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def finalize_animation_runtime_assets(
        notify_source_paths: list[str],
        notify_target_paths: list[str],
        rebuild_animation_paths: list[str],
    ) -> str:
        """迁入运行时通知并重建仍含迁移孤儿对象的动画包"""
        if len(notify_source_paths) != len(notify_target_paths):
            raise RuntimeError("通知源路径与目标路径数量不一致")

        migrated_notifies = []
        for source_path, target_path in zip(
            notify_source_paths,
            notify_target_paths,
        ):
            source_asset = unreal.EditorAssetLibrary.load_asset(source_path)
            if source_asset is None:
                target_asset = unreal.EditorAssetLibrary.load_asset(target_path)
                if target_asset is None:
                    raise RuntimeError(
                        "运行时通知源资产和正式资产均不存在: {}".format(
                            source_path,
                        )
                    )

                migrated_notifies.append(target_path)
                continue

            resolved_source_path = _path(source_asset).split(".", 1)[0]
            if resolved_source_path == target_path:
                migrated_notifies.append(target_path)
                continue

            target_asset = unreal.EditorAssetLibrary.load_asset(target_path)
            if target_asset is not None:
                raise RuntimeError("运行时通知正式路径已被占用: {}".format(target_path))

            if not unreal.EditorAssetLibrary.rename_asset(source_path, target_path):
                raise RuntimeError("迁移运行时通知失败: {}".format(source_path))

            target_asset = unreal.EditorAssetLibrary.load_asset(target_path)
            if target_asset is None:
                raise RuntimeError("迁移后无法加载运行时通知: {}".format(target_path))

            if target_asset.get_class().get_name() == "Blueprint":
                unreal.BlueprintEditorLibrary.compile_blueprint(target_asset)

            migrated_notifies.append(target_path)

        rebuilt_animations = []
        for animation_path in rebuild_animation_paths:
            animation = unreal.EditorAssetLibrary.load_asset(animation_path)
            if animation is None:
                raise RuntimeError("待重建动画不存在: {}".format(animation_path))

            temporary_path = "{}_MigrationClean".format(animation_path)
            if unreal.EditorAssetLibrary.does_asset_exist(temporary_path):
                raise RuntimeError("临时动画路径已存在: {}".format(temporary_path))

            temporary_asset = unreal.EditorAssetLibrary.duplicate_asset(
                animation_path,
                temporary_path,
            )
            if temporary_asset is None:
                raise RuntimeError("复制待重建动画失败: {}".format(animation_path))

            if not unreal.EditorAssetLibrary.consolidate_assets(
                temporary_asset,
                [animation],
            ):
                raise RuntimeError("重建动画引用失败: {}".format(animation_path))

            if unreal.EditorAssetLibrary.does_asset_exist(animation_path):
                if not unreal.EditorAssetLibrary.delete_asset(animation_path):
                    raise RuntimeError(
                        "删除重建动画留下的重定向器失败: {}".format(
                            animation_path,
                        )
                    )

            if not unreal.EditorAssetLibrary.rename_asset(
                temporary_path,
                animation_path,
            ):
                raise RuntimeError("恢复重建动画正式路径失败: {}".format(animation_path))

            rebuilt_animations.append(animation_path)

        unreal.SystemLibrary.collect_garbage()

        if not unreal.EditorAssetLibrary.save_directory(
            "/Game/BBBC/AnimationSystem/Shared",
            True,
            True,
        ):
            raise RuntimeError("保存正式动画共享目录失败")
        if not unreal.EditorAssetLibrary.save_directory(
            "/Game/BBBC/Animation",
            True,
            True,
        ):
            raise RuntimeError("保存正式动画目录失败")

        return json.dumps(
            {
                "migratedNotifies": migrated_notifies,
                "rebuiltAnimations": rebuilt_animations,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def clean_retargeted_animation_dependencies(
        root_path: str,
        legacy_root: str,
        compression_source_path: str,
        compression_target_path: str,
    ) -> str:
        """清除正式动画对迁移源目录的编辑器依赖并修正运行时引用"""
        target_paths = _list_animation_sequences(root_path)
        target_index = _index_assets_by_name(target_paths)
        duplicate_names = sorted(
            name
            for name, paths in target_index.items()
            if len(paths) != 1
        )
        if duplicate_names:
            raise RuntimeError(
                "正式动画存在重名，无法确定加法基准映射: {}".format(
                    ", ".join(duplicate_names),
                )
            )

        compression_settings = unreal.EditorAssetLibrary.load_asset(
            compression_target_path,
        )
        if compression_settings is None:
            compression_settings = unreal.EditorAssetLibrary.duplicate_asset(
                compression_source_path,
                compression_target_path,
            )
        if compression_settings is None:
            raise RuntimeError("复制正式曲线压缩设置失败")

        cleaned_modifier_assets = 0
        remapped_compression_assets = 0
        remapped_reference_pose_assets = 0

        for asset_path in target_paths:
            animation = unreal.EditorAssetLibrary.load_asset(asset_path)
            modifier_data = animation.get_asset_user_data_of_class(
                unreal.AnimationModifiersAssetUserData,
            )
            if modifier_data is not None:
                modifier_instances = list(
                    modifier_data.get_editor_property(
                        "animation_modifier_instances",
                    )
                )
                applied_modifiers = modifier_data.get_editor_property(
                    "applied_modifiers",
                )
                if modifier_instances or applied_modifiers:
                    modifier_data.set_editor_property(
                        "animation_modifier_instances",
                        [],
                    )
                    modifier_data.set_editor_property(
                        "applied_modifiers",
                        {},
                    )
                    cleaned_modifier_assets += 1

            curve_settings = animation.get_editor_property(
                "curve_compression_settings",
            )
            curve_settings_path = _path(curve_settings)
            if curve_settings_path is not None:
                curve_settings_path = curve_settings_path.split(".", 1)[0]
            if curve_settings_path == compression_source_path:
                animation.set_editor_property(
                    "curve_compression_settings",
                    compression_settings,
                )
                remapped_compression_assets += 1

            reference_pose = animation.get_editor_property("ref_pose_seq")
            if _path(reference_pose) is not None and _path(reference_pose).startswith(
                legacy_root,
            ):
                reference_name = reference_pose.get_name()
                target_reference_paths = target_index.get(reference_name, [])
                if not target_reference_paths:
                    raise RuntimeError(
                        "找不到加法基准动画的正式同名资产: {}".format(
                            _path(reference_pose),
                        )
                    )

                target_reference_path = target_reference_paths[0]
                target_reference = unreal.EditorAssetLibrary.load_asset(
                    target_reference_path,
                )
                if target_reference is None:
                    raise RuntimeError(
                        "找不到加法基准动画的正式同名资产: {}".format(
                            _path(reference_pose),
                        )
                    )

                animation.set_editor_property("ref_pose_seq", target_reference)
                remapped_reference_pose_assets += 1

        unreal.SystemLibrary.collect_garbage()

        if not unreal.EditorAssetLibrary.save_directory(root_path, True, True):
            raise RuntimeError("保存正式动画目录失败")
        if not unreal.EditorAssetLibrary.save_asset(compression_target_path, False):
            raise RuntimeError("保存正式曲线压缩设置失败")

        return json.dumps(
            {
                "animationCount": len(target_paths),
                "cleanedModifierAssets": cleaned_modifier_assets,
                "compressionSettings": compression_target_path,
                "remappedCompressionAssets": remapped_compression_assets,
                "remappedReferencePoseAssets": remapped_reference_pose_assets,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def replace_lyra_animation_references(
        source_root: str,
        target_root: str,
        dry_run: bool = True,
    ) -> str:
        """按同名规则将 Lyra 动画引用一次性替换为 BBB 重定向动画"""
        source_paths = _list_animation_sequences(source_root)
        target_paths = _list_animation_sequences(target_root)
        target_index = _index_assets_by_name(target_paths)
        matched = []
        missing = []
        ambiguous = []
        failed = []

        for source_path in source_paths:
            asset_name = source_path.rsplit("/", 1)[-1].split(".", 1)[0]
            candidates = target_index.get(asset_name, [])
            if not candidates:
                missing.append(source_path)
                continue

            if len(candidates) > 1:
                ambiguous.append(
                    {
                        "name": asset_name,
                        "source": source_path,
                        "targets": candidates,
                    }
                )
                continue

            target_path = candidates[0]
            if not dry_run:
                source_asset = unreal.EditorAssetLibrary.load_asset(source_path)
                target_asset = unreal.EditorAssetLibrary.load_asset(target_path)
                if source_asset is None or target_asset is None:
                    failed.append(source_path)
                    continue

                if not unreal.EditorAssetLibrary.consolidate_assets(
                    target_asset,
                    [source_asset],
                ):
                    failed.append(source_path)
                    continue

            matched.append(
                {
                    "source": source_path,
                    "target": target_path,
                }
            )

        if not dry_run:
            unreal.EditorAssetLibrary.save_directory(target_root, True, True)

        result = {
            "ambiguous": ambiguous,
            "dryRun": dry_run,
            "failed": failed,
            "matched": matched,
            "missing": missing,
            "sourceCount": len(source_paths),
            "targetCount": len(target_paths),
        }

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def retarget_missing_animations(
        source_asset_paths: list[str],
        retargeter_path: str,
        target_path: str,
    ) -> str:
        """使用指定 IK Retargeter 仅补齐迁移中缺失的动画"""
        if not source_asset_paths:
            return json.dumps({"created": []}, ensure_ascii=False)

        retargeter = unreal.EditorAssetLibrary.load_asset(retargeter_path)
        if retargeter is None:
            raise RuntimeError("IK Retargeter 不存在: {}".format(retargeter_path))

        controller = unreal.IKRetargeterController.get_controller(retargeter)
        source_mesh = controller.get_preview_mesh(
            unreal.RetargetSourceOrTarget.SOURCE,
        )
        target_mesh = controller.get_preview_mesh(
            unreal.RetargetSourceOrTarget.TARGET,
        )
        if source_mesh is None or target_mesh is None:
            raise RuntimeError("IK Retargeter 未配置完整的源与目标预览网格")

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        source_assets = []
        for source_path in source_asset_paths:
            object_path = "{}.{}".format(
                source_path,
                source_path.rsplit("/", 1)[-1],
            )
            asset_data = registry.get_asset_by_object_path(unreal.Name(object_path))
            if not asset_data.is_valid():
                raise RuntimeError("源动画不存在: {}".format(source_path))

            source_assets.append(asset_data)

        unreal.EditorAssetLibrary.make_directory(target_path)

        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = source_assets
        inputs.source_mesh = source_mesh
        inputs.target_mesh = target_mesh
        inputs.ik_retarget_asset = retargeter
        inputs.target_path = target_path
        inputs.include_referenced_assets = False
        inputs.overwrite_existing_files = False
        inputs.retain_additive_flags = True

        results = unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)
        created = [str(result.package_name) for result in results]
        if len(created) != len(source_asset_paths):
            raise RuntimeError(
                "重定向数量不一致: 请求 {}，创建 {}".format(
                    len(source_asset_paths),
                    len(created),
                )
            )

        unreal.EditorAssetLibrary.save_directory(target_path, True, True)

        return json.dumps({"created": created}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def set_animation_blueprint_skeletons(
        blueprint_paths: list[str],
        skeleton_path: str,
    ) -> str:
        """将迁移后的动画蓝图统一绑定到 BBB 目标骨架并重新编译"""
        skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
        if skeleton is None:
            raise RuntimeError("目标骨架不存在: {}".format(skeleton_path))

        updated = []
        for blueprint_path in blueprint_paths:
            blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
            if blueprint is None:
                raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

            if blueprint.get_class().get_name() != "AnimBlueprint":
                raise RuntimeError("资产不是 AnimBlueprint: {}".format(blueprint_path))

            blueprint.set_editor_property("target_skeleton", skeleton)
            unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
            if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                raise RuntimeError("动画蓝图保存失败: {}".format(blueprint_path))

            updated.append(blueprint_path)

        return json.dumps({"updated": updated}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def set_animation_blueprint_preview_mesh(
        blueprint_path: str,
        mesh_path: str,
    ) -> str:
        """设置动画蓝图的预览骨骼网格并重新编译保存"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None or blueprint.get_class().get_name() != "AnimBlueprint":
            raise RuntimeError("资产不是有效的 AnimBlueprint: {}".format(blueprint_path))

        preview_mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        if not isinstance(preview_mesh, unreal.SkeletalMesh):
            raise RuntimeError("预览网格不是 SkeletalMesh: {}".format(mesh_path))

        if not unreal.BBBBlueprintEditorLibrary.set_animation_blueprint_preview_mesh(
            blueprint,
            preview_mesh,
        ):
            raise RuntimeError("设置动画蓝图预览网格失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("动画蓝图编译失败: {}".format(blueprint_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "previewMesh": mesh_path,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_animation_asset_preview_meshes(
        mesh_path: str,
        dry_run: bool = True,
    ) -> str:
        """按骨架匹配批量设置 UA 动画预览网格 不编译动画蓝图"""
        preview_mesh = unreal.load_asset(mesh_path)
        if preview_mesh is None:
            raise RuntimeError("预览网格不是 SkeletalMesh: {}".format(mesh_path))

        preview_mesh_class = preview_mesh.get_class().get_name()
        if preview_mesh_class != "SkeletalMesh":
            raise RuntimeError(
                "预览资产类型不是 SkeletalMesh: {} ({})".format(
                    mesh_path,
                    preview_mesh_class,
                )
            )

        preview_skeleton = preview_mesh.get_editor_property("skeleton")
        if preview_skeleton is None:
            raise RuntimeError("预览网格没有绑定骨架: {}".format(mesh_path))

        preview_skeleton_path = _path(preview_skeleton)
        candidates = []
        counts_by_class = {}

        for asset_path in unreal.EditorAssetLibrary.list_assets(
            "/Game/BBBC_UA",
            True,
            False,
        ):
            asset = unreal.load_asset(asset_path)
            if asset is None:
                continue

            asset_class = asset.get_class().get_name()
            if asset_class not in (
                "AnimSequence",
                "AnimMontage",
                "BlendSpace",
                "BlendSpace1D",
                "AnimBlueprint",
            ):
                continue

            if asset_class == "AnimBlueprint" and "/Interfaces/" in asset_path:
                continue

            if asset_class == "AnimBlueprint":
                skeleton = asset.get_editor_property("target_skeleton")
            else:
                skeleton = asset.get_skeleton()

            if skeleton is None or _path(skeleton) != preview_skeleton_path:
                continue

            candidates.append((asset_path, asset_class))
            counts_by_class[asset_class] = counts_by_class.get(asset_class, 0) + 1

        if not candidates:
            raise RuntimeError("没有找到与预览网格骨架匹配的 UA 动画资产")

        if dry_run:
            return json.dumps(
                {
                    "dryRun": True,
                    "previewMesh": mesh_path,
                    "skeleton": preview_skeleton_path,
                    "count": len(candidates),
                    "countsByClass": counts_by_class,
                    "assetPaths": [asset_path for asset_path, _ in candidates],
                },
                ensure_ascii=False,
            )

        updated = []
        for asset_path, asset_class in candidates:
            asset = unreal.load_asset(asset_path)
            if asset is None:
                raise RuntimeError("动画资产加载失败: {}".format(asset_path))

            if asset_class == "AnimBlueprint":
                if not unreal.BBBBlueprintEditorLibrary.set_animation_blueprint_preview_mesh(
                    asset,
                    preview_mesh,
                ):
                    raise RuntimeError("设置动画蓝图预览网格失败: {}".format(asset_path))
            else:
                asset.set_preview_skeletal_mesh(preview_mesh)

            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError("动画预览网格保存失败: {}".format(asset_path))

            updated.append(asset_path)

        return json.dumps(
            {
                "dryRun": False,
                "previewMesh": mesh_path,
                "count": len(updated),
                "countsByClass": counts_by_class,
                "updated": updated,
                "compiledAnimationBlueprints": False,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_animation_sequence_preview_meshes(
        animation_paths: list[str],
        mesh_path: str,
        dry_run: bool = True,
    ) -> str:
        """按显式动画序列路径设置预览网格"""
        if not animation_paths:
            raise RuntimeError("动画序列路径列表为空")

        if len(set(animation_paths)) != len(animation_paths):
            raise RuntimeError("动画序列路径列表包含重复项")

        preview_mesh = unreal.load_asset(mesh_path)
        if preview_mesh is None or preview_mesh.get_class().get_name() != "SkeletalMesh":
            raise RuntimeError("预览网格不是 SkeletalMesh: {}".format(mesh_path))

        preview_skeleton = preview_mesh.get_editor_property("skeleton")
        if preview_skeleton is None:
            raise RuntimeError("预览网格没有绑定骨架: {}".format(mesh_path))

        preview_skeleton_path = _path(preview_skeleton)
        candidates = []

        for animation_path in animation_paths:
            if not animation_path.startswith(
                "/Game/BBBC_UA/Animation/RifleAnimsetPro/"
            ):
                raise RuntimeError("动画不属于步枪重定向包: {}".format(animation_path))

            animation = unreal.EditorAssetLibrary.load_asset(animation_path)
            if animation is None:
                raise RuntimeError("动画序列不存在: {}".format(animation_path))

            if animation.get_class().get_name() != "AnimSequence":
                raise RuntimeError("资产不是 AnimSequence: {}".format(animation_path))

            skeleton = animation.get_skeleton()
            if skeleton is None or _path(skeleton) != preview_skeleton_path:
                raise RuntimeError("动画序列与预览网格骨架不一致: {}".format(animation_path))

            candidates.append((animation_path, animation))

        if dry_run:
            return json.dumps(
                {
                    "dryRun": True,
                    "previewMesh": mesh_path,
                    "skeleton": preview_skeleton_path,
                    "count": len(candidates),
                    "animationPaths": [path for path, _ in candidates],
                },
                ensure_ascii=False,
            )

        updated = []

        for animation_path, animation in candidates:
            animation.set_preview_skeletal_mesh(preview_mesh)

            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError("动画预览网格保存失败: {}".format(animation_path))

            updated.append(animation_path)

        return json.dumps(
            {
                "dryRun": False,
                "previewMesh": mesh_path,
                "skeleton": preview_skeleton_path,
                "count": len(updated),
                "updated": updated,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_animation_folder_preview_meshes(
        folder_path: str,
        mesh_path: str,
        dry_run: bool = True,
    ) -> str:
        """只处理 Lyra 动画目录中的动画序列和蒙太奇预览网格"""
        allowed_folder_path = "/Game/BBBC_UA/Animation/Lyra"
        normalized_folder_path = folder_path.rstrip("/")

        if normalized_folder_path != allowed_folder_path:
            raise RuntimeError(
                "只允许处理 Lyra 动画目录: {}".format(folder_path)
            )

        preview_mesh = unreal.load_asset(mesh_path)
        if (
            preview_mesh is None
            or preview_mesh.get_class().get_name() != "SkeletalMesh"
        ):
            raise RuntimeError("预览网格不是 SkeletalMesh: {}".format(mesh_path))

        preview_skeleton = preview_mesh.get_editor_property("skeleton")
        if preview_skeleton is None:
            raise RuntimeError("预览网格没有绑定骨架: {}".format(mesh_path))

        preview_skeleton_path = _path(preview_skeleton)
        candidates = []
        counts_by_class = {}
        asset_paths = unreal.EditorAssetLibrary.list_assets(
            normalized_folder_path,
            True,
            False,
        )

        for animation_path in asset_paths:
            if not animation_path.startswith(normalized_folder_path + "/"):
                raise RuntimeError("动画路径超出指定目录: {}".format(animation_path))

            animation = unreal.EditorAssetLibrary.load_asset(animation_path)
            if animation is None:
                raise RuntimeError("动画资产加载失败: {}".format(animation_path))

            animation_class = animation.get_class().get_name()
            if animation_class not in ("AnimSequence", "AnimMontage"):
                continue

            skeleton = animation.get_skeleton()
            if skeleton is None or _path(skeleton) != preview_skeleton_path:
                raise RuntimeError(
                    "动画资产与预览网格骨架不一致: {}".format(animation_path)
                )

            candidates.append((animation_path, animation))
            counts_by_class[animation_class] = (
                counts_by_class.get(animation_class, 0) + 1
            )

        if not candidates:
            raise RuntimeError("指定目录中没有可设置预览网格的动画资产")

        if dry_run:
            return json.dumps(
                {
                    "dryRun": True,
                    "folder": normalized_folder_path,
                    "previewMesh": mesh_path,
                    "skeleton": preview_skeleton_path,
                    "count": len(candidates),
                    "countsByClass": counts_by_class,
                    "assetPaths": [path for path, _ in candidates],
                },
                ensure_ascii=False,
            )

        updated = []

        for animation_path, animation in candidates:
            animation.set_preview_skeletal_mesh(preview_mesh)

            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError(
                    "动画预览网格保存失败，已保存 {} 个资产: {}".format(
                        len(updated),
                        animation_path,
                    )
                )

            updated.append(animation_path)

        return json.dumps(
            {
                "dryRun": False,
                "folder": normalized_folder_path,
                "previewMesh": mesh_path,
                "skeleton": preview_skeleton_path,
                "count": len(updated),
                "countsByClass": counts_by_class,
                "updated": updated,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def run_pie_input_sequence(steps_json: str) -> str:
        """按 schemaVersion:2 在 PIE 游戏帧中注入角色 Enhanced Input"""
        try:
            request = json.loads(steps_json)
        except Exception as error:
            raise RuntimeError("steps_json不是有效JSON: {}".format(error))

        if not isinstance(request, dict):
            raise RuntimeError("steps_json必须是schemaVersion:2的对象")

        return unreal.BBBPIEInputEditorLibrary.start_pie_input_sequence(
            steps_json
        )

    @toolset_registry.tool_call
    @staticmethod
    def get_pie_input_sequence_status() -> str:
        """读取PIE输入序列的当前执行状态"""
        return unreal.BBBPIEInputEditorLibrary.get_pie_input_sequence_status(
        )

    @toolset_registry.tool_call
    @staticmethod
    def stop_pie_input_sequence() -> str:
        """停止PIE输入序列并释放全部注入输入"""
        return unreal.BBBPIEInputEditorLibrary.stop_pie_input_sequence()

    @toolset_registry.tool_call
    @staticmethod
    def export_animation_blueprint_graphs(blueprint_path: str) -> str:
        """严格只读导出动画蓝图图、节点、引脚与绑定"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        return unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(
            blueprint
        )

    @toolset_registry.tool_call
    @staticmethod
    def restore_lyra_stop_pose(blueprint_path: str) -> str:
        """恢复 Lyra 原版停步姿势并移除停步专用方向扭曲"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)

        if blueprint is None or blueprint.get_class().get_name() != "AnimBlueprint":
            raise RuntimeError("停步动画蓝图不存在或类型错误: {}".format(blueprint_path))

        updated_count = unreal.BBBBlueprintEditorLibrary.restore_lyra_stop_pose(
            blueprint
        )

        if updated_count < 0:
            raise RuntimeError("Lyra 停步姿势恢复失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)

        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("停步动画蓝图编译失败: {}".format(blueprint_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("停步动画蓝图保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "updatedNodeCount": updated_count,
                "compileStatus": str(blueprint.get_editor_property("status")),
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def capture_pie_character_pose(camera_offset: list[float], file_name: str, width: int = 960, height: int = 960) -> str:
        """在 PIE 世界临时渲染本地角色，输出带游戏帧号的姿势截图路径"""
        if len(camera_offset) != 3 or os.path.basename(file_name) != file_name or not file_name.endswith(".png"):
            raise RuntimeError("角色截图需要三维摄像机偏移及不含目录的 PNG 文件名")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("角色截图要求 PIE 正在运行")

        pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
        if pawn is None:
            raise RuntimeError("角色截图未找到本地玩家")

        snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.probe_character_animation_runtime(pawn))
        target = pawn.get_actor_location()
        location = target + unreal.Vector(*camera_offset)
        rotation = unreal.MathLibrary.find_look_at_rotation(location, target)
        transform = unreal.Transform(location=location, rotation=rotation)
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
            world,
            unreal.SceneCapture2D,
            transform,
        )
        if actor is None:
            raise RuntimeError("无法创建 PIE 姿势截图组件")

        try:
            render_target = unreal.RenderingLibrary.create_render_target2d(
                world,
                max(64, min(width, 2048)),
                max(64, min(height, 2048)),
                unreal.TextureRenderTargetFormat.RTF_RGBA8,
            )
            component = actor.capture_component2d
            component.set_editor_property("texture_target", render_target)
            component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            component.set_editor_property("fov_angle", 45.0)
            component.capture_scene()
            directory = os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "StopPoseCaptures")
            os.makedirs(directory, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, render_target, directory, file_name)
            output_path = os.path.abspath(os.path.join(directory, file_name))
            if not os.path.isfile(output_path):
                raise RuntimeError("PIE 姿势截图未生成，需要启用渲染的编辑器")

            return json.dumps({"imagePath": output_path, "pawn": pawn.get_path_name(), "frame": snapshot.get("frame"), "states": snapshot.get("mainInstance", {}).get("states", [])}, ensure_ascii=False)
        finally:
            actor.destroy_actor()

    @toolset_registry.tool_call
    @staticmethod
    def probe_pie_character_animation_runtime() -> str:
        """读取PIE本地玩家角色的主层、链接层和腿部骨骼快照"""
        subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        game_world = subsystem.get_game_world()
        if game_world is None:
            raise RuntimeError("PIE未运行，无法读取角色动画快照")

        pawn = unreal.GameplayStatics.get_player_pawn(game_world, 0)
        if pawn is None:
            raise RuntimeError("PIE本地玩家角色不存在")

        return unreal.BBBBlueprintEditorLibrary.probe_character_animation_runtime(
            pawn
        )

    @toolset_registry.tool_call
    @staticmethod
    def build_weapon_animation_graph(
        blueprint_path: str,
        fire_animation_path: str,
        reload_animation_path: str,
    ) -> str:
        """重建武器动画蓝图的无状态开火与换弹动作图"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        fire_animation = unreal.EditorAssetLibrary.load_asset(fire_animation_path)
        reload_animation = unreal.EditorAssetLibrary.load_asset(reload_animation_path)

        if blueprint is None or blueprint.get_class().get_name() != "AnimBlueprint":
            raise RuntimeError("资产不是有效的 AnimBlueprint: {}".format(blueprint_path))
        if fire_animation is None or fire_animation.get_class().get_name() != "AnimSequence":
            raise RuntimeError("开火动画不存在或类型错误: {}".format(fire_animation_path))
        if reload_animation is None or reload_animation.get_class().get_name() != "AnimSequence":
            raise RuntimeError("换弹动画不存在或类型错误: {}".format(reload_animation_path))

        if not unreal.BBBBlueprintEditorLibrary.build_weapon_animation_graph(
            blueprint,
            fire_animation,
            reload_animation,
        ):
            raise RuntimeError("武器动画图重建失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("武器动画图编译失败: {}".format(blueprint_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("武器动画蓝图保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "fireAnimation": fire_animation_path,
                "reloadAnimation": reload_animation_path,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def remap_animation_blueprint_blend_profiles(
        blueprint_path: str,
        skeleton_path: str,
    ) -> str:
        """将动画蓝图的混合描述文件按名称重绑到指定骨架"""
        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            raise RuntimeError("动画蓝图不存在: {}".format(blueprint_path))

        skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
        if skeleton is None:
            raise RuntimeError("目标骨架不存在: {}".format(skeleton_path))

        blueprint.set_editor_property("target_skeleton", skeleton)
        updated_count = unreal.BBBBlueprintEditorLibrary.remap_animation_blend_profiles(
            blueprint,
            skeleton,
        )
        if updated_count < 0:
            raise RuntimeError("动画蓝图混合描述文件重绑失败: {}".format(blueprint_path))

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("动画蓝图编译失败: {}".format(blueprint_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败: {}".format(blueprint_path))

        return json.dumps(
            {
                "blueprint": blueprint_path,
                "skeleton": skeleton_path,
                "updatedCount": updated_count,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def rebuild_blend_space_skeleton(
        blend_space_path: str,
        skeleton_path: str,
    ) -> str:
        """原位重建混合空间并绑定到指定骨架"""
        blend_space = unreal.EditorAssetLibrary.load_asset(blend_space_path)
        if blend_space is None:
            raise RuntimeError("混合空间不存在: {}".format(blend_space_path))

        if blend_space.get_class().get_name() != "BlendSpace1D":
            raise RuntimeError("当前只支持 BlendSpace1D: {}".format(blend_space_path))

        skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
        if skeleton is None:
            raise RuntimeError("目标骨架不存在: {}".format(skeleton_path))

        temporary_path = "{}_SkeletonRebuild".format(blend_space_path)
        if unreal.EditorAssetLibrary.does_asset_exist(temporary_path):
            raise RuntimeError("临时混合空间已存在: {}".format(temporary_path))

        package_path, temporary_name = temporary_path.rsplit("/", 1)
        factory = unreal.BlendSpaceFactory1D()
        factory.set_editor_property("target_skeleton", skeleton)
        replacement = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            temporary_name,
            package_path,
            unreal.BlendSpace1D,
            factory,
        )
        if replacement is None:
            raise RuntimeError("创建临时混合空间失败: {}".format(temporary_path))

        copied_properties = (
            "scale_animation",
            "interpolation_param",
            "analysis_properties",
            "target_weight_interpolation_speed_per_sec",
            "target_weight_interpolation_ease_in_out",
            "allow_mesh_space_blending",
            "loop",
            "allow_marker_based_sync",
            "should_match_sync_phases",
            "use_legacy_sample_point_animation_length_calculations",
            "preview_base_pose",
            "notify_trigger_mode",
            "interpolate_using_grid",
            "preferred_triangulation_direction",
            "mirror_data_table",
            "per_bone_blend_mode",
            "manual_per_bone_overrides",
            "per_bone_blend_profile",
            "sample_data",
            "blend_parameters",
            "axis_to_scale_animation",
            "meta_data",
            "asset_user_data",
            "preview_pose_asset",
        )

        try:
            for property_name in copied_properties:
                property_value = blend_space.get_editor_property(property_name)
                replacement.set_editor_property(property_name, property_value)
        except Exception:
            unreal.EditorAssetLibrary.delete_asset(temporary_path)
            raise

        if not unreal.EditorAssetLibrary.save_loaded_asset(replacement, False):
            unreal.EditorAssetLibrary.delete_asset(temporary_path)
            raise RuntimeError("保存临时混合空间失败: {}".format(temporary_path))

        if not unreal.EditorAssetLibrary.consolidate_assets(
            replacement,
            [blend_space],
        ):
            unreal.EditorAssetLibrary.delete_asset(temporary_path)
            raise RuntimeError("替换混合空间引用失败: {}".format(blend_space_path))

        if unreal.EditorAssetLibrary.does_asset_exist(blend_space_path):
            if not unreal.EditorAssetLibrary.delete_asset(blend_space_path):
                raise RuntimeError("删除混合空间重定向器失败: {}".format(blend_space_path))

        if not unreal.EditorAssetLibrary.rename_asset(
            temporary_path,
            blend_space_path,
        ):
            raise RuntimeError("恢复混合空间正式路径失败: {}".format(blend_space_path))

        rebuilt_asset = unreal.EditorAssetLibrary.load_asset(blend_space_path)
        if rebuilt_asset is None:
            raise RuntimeError("重建后无法加载混合空间: {}".format(blend_space_path))

        rebuilt_skeleton = rebuilt_asset.get_skeleton()
        if _path(rebuilt_skeleton).split(".", 1)[0] != skeleton_path:
            raise RuntimeError("混合空间骨架重建后仍不匹配: {}".format(blend_space_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(rebuilt_asset, False):
            raise RuntimeError("保存重建混合空间失败: {}".format(blend_space_path))

        return json.dumps(
            {
                "blendSpace": blend_space_path,
                "skeleton": skeleton_path,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def copy_animation_skeleton_metadata(source_skeleton_path: str, target_skeleton_path: str, target_to_source_bones: dict[str, str]) -> str:
        """按目标骨名复制混合遮罩、虚拟骨骼、插槽与蒙太奇分组"""
        source = unreal.load_asset(source_skeleton_path)
        target = unreal.load_asset(target_skeleton_path)
        if not unreal.BBBBlueprintEditorLibrary.copy_animation_skeleton_metadata(source, target, target_to_source_bones):
            raise RuntimeError("骨架元数据复制失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
            raise RuntimeError("目标骨架保存失败")
        return json.dumps({"source": source_skeleton_path, "target": target_skeleton_path})

    @toolset_registry.tool_call
    @staticmethod
    def rebind_animation_blueprint_interface(blueprint_path: str, source_interface_path: str, target_interface_path: str) -> str:
        """替换已实现的动画接口并保留现有覆盖图"""
        blueprint = unreal.load_asset(blueprint_path)
        source = unreal.load_object(None, source_interface_path)
        target = unreal.load_object(None, target_interface_path)
        count = unreal.BBBBlueprintEditorLibrary.rebind_animation_blueprint_interface(blueprint, source, target)
        if count < 0:
            raise RuntimeError("动画接口重绑失败")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")
        return json.dumps({"blueprint": blueprint_path, "count": count, "status": str(blueprint.get_editor_property("status"))})

    @toolset_registry.tool_call
    @staticmethod
    def remap_animation_blueprint_class_references(blueprint_path: str, class_paths: dict[str, str]) -> str:
        """统一替换目标动画蓝图中的转换类、函数返回类与引脚类型"""
        blueprint = unreal.load_asset(blueprint_path)
        count = unreal.BBBBlueprintEditorLibrary.remap_animation_blueprint_class_references(blueprint, class_paths)
        if count < 0:
            raise RuntimeError("动画蓝图类引用替换失败")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("类引用替换后的动画蓝图编译失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")
        return json.dumps({"blueprint": blueprint_path, "count": count})

    @toolset_registry.tool_call
    @staticmethod
    def probe_animation_instance_runtime(instance_path: str) -> str:
        """安全读取 PIE 动画实例的实际状态和活跃播放器"""
        instance = unreal.find_object(None, instance_path)
        if not isinstance(instance, unreal.AnimInstance):
            raise RuntimeError("运行时动画实例不存在")
        return unreal.BBBBlueprintEditorLibrary.probe_animation_instance_runtime(instance)

    @toolset_registry.tool_call
    @staticmethod
    def remap_animation_sequence_notify_classes(animation_path: str, class_paths: dict[str, str]) -> str:
        """替换目标动画的通知类并保留全部事件设置"""
        animation = unreal.load_asset(animation_path)
        count = unreal.BBBBlueprintEditorLibrary.remap_animation_sequence_notify_classes(animation, class_paths)
        if count < 0:
            raise RuntimeError("动画通知类替换失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError("动画通知保存失败")
        return json.dumps({"animation": animation_path, "count": count})


    @toolset_registry.tool_call
    @staticmethod
    def audit_arm_twist_tracks(animation_paths: list[str], mesh_path: str) -> str:
        """
        /**
         * 审计前臂辅助骨的旋转分配和连续性
         * @param animation_paths	动画资产路径
         * @param mesh_path		目标骨骼网格
         * @return 审计摘要与报告路径
         */
        """
        import BBBArmTwistTools
        return BBBArmTwistTools.audit(animation_paths, mesh_path)

    @toolset_registry.tool_call
    @staticmethod
    def rebuild_arm_twist_tracks(animation_paths: list[str], mesh_path: str, dry_run: bool = True) -> str:
        """
        /**
         * 在独占签出后重建前臂辅助骨轨道
         * @param animation_paths	动画资产路径
         * @param mesh_path		目标骨骼网格
         * @param dry_run		仅预检开关
         * @return 修复摘要与验证报告路径
         */
        """
        import BBBArmTwistTools
        return BBBArmTwistTools.rebuild(animation_paths, mesh_path, dry_run)


    @toolset_registry.tool_call
    @staticmethod
    def capture_animation_pose(animation_path: str, mesh_path: str, time_seconds: float, focus_bone: str, camera_offset: list[float], file_name: str) -> str:
        """
        /**
         * 渲染指定动画姿势供视觉对照
         * @param animation_path	动画资产路径
         * @param mesh_path		目标网格路径
         * @param time_seconds	采样时间
         * @param focus_bone		相机关注骨骼
         * @param camera_offset	相机偏移
         * @param file_name		输出图像名称
         * @return 图像路径和拍摄参数
         */
        """
        import BBBArmTwistTools
        return BBBArmTwistTools.capture(animation_path, mesh_path, time_seconds, focus_bone, camera_offset, file_name)


    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_arm_pose() -> str:
        """/** @return 本地角色各网格的手臂姿势和活动动画报告 */"""
        import BBBArmTwistTools
        return BBBArmTwistTools.inspect_pie_arms()

    @toolset_registry.tool_call
    @staticmethod
    def capture_pie_bone_pose(focus_bone: str, camera_offset: list[float], file_name: str) -> str:
        """
        /**
         * 拍摄本地角色指定骨骼附近的实际姿势
         * @param focus_bone		关注骨骼
         * @param camera_offset	相机偏移
         * @param file_name		输出图像名称
         * @return 图像路径
         */
        """
        import BBBArmTwistTools
        return BBBArmTwistTools.capture_pie_bone(focus_bone, camera_offset, file_name)


    @toolset_registry.tool_call
    @staticmethod
    def limit_hand_swing_tracks(animation_paths: list[str], mesh_path: str, maximum_swing_degrees: float, dry_run: bool = True) -> str:
        """
        /**
         * 限制显式动画左手骨的摆动并保留轴向扭转
         * @param animation_paths	目标动画
         * @param mesh_path		目标网格
         * @param maximum_swing_degrees	最大摆动角度
         * @param dry_run		仅预检开关
         * @return 修复和验证报告
         */
        """
        import BBBArmTwistTools
        return BBBArmTwistTools.limit_hand_swing(animation_paths, mesh_path, maximum_swing_degrees, dry_run)


    @toolset_registry.tool_call
    @staticmethod
    def start_pie_montage_motion_capture(montage_path: str, sample_times: list[float], file_prefix: str, interrupt_time: float = -1.0, capture_images: bool = True, post_roll_seconds: float = 0.6, exposure_compensation: float = 1.0, fill_light_intensity: float = 5000.0, focus_bone: str = "spine_03") -> str:
        """在本地角色播放指定蒙太奇时记录手臂与装备运动并定时截图"""
        import BBBAnimationMotionTools
        return BBBAnimationMotionTools.start_capture(montage_path, sample_times, file_prefix, interrupt_time,
            capture_images, post_roll_seconds, exposure_compensation, fill_light_intensity, focus_bone)

    @toolset_registry.tool_call
    @staticmethod
    def get_pie_montage_motion_capture_status() -> str:
        """读取蒙太奇运动采样状态与报告目录"""
        import BBBAnimationMotionTools
        return BBBAnimationMotionTools.capture_status()


    @toolset_registry.tool_call
    @staticmethod
    def export_animation_motion_context(animation_paths: list[str], mesh_paths: list[str], file_name: str) -> str:
        """导出骨骼层级与原始动画轨道供离线动画编辑计算"""
        import BBBAnimationMotionTools
        return BBBAnimationMotionTools.export_context(animation_paths, mesh_paths, file_name)


    @toolset_registry.tool_call
    @staticmethod
    def restore_animation_from_source(source_path: str, destination_path: str) -> str:
        """删除目标动画并从源动画原位复制 使目标内容与源完全一致"""
        import BBBAnimationTrajectoryTools
        return BBBAnimationTrajectoryTools.restore_from_source(source_path, destination_path)


    @toolset_registry.tool_call
    @staticmethod
    def replace_montage_animation_references(montage_path: str, replacements_json: str) -> str:
        """按显式映射替换蒙太奇中的等长动画片段 保留通知和播放配置"""
        import BBBAnimationTrajectoryTools
        return BBBAnimationTrajectoryTools.replace_montage_references(montage_path, replacements_json)

    @toolset_registry.tool_call
    @staticmethod
    def hold_animation_bone_tracks(animation_path: str, bone_names: list[str], source_frame: int) -> str:
        """将指定骨骼轨道固定为选定帧 保留其它轨道与动画数据"""
        import BBBAnimationTrajectoryTools
        return BBBAnimationTrajectoryTools.hold_tracks(animation_path, bone_names, source_frame)




_registration = Registration([BBBAnimationMigrationToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
