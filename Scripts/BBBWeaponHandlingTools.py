import json
import math
import builtins

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools
from BBBAssetWritePolicy import require_write_access


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
            "peakCamera": [max((abs(s["camera"][axis]) for s in samples), default=0) for axis in (0, 1)],
            "sampleColumns": ["time", "shot", "pitch", "yaw", "roll", "aimPitch", "aimYaw"],
            "samples": [[s["time"], s.get("shot"), *s.get("cameraActor", s["camera"]), *s["characterOffset"]] for s in samples]}
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
    cameras = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.BBBPlayerCameraSystem)
    camera_actor = cameras[0] if len(cameras) == 1 else None
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
            if camera_actor:
                rotation = camera_actor.get_actor_rotation()
                sample["cameraActor"] = [rotation.pitch, rotation.yaw, rotation.roll]
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
            if not isinstance(value, unreal.BlueprintGraphPin):
                continue
            pin = node.find_input_pin(key)
            self.link(value, pin)
        for key, value in (inputs or {}).items():
            if isinstance(value, unreal.BlueprintGraphPin):
                continue
            pin = node.find_input_pin(key)
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


def _weapon_source(g, character, execute):
    """/** @param g 图表编辑器 @param character 角色快照 @param execute 执行入口 @return 有效装备分支与动画实例 */"""
    weapon = g.out(g.call("/Script/ABBB_Evac.BBBAnimInstance.TryGetWeaponAnimInstance", character))
    valid = g.out(g.call("NotEqual_ObjectObject", inputs={"A": weapon, "B": "None"}))
    branch = g.place(g.editor.add_branch_node())
    g.link(execute, branch.find_execute_pin())
    g.link(valid, branch.find_input_pin("Condition"))
    return branch, weapon


def _weapon_get(g, weapon, name):
    """/** @param g 图表编辑器 @param weapon 当前装备动画实例 @param name 只读接口名称 @return 快照输出引脚 */"""
    return g.out(g.call("/Script/ABBB_Evac.BBBEquipmentAnimInstance." + name, weapon))


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


def _configure_muzzle_aim_gate(aim):
    """
    /**
     * 移除现有瞄准权重门控中的步枪类型限制 保留枪口条件和动作曲线
     * @param aim	唯一瞄准节点
     * @return 已移除的类型门控节点数量
     */
    """
    graph = aim.get_outer()
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    if snapshot.get("error"):
        raise RuntimeError("瞄准权重图表读取失败 " + str(snapshot["error"]))
    functions = {item["path"]: item.get("function", {}).get("name") for item in snapshot["nodes"]}
    weight = list(aim.find_input_pin("Alpha").list_connected_pins())
    if len(weight) != 1:
        raise RuntimeError("瞄准权重必须有唯一曲线门控输入")
    select = weight[0].get_owning_node()
    if select.get_class().get_name() != "K2Node_Select":
        raise RuntimeError("瞄准权重缺少现有布尔选择门控")
    index = select.find_input_pin("Index")
    conditions = list(index.list_connected_pins())
    if len(conditions) != 1:
        raise RuntimeError("瞄准门控条件不是唯一输入")
    condition = conditions[0].get_owning_node()
    if functions.get(condition.get_path_name()) == "HasMuzzle":
        return 0
    if functions.get(condition.get_path_name()) != "BooleanAND":
        raise RuntimeError("瞄准门控条件不是枪口与装备类型合取")
    predicates = {}
    for name in ("A", "B"):
        inputs = list(condition.find_input_pin(name).list_connected_pins())
        if len(inputs) != 1:
            raise RuntimeError("瞄准合取条件缺少唯一谓词")
        source = inputs[0].get_owning_node()
        predicates[functions.get(source.get_path_name())] = (source, inputs[0])
    if set(predicates) != {"IsRifle", "HasMuzzle"}:
        raise RuntimeError("瞄准合取条件包含其它逻辑 不修改")
    rifle, rifle_output = predicates["IsRifle"]
    muzzle, muzzle_output = predicates["HasMuzzle"]
    if any(len(pin.list_connected_pins()) != 1 for pin in (rifle_output, muzzle_output, conditions[0])):
        raise RuntimeError("瞄准门控节点存在其它消费者 不删除")
    editor.remove_nodes([rifle, condition])
    if not muzzle_output.try_create_connection(index):
        raise RuntimeError("通用枪口瞄准门控连接失败")
    return 2


