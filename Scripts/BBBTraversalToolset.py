import json
import os
import hashlib
import struct
import unreal
import toolset_registry
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_asset_write, require_write_access
from toolset_registry.registration import Registration
from editor_toolset.toolsets.blueprint import BlueprintTools

_fixture = []
_fixture_world = None
_samples = []
_sample_handle = None
_sample_until = 0.0


def _blueprint(path):
    """/** @param path 动画蓝图路径 @return 已检查的动画蓝图 */"""
    result = unreal.load_asset(path)
    if not isinstance(result, unreal.AnimBlueprint):
        raise RuntimeError("目标必须是动画蓝图 " + path)
    return result


def _pin(node, name):
    """/** @param node 图节点 @param name 真实引脚名 @return 唯一匹配的引脚 */"""
    pins = [pin for pin in node.list_all_pins() if str(pin.get_pin_name()) == name]
    if len(pins) != 1:
        raise RuntimeError("引脚不唯一 " + name + " " + str([str(pin.get_pin_name()) for pin in node.list_all_pins()]))
    return pins[0]


def _connect(source, destination):
    """/** @param source 输出引脚 @param destination 输入引脚 @return 无 */"""
    if not source.try_create_connection(destination):
        raise RuntimeError("引脚连接失败 " + str(source.get_pin_name()) + " -> " + str(destination.get_pin_name()))


def _create(graph, exact_tail, x, y):
    """/** @param graph 目标图 @param exact_tail 精确类型尾名 @param x 横坐标 @param y 纵坐标 @return 新节点 */"""
    types = [name for name in BlueprintTools.find_node_types(graph, exact_tail) if name.rsplit("|", 1)[-1] == exact_tail]
    if len(types) != 1:
        raise RuntimeError("节点类型不唯一 " + exact_tail + " " + str(types))
    return BlueprintTools.create_node(graph, types[0], unreal.IntPoint(x, y))


def _animation_signature(animation):
    """/** @param animation 动画序列 @return 骨骼轨道及必须保留的数据指纹 */"""
    digest = hashlib.sha256()
    model = animation.data_model_interface
    for name in model.get_bone_track_names():
        digest.update(str(name).encode("utf-8"))
        transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
        for transform in transforms:
            position = transform.translation
            rotation = transform.rotation
            scale = transform.scale3d
            digest.update(struct.pack("<10d", position.x, position.y, position.z,
                                      rotation.x, rotation.y, rotation.z, rotation.w, scale.x, scale.y, scale.z))
    excluded = {"DisableLHandIK", "DisableAimIK"}
    curves = {}
    library = unreal.AnimationLibrary
    for name in library.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT):
        if str(name) not in excluded:
            times, values = library.get_float_keys(animation, name)
            curves[str(name)] = [list(times), list(values)]
    return {"boneHash": digest.hexdigest(), "keys": model.get_number_of_keys(),
            "length": animation.get_play_length(), "skeleton": animation.get_skeleton().get_path_name(),
            "rootMotion": animation.get_editor_property("enable_root_motion"),
            "rootLock": animation.get_editor_property("force_root_lock"),
            "rootLockMode": str(animation.get_editor_property("root_motion_root_lock")),
            "additive": str(animation.get_editor_property("additive_anim_type")),
            "notifies": [str(event) for event in library.get_animation_notify_events(animation)],
            "syncMarkers": [str(marker) for marker in library.get_animation_sync_markers(animation)],
            "otherFloatCurves": curves}


def _ik_sample(animation, layer_class, montage):
    """/** @param animation 主动画实例 @param layer_class 链接层类 @param montage 当前动作 @return 运行时曲线和按现有图公式计算的输入权重 */"""
    result = {"montagePosition": animation.montage_get_position(montage) if montage else None,
              "mainCurves": {name: animation.get_curve_value(name) for name in ("DisableLHandIK", "DisableAimIK")}}
    layer = animation.get_linked_anim_layer_instance_by_class(layer_class)
    if layer is None:
        result["linkedLayer"] = None
        return result
    curves = {name: layer.get_curve_value(name) for name in ("DisableLHandIK", "DisableAimIK")}
    valid = layer.has_left_hand_ik_target()
    source_alpha = animation.get_editor_property("AimIKAlpha")
    locomotion_alpha = layer.get_editor_property("LocomotionAimIKAlpha")
    result.update({"linkedLayer": layer.get_path_name(), "layerCurves": curves, "validLeftTarget": valid,
                   "sourceAimAlpha": source_alpha, "locomotionAimAlpha": locomotion_alpha,
                   "calculatedLeftInputAlpha": 1 - curves["DisableLHandIK"] if valid else 0,
                   "calculatedAimInputAlpha": source_alpha * locomotion_alpha * (1 - curves["DisableAimIK"])})
    return result


