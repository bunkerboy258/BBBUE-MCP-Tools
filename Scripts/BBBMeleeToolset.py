import os
from pathlib import Path
import hashlib
import json
import struct
import unreal
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_asset_write
from toolset_registry.registration import Registration
from editor_toolset.toolsets.blueprint import BlueprintTools


_staging_root = None

def _new_targets(paths):
    """/** @param paths 尚不存在的目标包 @return 无 隔离任务允许重写已打开添加的本任务半成品 */"""
    if _staging_root is None:
        require_asset_write([], paths)
        return
    states = unreal.SourceControl.query_file_states(paths, silent=True, use_source_control_state_cache=False)
    existing = [path for path, state in zip(paths, states) if state.is_added]
    for path in paths:
        filename = Path(unreal.Paths.project_content_dir()).resolve() / (path.removeprefix("/Game/") + ".uasset")
        if filename.exists():
            raise RuntimeError("隔离目标已存在正式文件 " + path)
    require_asset_write(existing, [path for path in paths if path not in existing])

def _save(asset, new=False):
    """/** @param asset 目标自有资产 @param new 是否新建 @return 无 保存或添加失败直接报警 */"""
    if _staging_root is not None:
        if not new:
            raise RuntimeError("隔离制作阶段禁止保存任何已有资产")
        saved = unreal.BBBEquipmentAuthoringEditorLibrary.save_staged_equipment_asset(asset, str(_staging_root))
        if not saved:
            raise RuntimeError("隔离装备资产保存失败 " + asset.get_path_name())
        return
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError("近战资产保存失败 " + asset.get_path_name())
    if new and not unreal.SourceControl.mark_file_for_add(asset.get_path_name(), silent=True):
        raise RuntimeError("近战新资产未加入 Perforce " + asset.get_path_name())


def _bones_hash(animation):
    """/** @param animation 只读序列 @return 原始骨骼关键帧摘要 */"""
    digest = hashlib.sha256()
    for name in animation.data_model_interface.get_bone_track_names():
        digest.update(str(name).encode("utf-8"))
        for transform in unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name):
            digest.update(struct.pack("<10d", *transform.translation.to_tuple(),
                                     *transform.rotation.to_tuple(), *transform.scale3d.to_tuple()))
    return digest.hexdigest()


def _pin(node, name):
    """/** @param node 图节点 @param name 精确引脚名 @return 唯一引脚 */"""
    items = [pin for pin in node.list_all_pins() if str(pin.get_pin_name()) == name]
    if len(items) != 1:
        raise RuntimeError("近战图表引脚不唯一 " + name)
    return items[0]