def _replace_rifle_snapshot_casts(blueprint):
    """
    /**
     * 将遗留步枪快照转换替换为当前装备非空分支 保留成功与空装备执行链
     * @param blueprint	角色基础动画层
     * @return 替换的类型转换节点数量
     */
    """
    count = 0
    for graph in unreal.BlueprintEditorLibrary.list_graphs(blueprint):
        g = _Graph(graph)
        casts = [node for node in g.editor.list_all_nodes() if node.get_class().get_name() == "K2Node_DynamicCast"]
        if not casts:
            continue
        snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
        if snapshot.get("error"):
            raise RuntimeError("装备快照类型转换图表读取失败")
        rifle_casts = {item["path"] for item in snapshot["nodes"] if any(
            pin["direction"] == "output" and pin.get("typeObject") == "/Script/ABBB_Evac.BBBRifleAnimInstance"
            for pin in item["pins"]
        )}
        functions = {item["path"]: item.get("function", {}) for item in snapshot["nodes"]}
        for node in casts:
            if node.get_path_name() not in rifle_casts:
                continue
            sources = list(node.find_input_pin("Object").list_connected_pins())
            outputs = [pin for pin in node.list_output_pins() if str(pin.get_pin_name()).startswith("As")]
            success = node.find_output_pin("bSuccess")
            if len(sources) != 1 or len(outputs) != 1 or success.list_connected_pins():
                raise RuntimeError("步枪快照转换结构超出预期 不替换")
            source = sources[0]
            consumers = list(outputs[0].list_connected_pins())
            predecessors = list(node.find_execute_pin().list_connected_pins())
            valid_targets = list(node.find_then_pin().list_connected_pins())
            null_targets = list(node.find_output_pin("CastFailed").list_connected_pins())
            if len(predecessors) != 1:
                raise RuntimeError("步枪快照转换必须有唯一执行前驱")
            valid = g.out(g.call("NotEqual_ObjectObject", inputs={"A": source, "B": "None"}))
            branch = g.place(g.editor.add_branch_node())
            g.link(valid, branch.find_input_pin("Condition"))
            for pin in consumers:
                consumer = pin.get_owning_node()
                function = functions.get(consumer.get_path_name(), {})
                if str(pin.get_pin_name()) != "self" or function.get("name") not in ("GetTimeSinceLastFireSeconds", "IsReloading"):
                    raise RuntimeError("步枪快照消费者不是公共只读动作接口")
                replacement = g.call("/Script/ABBB_Evac.BBBEquipmentAnimInstance." + function["name"], source)
                value = g.out(replacement)
                if function["name"] == "GetTimeSinceLastFireSeconds":
                    fired = g.binary("Greater_IntInt", _weapon_get(g, source, "GetFireSequence"), 0)
                    value = g.select(value, 1.0e38, fired)
                for destination in list(g.out(consumer).list_connected_pins()):
                    g.link(value, destination)
                g.editor.remove_nodes([consumer])
            g.editor.remove_nodes([node])
            g.link(predecessors[0], branch.find_execute_pin())
            for pin in valid_targets:
                g.link(branch.find_then_pin(), pin)
            for pin in null_targets:
                g.link(g.out(branch, "else"), pin)
            count += 1
    return count