@unreal.uclass()
class BBBTraversalToolset(unreal.ToolsetDefinition):
    """/** 检查和配置根运动翻越资产以及临时 PIE 验收场景 */"""

    @mcp_tool
    @staticmethod
    def configure_traversal_ik_transition(sequence_paths: list[str], base_path: str,
                                         expected_graph_signature: str, disable_seconds: float = 0.15,
                                         restore_seconds: float = 0.25, dry_run: bool = True,
                                         allow_dirty_sequences: bool = False) -> str:
        """
        /**
         * 为指定自有翻越序列配置平滑禁用曲线 并将整层旁路缩小为腿部旁路
         * @param sequence_paths            自有翻越动画序列
         * @param base_path                 基础链接动画蓝图
         * @param expected_graph_signature  调用前只读核对的骨骼控制图逻辑指纹
         * @param disable_seconds           开头退出握持和瞄准的秒数
         * @param restore_seconds           结尾恢复握持和瞄准的秒数
         * @param dry_run                   仅检查参数 签出和图结构
         * @param allow_dirty_sequences     明确允许保留并继续编辑目标动画的未保存改动
         * @return 曲线关键帧 编译保存结果和保留数据指纹
         */
        """
        if not sequence_paths or len(sequence_paths) > 16 or len(set(sequence_paths)) != len(sequence_paths):
            raise RuntimeError("需要一至十六条不重复动画")
        if not 0 < disable_seconds <= 1 or not 0 < restore_seconds <= 1:
            raise RuntimeError("平滑时间必须在零到一秒之间")
        paths = list(sequence_paths) + [base_path]
        if any(not path.startswith("/Game/_Project/") for path in paths):
            raise RuntimeError("仅允许修改自有资产")
        animations = [unreal.load_asset(path) for path in sequence_paths]
        if any(not isinstance(animation, unreal.AnimSequence) for animation in animations):
            raise RuntimeError("目标必须是动画序列")
        base = _blueprint(base_path)
        require_asset_write(animations + [base])
        dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if dirty.intersection(sequence_paths) and not allow_dirty_sequences:
            raise RuntimeError("目标动画存在未保存改动 请先协调该资产的编辑会话")
        before = [_animation_signature(animation) for animation in animations]
        report = {"dryRun": dry_run, "baseWasDirty": base_path in dirty, "sequences": []}
        for animation, signature in zip(animations, before):
            length = animation.get_play_length()
            if length <= disable_seconds + restore_seconds:
                raise RuntimeError("动画过短 无法容纳两段平滑过渡")
            keys = []
            for index in range(7):
                fraction = index / 6
                keys.append({"time": disable_seconds * fraction,
                             "value": fraction * fraction * (3 - 2 * fraction)})
            for index in range(7):
                fraction = index / 6
                keys.append({"time": length - restore_seconds + restore_seconds * fraction,
                             "value": 1 - fraction * fraction * (3 - 2 * fraction)})
            report["sequences"].append({"path": animation.get_path_name(), "length": length,
                                        "keys": keys, "preserved": signature})
        with toolset_registry.tool_raising_exceptions():
            graph = BlueprintTools.get_graph(base, "FullBody_SkeletalControls")
            snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
            if snapshot["logicSignature"] != expected_graph_signature:
                raise RuntimeError("骨骼控制图已经改变 必须重新只读核对")
            nodes = list(BlueprintTools.find_nodes(graph))
            def unique(node_class):
                found = [node for node in nodes if isinstance(node, node_class)]
                if len(found) != 1:
                    raise RuntimeError("图结构不唯一 " + str(node_class))
                return found[0]
            blend = unique(unreal.AnimGraphNode_BlendListByBool)
            fabrik = unique(unreal.AnimGraphNode_Fabrik)
            leg = unique(unreal.AnimGraphNode_LegIK)
            pose_input = unique(unreal.AnimGraphNode_LinkedInputPose)
            true_pin = _pin(blend, "BlendPose_0")
            existing = list(true_pin.list_connected_pins())
            if len(existing) != 1:
                raise RuntimeError("翻越分支姿势来源不唯一")
            source = existing[0].get_owning_node()
            already = isinstance(source, unreal.AnimGraphNode_ComponentToLocalSpace)
            if already:
                connected = list(_pin(source, "ComponentPose").list_connected_pins())
                if len(connected) != 1 or connected[0].get_owning_node() != fabrik:
                    raise RuntimeError("既有翻越分支并非左手 IK 后的腿部旁路")
            if not already and source != pose_input:
                raise RuntimeError("既有翻越分支不是原始输入 不自动覆盖未知结构")
            incoming = list(_pin(leg, "ComponentPose").list_connected_pins())
            if len(incoming) != 1 or incoming[0].get_owning_node() != fabrik:
                raise RuntimeError("腿部 IK 没有直接连接左手 IK")
            types = [name for name in BlueprintTools.find_node_types(graph, "从组件空间到本地")
                     if name.rsplit("|", 1)[-1] == "从组件空间到本地"]
            if not already and len(types) != 1:
                raise RuntimeError("组件空间转换节点类型不唯一 " + str(types))
            report["legBypassAlreadyConfigured"] = already
            if dry_run:
                return json.dumps(report, ensure_ascii=False)
            with unreal.ScopedEditorTransaction("翻越握持和瞄准曲线平滑过渡"):
                library = unreal.AnimationLibrary
                curve_type = unreal.RawCurveTrackTypes.RCT_FLOAT
                for animation, info, original in zip(animations, report["sequences"], before):
                    animation.modify()
                    for curve_name in ("DisableLHandIK", "DisableAimIK"):
                        name = unreal.Name(curve_name)
                        if name in library.get_animation_curve_names(animation, curve_type):
                            library.remove_curve(animation, name, False)
                        library.add_curve(animation, name, curve_type, False)
                        for key in info["keys"]:
                            library.add_float_curve_key(animation, name, key["time"], key["value"])
                        times, values = library.get_float_keys(animation, name)
                        if len(times) != len(info["keys"]) or any(abs(t - key["time"]) > 0.0001 or abs(v - key["value"]) > 0.0001
                                                                  for t, v, key in zip(times, values, info["keys"])):
                            raise RuntimeError("曲线写入结果与请求不一致 " + curve_name)
                    after = _animation_signature(animation)
                    changed = [name for name in original if original[name] != after[name]]
                    if changed:
                        raise RuntimeError("添加曲线改变了必须保留的数据 尚未保存 " + json.dumps(changed, ensure_ascii=False))
                if not already:
                    base.modify()
                    converter = BlueprintTools.create_node(graph, types[0], unreal.IntPoint(-244, -160))
                    _connect(_pin(fabrik, "Pose"), _pin(converter, "ComponentPose"))
                    true_pin.break_single_pin_link(existing[0])
                    _connect(_pin(converter, "Pose"), true_pin)
                unreal.BlueprintEditorLibrary.compile_blueprint(base)
                if base.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                    raise RuntimeError("动画层编译失败 尚未保存")
                for asset in animations + [base]:
                    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                        raise RuntimeError("保存失败 " + asset.get_path_name())
            report["saved"] = True
            report["boneAndMetadataUnchanged"] = True
            report["graphSignature"] = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))["logicSignature"]
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def remove_pie_traversal_obstacle() -> str:
        """
        /**
         * 删除本工具创建的临时障碍 用于验收目标失效后的动作退出
         * @return 是否成功删除临时障碍
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None or len(_fixture) < 2:
            raise RuntimeError("需要本工具创建的 PIE 障碍")
        actor = _fixture.pop(1)
        actor.destroy_actor()
        return json.dumps({"removed": not unreal.SystemLibrary.is_valid(actor)})

    @mcp_tool
    @staticmethod
    def prepare_pie_traversal_fixture(height: float, depth: float, blocked: bool = False) -> str:
        """
        /**
         * 在当前 PIE 创建临时地板和障碍 并安置本地玩家 不保存关卡
         * @param height 障碍高度 零表示无障碍
         * @param depth 障碍厚度
         * @param blocked 是否在上方增加阻挡以验收失败回退
         * @return 玩家和临时碰撞场景位置
         */
        """
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        global _fixture_world
        if world is None or not 0 <= height <= 300 or not 1 <= depth <= 600:
            raise RuntimeError("需要 PIE 世界和有效厘米尺寸")
        player = unreal.GameplayStatics.get_player_character(world, 0)
        if player is None:
            raise RuntimeError("PIE 没有本地角色")
        if _fixture_world != world:
            _fixture.clear()
        _fixture_world = world
        for actor in _fixture:
            if unreal.SystemLibrary.is_valid(actor):
                actor.destroy_actor()
        _fixture.clear()
        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
        origin = unreal.Vector(10000, 10000, 30000)
        definitions = [(unreal.Vector(10000, 10000, 29995), unreal.Vector(12, 12, 0.1))]
        if height > 0:
            definitions.append((unreal.Vector(10090 + depth / 2, 10000, 30000 + height / 2), unreal.Vector(depth / 100, 3, height / 100)))
        if blocked:
            definitions.append((unreal.Vector(10140, 10000, 30000 + height + 130), unreal.Vector(3, 3, 0.2)))
        for location, scale in definitions:
            transform = unreal.Transform(location=location, rotation=unreal.Rotator(), scale=scale)
            actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(player, unreal.StaticMeshActor, transform)
            if actor is None:
                raise RuntimeError("临时验收几何创建失败")
            mesh = actor.static_mesh_component
            mesh.set_mobility(unreal.ComponentMobility.MOVABLE)
            mesh.set_static_mesh(cube)
            mesh.set_collision_profile_name("BlockAll")
            mesh.set_mobility(unreal.ComponentMobility.STATIC)
            _fixture.append(actor)
        capsule = player.capsule_component
        half = capsule.get_scaled_capsule_half_height()
        movement = player.character_movement
        movement.stop_movement_immediately()
        player.set_actor_location(origin + unreal.Vector(0, 0, half + 2.5), False, True)
        player.set_actor_rotation(unreal.Rotator(), True)
        controller = player.get_controller()
        controller.set_control_rotation(unreal.Rotator())
        movement.set_movement_mode(unreal.MovementMode.MOVE_FALLING)
        return json.dumps({"player": player.get_path_name(), "height": height, "depth": depth, "blocked": blocked, "capsuleHalfHeight": half, "capsuleRadius": capsule.get_scaled_capsule_radius()}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def sample_pie_traversal(seconds: float = 5.0, include_ik_curves: bool = False) -> str:
        """
        /**
         * 异步按游戏时间采集动作 根骨 胶囊 移动模式和动画播放 不修改玩法状态
         * @param seconds 采样游戏秒数
         * @return 采样开始结果
         */
        """
        global _sample_handle, _sample_until
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None or not 0.1 <= seconds <= 15:
            raise RuntimeError("需要 PIE 和有效采样时长")
        if _sample_handle is not None:
            raise RuntimeError("上次采样尚未结束")
        _samples.clear()
        start = unreal.GameplayStatics.get_time_seconds(world)
        _sample_until = start + seconds
        layer_classes = []
        if include_ik_curves:
            for name in ("Rifle", "Unarmed"):
                path = "/Game/_Project/Characters/BBBC_UA/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_" + name
                layer_classes.append(_blueprint(path).generated_class())

        def tick(delta):
            global _sample_handle
            active_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
            if active_world != world:
                unreal.unregister_slate_post_tick_callback(_sample_handle)
                _sample_handle = None
                return
            now = unreal.GameplayStatics.get_time_seconds(world)
            if _samples and now - _samples[-1]["absoluteTime"] < 0.02:
                return
            player = unreal.GameplayStatics.get_player_character(world, 0)
            if player is None:
                return
            mesh = player.mesh
            animation = mesh.get_anim_instance()
            center = player.get_actor_location()
            root = mesh.get_socket_location("root")
            current = animation.get_current_active_montage()
            equipment = player.get_active_equipment()
            sample = {"time": now - start, "absoluteTime": now, "location": [center.x, center.y, center.z], "feetZ": center.z - player.capsule_component.get_scaled_capsule_half_height(), "rootZ": root.z, "yaw": player.get_actor_rotation().yaw, "mode": str(player.character_movement.get_editor_property("movement_mode")), "montage": current.get_path_name() if current else None, "traversing": animation.is_traversing(), "equipment": equipment.get_path_name() if equipment else None}
            if include_ik_curves:
                try:
                    for layer_class in layer_classes:
                        if animation.get_linked_anim_layer_instance_by_class(layer_class) is not None:
                            sample["ik"] = _ik_sample(animation, layer_class, current)
                            break
                except Exception as error:
                    sample["ikError"] = str(error)
            _samples.append(sample)
            if now >= _sample_until:
                unreal.unregister_slate_post_tick_callback(_sample_handle)
                _sample_handle = None

        _sample_handle = unreal.register_slate_post_tick_callback(tick)
        return json.dumps({"sampling": True, "seconds": seconds})

    @mcp_tool
    @staticmethod
    def get_pie_traversal_samples() -> str:
        """
        /**
         * @return 本轮基础验收样本与是否仍在运行
         */
        """
        return json.dumps({"running": _sample_handle is not None, "samples": _samples}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_traversal_blueprints(base_path: str, main_path: str, montage_paths: list[str]) -> str:
        """
        /**
         * 在 Base 纯配置中保存动画并建立全身输入链 翻越时跳过握持与地面修正
         * @param base_path 基础链接动画蓝图
         * @param main_path 主动画蓝图
         * @param montage_paths Vault 低攀爬 高攀爬三条蒙太奇
         * @return 编译和保存结果
         */
        """
        if len(montage_paths) != 3:
            raise RuntimeError("必须配置三种动作蒙太奇")
        base = _blueprint(base_path)
        main = _blueprint(main_path)
        require_asset_write([base, main])
        montages = [unreal.load_asset(path) for path in montage_paths]
        if any(not isinstance(asset, unreal.AnimMontage) for asset in montages):
            raise RuntimeError("动作配置必须为有效蒙太奇")
        names = ("TraversalVault", "TraversalClimbLow", "TraversalClimbHigh")
        event_graph = unreal.BlueprintEditorLibrary.find_event_graph(base)
        event_editor = unreal.BlueprintGraphEditor.get_graph_editor(event_graph)
        if event_editor.find_event_node(unreal.Name("TraversalRequested")):
            raise RuntimeError("已经存在翻越请求链 请先只读检查 防止重复构建")
        with toolset_registry.tool_raising_exceptions():
            for name in names:
                if name not in unreal.BlueprintEditorLibrary.list_member_variable_names(base, False):
                    BlueprintTools.add_object_variable(base, name, unreal.AnimMontage.static_class())
                BlueprintTools.set_variable_category(base, name, "Traversal")
            unreal.BlueprintEditorLibrary.compile_blueprint(base)
            default = unreal.get_default_object(base.generated_class())
            for name, asset in zip(names, montages):
                default.set_editor_property(name, asset)
            event = BlueprintTools.add_event(base, "TraversalRequested", unreal.IntPoint(0, 2200))
            owner = _create(event_graph, "GetOwningActor", 0, 2440)
            cast = _create(event_graph, "CastToBBBCharacter", 320, 2200)
            switch = _create(event_graph, "SwitchonEBBBTraversalAction", 600, 2200)
            _connect(_pin(event, "then"), _pin(cast, "execute"))
            _connect(_pin(owner, "ReturnValue"), _pin(cast, "Object"))
            _connect(_pin(cast, "then"), _pin(switch, "execute"))
            _connect(_pin(event, "Action"), _pin(switch, "Selection"))
            for index, (action, variable) in enumerate(zip(("Vault", "ClimbLow", "ClimbHigh"), names)):
                y = 2200 + index * 260
                make = _create(event_graph, "MakeBBBFullBodyMontageLocalControlPacket", 980, y + 80)
                submit = _create(event_graph, "SubmitInput", 1260, y)
                get_types = [name for name in BlueprintTools.find_node_types(event_graph, variable) if "获取" in name or "Get" in name.rsplit("|", 1)[-1]]
                if len(get_types) != 1:
                    raise RuntimeError("配置读取节点不唯一 " + variable + " " + str(get_types))
                getter = BlueprintTools.create_node(event_graph, get_types[0], unreal.IntPoint(740, y + 100))
                _connect(_pin(getter, variable), _pin(make, "Montage"))
                _connect(_pin(make, "BBBFullBodyMontageLocalControlPacket"), _pin(submit, "Packet"))
                _connect(_pin(cast, "AsBBBCharacter"), _pin(submit, "self"))
                _connect(_pin(switch, action), _pin(submit, "execute"))
            layer = BlueprintTools.get_graph(base, "FullBody_SkeletalControls")
            nodes = list(BlueprintTools.find_nodes(layer))
            outputs = [node for node in nodes if isinstance(node, unreal.AnimGraphNode_Root)]
            inputs = [node for node in nodes if isinstance(node, unreal.AnimGraphNode_LinkedInputPose)]
            if len(outputs) != 1 or len(inputs) != 1:
                raise RuntimeError("骨骼控制层输入输出不唯一")
            result = _pin(outputs[0], "Result")
            previous = list(result.list_connected_pins())
            if len(previous) != 1:
                raise RuntimeError("原骨骼控制层输出没有唯一姿势")
            blend = _create(layer, "按布尔混合姿势", 80, 40)
            traversing = _create(layer, "IsTraversing", -180, 300)
            result.break_single_pin_link(previous[0])
            _connect(_pin(inputs[0], "Pose"), _pin(blend, "BlendPose_0"))
            _connect(previous[0], _pin(blend, "BlendPose_1"))
            _connect(_pin(traversing, "ReturnValue"), _pin(blend, "bActiveValue"))
            _connect(_pin(blend, "Pose"), result)
            outputs[0].set_node_pos(unreal.IntPoint(440, 40))
            foot = BlueprintTools.get_graph(main, "ShouldEnableControlRig")
            foot_result = [node for node in BlueprintTools.find_nodes(foot) if isinstance(node, unreal.K2Node_FunctionResult)]
            if len(foot_result) != 1:
                raise RuntimeError("脚部开关函数返回不唯一")
            value = _pin(foot_result[0], "ReturnValue")
            old = list(value.list_connected_pins())
            if len(old) != 1:
                raise RuntimeError("脚部原开关没有唯一来源")
            active = _create(foot, "IsTraversing", 0, 500)
            negate = _create(foot, "NOTBoolean", 260, 500)
            both = _create(foot, "ANDBoolean", 500, 220)
            _connect(_pin(active, "ReturnValue"), _pin(negate, "A"))
            _connect(_pin(negate, "ReturnValue"), _pin(both, "B"))
            _connect(old[0], _pin(both, "A"))
            value.break_single_pin_link(old[0])
            _connect(_pin(both, "ReturnValue"), value)
            for blueprint in (base, main):
                unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
                if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
                    raise RuntimeError("翻越动画蓝图编译失败 " + blueprint.get_path_name())
                if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
                    raise RuntimeError("翻越动画蓝图保存失败 " + blueprint.get_path_name())
        return json.dumps({"base": base_path, "main": main_path, "montages": list(montage_paths), "saved": True}, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_traversal_editing_schema(base_path: str, main_path: str) -> str:
        """
        /**
         * 只读返回实际编辑器的翻越图表节点类型和动画编辑接口
         * @param base_path 基础链接动画蓝图
         * @param main_path 主动画蓝图
         * @return 图表路径 节点类型和工具接口
         */
        """
        base = _blueprint(base_path)
        main = _blueprint(main_path)
        event = unreal.BlueprintEditorLibrary.find_event_graph(base)
        report = {"eventGraph": event.get_path_name(), "nodeTypes": {}, "graphs": []}
        with toolset_registry.tool_raising_exceptions():
            for query in ("SubmitInput", "OwningActor", "CastToBBBCharacter", "FullBodyMontageLocalControlPacket", "SwitchonEBBBTraversalAction", "BlendListByBool", "IsTraversing"):
                report["nodeTypes"][query] = list(BlueprintTools.find_node_types(event, query))
            for blueprint in (base, main):
                for graph in BlueprintTools.list_graphs(blueprint):
                    if graph.get_name() in ("FullBody_SkeletalControls", "ShouldEnableControlRig", "EventGraph"):
                        report["graphs"].append(json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph)))
        report["motionWarpingProperties"] = unreal.RootMotionModifier_SkewWarp.__doc__
        report["notifyMethods"] = [name for name in dir(unreal.AnimationLibrary) if "notify" in name]
        report["baseVariables"] = list(unreal.BlueprintEditorLibrary.list_member_variable_names(base, False))
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_traversal_montages(sequence_paths: list[str], destination_paths: list[str], windows_json: str) -> str:
        """
        /**
         * 从根运动序列创建或配置全身翻越蒙太奇及官方 Skew Warp 窗口
         * @param sequence_paths 已检查的根运动序列
         * @param destination_paths 自有目录下的目标蒙太奇
         * @param windows_json 每条动画的窗口数组 含 start end target 及可选 bone
         * @return 保存的蒙太奇与窗口配置
         */
        """
        windows = json.loads(windows_json)
        if len(sequence_paths) != len(destination_paths) or len(windows) != len(sequence_paths):
            raise RuntimeError("源动画 目标和窗口数量必须一致")
        assets = [unreal.load_asset(path) for path in sequence_paths]
        for animation in assets:
            if not isinstance(animation, unreal.AnimSequence) or not animation.get_editor_property("enable_root_motion"):
                raise RuntimeError("源动画必须是有效根运动序列")
        if len(set(destination_paths)) != len(destination_paths):
            raise RuntimeError("目标蒙太奇路径必须唯一")
        for sequence, definitions in zip(assets, windows):
            if not isinstance(definitions, list) or not definitions:
                raise RuntimeError("每条动画必须配置 Warp 窗口数组")
            for window in definitions:
                if not isinstance(window, dict) or not window.get("target"):
                    raise RuntimeError("Warp 窗口必须明确目标名称")
                start = float(window["start"])
                end = float(window["end"])
                if not 0 <= start < end <= sequence.get_play_length():
                    raise RuntimeError("Warp 窗口超出动画时间")
        if any(not path.startswith("/Game/_Project/") for path in destination_paths):
            raise RuntimeError("蒙太奇目标必须位于自有资产目录")
        existing = [path for path in destination_paths if os.path.isfile(os.path.join(unreal.Paths.project_content_dir(), path[len("/Game/"):] + ".uasset"))]
        new = [path for path in destination_paths if path not in existing]
        require_asset_write(existing, new)
        report = []
        for sequence, path, definitions in zip(assets, destination_paths, windows):
            montage = unreal.load_asset(path)
            if montage is None:
                factory = unreal.AnimMontageFactory()
                factory.set_editor_property("source_animation", sequence)
                folder, name = path.rsplit("/", 1)
                montage = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimMontage, factory)
            if not isinstance(montage, unreal.AnimMontage):
                raise RuntimeError("创建蒙太奇失败 " + path)
            tracks = list(montage.get_editor_property("slot_anim_tracks"))
            if len(tracks) != 1:
                raise RuntimeError("翻越蒙太奇必须只有一个 FullBody 轨道")
            tracks[0].set_editor_property("slot_name", unreal.Name("FullBody"))
            montage.set_editor_property("slot_anim_tracks", tracks)
            library = unreal.AnimationLibrary
            track = "TraversalWarp"
            if library.is_valid_anim_notify_track_name(montage, track):
                library.remove_animation_notify_events_by_track(montage, track)
            if not library.is_valid_anim_notify_track_name(montage, track):
                library.add_animation_notify_track(montage, track)
            for window in definitions:
                start = float(window["start"])
                end = float(window["end"])
                notify = library.add_animation_notify_state_event(montage, track, start, end - start, unreal.AnimNotifyState_MotionWarping)
                modifier = unreal.new_object(unreal.RootMotionModifier_SkewWarp, outer=notify)
                modifier.set_editor_properties({"warp_target_name": unreal.Name(window["target"]), "warp_translation": True, "ignore_z_axis": False, "warp_rotation": bool(window.get("rotation", True)), "warp_to_feet_location": True, "subtract_remaining_root_motion": bool(window.get("subtract_remaining", False))})
                if window.get("bone"):
                    modifier.set_editor_properties({"warp_point_anim_provider": unreal.WarpPointAnimProvider.BONE, "warp_point_anim_bone_name": unreal.Name(window["bone"])})
                notify.set_editor_property("root_motion_modifier", modifier)
            if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
                raise RuntimeError("蒙太奇保存失败 " + path)
            if path in new and not unreal.SourceControl.mark_file_for_add(path, silent=True):
                raise RuntimeError("新蒙太奇未能加入 Perforce " + path)
            report.append({"montage": path, "sequence": sequence.get_path_name(), "windows": definitions})
        return json.dumps(report, ensure_ascii=False)


_registration = Registration([BBBTraversalToolset])

if __name__ == "__bbb_editor_script__":
    def register_after_reload(delta_seconds):
        _registration.unregister()
        _registration.register()
        unreal.unregister_slate_post_tick_callback(registration_handle)

    registration_handle = unreal.register_slate_post_tick_callback(register_after_reload)