@unreal.uclass()
class BBBMeleeToolset(unreal.ToolsetDefinition):
    """/** 创建独立近战装备美术配置并核验动画伤害窗口 */"""

    @mcp_tool
    @staticmethod
    def stage_character_aim_gate(blueprint_path: str, node_path: str, task_directory: str,
                                source_project_directory: str, expected_source_sha256: str) -> str:
        """
        /**
         * 在独立宿主内增加步枪与有效枪口条件 仅暂存供合并的目标包
         * @param blueprint_path 目标角色动画蓝图
         * @param node_path 唯一 Aim IK 动画节点
         * @param task_directory 独立项目 Saved/temp 下的任务目录
         * @param source_project_directory 正式项目根目录
         * @param expected_source_sha256 正式目标文件开始编辑时的摘要
         * @return 严格编译和暂存结果 不保存正式目录
         */
        """
        project = Path(unreal.Paths.project_dir()).resolve()
        source_project = Path(source_project_directory).resolve()
        task = Path(task_directory).resolve()
        package = blueprint_path.split(".", 1)[0]
        if project == source_project or not package.startswith("/Game/_Project/") \
                or any(part in {"", ".", ".."} for part in package[1:].split("/")):
            raise RuntimeError("门控暂存必须在独立项目中操作自有资产")
        if (project / "Saved/temp").resolve() not in task.parents:
            raise RuntimeError("暂存目录必须属于独立项目的任务目录")
        relative = package.removeprefix("/Game/") + ".uasset"
        source_file = source_project / "Content" / relative
        if hashlib.sha256(source_file.read_bytes()).hexdigest() != expected_source_sha256:
            raise RuntimeError("正式目标已变化 禁止覆盖并行修改")
        control = unreal.SourceControl
        if not control.is_enabled() or not control.is_available() or control.current_provider() != "Perforce":
            raise RuntimeError("暂存前必须连接正式项目的 Perforce 工作区")
        states = list(control.query_file_states([str(source_file)], silent=True, use_source_control_state_cache=False))
        if len(states) != 1 or not states[0].is_valid or states[0].is_unknown or states[0].is_deleted \
                or states[0].is_checked_out_other or states[0].is_conflicted \
                or not states[0].can_edit or not (states[0].is_checked_out or states[0].is_added):
            raise RuntimeError("正式目标必须已独占签出 暂存不代办源控操作")
        if states[0].is_source_controlled and not states[0].is_added and not states[0].is_current:
            raise RuntimeError("正式目标不是仓库最新版本 禁止暂存")
        blueprint = unreal.load_asset(blueprint_path)
        node = unreal.load_object(None, node_path)
        if not isinstance(blueprint, unreal.AnimBlueprint) or not node \
                or node.get_class().get_name() != "AnimGraphNode_AimIK" \
                or not node_path.startswith(blueprint.get_path_name() + ":"):
            raise RuntimeError("目标必须为指定动画蓝图中的 Aim IK 节点")
        report = json.loads(unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(blueprint))
        candidates = [item for graph in report["graphs"] if graph["path"] == node.get_outer().get_path_name()
                      for item in graph["nodes"] if item["nodeClass"] == node.get_class().get_path_name()]
        if len(candidates) != 1:
            raise RuntimeError("目标图中的 Aim IK 节点不唯一")
        aim = candidates[0]
        properties = aim.get("animNodeProperties", aim.get("animNode", {}))
        bias = properties.get("alphaScaleBias", {})
        clamp = properties.get("alphaScaleBiasClamp", {})
        if bias.get("scale", 1) != 1 or bias.get("bias", 0) != 0 \
                or clamp.get("scale", 1) != 1 or clamp.get("bias", 0) != 0 \
                or clamp.get("bInterpResult", False):
            raise RuntimeError("Aim IK 权重存在反转或延迟 需要先明确最终权重语义")
        changed = unreal.BBBBlueprintEditorLibrary.add_animation_alpha_gate(node, ["IsRifle", "HasMuzzle"])
        if changed <= 0:
            raise RuntimeError("Aim IK 布尔门控构造失败")
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("门控蓝图编译存在错误或警告 禁止暂存")
        saved = unreal.BBBEquipmentAuthoringEditorLibrary.save_staged_asset(blueprint, str(task))
        if not saved:
            raise RuntimeError("门控蓝图暂存失败")
        return json.dumps({"valid": True, "sourceSha256": expected_source_sha256,
            "stagedFile": saved, "stagedSha256": hashlib.sha256(Path(saved).read_bytes()).hexdigest(),
            "nodesAdded": changed, "condition": "IsRifle && HasMuzzle"}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_melee_sources(mesh_paths: list[str], animation_paths: list[str]) -> str:
        """
        /**
         * @param mesh_paths 只读候选网格
         * @param animation_paths 只读候选攻击序列
         * @return 网格边界及角色双手采样姿势
         */
        """
        result = {"meshes": [], "animations": []}
        for path in mesh_paths:
            mesh = unreal.load_asset(path)
            row = {"asset": path, "class": mesh.get_class().get_path_name()}
            if isinstance(mesh, unreal.StaticMesh):
                bounds = mesh.get_bounding_box()
                row["minimum"] = list(bounds.min.to_tuple())
                row["maximum"] = list(bounds.max.to_tuple())
            result["meshes"].append(row)
        for path in animation_paths:
            animation = unreal.load_asset(path)
            if not isinstance(animation, unreal.AnimSequence):
                raise RuntimeError("近战候选不是动画序列 " + path)
            length = animation.get_play_length()
            options = unreal.AnimPoseEvaluationOptions()
            options.evaluation_type = unreal.AnimDataEvalType.RAW
            samples = []
            for index in range(9):
                time = length * index / 8
                pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, time, options)
                bones = {}
                for name in ("hand_r", "hand_l"):
                    transform = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)
                    bones[name] = {"position": list(transform.translation.to_tuple()), "rotation": list(transform.rotation.to_tuple())}
                samples.append({"time": time, "bones": bones})
            result["animations"].append({"asset": path, "length": length,
                "skeleton": animation.get_skeleton().get_path_name(),
                "additive": str(animation.get_editor_property("additive_anim_type")),
                "rootMotion": animation.get_editor_property("enable_root_motion"), "samples": samples})
        return json.dumps(result, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_rigid_equipment_mesh(source_path: str, mesh_path: str, skeleton_path: str,
                                    sockets_json: str) -> str:
        """
        /**
         * @param source_path 只读静态网格源
         * @param mesh_path 不存在的自有骨骼网格包
         * @param skeleton_path 不存在的自有骨架包
         * @param sockets_json 根骨骼插槽名称和三维位置数组
         * @return 新网格骨架及材质骨骼检查结果
         */
        """
        definitions = json.loads(sockets_json)
        if not definitions or len({item["name"] for item in definitions}) != len(definitions):
            raise RuntimeError("插槽配置为空或重名")
        require_asset_write([], [mesh_path, skeleton_path])
        source = unreal.load_asset(source_path)
        if not isinstance(source, unreal.StaticMesh):
            raise RuntimeError("源资产必须是静态网格")
        socket_positions = {unreal.Name(item["name"]): unreal.Vector(*item["position"]) for item in definitions}
        mesh = unreal.BBBEquipmentAuthoringEditorLibrary.create_rigid_equipment_mesh(source, mesh_path, skeleton_path, socket_positions)
        if not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("引擎原生静态到骨骼网格转换失败")
        skeleton = mesh.get_editor_property("skeleton")
        names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(unreal.AnimPoseExtensions.get_reference_pose(skeleton))]
        if names != ["root"] or len(mesh.get_editor_property("materials")) != len(source.get_editor_property("static_materials")):
            raise RuntimeError("刚性装备骨骼或材质数量不一致")
        _save(skeleton, True)
        _save(mesh, True)
        return json.dumps({"mesh": mesh.get_path_name(), "skeleton": skeleton.get_path_name(), "bones": names,
                           "sockets": definitions, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_melee_attack(source_path: str, sequence_path: str, montage_path: str,
                            contact_start: float, contact_end: float) -> str:
        """
        /**
         * @param source_path 不修改的非叠加角色动画
         * @param sequence_path 不存在的自有攻击序列
         * @param montage_path 不存在的自有攻击蒙太奇
         * @param contact_start 伤害窗口开始秒数
         * @param contact_end 伤害窗口结束秒数
         * @return FullBody 蒙太奇及骨骼关键帧保真核验
         */
        """
        _new_targets([sequence_path, montage_path])
        source = unreal.load_asset(source_path)
        if not isinstance(source, unreal.AnimSequence) or source.get_editor_property("additive_anim_type") != unreal.AdditiveAnimationType.AAT_NONE:
            raise RuntimeError("攻击动画必须为普通完整姿势")
        length = source.get_play_length()
        if not (0 < contact_start < contact_end < length - 0.02):
            raise RuntimeError("伤害窗口必须在动画内部且保留收手段")
        sequence = unreal.BBBEquipmentAuthoringEditorLibrary.duplicate_equipment_animation(source, sequence_path)
        if not sequence:
            raise RuntimeError("攻击动画复制失败")
        sequence.set_editor_properties({"enable_root_motion": False, "force_root_lock": True})
        library = unreal.AnimationLibrary
        for name in ("DisableLHandIK", "DisableAimIK"):
            curve_type = unreal.RawCurveTrackTypes.RCT_FLOAT
            if library.does_curve_exist(sequence, name, curve_type):
                library.remove_curve(sequence, name, False)
            library.add_curve(sequence, name, curve_type, False)
            for time, value in ((0.0, 0.0), (0.06, 1.0), (length - 0.12, 1.0), (length, 0.0)):
                library.add_float_curve_key(sequence, name, time, value)
        if _bones_hash(source) != _bones_hash(sequence):
            raise RuntimeError("攻击复制改变了源骨骼关键帧")
        _save(sequence, True)
        factory = unreal.AnimMontageFactory()
        factory.set_editor_property("source_animation", sequence)
        folder, name = montage_path.rsplit("/", 1)
        montage = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimMontage, factory)
        tracks = list(montage.get_editor_property("slot_anim_tracks"))
        if len(tracks) != 1:
            raise RuntimeError("攻击蒙太奇必须为单 FullBody 轨道")
        tracks[0].set_editor_property("slot_name", unreal.Name("FullBody"))
        montage.set_editor_property("slot_anim_tracks", tracks)
        for prop in ("blend_in", "blend_out"):
            blend = montage.get_editor_property(prop)
            blend.set_editor_property("blend_time", 0.08)
            montage.set_editor_property(prop, blend)
        for track in list(library.get_animation_notify_track_names(montage)):
            library.remove_animation_notify_events_by_track(montage, track)
        library.add_animation_notify_track(montage, "Action")
        library.add_animation_notify_track(montage, "Contact")
        lifecycle = unreal.load_class(None, "/Script/ABBB_Evac.BBBCharacterEquipmentActionLifecycleLogicAnimNotifyState")
        contact = unreal.load_class(None, "/Script/ABBB_Evac.BBBCharacterEquipmentContactWindowLogicAnimNotifyState")
        if not lifecycle or not contact:
            raise RuntimeError("近战通知原生类不可用")
        library.add_animation_notify_state_event(montage, "Action", 0.0, length - 0.015, lifecycle)
        library.add_animation_notify_state_event(montage, "Contact", contact_start, contact_end - contact_start, contact)
        _save(montage, True)
        return json.dumps({"sequence": sequence_path, "montage": montage_path, "length": length,
            "contact": [contact_start, contact_end], "bonesUnchanged": True, "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def create_melee_equipment(mesh_path: str, montage_path: str, definition_path: str,
                               blueprint_path: str, animation_blueprint_path: str,
                               character_layer_path: str, catalog_path: str,
                               equipment_id: str, display_name: str, settings_json: str, register_catalog: bool = True) -> str:
        """
        /**
         * @param mesh_path 新装备骨骼网格
         * @param montage_path 新攻击蒙太奇
         * @param definition_path 不存在的装备定义
         * @param blueprint_path 不存在的装备演员蓝图
         * @param animation_blueprint_path 不存在的装备参考姿势动画蓝图
         * @param character_layer_path 已有同骨架角色动画层
         * @param catalog_path 已独占签出的装备目录
         * @param equipment_id 唯一装备标识
         * @param display_name 中文显示名
         * @param settings_json 攻击伤害间隔及挂接位置旋转
         * @param register_catalog 是否立即登记目录 隔离阶段必须关闭
         * @return 创建的装备类及严格编译保存结果
         */
        """
        require_asset_write([catalog_path] if register_catalog else [], [definition_path, blueprint_path, animation_blueprint_path])
        settings = json.loads(settings_json)
        mesh = unreal.load_asset(mesh_path)
        montage = unreal.load_asset(montage_path)
        layer = unreal.load_asset(character_layer_path)
        catalog = unreal.load_asset(catalog_path)
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        classes = list(catalog.get_editor_property("equipment_classes"))
        for entry in classes:
            definition = unreal.get_default_object(entry).get_editor_property("definition")
            if definition and str(definition.get_editor_property("equipment_id")) == equipment_id:
                raise RuntimeError("装备目录已经包含同名标识")
        factory = unreal.AnimBlueprintFactory()
        factory.set_editor_properties({"parent_class": unreal.load_class(None, "/Script/ABBB_Evac.BBBMeleeAnimInstance"),
            "target_skeleton": mesh.get_editor_property("skeleton"), "preview_skeletal_mesh": mesh})
        folder, name = animation_blueprint_path.rsplit("/", 1)
        animation = tools.create_asset(name, folder, unreal.AnimBlueprint, factory)
        graph = BlueprintTools.get_graph(animation, "AnimGraph")
        outputs = [node for node in BlueprintTools.find_nodes(graph) if isinstance(node, unreal.AnimGraphNode_Root)]
        types = BlueprintTools.find_node_types(graph, "参考姿势")
        matches = [value for value in types if "本地空间" in value or "Local Space" in value]
        if len(matches) != 1 or len(outputs) != 1:
            raise RuntimeError("参考姿势节点类型或输出不唯一 " + str(types))
        pose = BlueprintTools.create_node(graph, matches[0], unreal.IntPoint(-240, 0))
        if not _pin(pose, "Pose").try_create_connection(_pin(outputs[0], "Result")):
            raise RuntimeError("装备参考姿势图连接失败")
        unreal.BlueprintEditorLibrary.compile_blueprint(animation)
        if animation.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("装备动画蓝图编译未通过")
        _save(animation, True)
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.load_class(None, "/Script/ABBB_Evac.BBBMeleeDefinition"))
        folder, name = definition_path.rsplit("/", 1)
        definition = tools.create_asset(name, folder, None, factory)
        offset = unreal.Transform(location=unreal.Vector(*settings["position"]),
            rotation=unreal.Rotator(*settings["rotation"]))
        definition.set_editor_properties({"equipment_id": unreal.Name(equipment_id), "display_name": unreal.Text(display_name),
            "description": unreal.Text("单次近战攻击 装备通知控制伤害窗口"), "equipment_mesh": mesh,
            "equipment_animation_class": animation.generated_class(), "character_animation_layer_class": layer.generated_class(),
            "attack_montage": montage, "spawn_offset": offset, "damage": settings["damage"],
            "trace_radius": settings["radius"], "attack_interval": settings["interval"]})
        _save(definition, True)
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", unreal.load_class(None, "/Script/ABBB_Evac.BBBMeleeEquipment"))
        folder, name = blueprint_path.rsplit("/", 1)
        blueprint = tools.create_asset(name, folder, unreal.Blueprint, factory)
        defaults = unreal.get_default_object(blueprint.generated_class())
        defaults.set_editor_property("definition", definition)
        component = defaults.get_component_by_class(unreal.SkeletalMeshComponent)
        component.set_editor_property("skeletal_mesh_asset", mesh)
        component.set_editor_property("anim_class", animation.generated_class())
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("近战装备演员蓝图编译未通过")
        _save(blueprint, True)
        if register_catalog:
            classes.append(blueprint.generated_class())
            catalog.set_editor_property("equipment_classes", classes)
            _save(catalog)
        return json.dumps({"definition": definition_path, "blueprint": blueprint_path,
            "animation": animation_blueprint_path, "catalogCount": len(classes), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def validate_melee_equipment(definition_path: str, blueprint_path: str, source_animation_path: str) -> str:
        """
        /**
         * @param definition_path 近战装备定义
         * @param blueprint_path 实际装备蓝图
         * @param source_animation_path 不修改的原始角色攻击序列
         * @return 骨骼轨道保真 曲线 通知 图表与网格配置检查结果
         */
        """
        definition = unreal.load_asset(definition_path)
        blueprint = unreal.load_asset(blueprint_path)
        montage = definition.get_editor_property("attack_montage")
        sequence = montage.get_editor_property("slot_anim_tracks")[0].get_editor_property("anim_track").get_editor_property("anim_segments")[0].get_editor_property("anim_reference")
        source = unreal.load_asset(source_animation_path)
        mesh = definition.get_editor_property("equipment_mesh")
        animation_class = definition.get_editor_property("equipment_animation_class")
        animation = unreal.BlueprintEditorLibrary.get_blueprint_asset(animation_class)
        defaults = unreal.get_default_object(blueprint.generated_class())
        component = defaults.get_component_by_class(unreal.SkeletalMeshComponent)
        if defaults.get_editor_property("definition") != definition or component.get_editor_property("skeletal_mesh_asset") != mesh:
            raise RuntimeError("装备默认对象的配置与预览网格不一致")
        if component.get_editor_property("anim_class") != animation_class:
            raise RuntimeError("装备默认动画类不一致")
        if _bones_hash(source) != _bones_hash(sequence) or sequence.get_editor_property("enable_root_motion"):
            raise RuntimeError("攻击骨骼轨道或根运动不一致")
        curves = {}
        for name in ("DisableLHandIK", "DisableAimIK"):
            times, values = unreal.AnimationLibrary.get_float_keys(sequence, name)
            if len(times) != 4 or list(values) != [0.0, 1.0, 1.0, 0.0]:
                raise RuntimeError("攻击 IK 渐变曲线错误 " + name)
            curves[name] = {"times": list(times), "values": list(values)}
        events = []
        for event in unreal.AnimationLibrary.get_animation_notify_events(montage):
            instance = event.get_editor_property("notify_state_class")
            events.append({"class": instance.get_class().get_path_name() if instance else "",
                "time": unreal.AnimationLibrary.get_anim_notify_event_trigger_time(event),
                "duration": unreal.AnimationLibrary.get_anim_notify_event_duration(event)})
        if len(events) != 2 or not any("ActionLifecycle" in event["class"] for event in events) or not any("ContactWindow" in event["class"] for event in events):
            raise RuntimeError("动作生命周期或伤害窗口通知配置不正确")
        layers = []
        layer_class = definition.get_editor_property("character_animation_layer_class")
        while layer_class:
            layer = unreal.BlueprintEditorLibrary.get_blueprint_asset(layer_class)
            if layer is None:
                break
            layers.append(layer)
            report = json.loads(unreal.BBBBlueprintEditorLibrary.export_animation_blueprint_graphs(layer))
            layer_class = unreal.load_class(None, report["parentClass"])
        compiled = []
        for asset in [*reversed(layers), blueprint, animation]:
            unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            if asset.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError("近战蓝图编译存在错误或警告 " + asset.get_path_name())
            compiled.append(asset.get_path_name())
        if not unreal.BBBEquipmentAuthoringEditorLibrary.run_melee_checks():
            raise RuntimeError("近战真实资产与运行链路验收未通过")
        return json.dumps({"valid": True, "definition": definition_path, "bonesUnchanged": True,
            "curves": curves, "notifies": events, "rootMotion": False, "runtimeChecks": True,
            "compiledBlueprints": compiled}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def register_melee_equipment(catalog_path: str, blueprint_path: str) -> str:
        """
        /**
         * @param catalog_path 已独占签出的现有装备目录
         * @param blueprint_path 已验证并合入的近战装备蓝图
         * @return 登记后的装备总数 不修改已有条目
         */
        """
        require_asset_write([catalog_path])
        blueprint = unreal.load_asset(blueprint_path)
        catalog = unreal.load_asset(catalog_path)
        entry = blueprint.generated_class()
        definition = unreal.get_default_object(entry).get_editor_property("definition")
        if not definition or definition.get_class().get_path_name() != "/Script/ABBB_Evac.BBBMeleeDefinition":
            raise RuntimeError("登记对象不是具体近战装备")
        classes = list(catalog.get_editor_property("equipment_classes"))
        identity = definition.get_editor_property("equipment_id")
        if any(unreal.get_default_object(value).get_editor_property("definition").get_editor_property("equipment_id") == identity for value in classes):
            raise RuntimeError("装备目录已包含同名标识")
        classes.append(entry)
        catalog.set_editor_property("equipment_classes", classes)
        _save(catalog)
        return json.dumps({"registered": True, "catalogCount": len(classes), "id": str(identity)})


_registration = Registration([BBBMeleeToolset])
if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)
    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)


if __name__ == "__main__":
    request_path = os.environ.get("BBB_MELEE_REQUEST")
    if not request_path:
        raise RuntimeError("命令行制作必须显式提供 BBB_MELEE_REQUEST")
    request_file = Path(request_path).resolve()
    temporary = (Path(unreal.Paths.project_saved_dir()).resolve() / "temp").resolve()
    if temporary not in request_file.parents:
        raise RuntimeError("隔离制作请求必须位于本项目 Saved/temp")
    request = json.loads(request_file.read_text(encoding="utf-8"))
    results = []
    operation = request.get("operation", "create")
    if operation == "create":
        _staging_root = request_file.parent
        results.append(json.loads(BBBMeleeToolset.create_rigid_equipment_mesh(**request["mesh"])))
        results.append(json.loads(BBBMeleeToolset.create_melee_attack(**request["attack"])))
        arguments = dict(request["equipment"])
        arguments["register_catalog"] = False
        results.append(json.loads(BBBMeleeToolset.create_melee_equipment(**arguments)))
    if operation not in ("create", "register", "verify"):
        raise RuntimeError("未知近战操作")
    results.append(json.loads(BBBMeleeToolset.validate_melee_equipment(request["equipment"]["definition_path"],
        request["equipment"]["blueprint_path"], request["attack"]["source_path"])))
    if operation == "register":
        results.append(json.loads(BBBMeleeToolset.register_melee_equipment(request["equipment"]["catalog_path"], request["equipment"]["blueprint_path"])))
    (request_file.parent / "result.json").write_text(json.dumps({"success": True, "operation": operation, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    unreal.log("[BBBMelee] ISOLATED_AUTHORING_SUCCESS " + operation)