def configure_continuous_bone_rotation(blueprint_path, bone_name, snapshot_properties):
    """
    /**
     * 在已有蒙太奇输出后添加连续骨骼旋转 平滑逻辑只在动画图运行
     * @param blueprint_path	独占持有的武器动画蓝图
     * @param bone_name		围绕自身局部 Z 轴旋转的骨骼
     * @param snapshot_properties	驱动标记 加速秒数 减速秒数 度每秒四个只读属性
     * @return 无警告编译与保存结果 不读取装备实例或配置对象
     */
    """
    if len(snapshot_properties) != 4 or len(set(snapshot_properties)) != 4 or not bone_name:
        raise RuntimeError("连续旋转需要四个不同的事实属性和明确骨骼")
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止修改连续旋转图")
    blueprint = unreal.load_asset(blueprint_path)
    if not isinstance(blueprint, unreal.AnimBlueprint):
        raise RuntimeError("目标必须是动画蓝图")
    require_write_access(blueprint)
    dirty = {value.get_path_name() for value in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if blueprint.get_outermost().get_path_name() in dirty:
        raise RuntimeError("目标存在未保存编辑 拒绝操作可能已失效的生成类")
    defaults = unreal.get_default_object(blueprint.generated_class())
    for name in snapshot_properties:
        defaults.get_editor_property(name)
    skeleton = blueprint.get_editor_property("target_skeleton")
    reference = skeleton.get_reference_pose()
    if bone_name not in [str(value) for value in reference.get_bone_names()]:
        raise RuntimeError("目标旋转骨骼不属于蓝图骨架")
    graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, "AnimGraph")
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    nodes = list(editor.list_all_nodes())
    roots = [value for value in nodes if value.get_class().get_name() == "AnimGraphNode_Root"]
    slots = [value for value in nodes if value.get_class().get_name() == "AnimGraphNode_Slot"]
    if len(nodes) != 3 or len(roots) != 1 or len(slots) != 1:
        raise RuntimeError("只允许在参考姿势 蒙太奇槽 输出三节点图上添加旋转")
    variables = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint, False)}
    if variables.intersection({"BarrelVisualSpeed", "BarrelVisualAngle", "BarrelVisualRotation"}):
        raise RuntimeError("连续旋转变量已存在 拒绝覆盖")
    for name, kind in [("BarrelVisualSpeed", "float"), ("BarrelVisualAngle", "float"), ("BarrelVisualRotation", "Rotator")]:
        BlueprintTools.add_variable(blueprint, name, kind)
        BlueprintTools.set_variable_category(blueprint, name, "枪管旋转表现")
    g = _function(blueprint, "BlueprintThreadSafeUpdateAnimation")
    g.editor.set_is_thread_safe_function(True)
    entry = next(value for value in g.editor.list_all_nodes() if isinstance(value, unreal.K2Node_FunctionEntry))
    delta = g.out(entry, "DeltaTime")
    driving = g.get(snapshot_properties[0])
    duration = g.select(g.get(snapshot_properties[1]), g.get(snapshot_properties[2]), driving)
    duration = g.out(g.call("FMax", inputs={"A": duration, "B": 0.0001}))
    speed = g.out(g.call("FInterpTo_Constant", inputs={"Current": g.get("BarrelVisualSpeed"),
        "Target": g.select(1, 0, driving), "DeltaTime": delta,
        "InterpSpeed": g.binary("Divide_DoubleDouble", 1, duration)}))
    increment = g.binary("Multiply_DoubleDouble", delta, g.binary("Multiply_DoubleDouble", g.get("BarrelVisualSpeed"), g.get(snapshot_properties[3])))
    angle = g.out(g.call("FMod", inputs={"Dividend": g.binary("Add_DoubleDouble", g.get("BarrelVisualAngle"), increment), "Divisor": 360}), "Remainder")
    execute = g.set("BarrelVisualSpeed", speed, g.editor.find_graph_entry_pin())
    execute = g.set("BarrelVisualAngle", angle, execute)
    rotation = g.out(g.call("MakeRotator", inputs={"Roll": 0, "Pitch": 0, "Yaw": g.get("BarrelVisualAngle")}))
    g.set("BarrelVisualRotation", rotation, execute)
    create = unreal.BBBBlueprintEditorLibrary.create_native_animation_node
    to_component = create(graph, unreal.AnimGraphNode_LocalToComponentSpace.static_class(), unreal.IntPoint(200, 0))
    modify = create(graph, unreal.AnimGraphNode_ModifyBone.static_class(), unreal.IntPoint(500, 0))
    to_local = create(graph, unreal.AnimGraphNode_ComponentToLocalSpace.static_class(), unreal.IntPoint(850, 0))
    if any(value is None for value in [to_component, modify, to_local]):
        raise RuntimeError("原生旋转节点创建失败 不保存")
    data = modify.get_editor_property("node")
    bone = data.get_editor_property("bone_to_modify")
    bone.set_editor_property("bone_name", bone_name)
    data.set_editor_property("bone_to_modify", bone)
    data.set_editor_property("rotation_mode", unreal.BoneModificationMode.BMM_ADDITIVE)
    data.set_editor_property("rotation_space", unreal.BoneControlSpace.BCS_BONE_SPACE)
    modify.set_editor_property("node", data)
    if not unreal.BBBBlueprintEditorLibrary.bind_animation_node_input(modify, "Rotation", ["BarrelVisualRotation"]):
        raise RuntimeError("旋转输入绑定失败 不保存")
    output = roots[0].find_input_pin("Result")
    output.break_pin_links()
    g.link(slots[0].find_output_pin("Pose"), to_component.find_input_pin("LocalPose"))
    g.link(to_component.find_output_pin("ComponentPose"), modify.find_input_pin("ComponentPose"))
    g.link(modify.find_output_pin("Pose"), to_local.find_input_pin("ComponentPose"))
    g.link(to_local.find_output_pin("Pose"), output)
    roots[0].set_node_pos(unreal.IntPoint(1150, 0))
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("连续旋转图存在编译错误或警告 不保存")
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError("连续旋转动画蓝图保存失败")
    return {"asset": blueprint_path, "bone": bone_name, "snapshotProperties": snapshot_properties, "saved": True}


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
    require_write_access(blueprint)
    variables = {str(n) for n in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint, False)}
    if "WeaponRecoilAnimation" not in variables:
        BlueprintTools.add_object_variable(blueprint, "WeaponRecoilAnimation", unreal.AnimSequence.static_class())
        BlueprintTools.set_variable_category(blueprint, "WeaponRecoilAnimation", "持枪表现")
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
    execute = g.set("WeaponRecoilAnimation", "None", execute)
    valid, weapon = _weapon_source(g, character, execute)
    execute = valid.find_then_pin()
    aiming, falling = _aim_air(g, character)
    def snapshot(name):
        return _weapon_get(g, weapon, "Get" + name)

    def field(name):
        return g.select(snapshot("AimFire" + name), snapshot("HipFire" + name), aiming)

    def scale(name):
        return g.select(snapshot("Airborne" + name), 1, falling)

    follow = g.binary("Multiply_DoubleDouble", field("AimFollowSpeed"), scale("AimFollowScale"))
    recoil = g.binary("Multiply_DoubleDouble", field("BackwardRecoilAlpha"), scale("BackwardRecoilScale"))
    recoil = g.out(g.call("FClamp", inputs={"Value": recoil, "Min": 0, "Max": 1}))
    sequence = _weapon_get(g, weapon, "GetFireSequence")
    fired = g.binary("Greater_IntInt", sequence, 0)
    reloading = _weapon_get(g, weapon, "IsReloading")
    recoil = g.select(0, g.select(recoil, 0, fired), reloading)
    elapsed = _weapon_get(g, weapon, "GetTimeSinceLastFireSeconds")
    time = _weapon_get(g, weapon, "GetSnapshotTimeSeconds")
    sway_parts = []
    hip_amplitude = g.call("BreakVector2D", inputs={"InVec": snapshot("HipFireSwayAmplitudeDegrees")})
    ads_amplitude = g.call("BreakVector2D", inputs={"InVec": snapshot("AimFireSwayAmplitudeDegrees")})
    hip_frequency = g.call("BreakVector2D", inputs={"InVec": snapshot("HipFireSwayFrequency")})
    ads_frequency = g.call("BreakVector2D", inputs={"InVec": snapshot("AimFireSwayFrequency")})
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
    execute = g.set("WeaponBackwardRecoilAlpha", recoil, execute)
    g.set("WeaponRecoilAnimation", _weapon_get(g, weapon, "GetRecoilAnimation"), execute)

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
    _configure_muzzle_aim_gate(aim_nodes[0])
    library = unreal.BBBBlueprintEditorLibrary
    if not library.bind_animation_node_input(aim_nodes[0], "AimFollowSpeed", ["WeaponAimFollowSpeed"]):
        raise RuntimeError("枪口跟随速度连接失败")
    if not library.bind_animation_node_input(aim_nodes[0], "AimOffsetDegrees", ["WeaponAimOffsetDegrees"]):
        raise RuntimeError("枪口角度与摇摆连接失败")
    from BBBRecoilAnimationTools import bind_recoil_additive_inputs
    bind_recoil_additive_inputs(blueprint, animation)
    additive_graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, "FullBodyAdditives")
    additive_editor = unreal.BlueprintGraphEditor.get_graph_editor(additive_graph)
    evaluators = [node for node in additive_editor.list_all_nodes() if node.get_class().get_name() == "AnimGraphNode_SequenceEvaluator"]
    if len(evaluators) != 1:
        raise RuntimeError("后坐力序列播放器数量不为一")
    evaluator = evaluators[0]
    data = evaluator.get_editor_property("node")
    data.set_editor_property("sequence", None)
    evaluator.set_editor_property("node", data)
    if not library.bind_animation_node_input(evaluator, "Sequence", ["WeaponRecoilAnimation"]):
        raise RuntimeError("装备专属后坐力序列绑定失败")
    if "RecoilAdditiveAnimation" in variables:
        BlueprintTools.remove_variable(blueprint, "RecoilAdditiveAnimation")
    _replace_rifle_snapshot_casts(blueprint)
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
    require_write_access(blueprint)
    g = _function(blueprint, "ReadRecoilSource")
    entry = next(node for node in g.editor.list_all_nodes() if isinstance(node, unreal.K2Node_FunctionEntry))
    character = g.out(entry, "CharacterAnimation")
    branch, weapon = _weapon_source(g, character, entry.find_then_pin())
    aiming, falling = _aim_air(g, character)
    hip = g.break_struct(_weapon_get(g, weapon, "GetHipFireCameraSettings"), "BBBPlayerCameraRecoilSettings")
    ads = g.break_struct(_weapon_get(g, weapon, "GetAimFireCameraSettings"), "BBBPlayerCameraRecoilSettings")
    source_settings = {}
    impulse_scale = g.select(_weapon_get(g, weapon, "GetAirborneCameraImpulseScale"), 1, falling)
    recovery_scale = g.select(_weapon_get(g, weapon, "GetAirborneCameraRecoveryScale"), 1, falling)
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
    g.link(branch.find_then_pin(), result.find_execute_pin())
    g.link(weapon, result.find_input_pin("Source"))
    g.link(_weapon_get(g, weapon, "GetFireSequence"), result.find_input_pin("FireSequence"))
    g.link(g.out(make, "BBBPlayerCameraRecoilSettings"), result.find_input_pin("Settings"))
    result.find_input_pin("ReturnValue").set_pin_value("true")
    fallback = g.editor.add_return_node()
    g.link(g.out(branch, "else"), fallback.find_execute_pin())
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
