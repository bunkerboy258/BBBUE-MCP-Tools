import base64
import datetime
import json
import math
import os
import re
import shutil
import struct

import unreal

import toolset_registry
from toolset_registry.registration import Registration


def _serialize_value(value):
    if value is None:
        return None

    if isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, unreal.Object):
        return value.get_path_name()

    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _serialize_value(item)
            for key, item in value.items()
        }

    if hasattr(value, "to_tuple"):
        return _serialize_value(value.to_tuple())

    return str(value)


def _load_blueprint_default_object(asset_path):
    blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not isinstance(blueprint, unreal.Blueprint):
        raise RuntimeError("目标不是蓝图资产: {}".format(asset_path))

    generated_class = blueprint.generated_class()
    if generated_class is None:
        raise RuntimeError("蓝图尚未生成有效类: {}".format(asset_path))

    default_object = unreal.get_default_object(generated_class)
    if default_object is None:
        raise RuntimeError("无法读取蓝图类默认对象: {}".format(asset_path))

    return blueprint, generated_class, default_object


def _apply_editor_property(target, property_name, requested_value):
    current_value = target.get_editor_property(property_name)

    if isinstance(requested_value, dict) and "refPath" in requested_value:
        reference_path = requested_value["refPath"]
        loaded_object = unreal.load_asset(reference_path) if reference_path else None
        if reference_path and loaded_object is None:
            raise RuntimeError("引用资产不存在: {}".format(reference_path))
        target.set_editor_property(property_name, loaded_object)
        return

    if isinstance(requested_value, dict):
        if current_value is None or not hasattr(current_value, "set_editor_property"):
            raise RuntimeError("属性不支持结构化更新: {}".format(property_name))

        for child_name, child_value in requested_value.items():
            _apply_editor_property(current_value, str(child_name), child_value)

        target.set_editor_property(property_name, current_value)
        return

    if isinstance(current_value, unreal.Object) and isinstance(requested_value, str):
        loaded_object = unreal.load_asset(requested_value) if requested_value else None
        if requested_value and loaded_object is None:
            raise RuntimeError("引用资产不存在: {}".format(requested_value))
        target.set_editor_property(property_name, loaded_object)
        return

    target.set_editor_property(property_name, requested_value)


