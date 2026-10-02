import json
import math
import builtins

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools
from toolset_registry.helpers import require_editable


def sample_runtime(action, seconds, equipment_class_path):
    """
    /**
     * 通过现有调试输入入口切换装备 或按帧采样真实动画与镜头
     * @param action		start status equip
     * @param seconds		采样游戏秒数
     * @param equipment_class_path	装备调试注入的类路径
     * @return 采样状态或调试演员路径
     */
    """
    key = "BBB_WEAPON_HANDLING_PROBE"
    state = getattr(builtins, key, None)
    if action == "status":
        if not state:
            return {"state": "idle"}
        samples = state["samples"]
        events = []
        modes = {}
        for index, sample in enumerate(samples):
            mode_key = str((sample["aiming"], sample["mode"], sample.get("follow"), sample.get("backwardAlpha")))
            modes[mode_key] = modes.get(mode_key, 0) + 1
            if index > 0 and sample.get("shot") != samples[index - 1].get("shot"):
                events.append({"time": sample["time"], "shot": sample.get("shot"),
                    "aiming": sample["aiming"], "mode": sample["mode"],
                    "next": samples[min(index + 1, len(samples) - 1)]})
        return {"state": state["state"], "errors": state["errors"], "sampleCount": len(samples),
            "first": samples[:1], "last": samples[-1:], "shotEvents": events, "modes": modes,
            "peakCharacter": [max((abs(s["characterOffset"][axis]) for s in samples), default=0) for axis in (0, 1)],
            "peakCamera": [max((abs(s["camera"][axis]) for s in samples), default=0) for axis in (0, 1)]}
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        raise RuntimeError("需要已开始的 PIE")
    if action == "equip":
        equipment_class = unreal.load_class(None, equipment_class_path)
        if equipment_class is None:
            raise RuntimeError("装备类不存在")
        debug_class = unreal.load_class(None, "/Game/BBBC_UA/Debug/Equipment/BP_EquipmentDebug.BP_EquipmentDebug_C")
        if debug_class is None:
            raise RuntimeError("现有装备注入调试蓝图不存在")
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(world, debug_class, unreal.Transform())
        if actor is None:
            raise RuntimeError("PIE 装备注入演员创建失败")
        actor.set_editor_property("EquipmentClass", equipment_class)
        return {"actor": actor.get_path_name(), "equipment": equipment_class_path}
    if action != "start" or seconds <= 0 or seconds > 60:
        raise RuntimeError("采样动作或时长无效")
    if state and state.get("state") == "running":
        raise RuntimeError("已有采样正在运行")
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    mesh = pawn.get_editor_property("Mesh")
    main = mesh.get_anim_instance()
    layer_class = unreal.load_class(None, "/Game/BBBC_UA/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_Rifle.ABP_BBB_LocomotionLayer_Rifle_C")
    start = unreal.GameplayStatics.get_time_seconds(world)
    state = {"state": "running", "duration": seconds, "samples": [], "errors": []}
    setattr(builtins, key, state)
    previous = [-1.0]

    def tick(delta_seconds):
        try:
            current_world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
            if current_world != world:
                raise RuntimeError("采样期间 PIE 已结束")
            time = unreal.GameplayStatics.get_time_seconds(world) - start
            if time == previous[0]:
                return
            previous[0] = time
            layer = main.get_linked_anim_layer_instance_by_class(layer_class)
            weapon = main.try_get_weapon_anim_instance()
            offset = main.get_aim_offset_degrees()
            camera = pawn.get_controller().get_control_rotation()
            sample = {"time": time, "aiming": main.is_aiming(), "mode": str(main.get_editor_property("SourceMovementMode")),
                "characterOffset": [offset.x, offset.y], "camera": [camera.pitch, camera.yaw, camera.roll],
                "hand": str(mesh.get_socket_location("hand_r")), "elbow": str(mesh.get_socket_location("lowerarm_r"))}
            if isinstance(weapon, unreal.BBBRifleAnimInstance):
                sample.update({"weapon": weapon.get_path_name(), "shot": weapon.get_fire_sequence(), "shotTime": weapon.get_time_since_last_fire_seconds()})
            if layer:
                sample["follow"] = layer.get_editor_property("WeaponAimFollowSpeed")
                sample["backwardAlpha"] = layer.get_editor_property("WeaponBackwardRecoilAlpha")
                sample["recoilTime"] = layer.get_editor_property("WeaponRecoilTime")
                sway = layer.get_editor_property("WeaponAimOffsetDegrees")
                sample["aimOffset"] = [sway.x, sway.y]
            state["samples"].append(sample)
            if time >= seconds:
                state["state"] = "finished"
                unreal.unregister_slate_post_tick_callback(handle)
        except Exception as error:
            state["state"] = "failed"
            state["errors"].append(str(error))
            unreal.unregister_slate_post_tick_callback(handle)

    handle = unreal.register_slate_post_tick_callback(tick)
    return {"state": "running", "duration": seconds}


class _Graph:
    def __init__(self, graph):
        self.graph = graph
        self.editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        self.nodes = []

    def place(self, node):
        if node is None:
            raise RuntimeError("创建持枪图表节点失败")
        index = len(self.nodes)
        node.set_node_pos(unreal.IntPoint((index % 6) * 300, (index // 6) * 220))
        self.nodes.append(node)
        return node

    def call(self, name, target=None, inputs=None):
        path = name if name.startswith("/Script/") else "/Script/Engine.KismetMathLibrary." + name
        node = self.place(self.editor.add_call_function_node(path))
        if target is not None:
            self.link(target, node.find_input_pin("self"))
        for key, value in (inputs or {}).items():
            pin = node.find_input_pin(key)
            if isinstance(value, unreal.BlueprintGraphPin):
                self.link(value, pin)
                continue
            if not pin.set_pin_value(str(value)):
                raise RuntimeError("引脚默认值写入失败 " + name + "." + key)
        return node

    def out(self, node, name="ReturnValue"):
        matches = [p for p in node.list_output_pins() if str(p.get_pin_name()).replace(" ", "") == name.replace(" ", "")]
        if len(matches) != 1:
            raise RuntimeError("输出引脚缺失 " + node.get_name() + "." + name + " " + str([str(p.get_pin_name()) for p in node.list_output_pins()]))
        return matches[0]

    def link(self, output, input_pin):
        if not output.is_valid() or not input_pin.is_valid() or not output.try_create_connection(input_pin):
            raise RuntimeError("持枪图表连线失败 " + str(output) + " -> " + str(input_pin))

    def get(self, name, target=None, class_path=""):
        node = self.place(self.editor.add_get_member_variable_node(name, class_path))
        if target is not None:
            inputs = list(node.list_input_pins())
            if not inputs:
                self.editor.remove_nodes([node])
                available = list(self.editor.list_available_nodes([]))
                matches = [n for n in available if n.rsplit("|", 1)[-1] in ("PropertyAccess", "属性存取")]
                if len(matches) != 1:
                    raise RuntimeError("无法创建属性访问节点 " + str(matches))
                node = self.place(self.editor.create_node_from_name(matches[0], unreal.Vector2D(), []))
                if not unreal.BBBBlueprintEditorLibrary.set_property_access_path(node, ["GetBBBMainAnimInstanceThreadSafe", name]):
                    raise RuntimeError("主角色属性访问路径设置失败 " + name)
                return self.out(node, "Value")
            self.link(target, node.find_input_pin("self"))
        return self.out(node, name)

    def set(self, name, value, execute):
        node = self.place(self.editor.add_set_member_variable_node(name))
        self.link(execute, node.find_execute_pin())
        pin = node.find_input_pin(name)
        if isinstance(value, unreal.BlueprintGraphPin):
            self.link(value, pin)
        if not isinstance(value, unreal.BlueprintGraphPin):
            if not pin.set_pin_value(str(value)):
                raise RuntimeError("持枪变量默认值设置失败 " + name)
        return node.find_then_pin()

    def binary(self, name, a, b):
        return self.out(self.call(name, inputs={"A": a, "B": b}))

    def select(self, a, b, condition):
        return self.out(self.call("SelectFloat", inputs={"A": a, "B": b, "bPickA": condition}))

    def break_struct(self, value, struct_name):
        available = list(self.editor.list_available_nodes([value]))
        matches = [name for name in available if name.rsplit("|", 1)[-1] == "Break" + struct_name]
        if len(matches) != 1:
            raise RuntimeError("无法唯一定位结构拆分节点 " + struct_name + " " + str(matches))
        node = self.place(self.editor.create_node_from_name(matches[0], unreal.Vector2D(), [value]))
        for pin in node.list_input_pins():
            if value.can_create_connection(pin):
                self.link(value, pin)
                return node
        raise RuntimeError("结构拆分输入缺失 " + struct_name)


def _function(blueprint, name):
    graph = BlueprintTools.add_function_graph(blueprint, name)
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    nodes = list(editor.list_all_nodes())
    editor.remove_nodes([node for node in nodes if not isinstance(node, (unreal.K2Node_FunctionEntry, unreal.K2Node_FunctionResult))])
    for node in editor.list_all_nodes():
        for pin in node.list_all_pins():
            pin.break_pin_links()
    return _Graph(graph)


def _rifle_source(g, character, execute):
    weapon = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance", character))
    available = list(g.editor.list_available_nodes([weapon]))
    matches = [name for name in available if name.rsplit("|", 1)[-1] == "CastToBBBRifleAnimInstance"]
    if len(matches) != 1:
        raise RuntimeError("无法创建步枪动画类型检查 " + str(matches))
    cast = g.place(g.editor.create_node_from_name(matches[0], unreal.Vector2D(), [weapon]))
    g.link(weapon, cast.find_input_pin("Object"))
    g.link(execute, cast.find_execute_pin())
    return cast, g.out(cast, "AsBBBRifleAnimInstance")


def _rifle_get(g, rifle, name):
    return g.out(g.call("/Script/ABBB_Evac.BBBRifleAnimInstance." + name, rifle))


def _aim_air(g, character):
    aiming = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.IsAiming", character))
    mode = g.get("SourceMovementMode", character, "/Script/ABBB_Evac.BBBAnimInstance")
    available = list(g.editor.list_available_nodes([mode]))
    matches = [name for name in available if name.rsplit("|", 1)[-1] in ("Equal(Enum)", "==(Enum)", "等于(枚举)", "等于（枚举）", "==(枚举)")]
    if len(matches) != 1:
        raise RuntimeError("无法唯一定位枚举比较 " + str([n for n in available if "Enum" in n or "枚举" in n][-30:]))
    equal = g.place(g.editor.create_node_from_name(matches[0], unreal.Vector2D(), [mode]))
    g.link(mode, equal.find_input_pin("A"))
    if not equal.find_input_pin("B").set_pin_value("MOVE_Falling"):
        raise RuntimeError("腾空状态枚举写入失败")
    falling = g.out(equal)
    return aiming, falling


def configure_animation_handling(blueprint_path, animation_path):
    """
    /**
     * 用步枪只读快照重建角色持枪表现函数与逐枪加法动画层
     * @param blueprint_path	角色基础动画层资产
     * @param animation_path	向后冲击的加法动画序列
     * @return 编译结果与实际节点数量 不自动保存
     */
    """
    blueprint = unreal.load_asset(blueprint_path)
    animation = unreal.load_asset(animation_path)
    require_editable(blueprint)
    variables = {str(n) for n in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint, False)}
    for name, kind in (("WeaponAimFollowSpeed", "float"), ("WeaponAimOffsetDegrees", "Vector2D"), ("WeaponRecoilTime", "float"), ("WeaponBackwardRecoilAlpha", "float")):
        if name not in variables:
            BlueprintTools.add_variable(blueprint, name, kind)

    g = _function(blueprint, "UpdateWeaponHandling")
    g.editor.set_is_thread_safe_function(True)
    execute = g.editor.find_graph_entry_pin()
    character = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.GetBBBMainAnimInstanceThreadSafe"))
    impulse = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.GetAimOffsetDegrees", character))
    execute = g.set("WeaponAimFollowSpeed", 18, execute)
    execute = g.set("WeaponAimOffsetDegrees", impulse, execute)
    execute = g.set("WeaponRecoilTime", 1, execute)
    execute = g.set("WeaponBackwardRecoilAlpha", 0, execute)
    cast, rifle = _rifle_source(g, character, execute)
    execute = cast.find_then_pin()
    aiming, falling = _aim_air(g, character)
    hip = g.break_struct(_rifle_get(g, rifle, "GetHipFireSettings"), "BBBRifleHandlingSettings")
    ads = g.break_struct(_rifle_get(g, rifle, "GetAimFireSettings"), "BBBRifleHandlingSettings")
    air = g.break_struct(_rifle_get(g, rifle, "GetAirborneModifiers"), "BBBRifleAirborneModifiers")

    def field(name):
        return g.select(g.out(ads, name), g.out(hip, name), aiming)

    def scale(name):
        return g.select(g.out(air, name), 1, falling)

    follow = g.binary("Multiply_DoubleDouble", field("AimFollowSpeed"), scale("AimFollowScale"))
    recoil = g.binary("Multiply_DoubleDouble", field("BackwardRecoilAlpha"), scale("BackwardRecoilScale"))
    recoil = g.out(g.call("FClamp", inputs={"Value": recoil, "Min": 0, "Max": 1}))
    sequence = _rifle_get(g, rifle, "GetFireSequence")
    fired = g.binary("Greater_IntInt", sequence, 0)
    reloading = _rifle_get(g, rifle, "IsReloading")
    recoil = g.select(0, g.select(recoil, 0, fired), reloading)
    elapsed = _rifle_get(g, rifle, "GetTimeSinceLastFireSeconds")
    time = _rifle_get(g, rifle, "GetSnapshotTimeSeconds")
    sway_parts = []
    hip_amplitude = g.call("BreakVector2D", inputs={"InVec": g.out(hip, "SwayAmplitudeDegrees")})
    ads_amplitude = g.call("BreakVector2D", inputs={"InVec": g.out(ads, "SwayAmplitudeDegrees")})
    hip_frequency = g.call("BreakVector2D", inputs={"InVec": g.out(hip, "SwayFrequency")})
    ads_frequency = g.call("BreakVector2D", inputs={"InVec": g.out(ads, "SwayFrequency")})
    for axis in ("X", "Y"):
        amplitude = g.select(g.out(ads_amplitude, axis), g.out(hip_amplitude, axis), aiming)
        frequency = g.select(g.out(ads_frequency, axis), g.out(hip_frequency, axis), aiming)
        phase = g.binary("Multiply_DoubleDouble", time, g.binary("Multiply_DoubleDouble", frequency, scale("SwayFrequencyScale")))
        phase = g.binary("Multiply_DoubleDouble", phase, math.tau)
        wave = g.out(g.call("Sin", inputs={"A": phase}))
        sway_parts.append(g.binary("Multiply_DoubleDouble", wave, g.binary("Multiply_DoubleDouble", amplitude, scale("SwayAmplitudeScale"))))
    sway = g.out(g.call("MakeVector2D", inputs={"X": sway_parts[0], "Y": sway_parts[1]}))
    offset = g.binary("Add_Vector2DVector2D", impulse, sway)
    execute = g.set("WeaponAimFollowSpeed", follow, execute)
    execute = g.set("WeaponAimOffsetDegrees", offset, execute)
    execute = g.set("WeaponRecoilTime", elapsed, execute)
    g.set("WeaponBackwardRecoilAlpha", recoil, execute)

    event_graph = BlueprintTools.add_function_graph(blueprint, "BlueprintThreadSafeUpdateAnimation")
    event_editor = unreal.BlueprintGraphEditor.get_graph_editor(event_graph)
    for node in list(event_editor.list_all_nodes()):
        if str(node.get_node_title()).replace(" ", "").replace("\n", "") != "UpdateWeaponHandling":
            continue
        predecessors = list(node.find_execute_pin().list_connected_pins())
        successors = list(node.find_then_pin().list_connected_pins())
        event_editor.remove_nodes([node])
        for predecessor in predecessors:
            for successor in successors:
                if not predecessor.try_create_connection(successor):
                    raise RuntimeError("旧持枪更新节点清理失败")
    entry = event_editor.find_graph_entry_pin()
    connections = list(entry.list_connected_pins())
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    update = event_editor.add_call_function_node(blueprint.generated_class().get_path_name() + ".UpdateWeaponHandling")
    if update is None:
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        update = event_editor.add_call_function_node(blueprint.generated_class().get_path_name() + ".UpdateWeaponHandling")
    entry.break_pin_links()
    if not entry.try_create_connection(update.find_execute_pin()):
        raise RuntimeError("线程安全更新入口连接失败")
    for pin in connections:
        if not update.find_then_pin().try_create_connection(pin):
            raise RuntimeError("现有线程安全更新链恢复失败")

    aim_nodes = []
    for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        aim_nodes.extend(node for node in editor.list_all_nodes() if node.get_class().get_name() == "AnimGraphNode_AimIK")
    if len(aim_nodes) != 1:
        raise RuntimeError("AimIK 节点数量不为一 " + str(len(aim_nodes)))
    library = unreal.BBBBlueprintEditorLibrary
    if not library.bind_animation_node_input(aim_nodes[0], "AimFollowSpeed", ["WeaponAimFollowSpeed"]):
        raise RuntimeError("枪口跟随速度连接失败")
    if not library.bind_animation_node_input(aim_nodes[0], "AimOffsetDegrees", ["WeaponAimOffsetDegrees"]):
        raise RuntimeError("枪口角度与摇摆连接失败")
    if not library.configure_timed_additive_layer(blueprint, "FullBodyRecoil", animation, ["WeaponRecoilTime"], ["WeaponBackwardRecoilAlpha"]):
        raise RuntimeError("逐枪后震动画层重建失败")
    if "RecoilAdditiveAnimation" in variables:
        BlueprintTools.remove_variable(blueprint, "RecoilAdditiveAnimation")
    for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        for node in list(editor.list_all_nodes()):
            if node.get_class().get_name() != "K2Node_PropertyAccess":
                continue
            path = list(library.get_property_access_path(node))
            if path in (["WeaponAimFollowSpeed"], ["WeaponAimOffsetDegrees"]):
                if not any(pin.list_connected_pins() for pin in node.list_output_pins()):
                    editor.remove_nodes([node])
    BlueprintTools.compile_blueprint(blueprint)
    return {"blueprint": blueprint_path, "nodes": len(g.nodes), "saved": False}


def configure_camera_recoil(blueprint_path):
    """
    /**
     * 在相机蓝图中选择武器动画快照的腰射 瞄准及空中镜头贡献
     * @param blueprint_path	相机蓝图资产
     * @return 编译结果 不自动保存
     */
    """
    blueprint = unreal.load_asset(blueprint_path)
    require_editable(blueprint)
    g = _function(blueprint, "ReadRecoilSource")
    entry = next(node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    character = g.out(entry, "CharacterAnimation")
    cast, rifle = _rifle_source(g, character, entry.find_then_pin())
    aiming, falling = _aim_air(g, character)
    hip = g.break_struct(_rifle_get(g, rifle, "GetHipFireCameraSettings"), "BBBPlayerCameraRecoilSettings")
    ads = g.break_struct(_rifle_get(g, rifle, "GetAimFireCameraSettings"), "BBBPlayerCameraRecoilSettings")
    source_settings = {}
    impulse_scale = g.select(_rifle_get(g, rifle, "GetAirborneCameraImpulseScale"), 1, falling)
    recovery_scale = g.select(_rifle_get(g, rifle, "GetAirborneCameraRecoveryScale"), 1, falling)
    for name in ("ImpulseDegrees", "RandomDegrees", "LimitDegrees"):
        value = g.out(g.call("SelectVector", inputs={"A": g.out(ads, name), "B": g.out(hip, name), "bPickA": aiming}))
        if name != "LimitDegrees":
            value = g.binary("Multiply_VectorFloat", value, impulse_scale)
        source_settings[name] = value
    source_settings["RecoverySpeed"] = g.binary("Multiply_DoubleDouble", g.select(g.out(ads, "RecoverySpeed"), g.out(hip, "RecoverySpeed"), aiming), recovery_scale)
    available = list(g.editor.list_available_nodes([]))
    matches = [name for name in available if name.rsplit("|", 1)[-1] == "MakeBBBPlayerCameraRecoilSettings"]
    if len(matches) != 1:
        raise RuntimeError("无法创建相机后坐力配置组装节点 " + str(matches))
    make = g.place(g.editor.create_node_from_name(matches[0], unreal.Vector2D(), []))
    for name, value in source_settings.items():
        g.link(value, make.find_input_pin(name))
    returns = [node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionResult)]
    result = returns[0] if returns else g.editor.add_return_node()
    g.link(cast.find_then_pin(), result.find_execute_pin())
    g.link(rifle, result.find_input_pin("Source"))
    g.link(_rifle_get(g, rifle, "GetFireSequence"), result.find_input_pin("FireSequence"))
    g.link(g.out(make, "BBBPlayerCameraRecoilSettings"), result.find_input_pin("Settings"))
    result.find_input_pin("ReturnValue").set_pin_value("true")
    fallback = g.editor.add_return_node()
    g.link(g.out(cast, "CastFailed"), fallback.find_execute_pin())
    fallback.find_input_pin("ReturnValue").set_pin_value("false")
    BlueprintTools.compile_blueprint(blueprint)
    return {"blueprint": blueprint_path, "nodes": len(g.nodes), "saved": False}


def create_backward_additive(source_path, destination_path, bone_name, local_offset, duration):
    """
    /**
     * 从源动画首帧建立右手向后移动的加法动画 通过双骨旋转保持臂长与手部朝向
     * @param source_path		基准持枪动画
     * @param destination_path	新动画资产路径
     * @param bone_name		需要后震的骨骼
     * @param local_offset		峰值骨骼局部平移厘米
     * @param duration		动画时长秒
     * @return 新建动画轨道摘要
     */
    """
    source = unreal.load_asset(source_path)
    if not isinstance(source, unreal.AnimSequence) or len(local_offset) != 3 or duration <= 0:
        raise RuntimeError("后震动画创建参数无效")
    if unreal.EditorAssetLibrary.does_asset_exist(destination_path):
        raise RuntimeError("目标后震动画已经存在")
    model = source.data_model_interface
    track_names = [str(name) for name in model.get_bone_track_names()]
    if bone_name not in track_names:
        raise RuntimeError("后震目标骨骼不存在 " + bone_name)
    pose = source.get_anim_pose_at_frame(0, unreal.AnimPoseEvaluationOptions())
    if bone_name != "hand_r":
        raise RuntimeError("当前后震作者工具要求右手双骨链")
    upper = pose.get_bone_pose("upperarm_r", unreal.AnimPoseSpaces.WORLD)
    lower = pose.get_bone_pose("lowerarm_r", unreal.AnimPoseSpaces.WORLD)
    hand = pose.get_bone_pose("hand_r", unreal.AnimPoseSpaces.WORLD)
    clavicle = pose.get_bone_pose("clavicle_r", unreal.AnimPoseSpaces.WORLD)
    folder, name = destination_path.rsplit("/", 1)
    factory = unreal.AnimSequenceFactory()
    factory.set_editor_property("target_skeleton", source.get_skeleton())
    animation = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimSequence, factory)
    frames = round(duration * 60)
    controller = animation.controller
    controller.open_bracket("创建向后后震加法动画", False)
    try:
        controller.set_frame_rate(unreal.FrameRate(60, 1), False)
        controller.set_number_of_frames(unreal.FrameNumber(frames), False)
        arm_rotations = {name: [] for name in ("upperarm_r", "lowerarm_r", "hand_r")}
        for frame in range(frames + 1):
            t = frame / frames
            alpha = math.sin(min(t / 0.15, 1) * math.pi * 0.5)
            if t > 0.15:
                a = (t - 0.15) / 0.85
                alpha = (1 - a) ** 2 * (1 + 2 * a)
            displacement = lower.rotation.rotate_vector(unreal.Vector(*local_offset)) * alpha
            joint, end = unreal.AnimGraphLibrary.two_bone_ik(upper.translation, lower.translation, hand.translation,
                lower.translation, hand.translation + displacement, False, 1.0, 1.0)
            upper_rotation = unreal.MathLibrary.quat_find_between_vectors(lower.translation - upper.translation, joint - upper.translation) * upper.rotation
            lower_rotation = unreal.MathLibrary.quat_find_between_vectors(hand.translation - lower.translation, end - joint) * lower.rotation
            arm_rotations["upperarm_r"].append(clavicle.rotation.inversed() * upper_rotation)
            arm_rotations["lowerarm_r"].append(upper_rotation.inversed() * lower_rotation)
            arm_rotations["hand_r"].append(lower_rotation.inversed() * hand.rotation)
        for bone in track_names:
            transform = pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
            positions = [transform.translation] * (frames + 1)
            controller.add_bone_track(bone, False)
            if not controller.set_bone_track_keys(bone, positions, arm_rotations.get(bone, [transform.rotation] * (frames + 1)), [transform.scale3d] * (frames + 1), False):
                raise RuntimeError("后震轨道写入失败 " + bone)
    finally:
        controller.close_bracket(False)
    animation.set_editor_property("additive_anim_type", unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE)
    animation.set_editor_property("ref_pose_type", unreal.AdditiveBasePoseType.ABPT_ANIM_FRAME)
    animation.set_editor_property("ref_pose_seq", source)
    animation.set_editor_property("ref_frame_index", 0)
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError("后震动画保存失败")
    return {"animation": animation.get_path_name(), "bone": bone_name, "offset": list(local_offset), "frames": frames, "seconds": animation.get_play_length()}