@unreal.uclass()
class BBBGenericEditorToolset(unreal.ToolsetDefinition):
    """提供不绑定具体领域的官方 UE 编辑器工具"""

    @toolset_registry.tool_call
    @staticmethod
    def inspect_control_rig_graphs(asset_path: str) -> str:
        """只读导出 Control Rig 模型与本地函数的节点引脚和连线"""
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.ControlRigBlueprint):
            raise RuntimeError("资产不是 Control Rig 蓝图")

        models = list(asset.get_all_models())
        library = asset.get_local_function_library()
        if library is not None:
            models.append(library)

        visited = set()
        graphs = []
        while models:
            model = models.pop(0)
            path = model.get_path_name()
            if path in visited:
                continue

            visited.add(path)
            graph = {
                "name": model.get_name(),
                "path": path,
                "class": model.get_class().get_name(),
                "nodes": [],
                "links": [],
            }
            for node in model.get_nodes():
                node_data = {
                    "name": node.get_name(),
                    "path": node.get_node_path(),
                    "class": node.get_class().get_name(),
                    "title": node.get_node_title(),
                    "pins": [],
                }
                pins = list(node.get_pins())
                while pins:
                    pin = pins.pop(0)
                    pins.extend(pin.get_sub_pins())
                    node_data["pins"].append({
                        "name": pin.get_name(),
                        "path": pin.get_pin_path(),
                        "direction": str(pin.get_direction()),
                        "cpp_type": pin.get_cpp_type(),
                        "default_value": pin.get_default_value(),
                        "linked_sources": [
                            source.get_pin_path()
                            for source in pin.get_linked_source_pins(False)
                        ],
                        "linked_targets": [
                            target.get_pin_path()
                            for target in pin.get_linked_target_pins(False)
                        ],
                    })

                graph["nodes"].append(node_data)

            for link in model.get_links():
                source_pin = link.get_source_pin()
                target_pin = link.get_target_pin()
                if source_pin is None or target_pin is None:
                    raise RuntimeError("Control Rig 连线存在缺失引脚 {}".format(path))

                graph["links"].append({
                    "source": source_pin.get_pin_path(),
                    "target": target_pin.get_pin_path(),
                })

            graphs.append(graph)
            for node in model.get_nodes():
                if isinstance(node, unreal.RigVMCollapseNode):
                    models.append(node.get_contained_graph())

        if not graphs:
            raise RuntimeError("Control Rig 模型为空")

        return json.dumps({"asset": asset.get_path_name(), "graphs": graphs}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def probe_pie_character_ground_contacts() -> str:
        """
        /**
         * 只读采样本地角色脚部地面命中和运行中的贴地绑定变量
         * @return 脚骨世界位置 地面接触点 高度差与绑定补偿
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 尚未运行")

        pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
        if not isinstance(pawn, unreal.Character):
            raise RuntimeError("本地玩家不是角色")

        mesh = pawn.get_editor_property("mesh")
        bones = {}
        contacts = {}
        for bone_name in ("pelvis", "ik_foot_l", "ik_foot_r", "foot_l", "foot_r", "ball_l", "ball_r"):
            if mesh.get_bone_index(bone_name) < 0:
                raise RuntimeError("角色缺少验收骨骼 {}".format(bone_name))

            location = mesh.get_socket_location(bone_name)
            bones[bone_name] = [location.x, location.y, location.z]
            if bone_name not in ("ball_l", "ball_r"):
                continue

            start = location + unreal.Vector(0.0, 0.0, 50.0)
            end = location - unreal.Vector(0.0, 0.0, 100.0)
            hit = unreal.SystemLibrary.line_trace_single(
                world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                True, [pawn], unreal.DrawDebugTrace.NONE, True)
            contact = {"hit": hit is not None}
            if hit is not None:
                fields = hit.to_tuple()
                if len(fields) != 18:
                    raise RuntimeError("UE 地面命中结构字段数量异常 {}".format(len(fields)))

                point = fields[5]
                normal = fields[7]
                contact["point"] = [point.x, point.y, point.z]
                contact["normal"] = [normal.x, normal.y, normal.z]
                contact["ballHeightAboveGround"] = location.z - point.z

            contacts[bone_name] = contact

        rigs = []
        for rig in unreal.ObjectIterator(unreal.ControlRig):
            if pawn.get_path_name() not in rig.get_path_name():
                continue

            if "CR_BBB_MannequinFootPlant_C" not in rig.get_class().get_name():
                continue

            variables = {}
            for name in (
                "DidLeftFootTraceHit", "DidRightFootTraceHit",
                "TargetLeftFootOffsetZ", "TargetRightFootOffsetZ",
                "CurrentLeftFootOffsetZ", "CurrentRightFootOffsetZ",
                "CurrentPelvisOffsetZ", "CurrentLeftFootHitNormal", "CurrentRightFootHitNormal"):
                variables[name] = rig.get_variable_as_string(name)

            rigs.append({"path": rig.get_path_name(), "variables": variables})

        if len(rigs) != 1:
            raise RuntimeError("运行中的脚部绑定数量异常 {}".format(len(rigs)))

        result = {
            "worldTime": unreal.GameplayStatics.get_time_seconds(world),
            "pawn": pawn.get_path_name(),
            "traceChannel": "Visibility",
            "bones": bones,
            "contacts": contacts,
            "rigs": rigs,
        }
        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_float_curves(asset_paths: list[str], curve_names: list[str]) -> str:
        """只读返回动画浮点曲线的原始时间与值 缺少曲线时明确标记"""
        results = []
        for asset_path in asset_paths:
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if not isinstance(asset, unreal.AnimSequence):
                raise RuntimeError("资产不是动画序列 {}".format(asset_path))

            available = {
                str(name).casefold(): str(name)
                for name in unreal.AnimationLibrary.get_animation_curve_names(asset, unreal.RawCurveTrackTypes.RCT_FLOAT)
            }
            curves = {}
            for curve_name in curve_names:
                stored_curve_name = available.get(curve_name.casefold())
                if stored_curve_name is None:
                    curves[curve_name] = {"exists": False}
                    continue

                times, values = unreal.AnimationLibrary.get_float_keys(asset, stored_curve_name)
                curves[curve_name] = {"exists": True, "times": list(times), "values": list(values)}

            results.append({"asset": asset.get_path_name(), "curves": curves})

        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def replace_animation_float_curve(asset_path: str, curve_name: str, keys_json: str, dry_run: bool = True) -> str:
        """
        /**
         * 校验并原位替换动画浮点曲线
         * @param asset_path		动画序列路径
         * @param curve_name		曲线名称
         * @param keys_json		关键帧数组
         * @param dry_run		仅预检开关
         * @return			审计结果与备份路径
         */
        """
        from editor_toolset.toolsets.asset import AssetTools
        from toolset_registry.helpers import require_editable

        def fail(message: str) -> None:
            unreal.log_error("[BBB][LeftHandIKCurve] " + message)
            raise RuntimeError(message)

        if not asset_path.startswith("/Game/"):
            fail("动画路径必须位于 Game 内容目录")

        if not curve_name.strip():
            fail("曲线名称不能为空")

        try:
            keys = json.loads(keys_json)
        except Exception as error:
            fail("关键帧 JSON 无效: {}".format(error))

        if not isinstance(keys, list) or len(keys) < 2:
            fail("关键帧必须是至少包含两项的数组")

        animation = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(animation, unreal.AnimSequence):
            fail("目标必须是 AnimSequence: {}".format(asset_path))

        game_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if game_world is not None:
            fail("PIE 期间禁止修改动画曲线")

        animation_length = float(animation.get_play_length())
        if not math.isfinite(animation_length) or animation_length <= 0.0:
            fail("动画时长无效: {}".format(asset_path))

        validated_keys = []
        for item in keys:
            if not isinstance(item, dict) or "time" not in item or "value" not in item:
                fail("每个关键帧必须包含 time 与 value")

            try:
                time_seconds = float(item["time"])
                value = float(item["value"])
            except (TypeError, ValueError):
                fail("关键帧时间与数值必须是数字")

            if not math.isfinite(time_seconds) or not math.isfinite(value):
                fail("关键帧包含非有限数值")
            if time_seconds < 0.0 or time_seconds > animation_length + 0.00001:
                fail("关键帧时间超出动画范围: {}".format(time_seconds))

            validated_keys.append({"time": time_seconds, "value": value})

        validated_keys.sort(key=lambda item: item["time"])
        for index in range(1, len(validated_keys)):
            if abs(validated_keys[index]["time"] - validated_keys[index - 1]["time"]) <= 0.000001:
                fail("关键帧时间不能重复")

        library = unreal.AnimationLibrary
        float_curve_type = unreal.RawCurveTrackTypes.RCT_FLOAT
        available_curves = {
            str(name).casefold(): str(name)
            for name in library.get_animation_curve_names(animation, float_curve_type)
        }
        stored_curve_name = available_curves.get(curve_name.casefold())
        original_keys = []
        if stored_curve_name is not None:
            original_times, original_values = library.get_float_keys(animation, stored_curve_name)
            original_keys = [
                {"time": float(time_seconds), "value": float(value)}
                for time_seconds, value in zip(original_times, original_values)
            ]

        is_dirty = AssetTools.is_dirty(asset_path)
        if is_dirty:
            fail("目标动画已有未保存修改: {}".format(asset_path))

        checked_out = AssetTools.is_checked_out(asset_path)
        can_edit = AssetTools.can_edit_asset(asset_path)
        if dry_run:
            return json.dumps(
                {
                    "asset": asset_path,
                    "curveName": curve_name,
                    "storedCurveName": stored_curve_name,
                    "animationLength": animation_length,
                    "originalKeys": original_keys,
                    "requestedKeys": validated_keys,
                    "checkedOut": checked_out,
                    "canEdit": can_edit,
                    "dryRun": True,
                },
                ensure_ascii=False,
            )

        require_editable(animation)
        state = unreal.SourceControl.query_file_state(asset_path)
        writable = checked_out and can_edit
        if state.is_valid and state.is_added and state.can_edit and not state.is_checked_out_other:
            writable = True

        if not writable:
            fail("写入前必须独占签出且可编辑目标动画: {}".format(asset_path))

        package_path = animation.get_path_name().split(".", 1)[0]
        relative_package_path = package_path[len("/Game/"):].replace("/", os.sep)
        source_asset_path = os.path.join(unreal.Paths.project_content_dir(), relative_package_path + ".uasset")
        if not os.path.isfile(source_asset_path):
            fail("目标动画文件不存在: {}".format(source_asset_path))

        timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup_directory = os.path.join(
            unreal.Paths.project_saved_dir(),
            "Diagnostics",
            "LeftHandIKCurves",
            "Backups",
        )
        os.makedirs(backup_directory, exist_ok=True)

        package_name = os.path.basename(relative_package_path)
        backup_base_name = "{}_{}_{}".format(package_name, curve_name, timestamp)
        backup_asset_path = os.path.join(backup_directory, backup_base_name + ".uasset")
        backup_report_path = os.path.join(backup_directory, backup_base_name + ".json")
        shutil.copy2(source_asset_path, backup_asset_path)

        backup_report = {
            "asset": asset_path,
            "curveName": curve_name,
            "storedCurveName": stored_curve_name,
            "animationLength": animation_length,
            "originalKeys": original_keys,
            "requestedKeys": validated_keys,
            "backupAsset": backup_asset_path,
            "timestamp": timestamp,
        }
        with open(backup_report_path, "x", encoding="utf-8") as backup_file:
            json.dump(backup_report, backup_file, ensure_ascii=False, indent=4)

        curve_name_to_write = stored_curve_name or curve_name
        with unreal.ScopedEditorTransaction("替换动画浮点曲线"):
            animation.modify()
            if stored_curve_name is not None:
                library.remove_curve(animation, stored_curve_name, False)
            library.add_curve(animation, curve_name_to_write, float_curve_type, False)
            for key in validated_keys:
                library.add_float_curve_key(animation, curve_name_to_write, key["time"], key["value"])

        written_times, written_values = library.get_float_keys(animation, curve_name_to_write)
        written_keys = [
            {"time": float(time_seconds), "value": float(value)}
            for time_seconds, value in zip(written_times, written_values)
        ]
        if len(written_keys) != len(validated_keys):
            fail("曲线关键帧写入数量不匹配 备份位于 {}".format(backup_asset_path))

        for written, expected in zip(written_keys, validated_keys):
            if abs(written["time"] - expected["time"]) > 0.0001 or abs(written["value"] - expected["value"]) > 0.0001:
                fail("曲线关键帧写入校验失败 备份位于 {}".format(backup_asset_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            fail("动画曲线保存失败 备份位于 {}".format(backup_asset_path))

        saved_times, saved_values = library.get_float_keys(animation, curve_name_to_write)
        saved_keys = [
            {"time": float(time_seconds), "value": float(value)}
            for time_seconds, value in zip(saved_times, saved_values)
        ]
        if len(saved_keys) != len(validated_keys):
            fail("保存后曲线关键帧数量不匹配 备份位于 {}".format(backup_asset_path))

        for saved, expected in zip(saved_keys, validated_keys):
            if abs(saved["time"] - expected["time"]) > 0.0001 or abs(saved["value"] - expected["value"]) > 0.0001:
                fail("保存后曲线关键帧校验失败 备份位于 {}".format(backup_asset_path))

        unreal.log("[BBB][LeftHandIKCurve] 已更新 {} 的 {} 曲线".format(asset_path, curve_name_to_write))
        return json.dumps(
            {
                "asset": asset_path,
                "curveName": curve_name_to_write,
                "keys": saved_keys,
                "backupAsset": backup_asset_path,
                "backupReport": backup_report_path,
                "dryRun": False,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_instanced_struct_array(asset_path: str, struct_property: str, array_property: str, instances_json: str) -> str:
        """为资产结构体内的实例化对象数组创建真实子对象并保存"""
        from toolset_registry.helpers import require_editable

        asset = unreal.load_asset(asset_path)
        if asset is None:
            raise RuntimeError("资产不存在")
        require_editable(asset)
        descriptions = json.loads(instances_json)
        if not isinstance(descriptions, list):
            raise RuntimeError("实例配置必须为数组")

        structure = asset.get_editor_property(struct_property)
        objects = []
        for description in descriptions:
            object_class = unreal.load_class(None, description["class"])
            if object_class is None:
                raise RuntimeError("子对象类不存在")
            instance = unreal.new_object(object_class, outer=asset)
            if not unreal.ToolsetLibrary.set_object_properties(instance, json.dumps(description.get("properties", {}))):
                raise RuntimeError("子对象属性配置失败")
            objects.append(instance)

        asset.modify()
        structure.set_editor_property(array_property, objects)
        asset.set_editor_property(struct_property, structure)
        applied = asset.get_editor_property(struct_property).get_editor_property(array_property)
        if len(applied) != len(objects) or any(item is None for item in applied):
            raise RuntimeError("实例数组写回失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset):
            raise RuntimeError("资产保存失败")
        return json.dumps({"asset": asset.get_path_name(), "instances": [item.get_path_name() for item in applied]})

    @toolset_registry.tool_call
    @staticmethod
    def create_asset_with_factory(asset_path: str, asset_class_path: str, factory_class_path: str, factory_properties_json: str = "{}") -> str:
        """通过指定原生工厂创建新资产 拒绝覆盖已有资产"""
        if not asset_path.startswith("/Game/") or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("必须提供尚不存在的 Game 资产路径")
        asset_class = unreal.load_class(None, asset_class_path)
        factory_class = unreal.load_class(None, factory_class_path)
        if asset_class is None or factory_class is None:
            raise RuntimeError("资产或工厂类不存在")
        factory = unreal.new_object(factory_class)
        if not unreal.ToolsetLibrary.set_object_properties(factory, factory_properties_json):
            raise RuntimeError("工厂属性无效")
        folder, name = asset_path.rsplit("/", 1)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, asset_class, factory)
        if asset is None:
            raise RuntimeError("工厂创建失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset):
            raise RuntimeError("资产保存失败")
        return asset.get_path_name()

    @toolset_registry.tool_call
    @staticmethod
    def import_files_from_directory(source_directory: str, destination_path: str, extensions_json: str, recursive: bool = True) -> str:
        """将目录中的指定文件批量导入 Game 内容目录 保留目录结构并拒绝覆盖"""
        source_root = os.path.realpath(source_directory)
        if not os.path.isdir(source_root):
            raise RuntimeError("源目录不存在: {}".format(source_directory))

        destination_parts = destination_path.split("/")
        if not destination_path.startswith("/Game/") or any(part in {"", ".", ".."} for part in destination_parts[2:]):
            raise RuntimeError("目标必须是有效的 /Game/ 内容目录")

        extensions = json.loads(extensions_json)
        if not isinstance(extensions, list) or not extensions:
            raise RuntimeError("extensions_json 必须是非空扩展名数组")

        normalized_extensions = set()
        for extension in extensions:
            if not isinstance(extension, str) or not extension.strip():
                raise RuntimeError("扩展名必须是非空字符串")
            normalized_extension = extension.strip().lower()
            if not normalized_extension.startswith("."):
                normalized_extension = "." + normalized_extension
            if not re.fullmatch(r"\.[a-z0-9]+", normalized_extension):
                raise RuntimeError("扩展名格式无效: {}".format(extension))
            normalized_extensions.add(normalized_extension)

        editor_assets = unreal.EditorAssetLibrary
        if editor_assets.does_asset_exist(destination_path):
            raise RuntimeError("目标路径已是资产 拒绝覆盖: {}".format(destination_path))
        if editor_assets.does_directory_exist(destination_path):
            existing_assets = editor_assets.list_assets(destination_path, recursive=True, include_folder=False)
            if existing_assets:
                raise RuntimeError("目标目录已有资产 拒绝覆盖: {}".format(destination_path))

        source_files = []
        target_packages = set()
        target_directories = {destination_path}
        for current_directory, child_directories, file_names in os.walk(source_root, followlinks=False):
            child_directories.sort()
            if not recursive:
                child_directories[:] = []

            for file_name in sorted(file_names):
                source_file = os.path.join(current_directory, file_name)
                if os.path.splitext(file_name)[1].lower() not in normalized_extensions:
                    continue
                if os.path.islink(source_file) or not os.path.isfile(source_file):
                    raise RuntimeError("源文件不是普通文件: {}".format(source_file))

                relative_directory = os.path.relpath(current_directory, source_root)
                target_directory = destination_path
                if relative_directory != ".":
                    safe_directories = []
                    for source_segment in relative_directory.split(os.sep):
                        safe_segment = re.sub(r"[^A-Za-z0-9_-]+", "_", source_segment).strip("_")
                        if not safe_segment:
                            raise RuntimeError("源目录名无法转换为有效资产目录: {}".format(source_segment))
                        safe_directories.append(safe_segment)
                    target_directory = destination_path + "/" + "/".join(safe_directories)

                source_asset_name = os.path.splitext(file_name)[0]
                asset_name = re.sub(r"[^A-Za-z0-9_-]+", "_", source_asset_name).strip("_")
                if not asset_name:
                    raise RuntimeError("源文件名无法转换为有效资产名: {}".format(file_name))
                target_package = target_directory + "/" + asset_name
                if target_package.casefold() in target_packages:
                    raise RuntimeError("源目录中存在重名资产: {}".format(target_package))
                if editor_assets.does_asset_exist(target_package):
                    raise RuntimeError("目标资产已存在 拒绝覆盖: {}".format(target_package))

                target_packages.add(target_package.casefold())
                target_directories.add(target_directory)
                source_files.append((source_file, target_directory, asset_name))

        if not source_files:
            raise RuntimeError("源目录中没有匹配扩展名的文件")
        if len(source_files) > 5000:
            raise RuntimeError("单次导入文件数超过安全上限 5000")

        for directory in sorted(target_directories, key=lambda item: (item.count("/"), item)):
            created = editor_assets.make_directory(directory)
            if not created and not editor_assets.does_directory_exist(directory):
                raise RuntimeError("无法创建目标目录: {}".format(directory))

        import_tasks = []
        for source_file, target_directory, asset_name in source_files:
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", source_file)
            task.set_editor_property("destination_path", target_directory)
            task.set_editor_property("destination_name", asset_name)
            task.set_editor_property("automated", True)
            task.set_editor_property("replace_existing", False)
            task.set_editor_property("save", False)
            import_tasks.append(task)

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(import_tasks)

        imported_assets = []
        failed_sources = []
        for source_file, task in zip(source_files, import_tasks):
            objects = list(task.get_objects())
            if not objects:
                failed_sources.append(source_file[0])
                continue

            for asset in objects:
                asset_path = asset.get_path_name()
                if not asset_path.startswith(destination_path + "/"):
                    failed_sources.append(source_file[0] + " -> " + asset_path)
                    continue
                imported_assets.append(asset)

        if failed_sources:
            unreal.log_error("[BBBGenericImport] 导入结果校验失败: " + json.dumps(failed_sources, ensure_ascii=False))
            raise RuntimeError("部分源文件未生成有效目标资产 未保存导入结果: {}".format(len(failed_sources)))

        saved_paths = []
        for asset in imported_assets:
            if not editor_assets.save_loaded_asset(asset, only_if_is_dirty=False):
                unreal.log_error("[BBBGenericImport] 资产保存失败: " + asset.get_path_name())
                raise RuntimeError("资产保存失败: {}".format(asset.get_path_name()))
            saved_paths.append(asset.get_path_name())

        unreal.log("[BBBGenericImport] Saved {} assets from {} files to {}".format(
            len(saved_paths), len(source_files), destination_path))
        return json.dumps({
            "sourceDirectory": source_root,
            "destinationPath": destination_path,
            "sourceFileCount": len(source_files),
            "importedAssetCount": len(saved_paths),
            "assets": saved_paths,
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def reimport_sound_waves(source_directory: str, destination_path: str, source_suffix: str = "_Shot", recursive: bool = True) -> str:
        """将目录中的 WAV 原位重导入已有 SoundWave 并仅保存目标资产"""
        from toolset_registry.helpers import require_editable

        source_root = os.path.realpath(source_directory)
        if not os.path.isdir(source_root):
            raise RuntimeError("源目录不存在: {}".format(source_directory))

        if not destination_path.startswith("/Game/") or "." in destination_path:
            raise RuntimeError("目标必须是有效的 /Game/ 内容目录")

        if not source_suffix or not re.fullmatch(r"_[A-Za-z0-9_]+", source_suffix):
            raise RuntimeError("源文件后缀必须以一个下划线开头且仅包含字母数字和下划线")

        editor_assets = unreal.EditorAssetLibrary
        dirty_packages = {
            package.get_path_name()
            for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        }

        imports = []
        target_paths = set()
        for current_directory, child_directories, file_names in os.walk(source_root, followlinks=False):
            child_directories.sort()
            if not recursive:
                child_directories[:] = []

            for file_name in sorted(file_names):
                if not file_name.lower().endswith(source_suffix.lower() + ".wav"):
                    continue

                source_file = os.path.join(current_directory, file_name)
                if os.path.islink(source_file) or not os.path.isfile(source_file):
                    raise RuntimeError("源文件不是普通 WAV: {}".format(source_file))

                relative_directory = os.path.relpath(current_directory, source_root)
                target_directory = destination_path
                if relative_directory != ".":
                    safe_directories = []
                    for source_segment in relative_directory.split(os.sep):
                        safe_segment = re.sub(r"[^A-Za-z0-9_-]+", "_", source_segment).strip("_")
                        if not safe_segment:
                            raise RuntimeError("源目录名无法转换为有效资产目录: {}".format(source_segment))
                        safe_directories.append(safe_segment)
                    target_directory += "/" + "/".join(safe_directories)

                asset_name = file_name[:-(len(source_suffix) + 4)]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", asset_name):
                    raise RuntimeError("源文件名无法转换为已有资产名: {}".format(file_name))

                asset_path = target_directory + "/" + asset_name
                if asset_path.casefold() in target_paths:
                    raise RuntimeError("源目录中存在重名目标资产: {}".format(asset_path))
                target_paths.add(asset_path.casefold())

                asset = unreal.load_asset(asset_path)
                if not isinstance(asset, unreal.SoundWave):
                    raise RuntimeError("目标不是已有 SoundWave: {}".format(asset_path))
                if asset_path in dirty_packages:
                    raise RuntimeError("目标 SoundWave 有未保存修改: {}".format(asset_path))
                require_editable(asset)
                imports.append((source_file, asset_path, asset))

        if not imports:
            raise RuntimeError("源目录中没有匹配后缀的 WAV")
        if len(imports) > 256:
            raise RuntimeError("单次重导入数量超过安全上限 256")

        saved_assets = []
        for source_file, asset_path, original_asset in imports:
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", source_file)
            task.set_editor_property("destination_path", asset_path.rsplit("/", 1)[0])
            task.set_editor_property("destination_name", asset_path.rsplit("/", 1)[1])
            task.set_editor_property("automated", True)
            task.set_editor_property("replace_existing", True)
            task.set_editor_property("replace_existing_settings", False)
            task.set_editor_property("save", False)

            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

            imported = list(task.get_objects())
            if len(imported) != 1 or imported[0].get_path_name() != original_asset.get_path_name():
                unreal.log_error("[BBBSoundReimport] 原位重导入失败: " + asset_path)
                raise RuntimeError("重导入未返回唯一目标 SoundWave: {}".format(asset_path))

            sound_wave = imported[0]
            if not isinstance(sound_wave, unreal.SoundWave):
                unreal.log_error("[BBBSoundReimport] 重导入后的资产类型无效: " + asset_path)
                raise RuntimeError("重导入后的资产类型无效: {}".format(asset_path))

            duration = sound_wave.get_editor_property("duration")
            if duration <= 0:
                unreal.log_error("[BBBSoundReimport] 重导入后的 SoundWave 无效: " + asset_path)
                raise RuntimeError("重导入后的 SoundWave 无效: {}".format(asset_path))

            if not editor_assets.save_loaded_asset(sound_wave, only_if_is_dirty=False):
                unreal.log_error("[BBBSoundReimport] 资产保存失败: " + asset_path)
                raise RuntimeError("SoundWave 保存失败: {}".format(asset_path))

            saved_assets.append({"asset": asset_path, "duration": duration, "source": source_file})

        unreal.log("[BBBSoundReimport] Saved {} existing SoundWave assets".format(len(saved_assets)))
        return json.dumps({"savedCount": len(saved_assets), "assets": saved_assets}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def import_animation_fbx(source_file: str, asset_path: str, skeleton_path: str) -> str:
        """从单动作 FBX 精确覆盖已签出的动画 保持骨骼和资产路径不变"""
        from toolset_registry.helpers import require_editable
        from editor_toolset.toolsets.asset import AssetTools

        if not os.path.isfile(source_file) or not source_file.lower().endswith(".fbx"):
            raise RuntimeError("必须提供存在的 FBX 文件")

        if not asset_path.startswith("/Game/") or "." in asset_path:
            raise RuntimeError("必须提供精确的 Game 动画包路径")

        asset = unreal.load_asset(asset_path)
        skeleton = unreal.load_asset(skeleton_path)
        if not isinstance(asset, unreal.AnimSequence) or not isinstance(skeleton, unreal.Skeleton):
            raise RuntimeError("目标必须是已有动画和骨骼")

        if asset.get_editor_property("skeleton") != skeleton:
            raise RuntimeError("目标动画骨骼与指定骨骼不一致")

        require_editable(asset)
        if not AssetTools.is_checked_out(asset_path):
            raise RuntimeError("覆盖前必须独占签出目标动画")

        if asset_path in {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}:
            raise RuntimeError("目标动画存在未保存修改")

        options = unreal.FbxImportUI()
        options.set_editor_property("automated_import_should_detect_type", False)
        options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
        options.set_editor_property("original_import_type", unreal.FBXImportType.FBXIT_ANIMATION)
        options.set_editor_property("import_mesh", False)
        options.set_editor_property("import_animations", True)
        options.set_editor_property("import_materials", False)
        options.set_editor_property("import_textures", False)
        options.set_editor_property("skeleton", skeleton)
        options.anim_sequence_import_data.set_editor_property("use_default_sample_rate", True)

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source_file)
        task.set_editor_property("destination_path", asset_path.rsplit("/", 1)[0])
        task.set_editor_property("destination_name", asset_path.rsplit("/", 1)[1])
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", False)
        task.set_editor_property("factory", unreal.FbxFactory())
        task.set_editor_property("options", options)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

        imported = list(task.get_objects())
        if len(imported) != 1 or imported[0].get_path_name() != asset.get_path_name():
            raise RuntimeError("导入未返回唯一目标动画 禁止保存")

        animation = imported[0]
        if animation.get_editor_property("skeleton") != skeleton or animation.get_play_length() <= 0:
            raise RuntimeError("导入动画的骨骼或时长无效 禁止保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, only_if_is_dirty=False):
            raise RuntimeError("动画保存失败")

        unreal.log("[BBBAnimationImport] Saved " + asset_path)
        return json.dumps({"asset": animation.get_path_name(), "length": animation.get_play_length(),
            "skeleton": skeleton.get_path_name(), "source": source_file}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def capture_editor_screenshot(widget_ref: str, file_name: str) -> str:
        """通过官方 Slate 截图保存指定编辑器窗口或控件 不切换焦点 不发送输入"""
        if not widget_ref:
            raise RuntimeError("必须先通过官方 Slate Snapshot 获取明确的窗口或控件引用")

        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.png", file_name, re.IGNORECASE):
            raise RuntimeError("文件名必须为不包含目录的 PNG 名称")

        output_directory = os.path.realpath(os.path.join(unreal.Paths.project_saved_dir(), "Screenshots", "MCP"))
        output_path = os.path.realpath(os.path.join(output_directory, file_name))
        if os.path.commonpath([output_directory, output_path]) != output_directory:
            raise RuntimeError("截图输出超出指定目录")

        if os.path.exists(output_path):
            raise RuntimeError("截图文件已存在 请使用新的文件名")

        toolset_class = unreal.load_class(None, "/Script/SlateInspectorToolset.SlateInspectorToolset")
        if toolset_class is None:
            raise RuntimeError("请在宿主启动时启用官方 SlateInspectorToolset 插件")

        toolset = unreal.get_default_object(toolset_class)
        captured = toolset.call_method("Screenshot", (widget_ref,))
        encoded = captured.get_editor_property("data")
        if not encoded:
            raise RuntimeError("截图失败 请检查窗口引用及真实渲染宿主 NullRHI 不支持截图")

        pixels = base64.b64decode(encoded, validate=True)
        if len(pixels) < 24 or pixels[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("官方截图未返回有效 PNG")

        width, height = struct.unpack(">II", pixels[16:24])
        if width <= 0 or height <= 0:
            raise RuntimeError("截图尺寸无效")

        os.makedirs(output_directory, exist_ok=True)
        with open(output_path, "xb") as output_file:
            output_file.write(pixels)

        return json.dumps({"path": output_path, "width": width, "height": height, "widgetRef": widget_ref}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def resize_pie_window(width: int, height: int) -> str:
        """仅调整唯一浮动 PIE 窗口尺寸 不修改编辑器主窗口和桌面分辨率"""
        if type(width) is not int or type(height) is not int:
            raise RuntimeError("窗口宽高必须是整数")

        if width < 320 or height < 320 or width > 4096 or height > 4096 or width * height > 8388608:
            raise RuntimeError("窗口尺寸超出允许范围")

        result = json.loads(unreal.BBBPIEWindowEditorLibrary.resize_pie_window(width, height))
        if not result.get("success"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))

        return json.dumps(result, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def render_asset_thumbnails(requests_json: str) -> str:
        """按显式源网格与目标纹理列表生成真实部件缩略图 每项保存并返回结果"""
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("请先停止 PIE 再生成并导入缩略图")

        requests = json.loads(requests_json)
        if not isinstance(requests, list) or not requests or len(requests) > 100:
            raise RuntimeError("请求必须是非空列表 且不超过一百项")

        results = []
        for request in requests:
            source = str(request["source"])
            destination = str(request["destination"])
            if not source.startswith("/Game/") or not destination.startswith("/Game/") or "." in destination:
                raise RuntimeError("源资产与目标包必须位于 Game 目录")

            exists = unreal.EditorAssetLibrary.does_asset_exist(destination)
            diagnostic_only = bool(request.get("diagnostic_only", False))
            if exists and not diagnostic_only and not unreal.EditorAssetLibrary.checkout_asset(destination):
                results.append({"destination": destination, "error": "独占签出失败"})
                continue

            file_name = destination.rsplit("/", 1)[1] + ".png"
            image_path = unreal.BBBAssetThumbnailEditorLibrary.render_mesh_thumbnail(
                source, file_name, float(request.get("yaw", 75.0)))
            if not image_path:
                results.append({"destination": destination, "error": "网格渲染失败"})
                continue

            if diagnostic_only:
                results.append({"source": source, "image": image_path, "saved": False})
                continue

            task = unreal.AssetImportTask()
            task.filename = image_path
            task.destination_path = destination.rsplit("/", 1)[0]
            task.destination_name = destination.rsplit("/", 1)[1]
            task.automated = True
            task.replace_existing = exists
            task.save = False
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            if not task.imported_object_paths:
                results.append({"destination": destination, "error": "纹理导入未返回结果"})
                continue

            texture = unreal.EditorAssetLibrary.load_asset(destination)
            if not isinstance(texture, unreal.Texture2D):
                results.append({"destination": destination, "error": "纹理导入失败"})
                continue

            texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_EDITOR_ICON)
            texture.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
            texture.set_editor_property("never_stream", True)
            texture.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
            saved = unreal.EditorAssetLibrary.save_loaded_asset(texture, False)
            results.append({"destination": destination, "source": source, "image": image_path, "saved": saved})

        return json.dumps(results, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_notifies(asset_path: str) -> str:
        """只读返回动画序列或蒙太奇的通知类 时间与所属轨道"""
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.AnimSequenceBase):
            raise RuntimeError("资产不是动画序列或蒙太奇: {}".format(asset_path))

        library = unreal.AnimationLibrary
        tracks = list(library.get_animation_notify_track_names(asset))
        results = []
        for track in tracks:
            for event in library.get_animation_notify_events_for_track(asset, track):
                notify = event.get_editor_property("notify")
                state = event.get_editor_property("notify_state_class")
                instance = notify if notify is not None else state
                results.append({
                    "track": str(track),
                    "name": str(event.get_editor_property("notify_name")),
                    "classPath": instance.get_class().get_path_name() if instance else None,
                    "time": library.get_anim_notify_event_trigger_time(event),
                    "duration": library.get_anim_notify_event_duration(event),
                    "isState": state is not None,
                })

        return json.dumps({"asset": asset_path, "length": asset.get_play_length(),
            "tracks": [str(track) for track in tracks], "events": results}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_notify_properties(asset_path: str, class_path: str, property_names: list[str]) -> str:
        """只读返回动画中唯一通知实例的指定可编辑属性"""
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.AnimSequenceBase) or not property_names:
            raise RuntimeError("动画资产或属性名称无效")

        matches = []
        for event in unreal.AnimationLibrary.get_animation_notify_events(asset):
            instance = event.get_editor_property("notify") or event.get_editor_property("notify_state_class")
            if instance is not None and instance.get_class().get_path_name() == class_path:
                matches.append(instance)
        if len(matches) != 1:
            raise RuntimeError("目标通知实例必须恰好出现一次")

        properties = {}
        for name in property_names:
            value = matches[0].get_editor_property(name)
            properties[name] = value.export_text() if isinstance(value, unreal.Transform) else _serialize_value(value)
        return json.dumps({"asset": asset_path, "class": class_path,
            "properties": properties}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def remove_empty_animation_notify_track(asset_path: str, track_name: str) -> str:
        """仅删除动画序列或蒙太奇中已清空的通知轨道"""
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止删除通知轨道")

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.AnimSequenceBase) or not track_name.strip():
            raise RuntimeError("动画资产或通知轨道无效")

        require_editable(asset)
        library = unreal.AnimationLibrary
        if not library.is_valid_anim_notify_track_name(asset, track_name):
            raise RuntimeError("通知轨道不存在: {}".format(track_name))

        if library.get_animation_notify_events_for_track(asset, track_name):
            raise RuntimeError("通知轨道非空 禁止删除: {}".format(track_name))

        with unreal.ScopedEditorTransaction("删除空动画通知轨道"):
            asset.modify()
            library.remove_animation_notify_track(asset, track_name)

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("保存通知轨道删除结果失败")

        return BBBGenericEditorToolset.inspect_animation_notifies(asset_path)

    @toolset_registry.tool_call
    @staticmethod
    def resave_asset(asset_path: str) -> str:
        """按当前类定义重新序列化已经独占签出的资产"""
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止重新保存资产")

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if asset is None:
            raise RuntimeError("资产不存在: {}".format(asset_path))
        require_editable(asset)
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("重新保存资产失败")

        return json.dumps({"asset": asset_path, "class": asset.get_class().get_path_name()}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_animation_montage_segments(asset_path: str) -> str:
        """
        /**
         * 只读返回蒙太奇插槽中引用的动画片段
         * @param asset_path	蒙太奇路径
         * @return 插槽与片段资产列表
         */
        """
        montage = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(montage, unreal.AnimMontage):
            raise RuntimeError("资产不是动画蒙太奇")

        tracks = []
        for slot in montage.get_editor_property("slot_anim_tracks"):
            segments = []
            for segment in slot.get_editor_property("anim_track").get_editor_property("anim_segments"):
                reference = segment.get_editor_property("anim_reference")
                segments.append({
                    "animation": reference.get_path_name() if reference else None,
                    "start": segment.get_editor_property("start_pos"),
                    "animationStart": segment.get_editor_property("anim_start_time"),
                    "animationEnd": segment.get_editor_property("anim_end_time"),
                    "playRate": segment.get_editor_property("anim_play_rate"),
                })
            tracks.append({"slot": str(slot.get_editor_property("slot_name")), "segments": segments})

        return json.dumps({"asset": asset_path, "length": montage.get_play_length(),
            "tracks": tracks}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def add_animation_notify_events(asset_path: str, track_name: str, events_json: str) -> str:
        """
        /**
         * 向动画序列或蒙太奇轨道添加单次通知并保留全部已有事件
         * @param asset_path	动画资产路径
         * @param track_name	通知轨道名称
         * @param events_json	通知类路径与触发时间数组
         * @return 保存后的完整通知列表
         */
        """
        from toolset_registry.helpers import require_editable

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.AnimSequenceBase) or not track_name.strip():
            raise RuntimeError("动画资产或通知轨道无效")
        require_editable(asset)

        events = json.loads(events_json)
        if not isinstance(events, list) or not events:
            raise RuntimeError("新增通知配置必须是非空数组")

        library = unreal.AnimationLibrary
        existing = list(library.get_animation_notify_events(asset))
        validated = []
        for event in events:
            notify_class = unreal.load_class(None, event["class_path"])
            time_seconds = float(event["time"])
            if notify_class is None or not unreal.MathLibrary.class_is_child_of(notify_class, unreal.AnimNotify.static_class()):
                raise RuntimeError("通知类不存在或不是单次通知")
            if not math.isfinite(time_seconds) or time_seconds < 0.0 or time_seconds >= asset.get_play_length():
                raise RuntimeError("通知时间超出动画范围")
            for previous in existing:
                previous_notify = previous.get_editor_property("notify")
                previous_time = library.get_anim_notify_event_trigger_time(previous)
                if previous_notify is not None and previous_notify.get_class() == notify_class and abs(previous_time - time_seconds) < 0.001:
                    raise RuntimeError("通知类和触发时间已经存在")
            validated.append((notify_class, time_seconds))

        with unreal.ScopedEditorTransaction("添加动画通知事件"):
            asset.modify()
            if not library.is_valid_anim_notify_track_name(asset, track_name):
                library.add_animation_notify_track(asset, track_name)
            for notify_class, time_seconds in validated:
                created = library.add_animation_notify_event(asset, track_name, time_seconds, notify_class)
                if created is None:
                    raise RuntimeError("创建动画通知失败")

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("保存动画通知失败")
        return BBBGenericEditorToolset.inspect_animation_notifies(asset_path)

    @toolset_registry.tool_call
    @staticmethod
    def replace_animation_notify_track(asset_path: str, track_name: str, events_json: str) -> str:
        """校验后仅替换指定通知轨道 保留其它轨道并保存动画资产"""
        from toolset_registry.helpers import require_editable

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.AnimSequenceBase) or not track_name.strip():
            raise RuntimeError("动画资产或通知轨道无效")
        require_editable(asset)

        events = json.loads(events_json)
        if not isinstance(events, list):
            raise RuntimeError("通知配置必须是数组")

        length = asset.get_play_length()
        validated = []
        for event in events:
            class_path = event["class_path"]
            notify_class = unreal.load_class(None, class_path)
            if notify_class is None:
                raise RuntimeError("通知类不存在: {}".format(class_path))
            is_state = unreal.MathLibrary.class_is_child_of(notify_class, unreal.AnimNotifyState.static_class())
            is_notify = unreal.MathLibrary.class_is_child_of(notify_class, unreal.AnimNotify.static_class())
            start = float(event["time"])
            duration = float(event.get("duration", 0.0))
            if not (is_state or is_notify) or not math.isfinite(start) or not math.isfinite(duration):
                raise RuntimeError("通知类型或时间无效")
            if start < 0.0 or start >= length or duration < 0.0 or start + duration > length + 0.00001:
                raise RuntimeError("通知超出动画时间范围")
            if is_state and duration <= 0.0:
                raise RuntimeError("通知状态必须指定正的持续时间")
            if is_notify and duration != 0.0:
                raise RuntimeError("单次通知不能指定持续时间")
            properties = event.get("properties", {})
            if not isinstance(properties, dict):
                raise RuntimeError("通知实例属性必须是对象")
            validated.append((notify_class, start, duration, is_state, properties))

        library = unreal.AnimationLibrary
        with unreal.ScopedEditorTransaction("配置动画通知轨道"):
            asset.modify()
            if library.is_valid_anim_notify_track_name(asset, track_name):
                library.remove_animation_notify_events_by_track(asset, track_name)
            if not library.is_valid_anim_notify_track_name(asset, track_name):
                library.add_animation_notify_track(asset, track_name)
            for notify_class, start, duration, is_state, properties in validated:
                if is_state:
                    created = library.add_animation_notify_state_event(asset, track_name, start, duration, notify_class)
                if not is_state:
                    created = library.add_animation_notify_event(asset, track_name, start, notify_class)
                if created is None:
                    raise RuntimeError("创建通知失败 未保存资产 请检查当前脏包")
                instance = created
                for property_name, requested_value in properties.items():
                    current_value = instance.get_editor_property(property_name)
                    if isinstance(current_value, unreal.Transform):
                        location = requested_value.get("location")
                        rotation = requested_value.get("rotation")
                        quaternion = requested_value.get("rotation_quaternion")
                        scale = requested_value.get("scale", [1.0, 1.0, 1.0])
                        if not isinstance(location, list) or len(location) != 3:
                            raise RuntimeError("通知实例变换必须提供位置旋转缩放数组")
                        if not isinstance(scale, list) or len(scale) != 3:
                            raise RuntimeError("通知实例变换缩放必须是三个数值")
                        if quaternion is not None:
                            if not isinstance(quaternion, list) or len(quaternion) != 4:
                                raise RuntimeError("通知实例四元数必须是四个数值")
                            rotation_value = unreal.Quat(*[float(value) for value in quaternion]).rotator()
                            rotation = [rotation_value.pitch, rotation_value.yaw, rotation_value.roll]
                        if not isinstance(rotation, list) or len(rotation) != 3:
                            raise RuntimeError("通知实例旋转必须是三个数值")
                        numbers = [float(value) for item in (location, rotation, scale) for value in item]
                        if not all(math.isfinite(value) for value in numbers):
                            raise RuntimeError("通知实例变换包含无效数值")
                        requested_value = unreal.Transform(
                            location=unreal.Vector(*numbers[0:3]),
                            rotation=unreal.Rotator(pitch=numbers[3], yaw=numbers[4], roll=numbers[5]),
                            scale=unreal.Vector(*numbers[6:9]),
                        )
                    _apply_editor_property(instance, property_name, requested_value)

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("通知资产保存失败")
        return BBBGenericEditorToolset.inspect_animation_notifies(asset_path)

    @toolset_registry.tool_call
    @staticmethod
    def move_animation_notify_event(asset_path: str, notify_class_path: str, time_seconds: float) -> str:
        """
        /**
         * 移动唯一的单次动画通知并保留其他通知
         * @param asset_path	动画资产路径
         * @param notify_class_path	通知类路径
         * @param time_seconds	新的触发时间
         * @return 保存后的完整通知列表
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止移动动画通知")

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        notify_class = unreal.load_class(None, notify_class_path)
        if not isinstance(asset, unreal.AnimSequenceBase) or notify_class is None:
            raise RuntimeError("动画资产或通知类无效")
        if not unreal.MathLibrary.class_is_child_of(notify_class, unreal.AnimNotify.static_class()):
            raise RuntimeError("目标类不是单次动画通知")
        if not math.isfinite(time_seconds) or time_seconds < 0.0 or time_seconds >= asset.get_play_length():
            raise RuntimeError("通知时间超出动画范围")
        require_editable(asset)

        library = unreal.AnimationLibrary
        matches = []
        for event in library.get_animation_notify_events(asset):
            notify = event.get_editor_property("notify")
            if notify is not None and notify.get_class() == notify_class:
                matches.append(event)

        if len(matches) != 1:
            raise RuntimeError("目标通知必须在资产中恰好出现一次")

        event = matches[0]
        notify_name = str(event.get_editor_property("notify_name"))
        same_name = [item for item in library.get_animation_notify_events(asset)
                     if str(item.get_editor_property("notify_name")) == notify_name]
        if len(same_name) != 1:
            raise RuntimeError("通知名称不唯一 无法安全移动")

        track_names = []
        for track in library.get_animation_notify_track_names(asset):
            track_events = library.get_animation_notify_events_for_track(asset, track)
            if any(item.get_editor_property("notify") == event.get_editor_property("notify")
                   for item in track_events):
                track_names.append(str(track))
        if len(track_names) != 1:
            raise RuntimeError("无法确定目标通知所属的唯一轨道")

        track_name = track_names[0]
        with unreal.ScopedEditorTransaction("移动动画通知"):
            asset.modify()
            removed = library.remove_animation_notify_events_by_name(asset, notify_name)
            if removed != 1:
                raise RuntimeError("移除原通知失败 请检查当前脏包")
            created = library.add_animation_notify_event(asset, track_name, time_seconds, notify_class)
            if created is None:
                raise RuntimeError("在目标帧创建通知失败 请检查当前脏包")

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("保存动画通知失败")
        return BBBGenericEditorToolset.inspect_animation_notifies(asset_path)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_player_control(player_index: int = 0) -> str:
        """只读检查 PIE 玩家控制器与组件的注册和更新状态"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 尚未运行")

        controller = unreal.GameplayStatics.get_player_controller(world, player_index)
        if controller is None:
            raise RuntimeError("玩家控制器不存在")

        input_properties = {}
        input_errors = {}
        for name in ("DefaultMappingContext", "show_mouse_cursor"):
            try:
                input_properties[name] = _serialize_value(controller.get_editor_property(name))
            except Exception as error:
                input_errors[name] = str(error)

        manager = unreal.GameplayStatics.get_player_camera_manager(world, player_index)
        camera = {}
        if manager is not None:
            camera["location"] = _serialize_value(manager.get_camera_location())
            camera["rotation"] = _serialize_value(manager.get_camera_rotation())
            camera["fov"] = manager.get_fov_angle()
        target = controller.get_view_target()
        if target is not None:
            camera["arms"] = [{
                "path": arm.get_path_name(),
                "length": arm.get_editor_property("target_arm_length"),
                "collisionEnabled": arm.get_editor_property("do_collision_test"),
                "collisionFixApplied": arm.is_collision_fix_applied(),
                "unfixedPosition": _serialize_value(arm.get_unfixed_camera_position()),
            } for arm in target.get_components_by_class(unreal.SpringArmComponent)]

        pawn = controller.get_controlled_pawn()
        actors = [controller]
        if pawn is not None:
            actors.append(pawn)

        results = []
        for actor in actors:
            components = []
            for component in actor.get_components_by_class(unreal.ActorComponent):
                components.append({
                    "path": component.get_path_name(),
                    "class": component.get_class().get_path_name(),
                    "active": component.is_active(),
                    "tickEnabled": component.is_component_tick_enabled(),
                })
            results.append({
                "path": actor.get_path_name(),
                "tickEnabled": actor.is_actor_tick_enabled(),
                "components": components,
            })

        return json.dumps({
            "world": world.get_path_name(),
            "localController": controller.is_local_controller(),
            "localPawn": pawn.is_locally_controlled() if pawn else False,
            "viewTarget": _serialize_value(controller.get_view_target()),
            "controlRotation": str(controller.get_control_rotation()),
            "inputProperties": input_properties,
            "camera": camera,
            "inputPropertyErrors": input_errors,
            "actors": results,
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def invoke_pie_actor_function(actor_path: str, function_name: str, arguments_json: str = "[]") -> str:
        """调用当前 PIE 世界中指定 Actor 的反射函数 不接受编辑器世界对象"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        actor = unreal.find_object(None, actor_path)
        arguments = json.loads(arguments_json)
        if world is None or not isinstance(actor, unreal.Actor) or actor.get_world() != world:
            raise RuntimeError("目标必须是当前 PIE 世界中已存在的 Actor")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name) or not isinstance(arguments, list):
            raise RuntimeError("函数名或位置参数数组无效")
        result = actor.call_method(function_name, tuple(arguments))
        return json.dumps({"actor": actor_path, "function": function_name, "result": _serialize_value(result)}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def capture_pie_player_view(file_name: str, width: int = 1280, height: int = 720, player_index: int = 0) -> str:
        """使用玩家实际视点与视野渲染截图 不包含界面 不修改资产"""
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.png", file_name, re.IGNORECASE):
            raise RuntimeError("文件名必须为不包含目录的 PNG 名称")
        if width < 64 or height < 64 or width > 2048 or height > 2048:
            raise RuntimeError("截图尺寸必须在六十四至二千零四十八之间")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 尚未运行")
        manager = unreal.GameplayStatics.get_player_camera_manager(world, player_index)
        if manager is None:
            raise RuntimeError("玩家相机不存在")
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "PlayerView"))
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            raise RuntimeError("截图文件已存在 请使用新的文件名")
        location = manager.get_camera_location()
        rotation = manager.get_camera_rotation()
        fov = manager.get_fov_angle()
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
            world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
        if actor is None:
            raise RuntimeError("无法创建临时相机截图组件")
        try:
            target = unreal.RenderingLibrary.create_render_target2d(
                world, width, height, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            component = actor.capture_component2d
            component.set_editor_property("texture_target", target)
            component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            component.set_editor_property("fov_angle", fov)
            component.capture_scene()
            os.makedirs(directory, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, target, directory, file_name)
            if not os.path.isfile(path):
                raise RuntimeError("截图未生成 请使用启用渲染的编辑器")
            return json.dumps({"imagePath": path, "location": _serialize_value(location),
                "rotation": _serialize_value(rotation), "fov": fov}, ensure_ascii=False)
        finally:
            actor.destroy_actor()

    @toolset_registry.tool_call
    @staticmethod
    def export_pie_render_target(target_path: str, file_name: str) -> str:
        """导出当前 PIE 本地玩家持有的临时渲染目标"""
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.png", file_name, re.IGNORECASE):
            raise RuntimeError("文件名必须为不包含目录的 PNG 名称")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 尚未运行")

        target = unreal.find_object(None, target_path)
        if not isinstance(target, unreal.TextureRenderTarget2D):
            raise RuntimeError("目标不是已加载的渲染目标")
        if target.get_editor_property("render_target_format") != unreal.TextureRenderTargetFormat.RTF_RGBA8:
            raise RuntimeError("仅支持 RTF_RGBA8 目标以确保导出文件确实为 PNG")

        owner = target.get_outer()
        while owner is not None and not isinstance(owner, unreal.LocalPlayer):
            owner = owner.get_outer()
        if owner is None:
            raise RuntimeError("目标不属于本地玩家")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "PreviewTarget"))
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            raise RuntimeError("截图文件已存在 请使用新的文件名")

        os.makedirs(directory, exist_ok=True)
        unreal.RenderingLibrary.export_render_target(world, target, directory, file_name)
        if not os.path.isfile(path):
            raise RuntimeError("截图未生成 请使用启用渲染的编辑器")

        return json.dumps({
            "imagePath": path,
            "target": target_path,
            "width": target.get_editor_property("size_x"),
            "height": target.get_editor_property("size_y"),
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def duplicate_loaded_actors_to_current_level(actor_paths: list[str]) -> str:
        """将已加载关卡的指定对象独立复制到当前关卡"""
        if not actor_paths:
            raise RuntimeError("对象路径不能为空")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world is None:
            raise RuntimeError("当前编辑器世界不可用")

        actors = []
        for actor_path in actor_paths:
            actor = unreal.find_object(None, actor_path)
            if not isinstance(actor, unreal.Actor) or not unreal.SystemLibrary.is_valid(actor):
                raise RuntimeError("源对象未加载或无效: {}".format(actor_path))

            if actor.get_world() == world:
                raise RuntimeError("源对象已经位于当前关卡: {}".format(actor_path))

            actors.append(actor)

        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        duplicated = subsystem.duplicate_actors(actors, world, unreal.Vector(0.0, 0.0, 0.0))
        if len(duplicated) != len(actors):
            raise RuntimeError("对象复制数量不符 预期 {} 实际 {}".format(len(actors), len(duplicated)))

        return json.dumps(
            {"duplicated": [actor.get_path_name() for actor in duplicated]},
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def refresh_material_instances(asset_paths: list[str]) -> str:
        """刷新材质实例缓存并强制保存指定资产"""
        if not asset_paths:
            raise RuntimeError("资产路径不能为空")

        results = []
        for asset_path in asset_paths:
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if not isinstance(asset, unreal.MaterialInstanceConstant):
                raise RuntimeError("资产不是材质实例: {}".format(asset_path))

            unreal.MaterialEditingLibrary.update_material_instance(asset)
            saved = unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)
            if not saved:
                raise RuntimeError("材质实例保存失败: {}".format(asset_path))

            results.append(asset.get_path_name())

        return json.dumps({"refreshed": results}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_dirty_packages() -> str:
        """只读列出未保存的内容包和关卡包，供编辑器生命周期操作前检查"""
        packages = list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
        packages.extend(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
        return json.dumps(sorted({package.get_path_name() for package in packages}), ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def reload_assets_from_disk(asset_paths: list[str], discard_dirty_packages: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 从磁盘重载显式资产 仅允许丢弃逐项声明的未保存内容包
         * @param asset_paths			资产包路径 不接受目录或地图
         * @param discard_dirty_packages	明确允许丢弃的脏包路径 默认应传空数组
         * @param dry_run				只预检而不执行重载
         * @return 预检目标 重载结果与剩余脏包 不执行保存或版本控制操作
         */
        """
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("运行测试期间拒绝重载资产")

        if not asset_paths or len(asset_paths) > 64 or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("资产列表必须包含一至六十四个不重复包路径")

        permitted = set(discard_dirty_packages)
        if not permitted.issubset(set(asset_paths)):
            raise RuntimeError("丢弃列表必须是目标资产包路径的子集")

        packages = []
        for path in asset_paths:
            if not path.startswith("/Game/") or "." in path or ".." in path or ":" in path:
                raise RuntimeError("只接受精确 Game 内容包路径: " + path)

            filename = os.path.join(unreal.Paths.project_content_dir(), path[len("/Game/"):] + ".uasset")
            if not os.path.isfile(filename):
                raise RuntimeError("磁盘上不存在已保存的内容资产: " + path)

            asset = unreal.EditorAssetLibrary.load_asset(path)
            if asset is None:
                empty_package = unreal.find_object(None, path, type=unreal.Package, follow_redirectors=False)
                if empty_package is None or path not in permitted:
                    raise RuntimeError("目标未加载或没有显式允许重载空包: " + path)
                if any(obj != empty_package and obj.get_outermost() == empty_package for obj in unreal.ObjectIterator()):
                    raise RuntimeError("加载失败的包仍含对象 拒绝按空包重载: " + path)
                packages.append(empty_package)
                continue
            if asset is None or isinstance(asset, unreal.World):
                raise RuntimeError("目标不存在或属于地图: " + path)

            package = asset.get_outer()
            if not isinstance(package, unreal.Package) or package.get_path_name() != path:
                raise RuntimeError("目标不是资产直属包: " + path)

            packages.append(package)

        dirty_before = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        blocked = (set(asset_paths) & dirty_before) - permitted
        if blocked:
            raise RuntimeError("存在未授权丢弃的脏包: " + ", ".join(sorted(blocked)))

        report = {"dry_run": dry_run, "targets": list(asset_paths), "discarding": sorted(set(asset_paths) & dirty_before)}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        unreal.log_warning("[BBBAssetReload] 显式重载内容包: " + ", ".join(asset_paths))
        any_reloaded, error_message = unreal.EditorLoadingAndSavingUtils.reload_packages(
            packages,
            unreal.ReloadPackagesInteractionMode.ASSUME_POSITIVE,
        )
        dirty_after = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        remaining = sorted(set(asset_paths) & dirty_after)
        report.update({"reloaded": bool(any_reloaded), "error": str(error_message), "remaining_dirty_targets": remaining})
        if not any_reloaded or str(error_message) or remaining:
            unreal.log_error("[BBBAssetReload] 重载未完整通过: " + json.dumps(report, ensure_ascii=False))
            raise RuntimeError(json.dumps(report, ensure_ascii=False))

        unreal.log("[BBBAssetReload] 全部目标已重载且无脏标记")
        return json.dumps(report, ensure_ascii=False)


    @toolset_registry.tool_call
    @staticmethod
    def inspect_asset_properties(
        asset_paths: list[str],
        property_names: list[str],
    ) -> str:
        """只读读取任意 UE 资产的类型、路径和指定编辑器属性"""
        if not asset_paths:
            raise RuntimeError("资产路径不能为空")

        requested_properties = [str(name) for name in property_names]
        results = []
        for asset_path in asset_paths:
            if not asset_path:
                raise RuntimeError("资产路径不能包含空值")

            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if asset is None:
                raise RuntimeError("资产不存在: {}".format(asset_path))

            properties = {}
            property_errors = {}
            for property_name in requested_properties:
                if not property_name:
                    property_errors["<empty>"] = "属性名不能为空"
                    continue

                try:
                    value = asset.get_editor_property(property_name)
                    properties[property_name] = _serialize_value(value)
                except Exception as error:
                    property_errors[property_name] = str(error)

            results.append(
                {
                    "assetPath": asset.get_path_name(),
                    "classPath": asset.get_class().get_path_name(),
                    "properties": properties,
                    "propertyErrors": property_errors,
                }
            )

        return json.dumps(
            {
                "assets": results,
                "propertyNames": requested_properties,
                "readOnly": True,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_asset_object_property(asset_path: str, property_name: str, object_path: str) -> str:
        """
        /**
         * 为已签出的资产设置单个对象引用属性
         * @param asset_path	目标资产路径
         * @param property_name	目标属性名称
         * @param object_path	引用对象路径
         * @return 保存后的属性值
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改资产引用")

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        target = unreal.EditorAssetLibrary.load_asset(object_path)
        if asset is None or target is None or not property_name:
            raise RuntimeError("目标资产 引用对象或属性名称无效")
        require_editable(asset)

        current = asset.get_editor_property(property_name)
        if current is not None and not isinstance(current, unreal.Object):
            raise RuntimeError("目标属性不是对象引用")

        with unreal.ScopedEditorTransaction("设置资产对象引用"):
            asset.modify()
            asset.set_editor_property(property_name, target)

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("保存资产对象引用失败")
        value = asset.get_editor_property(property_name)
        return json.dumps({"asset": asset_path, "property": property_name,
            "value": value.get_path_name() if value else None}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def set_asset_transform_property(asset_path: str, property_name: str, transform_json: str) -> str:
        """
        /**
         * 为已签出的资产设置单个变换属性
         * @param asset_path	目标资产路径
         * @param property_name	变换属性名称
         * @param transform_json	位置旋转和缩放数组
         * @return 保存后的变换文本
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改资产变换")

        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if asset is None or not property_name:
            raise RuntimeError("目标资产或属性名称无效")
        require_editable(asset)

        current = asset.get_editor_property(property_name)
        if not isinstance(current, unreal.Transform):
            raise RuntimeError("目标属性不是变换")

        values = json.loads(transform_json)
        location = values.get("location")
        rotation = values.get("rotation")
        scale = values.get("scale", [1.0, 1.0, 1.0])
        if any(not isinstance(item, list) or len(item) != 3 for item in (location, rotation, scale)):
            raise RuntimeError("变换必须提供三个长度为三的数组")

        components = [float(value) for item in (location, rotation, scale) for value in item]
        if not all(math.isfinite(value) for value in components):
            raise RuntimeError("变换包含无效数值")
        if any(value <= 0.0 for value in components[6:9]):
            raise RuntimeError("变换缩放必须为正数")

        transform = unreal.Transform(
            location=unreal.Vector(*components[0:3]),
            rotation=unreal.Rotator(
                pitch=components[3],
                yaw=components[4],
                roll=components[5],
            ),
            scale=unreal.Vector(*components[6:9]),
        )
        with unreal.ScopedEditorTransaction("设置资产变换属性"):
            asset.modify()
            asset.set_editor_property(property_name, transform)

        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("保存资产变换失败")
        saved = asset.get_editor_property(property_name)
        if not isinstance(saved, unreal.Transform):
            raise RuntimeError("保存后变换属性无效")
        return json.dumps({"asset": asset_path, "property": property_name,
            "value": saved.export_text()}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_static_mesh_bounds(asset_path: str) -> str:
        """
        /**
         * 只读返回静态网格的局部包围盒
         * @param asset_path	静态网格资产路径
         * @return 网格包围盒
         */
        """
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.StaticMesh):
            raise RuntimeError("资产不是静态网格")

        bounds = asset.get_bounds()
        return json.dumps({
            "asset": asset_path,
            "origin": list(bounds.origin.to_tuple()),
            "extent": list(bounds.box_extent.to_tuple()),
        }, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_hand_attachments(bone_names: list[str]) -> str:
        """
        /**
         * 只读检查本地角色手部骨骼和附着静态网格
         * @param bone_names	需要读取的手部骨骼名称
         * @return 骨骼与附着网格的世界变换
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("PIE 尚未运行")

        pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
        if pawn is None or not bone_names:
            raise RuntimeError("本地角色或骨骼名称无效")

        meshes = [component for component in pawn.get_components_by_class(unreal.SkeletalMeshComponent)
                  if component.get_name() == "CharacterMesh0"]
        hand_mesh = meshes[0] if len(meshes) == 1 else None
        if hand_mesh is None or any(hand_mesh.get_bone_index(name) < 0 for name in bone_names):
            raise RuntimeError("角色主网格缺少指定手部骨骼")
        bones = {name: hand_mesh.get_socket_transform(name).export_text() for name in bone_names}
        attachments = []
        for component in hand_mesh.get_children_components(True):
            if not isinstance(component, unreal.StaticMeshComponent):
                continue

            static_mesh = component.get_editor_property("static_mesh")
            attachments.append({
                "component": component.get_path_name(),
                "mesh": static_mesh.get_path_name() if static_mesh else None,
                "socket": str(component.get_attach_socket_name()),
                "relativeTransform": component.get_relative_transform().export_text(),
                "worldTransform": component.get_socket_transform(unreal.Name("None")).export_text(),
            })

        return json.dumps({"pawn": pawn.get_path_name(), "bones": bones,
            "attachments": attachments}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_actor_skeletal_bones(class_path: str, bone_names: list[str]) -> str:
        """只读返回 PIE 中指定 Actor 的骨骼网格骨骼世界变换"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        actor_class = unreal.load_class(None, class_path)
        if world is None or actor_class is None or not bone_names:
            raise RuntimeError("PIE 世界 Actor 类或骨骼名无效")

        actors = unreal.GameplayStatics.get_all_actors_of_class(world, actor_class)
        result = []
        for actor in actors:
            meshes = actor.get_components_by_class(unreal.SkeletalMeshComponent)
            for mesh in meshes:
                if any(mesh.get_bone_index(name) < 0 for name in bone_names):
                    continue
                result.append({
                    "actor": actor.get_path_name(),
                    "mesh": mesh.get_path_name(),
                    "bones": {name: mesh.get_socket_transform(name).export_text() for name in bone_names},
                })

        return json.dumps({"class": class_path, "instances": result}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_bone_alignment(class_path: str, actor_bone_name: str, pawn_bone_name: str) -> str:
        """只读计算 PIE 中装备骨骼相对本地角色骨骼的变换"""
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        actor_class = unreal.load_class(None, class_path)
        if world is None or actor_class is None:
            raise RuntimeError("PIE 世界或 Actor 类无效")

        pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
        if pawn is None:
            raise RuntimeError("本地角色不存在")

        hand_mesh = next((mesh for mesh in pawn.get_components_by_class(unreal.SkeletalMeshComponent)
                          if mesh.get_bone_index(pawn_bone_name) >= 0), None)
        if hand_mesh is None:
            raise RuntimeError("角色骨骼不存在")

        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, actor_class):
            if actor.get_owner() != pawn:
                continue
            for mesh in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                if mesh.get_bone_index(actor_bone_name) < 0:
                    continue
                actor_world = mesh.get_socket_transform(actor_bone_name)
                pawn_world = hand_mesh.get_socket_transform(pawn_bone_name)
                relative = unreal.MathLibrary.make_relative_transform(actor_world, pawn_world)
                return json.dumps({
                    "actor": actor.get_path_name(),
                    "actorBone": actor_world.export_text(),
                    "pawnBone": pawn_world.export_text(),
                    "relative": relative.export_text(),
                }, ensure_ascii=False)

        raise RuntimeError("本地角色未持有指定 Actor 骨骼")

    @toolset_registry.tool_call
    @staticmethod
    def inspect_blueprint_class_defaults(
        asset_paths: list[str],
        property_names: list[str],
    ) -> str:
        """只读读取蓝图生成类默认对象的指定属性"""
        if not asset_paths:
            raise RuntimeError("资产路径不能为空")

        requested_properties = [str(name) for name in property_names]
        results = []
        for asset_path in asset_paths:
            blueprint, generated_class, default_object = _load_blueprint_default_object(asset_path)
            properties = {}
            property_errors = {}
            for property_name in requested_properties:
                if not property_name:
                    property_errors["<empty>"] = "属性名不能为空"
                    continue

                try:
                    value = default_object.get_editor_property(property_name)
                    properties[property_name] = _serialize_value(value)
                except Exception as error:
                    property_errors[property_name] = str(error)

            results.append(
                {
                    "assetPath": blueprint.get_path_name(),
                    "generatedClass": generated_class.get_path_name(),
                    "defaultObject": default_object.get_path_name(),
                    "properties": properties,
                    "propertyErrors": property_errors,
                }
            )

        return json.dumps(
            {
                "assets": results,
                "propertyNames": requested_properties,
                "readOnly": True,
            },
            ensure_ascii=False,
        )

    @toolset_registry.tool_call
    @staticmethod
    def set_blueprint_class_defaults(asset_path: str, values_json: str) -> str:
        """校验后更新蓝图生成类默认对象属性并编译保存"""
        from toolset_registry.helpers import require_editable
        from editor_toolset.toolsets.asset import AssetTools

        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 运行期间禁止修改蓝图默认值")

        values = json.loads(values_json)
        if not isinstance(values, dict) or not values:
            raise RuntimeError("默认值配置必须是非空对象")

        blueprint, generated_class, default_object = _load_blueprint_default_object(asset_path)
        require_editable(blueprint)
        if not AssetTools.is_checked_out(asset_path):
            raise RuntimeError("修改前必须独占签出目标蓝图")

        for property_name in values:
            default_object.get_editor_property(str(property_name))

        with unreal.ScopedEditorTransaction("更新蓝图类默认值"):
            blueprint.modify()
            default_object.modify()

            for property_name, requested_value in values.items():
                _apply_editor_property(default_object, str(property_name), requested_value)

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") == unreal.BlueprintStatus.BS_ERROR:
            raise RuntimeError("蓝图编译失败 禁止保存: {}".format(asset_path))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("蓝图保存失败: {}".format(asset_path))

        return BBBGenericEditorToolset.inspect_blueprint_class_defaults(
            [asset_path],
            [str(name) for name in values],
        )

    @toolset_registry.tool_call
    @staticmethod
    def remove_input_action_mappings(mapping_context_path: str, action_paths: list[str]) -> str:
        """从输入映射中移除指定动作的全部按键映射 保留其它映射原样"""
        from toolset_registry.helpers import require_editable

        if not action_paths or len(set(action_paths)) != len(action_paths):
            raise RuntimeError("必须提供不重复的输入动作路径")

        context = unreal.EditorAssetLibrary.load_asset(mapping_context_path)
        if not isinstance(context, unreal.InputMappingContext):
            raise RuntimeError("目标不是输入映射资产")

        require_editable(context)
        default_data = context.get_editor_property("default_key_mappings")
        default_mappings = list(default_data.get_editor_property("mappings"))
        legacy_mappings = list(context.get_editor_property("mappings"))
        removed = []

        for mapping in default_mappings + legacy_mappings:
            action = mapping.get_editor_property("action")
            action_path = action.get_path_name() if action else None
            if action_path and action_path.split(".")[0] in action_paths:
                removed.append(action_path)

        missing = set(action_paths) - {path.split(".")[0] for path in removed}
        if missing:
            raise RuntimeError("输入映射未找到动作: {}".format(", ".join(sorted(missing))))

        with unreal.ScopedEditorTransaction("移除输入动作映射"):
            context.modify()

            for action_path in action_paths:
                action = unreal.EditorAssetLibrary.load_asset(action_path)
                if not isinstance(action, unreal.InputAction):
                    raise RuntimeError("输入动作不存在: {}".format(action_path))

                context.unmap_all_keys_from_action(action)

            remaining_legacy = []
            for mapping in legacy_mappings:
                action = mapping.get_editor_property("action")
                action_path = action.get_path_name() if action else None
                if action_path and action_path.split(".")[0] in action_paths:
                    continue

                remaining_legacy.append(mapping)

            context.set_editor_property("mappings", remaining_legacy)

        remaining_default = list(context.get_editor_property("default_key_mappings").get_editor_property("mappings"))
        for mapping in remaining_default:
            action = mapping.get_editor_property("action")
            if action and action.get_path_name().split(".")[0] in action_paths:
                raise RuntimeError("输入动作仍存在于默认映射 禁止继续删除资产")

        if not unreal.EditorAssetLibrary.save_loaded_asset(context):
            raise RuntimeError("输入映射保存失败")

        return json.dumps({"asset": context.get_path_name(), "removed": removed,
            "remainingCount": len(remaining_default)}, ensure_ascii=False)


    @toolset_registry.tool_call
    @staticmethod
    def create_channel_sprite_system(channel_path: str, system_path: str) -> str:
        """通过原生 Niagara 图表 API 创建空间通道批量线段光效 拒绝覆盖"""
        from toolset_registry.helpers import require_editable

        channel = unreal.EditorAssetLibrary.load_asset(channel_path)
        if channel is None or not system_path.startswith("/Game/"):
            raise RuntimeError("通道必须存在 系统路径必须位于 Game")

        require_editable(channel)
        return unreal.BBBNiagaraEditorLibrary.create_channel_sprite_system(channel_path, system_path)

    @toolset_registry.tool_call
    @staticmethod
    def set_struct_array_object(object_path: str, array_property: str, index: int,
                                object_property: str, class_path: str, properties_json: str = "{}") -> str:
        """为结构体数组的指定元素创建实例化子对象 不影响其它字段"""
        from toolset_registry.helpers import require_editable

        target = unreal.load_object(None, object_path)
        if target is None:
            raise RuntimeError("对象不存在")

        require_editable(target)
        values = list(target.get_editor_property(array_property))
        if index < 0 or index >= len(values):
            raise RuntimeError("数组下标越界")

        subobject = unreal.new_object(unreal.load_class(None, class_path), outer=target)
        if not unreal.ToolsetLibrary.set_object_properties(subobject, properties_json):
            raise RuntimeError("子对象属性配置失败")

        target.modify()
        values[index].set_editor_property(object_property, subobject)
        target.set_editor_property(array_property, values)
        return subobject.get_path_name()

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_actor_properties(class_path: str, property_paths: list[str]) -> str:
        """只读检查所有 PIE 世界指定 Actor 类型的属性 数组仅返回数量与前三项"""
        actor_class = unreal.load_class(None, class_path)
        results = []
        for world in unreal.EditorLevelLibrary.get_pie_worlds(False):
            actors = unreal.GameplayStatics.get_all_actors_of_class(world, actor_class)
            items = []
            for actor in actors[:3]:
                values = {}
                for path in property_paths:
                    try:
                        value = actor
                        for field in path.split("."):
                            value = value.get_editor_property(field)

                        if isinstance(value, (list, tuple, unreal.Array)):
                            values[path] = {"count": len(value), "sample": [_serialize_value(item) for item in list(value)[:3]]}
                        else:
                            values[path] = _serialize_value(value)
                    except Exception as error:
                        values[path] = {"error": str(error)}
                items.append({"path": actor.get_path_name(), "values": values})
            results.append({"world": world.get_path_name(), "count": len(actors), "actors": items})
        return json.dumps(results, ensure_ascii=False)


    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_niagara_system(system_path: str) -> str:
        """只读检查指定系统的 PIE 光效组件与粒子数量"""
        return unreal.BBBNiagaraEditorLibrary.inspect_pie_system(system_path)

    @toolset_registry.tool_call
    @staticmethod
    def set_niagara_spawn_update_mode(system_path: str, mode: int) -> str:
        """设置原生首帧更新模式 0 跳过首帧更新 1 执行更新 2 插值更新"""
        from toolset_registry.helpers import require_editable

        system = unreal.EditorAssetLibrary.load_asset(system_path)
        if system is None:
            raise RuntimeError("系统资产不存在")

        require_editable(system)
        return unreal.BBBNiagaraEditorLibrary.set_spawn_update_mode(system_path, mode)


    @toolset_registry.tool_call
    @staticmethod
    def inspect_niagara_graphs(system_path: str) -> str:
        """只读导出系统内节点引脚与连接"""
        return unreal.BBBNiagaraEditorLibrary.inspect_graphs(system_path)

    @toolset_registry.tool_call
    @staticmethod
    def set_niagara_pin_default(system_path: str, node_path: str, pin_name: str, value: str) -> str:
        """修改系统内未连接引脚默认值并保存"""
        from toolset_registry.helpers import require_editable

        system = unreal.EditorAssetLibrary.load_asset(system_path)
        if system is None or not node_path.startswith(system.get_path_name() + ":"):
            raise RuntimeError("节点必须属于指定系统")

        require_editable(system)
        return unreal.BBBNiagaraEditorLibrary.set_pin_default(node_path, pin_name, value)


    @toolset_registry.tool_call
    @staticmethod
    def bind_niagara_channel_reader(system_path: str, channel_path: str) -> str:
        """将共享通道读取器绑定到发射器参数并保存"""
        from toolset_registry.helpers import require_editable

        system = unreal.EditorAssetLibrary.load_asset(system_path)
        if system is None:
            raise RuntimeError("系统不存在")

        require_editable(system)
        return unreal.BBBNiagaraEditorLibrary.bind_channel_reader(system_path, channel_path)

    @toolset_registry.tool_call
    @staticmethod
    def set_niagara_channel_reader_frame_mode(system_path: str, read_current_frame: bool) -> str:
        """
        /**
         * 设置系统内通道读取帧并编译保存 拒绝覆盖未保存改动
         * @param system_path		系统资产路径
         * @param read_current_frame	是否读取当前帧
         * @return 编译与保存结果
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止修改光效读取帧")

        system = unreal.EditorAssetLibrary.load_asset(system_path)
        if not isinstance(system, unreal.NiagaraSystem):
            raise RuntimeError("资产不是 Niagara 系统")

        dirty_packages = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        system_package_path = system.get_path_name().split(".", 1)[0]
        if system_package_path in {package.get_path_name() for package in dirty_packages}:
            raise RuntimeError("系统存在未保存改动 请先保存")

        require_editable(system)
        result = unreal.BBBNiagaraEditorLibrary.set_channel_reader_frame_mode(system_path, read_current_frame)
        if result.startswith("失败"):
            raise RuntimeError(result)

        return result

    @toolset_registry.tool_call
    @staticmethod
    def configure_persistent_projectile_tracer(system_path: str, channel_path: str) -> str:
        """将已有共享子弹系统配置为每颗子弹持续更新同一光段"""
        from toolset_registry.helpers import require_editable

        system = unreal.EditorAssetLibrary.load_asset(system_path)
        channel = unreal.EditorAssetLibrary.load_asset(channel_path)
        if system is None or channel is None:
            raise RuntimeError("子弹光效系统或通道不存在")

        require_editable(system)
        require_editable(channel)
        return unreal.BBBNiagaraEditorLibrary.configure_persistent_projectile_tracer(
            system_path, channel_path)



    @toolset_registry.tool_call
    @staticmethod
    def create_static_mesh_grid_graph(graph_path: str, mesh_paths: list[str], grid_extent: float = 600.0, cell_size: float = 300.0) -> str:
        """
        /**
         * 创建用于静态网格入库验证的平面网格 PCG 图 拒绝覆盖
         * @param graph_path	新建图的 Game 包路径
         * @param mesh_paths	已经入库的静态网格路径
         * @param grid_extent	平面网格半宽 厘米
         * @param cell_size	网格间距 厘米
         * @return 图路径和预计点数
         */
        """
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止创建验证图")
        if not re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", graph_path):
            raise RuntimeError("图路径必须是合法 Game 包路径")
        if unreal.EditorAssetLibrary.does_asset_exist(graph_path):
            raise RuntimeError("验证图已存在 拒绝覆盖")
        if not mesh_paths or len(mesh_paths) > 32 or len(set(mesh_paths)) != len(mesh_paths):
            raise RuntimeError("需要一到三十二个不同静态网格")
        if not math.isfinite(grid_extent) or not math.isfinite(cell_size):
            raise RuntimeError("网格参数必须为有限数值")
        if cell_size <= 0.0 or grid_extent < cell_size:
            raise RuntimeError("网格范围或间距无效")
        points_per_axis = math.floor(2.0 * grid_extent / cell_size)
        expected_points = points_per_axis * points_per_axis
        if expected_points > 256:
            raise RuntimeError("验证图超过二百五十六点安全上限")
        for path in mesh_paths:
            mesh = unreal.EditorAssetLibrary.load_asset(path)
            if not path.startswith("/Game/") or not isinstance(mesh, unreal.StaticMesh):
                raise RuntimeError("输入不是已入库 Game 静态网格: " + path)
        factory_class = unreal.load_class(None, "/Script/PCGEditor.PCGGraphFactory")
        if factory_class is None:
            raise RuntimeError("缺少 PCG 编辑器插件")
        folder, name = graph_path.rsplit("/", 1)
        graph = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, folder, unreal.PCGGraph, unreal.new_object(factory_class))
        if graph is None:
            raise RuntimeError("PCG 图创建失败")
        grid_node, grid_settings = graph.add_node_of_type(unreal.PCGCreatePointsGridSettings)
        grid_settings.set_editor_property("grid_extents", unreal.Vector(grid_extent, grid_extent, 0.0))
        grid_settings.set_editor_property("cell_size", unreal.Vector(cell_size, cell_size, 100.0))
        grid_settings.set_editor_property("coordinate_space", unreal.PCGCoordinateSpace.ORIGINAL_COMPONENT)
        grid_settings.set_editor_property("cull_points_outside_volume", False)
        spawner_node, spawner_settings = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
        selector = spawner_settings.get_editor_property("mesh_selector_parameters")
        if not isinstance(selector, unreal.PCGMeshSelectorWeighted):
            raise RuntimeError("默认网格选择器不是加权选择器")
        entries = []
        for path in mesh_paths:
            entry = unreal.PCGMeshSelectorWeightedEntry()
            descriptor = entry.get_editor_property("descriptor")
            descriptor.set_editor_property("static_mesh", unreal.EditorAssetLibrary.load_asset(path))
            entry.set_editor_property("descriptor", descriptor)
            entry.set_editor_property("weight", 1)
            entries.append(entry)
        selector.set_editor_property("mesh_entries", entries)
        grid_node.set_node_position(0, 0)
        spawner_node.set_node_position(400, 0)
        if graph.add_edge(grid_node, "Out", spawner_node, "In") is None:
            raise RuntimeError("PCG 网格到生成节点连线失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(graph, False):
            unreal.log_error("[BBBPCGValidation]验证图保存失败 " + graph_path)
            raise RuntimeError("验证图保存失败")
        unreal.log("[BBBPCGValidation]已创建图 {} 预计 {} 点".format(graph_path, expected_points))
        return json.dumps({"graph": graph.get_path_name(), "mesh_paths": list(mesh_paths),
            "expected_points": expected_points}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def generate_and_inspect_pcg(actor_path: str, graph_path: str, expected_level: str, generate: bool = False) -> str:
        """
        /**
         * 在指定已签出关卡的 PCG Actor 上生成或只读核验实例
         * @param actor_path	目标 PCG Actor 的完整对象路径
         * @param graph_path	已保存 PCG 图路径
         * @param expected_level	必须匹配的活动关卡包路径
         * @param generate	为真时启动生成 为假时仅回读
         * @return 生成状态 实例数量与网格路径
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止执行编辑器生成验证")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("活动关卡与预期不符")
        actor = unreal.find_object(None, actor_path)
        graph = unreal.EditorAssetLibrary.load_asset(graph_path)
        if not isinstance(actor, unreal.Actor) or actor.get_world() != world:
            raise RuntimeError("Actor 不属于目标编辑器世界")
        if not isinstance(graph, unreal.PCGGraph):
            raise RuntimeError("目标不是 PCG 图")
        components = actor.get_components_by_class(unreal.PCGComponent)
        if len(components) != 1:
            raise RuntimeError("Actor 必须恰好包含一个 PCG 组件")
        component = components[0]
        if not generate and component.get_graph() != graph:
            raise RuntimeError("组件使用的 PCG 图与预期不符")

        if generate:
            require_editable(actor)
            if component.get_editor_property("generated"):
                raise RuntimeError("组件已经生成 拒绝自动重放")
            component.modify()
            component.set_graph(graph)
            component.generate_local(True)
        instances = []
        for mesh_component in actor.get_components_by_class(unreal.InstancedStaticMeshComponent):
            mesh = mesh_component.get_editor_property("static_mesh")
            instances.append({"component": mesh_component.get_path_name(),
                "mesh": mesh.get_path_name() if mesh else None,
                "count": mesh_component.get_instance_count()})
        generated = bool(component.get_editor_property("generated"))
        count = sum(item["count"] for item in instances)
        if not generate and generated and count == 0:
            unreal.log_error("[BBBPCGValidation]生成标记有效但没有网格实例 " + actor_path)
            raise RuntimeError("PCG 生成未产生实例")
        return json.dumps({"actor": actor_path, "graph": graph_path, "generated": generated,
            "instance_count": count, "instances": instances}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def invoke_pie_object_function(object_path: str, function_name: str, arguments_json: str = "[]") -> str:
        """
        /**
         * 调用 PIE 演员或其组件的公开反射函数 不接受资产与编辑器世界
         * @param object_path		PIE 演员或组件路径
         * @param function_name	反射函数名称
         * @param arguments_json	位置参数数组 结构体参数按反射接口传入
         * @return 目标世界与实际返回值 不保存资产
         */
        """
        target = unreal.find_object(None, object_path)
        owner = target
        if isinstance(target, unreal.ActorComponent):
            owner = target.get_owner()

        if not isinstance(owner, unreal.Actor) or owner.get_world() not in unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("目标必须是 PIE 世界的演员或其组件")

        arguments = json.loads(arguments_json)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name) or not isinstance(arguments, list):
            raise RuntimeError("函数名或位置参数数组无效")

        result = target.call_method(function_name, tuple(arguments))
        report = {"object": object_path, "world": owner.get_world().get_path_name(), "function": function_name, "result": _serialize_value(result)}
        unreal.log("[BBBPIEObjectCall] " + object_path + " " + function_name)
        return json.dumps(report, ensure_ascii=False)



    @toolset_registry.tool_call
    @staticmethod
    def set_scene_actor_collision(expected_level: str, actor_paths: list[str], enabled: bool) -> str:
        """
        /**
         * 通过原生接口同步演员与静态网格组件碰撞状态
         * @param expected_level\t预期关卡路径
         * @param actor_paths\t显式演员路径列表
         * @param enabled\t是否启用 BlockAll 碰撞
         * @return 已处理演员与组件回读值 不自动保存
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止编辑场景碰撞")

        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("活动关卡不匹配")

        if not actor_paths or len(actor_paths) > 400 or len(set(actor_paths)) != len(actor_paths):
            raise RuntimeError("目标数量或唯一性无效")

        actors = []
        for path in actor_paths:
            actor = unreal.find_object(None, path)
            if not isinstance(actor, unreal.StaticMeshActor) or actor.get_world() != world:
                raise RuntimeError("目标不是当前世界静态网格演员")

            require_editable(actor)
            actors.append(actor)

        result = []
        for actor in actors:
            actor.modify()
            component = actor.static_mesh_component
            component.modify()
            component.set_collision_profile_name("BlockAll" if enabled else "NoCollision")
            actor.set_actor_enable_collision(enabled)
            result.append({"actor": actor.get_path_name(), "actor_enabled": actor.get_actor_enable_collision(),
                "component_enabled": str(component.get_collision_enabled()),
                "profile": str(component.get_collision_profile_name())})

        unreal.log("[BBBSceneCollision]更新数量 {} 状态 {}".format(len(result), enabled))
        return json.dumps(result)

    @toolset_registry.tool_call
    @staticmethod
    def configure_static_mesh_surface_collision(mesh_path: str, apply_changes: bool = False) -> str:
        """
        /**
         * 核验并配置静态地表的逐三角形与分段碰撞
         * @param mesh_path\t目标静态网格包路径
         * @param apply_changes\t为真时启用所有分段碰撞并重建网格
         * @return 修改前后复杂度与分段碰撞状态 不自动保存
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止重建地表碰撞")

        mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError("目标不是静态网格")

        subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        before = []
        for lod in range(mesh.get_num_lods()):
            for section in range(mesh.get_num_sections(lod)):
                before.append({"lod": lod, "section": section,
                    "enabled": subsystem.is_section_collision_enabled(mesh, lod, section)})

        complexity = str(subsystem.get_collision_complexity(mesh))
        if not apply_changes:
            return json.dumps({"mesh": mesh_path, "complexity": complexity, "sections": before})

        require_editable(mesh)
        mesh.modify()
        body = mesh.get_editor_property("body_setup")
        if body is None:
            raise RuntimeError("网格缺少碰撞设置")

        body.modify()
        body.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
        body.set_editor_property("double_sided_geometry", True)
        for section in before:
            subsystem.enable_section_collision(mesh, True, section["lod"], section["section"])

        subsystem.set_nanite_settings(mesh, subsystem.get_nanite_settings(mesh))
        after = []
        for section in before:
            enabled = subsystem.is_section_collision_enabled(mesh, section["lod"], section["section"])
            if not enabled:
                unreal.log_error("[BBBSurfaceCollision]分段碰撞未生效 " + mesh_path)
                raise RuntimeError("分段碰撞回读失败")

            after.append({"lod": section["lod"], "section": section["section"], "enabled": enabled})

        unreal.log("[BBBSurfaceCollision]已启用地表碰撞 " + mesh_path)
        return json.dumps({"mesh": mesh_path, "previous_complexity": complexity,
            "complexity": str(subsystem.get_collision_complexity(mesh)), "before": before, "sections": after})

    @toolset_registry.tool_call
    @staticmethod
    def create_static_mesh_points_graph(graph_path: str, mesh_path: str, points_json: str, collision: bool = False) -> str:
        """
        /**
         * 从显式世界变换创建可编辑的 PCG 点集与网格生成图 拒绝覆盖
         * @param graph_path	新建图路径
         * @param mesh_path	已入库静态网格路径
         * @param points_json	包含 location rotation scale 三元数组的点列表 单位厘米与角度
         * @param collision	是否启用实例查询和物理碰撞
         * @return 图路径与预计实例数量
         */
        """
        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止创建点集图")
        if not re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", graph_path):
            raise RuntimeError("PCG 图路径无效")
        if unreal.EditorAssetLibrary.does_asset_exist(graph_path):
            raise RuntimeError("PCG 图已经存在 拒绝覆盖")
        records = json.loads(points_json)
        if isinstance(records, dict):
            source_path = os.path.realpath(records["file"])
            project_path = os.path.realpath(unreal.Paths.project_dir())
            if os.path.commonpath([source_path, project_path]) != project_path or not source_path.endswith(".json"):
                raise RuntimeError("点集文件必须是项目目录内的 JSON")
            with open(source_path, "r", encoding="utf-8-sig") as source:
                manifest = json.load(source)
            records = manifest["pcg_groups"][records["group"]]
        if not isinstance(records, list) or not 1 <= len(records) <= 12000:
            raise RuntimeError("点集数量必须在一到一万二千之间")
        points = []
        for index, record in enumerate(records):
            for key in ("location", "rotation", "scale"):
                values = record[key]
                if not isinstance(values, list) or len(values) != 3:
                    raise RuntimeError("变换必须为三元数组: " + key)
                if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                    raise RuntimeError("变换必须为有限数字")
            if min(record["scale"]) <= 0.0 or max(record["scale"]) > 100.0:
                raise RuntimeError("缩放必须在零到一百之间")
            point = unreal.PCGPoint()
            transform = unreal.Transform(
                location=unreal.Vector(*record["location"]),
                rotation=unreal.Rotator(pitch=record["rotation"][0], yaw=record["rotation"][1], roll=record["rotation"][2]),
                scale=unreal.Vector(*record["scale"]))
            point.set_editor_property("transform", transform)
            point.set_editor_property("seed", index + 1)
            points.append(point)
        mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError("点集网格资产无效")
        factory_class = unreal.load_class(None, "/Script/PCGEditor.PCGGraphFactory")
        if factory_class is None:
            raise RuntimeError("PCG 编辑器工厂不可用")
        folder, name = graph_path.rsplit("/", 1)
        graph = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, folder, unreal.PCGGraph, unreal.new_object(factory_class))
        if graph is None:
            raise RuntimeError("点集图创建失败")
        point_node, point_settings = graph.add_node_of_type(unreal.PCGCreatePointsSettings)
        point_settings.set_editor_property("points_to_create", points)
        point_settings.set_editor_property("coordinate_space", unreal.PCGCoordinateSpace.WORLD)
        point_settings.set_editor_property("cull_points_outside_volume", False)
        spawn_node, spawn_settings = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
        selector = spawn_settings.get_editor_property("mesh_selector_parameters")
        if not isinstance(selector, unreal.PCGMeshSelectorWeighted):
            raise RuntimeError("默认网格选择器不是加权选择器")
        entry = unreal.PCGMeshSelectorWeightedEntry()
        descriptor = entry.get_editor_property("descriptor")
        descriptor.set_editor_property("static_mesh", mesh)
        body = descriptor.get_editor_property("body_instance")
        body.set_editor_property("collision_enabled",
            unreal.CollisionEnabled.QUERY_AND_PHYSICS if collision else unreal.CollisionEnabled.NO_COLLISION)
        descriptor.set_editor_property("body_instance", body)
        entry.set_editor_property("descriptor", descriptor)
        entry.set_editor_property("weight", 1)
        selector.set_editor_property("mesh_entries", [entry])
        point_node.set_node_position(0, 0)
        spawn_node.set_node_position(400, 0)
        if graph.add_edge(point_node, "Out", spawn_node, "In") is None:
            raise RuntimeError("点集到网格生成器连线失败")
        if not unreal.EditorAssetLibrary.save_loaded_asset(graph, False):
            unreal.log_error("[BBBPCGPoints]图保存失败 " + graph_path)
            raise RuntimeError("PCG 图保存失败")
        unreal.log("[BBBPCGPoints]创建 {} 点数 {}".format(graph_path, len(points)))
        return json.dumps({"graph": graph.get_path_name(), "expected_points": len(points),
            "mesh": mesh_path, "collision": collision}, ensure_ascii=False)


    @toolset_registry.tool_call
    @staticmethod
    def remove_scene_mesh_actors(expected_level: str, actor_paths: list[str], dry_run: bool = True) -> str:
        """
        /**
         * 删除显式列出的静态网格和文字演员 其它类型保留
         * @param expected_level	预期活动关卡
         * @param actor_paths	明确对象路径列表
         * @param dry_run	只检查不删除
         * @return 已删除或预览目标和保留对象
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止删除场景对象")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("活动关卡不匹配")
        if not 1 <= len(actor_paths) <= 5000 or len(set(actor_paths)) != len(actor_paths):
            raise RuntimeError("对象路径列表数量或唯一性无效")
        targets = []
        kept = []
        for path in actor_paths:
            actor = unreal.find_object(None, path)
            if not isinstance(actor, unreal.Actor) or actor.get_world() != world:
                raise RuntimeError("对象不属于当前编辑器世界: " + path)
            if not isinstance(actor, (unreal.StaticMeshActor, unreal.TextRenderActor)):
                kept.append({"path": path, "label": actor.get_actor_label()})
                continue
            require_editable(actor)
            targets.append(actor)
        result = [{"path": actor.get_path_name(), "label": actor.get_actor_label()} for actor in targets]
        if not dry_run:
            subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for actor in targets:
                if not subsystem.destroy_actor(actor):
                    unreal.log_error("[BBBSceneBatch]删除失败 " + actor.get_path_name())
                    raise RuntimeError("删除失败 需检查已处理对象")
        unreal.log("[BBBSceneBatch]删除预览={} 数量={}".format(dry_run, len(result)))
        return json.dumps({"dry_run": dry_run, "targets": result, "kept": kept}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def spawn_static_mesh_batch(expected_level: str, items_json: str) -> str:
        """
        /**
         * 按完整变换批量创建独立静态网格演员 拒绝重复标签
         * @param expected_level	预期活动关卡
         * @param items_json	含 name mesh location rotation scale 及可选 material folder collision 的列表
         * @return 新演员完整对象路径
         */
        """
        from toolset_registry.helpers import require_editable

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            raise RuntimeError("PIE 期间禁止批量创建")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_path_name().split(".", 1)[0] != expected_level:
            raise RuntimeError("活动关卡不匹配")
        require_editable(world)
        items = json.loads(items_json)
        if not isinstance(items, list) or not 1 <= len(items) <= 400:
            raise RuntimeError("批次需要一到四百项")
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        labels = {actor.get_actor_label() for actor in subsystem.get_all_level_actors()}
        meshes = {}
        materials = {}
        for item in items:
            name = item["name"]
            if not isinstance(name, str) or not name or name in labels:
                raise RuntimeError("演员标签为空或重复: " + str(name))
            labels.add(name)
            for key in ("location", "rotation", "scale"):
                values = item[key]
                if not isinstance(values, list) or len(values) != 3:
                    raise RuntimeError("变换必须为三元数组")
                if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                    raise RuntimeError("变换存在非有限数字")
            if any(value == 0.0 or abs(value) > 10000.0 for value in item["scale"]):
                raise RuntimeError("缩放无效")
            mesh_path = item["mesh"]
            if mesh_path not in meshes:
                mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
                if not isinstance(mesh, unreal.StaticMesh):
                    raise RuntimeError("网格无效: " + mesh_path)
                meshes[mesh_path] = mesh
            material_path = item.get("material", "")
            if material_path and material_path not in materials:
                material = unreal.EditorAssetLibrary.load_asset(material_path)
                if not isinstance(material, unreal.MaterialInterface):
                    raise RuntimeError("材质无效: " + material_path)
                materials[material_path] = material
        created = []
        for item in items:
            actor = subsystem.spawn_actor_from_class(unreal.StaticMeshActor,
                unreal.Vector(*item["location"]), unreal.Rotator(pitch=item["rotation"][0], yaw=item["rotation"][1], roll=item["rotation"][2]))
            if actor is None:
                unreal.log_error("[BBBSceneBatch]创建失败 " + item["name"])
                raise RuntimeError("创建中途失败 必须核对现有标签")
            actor.set_actor_label(item["name"])
            actor.set_actor_scale3d(unreal.Vector(*item["scale"]))
            actor.set_folder_path(item.get("folder", ""))
            component = actor.static_mesh_component
            component.set_static_mesh(meshes[item["mesh"]])
            material_path = item.get("material", "")
            if material_path:
                for index in range(component.get_num_materials()):
                    component.set_material(index, materials[material_path])
            if not item.get("collision", True):
                component.set_collision_profile_name("NoCollision")
                actor.set_actor_enable_collision(False)
            created.append({"name": item["name"], "actor": actor.get_path_name()})
        unreal.log("[BBBSceneBatch]已创建 {} 个静态网格演员".format(len(created)))
        return json.dumps({"created": created}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def inspect_pie_static_mesh_instances(mesh_path: str) -> str:
        """
        /**
         * 检查指定静态网格的 PIE 物理表现对象
         * @param mesh_path	静态网格资产路径
         * @return 对象数量与物理状态
         */
        """
        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.StaticMesh):
            raise RuntimeError("物理对象检查需要有效静态网格")
        rows = []
        for world in unreal.EditorLevelLibrary.get_pie_worlds(False):
            for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
                component = actor.static_mesh_component
                if component.get_editor_property("static_mesh") != mesh:
                    continue
                rows.append({"actor": actor.get_path_name(), "simulatingPhysics": component.is_simulating_physics(),
                             "velocity": _serialize_value(component.get_physics_linear_velocity()),
                             "remainingLifeSeconds": actor.get_life_span()})
        return json.dumps({"mesh": mesh_path, "count": len(rows), "instances": rows}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def capture_niagara_preview(system_path: str, age_seconds: float, file_name: str) -> str:
        """
        /**
         * 渲染指定 Niagara 系统的固定模拟时刻
         * @param system_path	系统资产路径
         * @param age_seconds	模拟时间
         * @param file_name	输出图像名称
         * @return 图像路径与系统模拟时间
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        system = unreal.load_asset(system_path)
        if world is None or not isinstance(system, unreal.NiagaraSystem):
            raise RuntimeError("特效截图需要启用渲染的 PIE 世界与有效系统")
        if not math.isfinite(age_seconds) or age_seconds < 0.0 or age_seconds > 5.0:
            raise RuntimeError("特效模拟时间必须在零至五秒之间")
        if os.path.basename(file_name) != file_name or not file_name.endswith(".png"):
            raise RuntimeError("特效截图名称无效")
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "NiagaraCaptures"))
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            raise RuntimeError("特效截图文件已存在")
        actor = None
        camera = None
        try:
            origin = unreal.Vector(0.0, 0.0, 10000.0)
            actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
                world, unreal.NiagaraActor, unreal.Transform(location=origin))
            if actor is None:
                raise RuntimeError("特效预览对象创建失败")
            component = actor.get_component_by_class(unreal.NiagaraComponent)
            component.set_asset(system)
            component.activate(True)
            component.advance_simulation(max(1, int(age_seconds * 120.0)), 1.0 / 120.0)
            target = origin + unreal.Vector(15.0, 0.0, 0.0)
            location = target + unreal.Vector(65.0, 90.0, 35.0)
            rotation = unreal.MathLibrary.find_look_at_rotation(location, target)
            camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
                world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
            if camera is None:
                raise RuntimeError("特效截图相机创建失败")
            capture = camera.capture_component2d
            render_target = unreal.RenderingLibrary.create_render_target2d(
                world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture.set_editor_property("texture_target", render_target)
            capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.set_editor_property("show_only_actors", [actor])
            capture.set_editor_property("fov_angle", 60.0)
            capture.capture_scene()
            os.makedirs(directory, exist_ok=True)
            unreal.RenderingLibrary.export_render_target(world, render_target, directory, file_name)
            if not os.path.isfile(path) or os.path.getsize(path) < 1024:
                raise RuntimeError("特效截图未产生有效输出")
            return json.dumps({"imagePath": path, "system": system_path, "ageSeconds": age_seconds})
        finally:
            if camera is not None:
                camera.destroy_actor()
            if actor is not None:
                actor.destroy_actor()

    @toolset_registry.tool_call
    @staticmethod
    def export_skeletal_mesh_fbx(mesh_path: str, export_name: str) -> str:
        """
        /**
         * 导出骨骼蒙皮网格和参考姿势供离线动画制作 拒绝覆盖现有交付目录
         * @param mesh_path		骨骼网格资产路径
         * @param export_name		Saved Exports 下的新目录名称
         * @return FBX 与骨骼清单路径及导出统计
         */
        """
        def fail(message):
            unreal.log_error("[BBB][SkeletalExport] " + message)
            raise RuntimeError(message)

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", export_name):
            fail("导出目录名称必须使用字母数字下划线或连字符")

        if "-nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            fail("UE 骨骼 FBX 导出需要渲染宿主 请关闭 NullRHI 后再调用")

        if unreal.EditorLevelLibrary.get_pie_worlds(False):
            fail("PIE 期间禁止导出参考网格")

        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            fail("目标不是骨骼网格 " + mesh_path)

        package_path = mesh.get_path_name().split(".", 1)[0]
        dirty_paths = {item.get_path_name() for item in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        skeleton = mesh.get_editor_property("skeleton")
        if skeleton is None:
            fail("目标网格缺少骨骼")

        if package_path in dirty_paths or skeleton.get_path_name().split(".", 1)[0] in dirty_paths:
            fail("目标网格或骨骼存在未保存改动")

        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Exports", export_name))
        if os.path.exists(directory):
            fail("交付目录已经存在 " + directory)

        subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
        reference = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
        bones = []
        for bone_name in reference.get_bone_names():
            poses = {}
            for label, space in (("local", unreal.AnimPoseSpaces.LOCAL), ("component", unreal.AnimPoseSpaces.WORLD)):
                pose = reference.get_ref_bone_pose(bone_name, space)
                poses[label] = {
                    "position": [pose.translation.x, pose.translation.y, pose.translation.z],
                    "rotation": [pose.rotation.x, pose.rotation.y, pose.rotation.z, pose.rotation.w],
                    "scale": [pose.scale3d.x, pose.scale3d.y, pose.scale3d.z],
                }
            bones.append({"name": str(bone_name), "parent": str(subsystem.get_bone_parent(mesh, bone_name)), **poses})

        options = unreal.FbxExportOption()
        options.set_editor_properties({
            "ascii": False,
            "fbx_export_compatibility": unreal.FbxExportCompatibility.FBX_2013,
            "force_front_x_axis": True,
            "level_of_detail": False,
            "collision": False,
            "export_morph_targets": True,
            "bake_material_inputs": unreal.FbxMaterialBakeMode.DISABLED,
        })
        os.makedirs(directory)
        fbx_path = os.path.join(directory, "Reference.fbx")
        task = unreal.AssetExportTask()
        task.set_editor_properties({
            "object": mesh,
            "filename": fbx_path,
            "exporter": unreal.SkeletalMeshExporterFBX(),
            "options": options,
            "automated": True,
            "prompt": False,
            "replace_identical": False,
            "write_empty_files": False,
        })
        if not unreal.Exporter.run_asset_export_task(task):
            fail("官方 FBX 导出器失败 " + str(list(task.get_editor_property("errors"))))

        if not os.path.isfile(fbx_path) or os.path.getsize(fbx_path) < 1024:
            fail("导出器未产生有效 FBX")

        with open(fbx_path, "rb") as source:
            if source.read(23) != b"Kaydara FBX Binary  \x00\x1a\x00":
                fail("导出结果不是 Blender 可读取的二进制 FBX")

        report = {
            "schemaVersion": 1,
            "mesh": mesh.get_path_name(),
            "skeleton": skeleton.get_path_name(),
            "engineVersion": unreal.SystemLibrary.get_engine_version(),
            "coordinateSystem": "UE left-handed X forward Y right Z up",
            "positionUnit": "centimeter",
            "rotationFormat": "quaternion XYZW",
            "componentSpace": "mesh reference pose space",
            "boneCount": len(bones),
            "lod0VertexCount": subsystem.get_num_verts(mesh, 0),
            "bones": bones,
        }
        from VerifySkeletalMeshFbx import inspect_fbx

        verification = inspect_fbx(fbx_path, report)
        exported_names = verification.pop("exportedBoneNames")
        for bone in bones:
            bone["fbxName"] = exported_names[bone["name"].casefold()]
        report["fbxVerification"] = verification
        json_path = os.path.join(directory, "Skeleton.json")
        with open(json_path, "x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=4, allow_nan=False)

        result = {"directory": directory, "fbx": fbx_path, "skeletonJson": json_path, "boneCount": len(bones), "vertexCount": report["lod0VertexCount"]}
        unreal.log("[BBB][SkeletalExport] " + json.dumps(result, ensure_ascii=False))
        return json.dumps(result, ensure_ascii=False)


_registration = Registration([BBBGenericEditorToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
