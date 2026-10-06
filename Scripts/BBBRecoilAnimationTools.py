import json
import math
import os
import builtins

import unreal
from BBBAssetWritePolicy import require_asset_write
from editor_toolset.toolsets.blueprint import BlueprintTools


def recoil_envelope(time, peak_time, settle_time):
    """
    /**
     * @param time		取样秒数
     * @param peak_time	最大受力时刻
     * @param settle_time	完全恢复时刻
     * @return 首尾速度为零的标准受力幅度
     */
    """
    if time <= 0 or time >= settle_time:
        return 0.0
    if time <= peak_time:
        phase = time / peak_time
        return phase * phase * (3.0 - 2.0 * phase)
    phase = (time - peak_time) / (settle_time - peak_time)
    return 1.0 - phase * phase * (3.0 - 2.0 * phase)


def _angle(first, second):
    """/** @param first 基准四元数 @param second 当前四元数 @return 最短夹角度数 */"""
    dot = abs(first.x * second.x + first.y * second.y + first.z * second.z + first.w * second.w)
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def _length(value):
    """/** @param value 位移向量 @return 厘米长度 */"""
    return math.sqrt(value.x ** 2 + value.y ** 2 + value.z ** 2)


def _weighted_rotation(original, animated, alpha):
    """/** @param original 基准旋转 @param animated 目标旋转 @param alpha 强度 @return 局部加法混合旋转 */"""
    delta = animated * original.inversed()
    if delta.w < 0:
        delta = unreal.Quat(-delta.x, -delta.y, -delta.z, -delta.w)
    weighted = unreal.Quat(delta.x * alpha, delta.y * alpha, delta.z * alpha, 1.0 + (delta.w - 1.0) * alpha)
    weighted = weighted.normalized()
    return weighted * original


def _alpha_hand_pose(baseline, animated, side, alpha):
    """/** @param baseline 基准姿势 @param animated 受力姿势 @param side 左右侧 @param alpha 强度 @return 层级合成后的双手位置和朝向 */"""
    body_original = baseline.get_bone_pose("spine_03", unreal.AnimPoseSpaces.WORLD)
    body_animated = animated.get_bone_pose("spine_03", unreal.AnimPoseSpaces.WORLD)
    body_delta = (body_animated.translation - body_original.translation) * alpha
    clavicle = baseline.get_bone_pose("clavicle_" + side, unreal.AnimPoseSpaces.WORLD)
    parent_position = clavicle.translation + body_delta
    parent_rotation = clavicle.rotation
    for bone in ("upperarm_" + side, "lowerarm_" + side, "hand_" + side):
        original = baseline.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
        target = animated.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
        local_position = original.translation + (target.translation - original.translation) * alpha
        local_rotation = _weighted_rotation(original.rotation, target.rotation, alpha)
        parent_position = parent_position + parent_rotation.rotate_vector(local_position)
        parent_rotation = parent_rotation * local_rotation
    return parent_position, parent_rotation


def _context(source_path, definition_path):
    """/** @param source_path 持枪动画 @param definition_path 装备定义 @return 基准姿势与真实枪口轴 */"""
    source = unreal.load_asset(source_path)
    definition = unreal.load_asset(definition_path)
    if not isinstance(source, unreal.AnimSequence) or definition is None:
        raise RuntimeError("持枪基准动画或装备定义无效")
    mesh = definition.get_editor_property("equipment_mesh")
    muzzle_name = definition.get_editor_property("muzzle_socket_name")
    muzzle_socket = mesh.find_socket(muzzle_name)
    if muzzle_socket is None:
        raise RuntimeError("装备网格缺少枪口插槽")
    weapon_pose = mesh.get_editor_property("skeleton").get_reference_pose()
    muzzle_parent = weapon_pose.get_bone_pose(muzzle_socket.get_editor_property("bone_name"), unreal.AnimPoseSpaces.WORLD)
    muzzle_rotation = muzzle_parent.rotation * muzzle_socket.get_editor_property("relative_rotation").quaternion()
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    options.retrieve_additive_as_full_pose = True
    pose = source.get_anim_pose_at_frame(0, options)
    hand = pose.get_bone_pose("hand_r", unreal.AnimPoseSpaces.WORLD)
    offset = definition.get_editor_property("spawn_offset")
    forward = (hand.rotation * offset.rotation * muzzle_rotation).rotate_vector(unreal.Vector(1.0, 0.0, 0.0))
    forward = forward / _length(forward)
    return source, definition, pose, forward


def inspect_recoil_context(source_path, definition_path):
    """
    /**
     * @param source_path	持枪基准动画
     * @param definition_path	包含挂接变换和枪口的装备定义
     * @return 真实枪口轴与骨骼基准 仅只读
     */
    """
    source, definition, pose, forward = _context(source_path, definition_path)
    bones = ["root", "pelvis", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r"]
    return {"source": source.get_path_name(), "forward": [forward.x, forward.y, forward.z], "fireInterval": definition.get_editor_property("fire_interval"), "bones": {bone: pose.get_bone_pose(bone, unreal.AnimPoseSpaces.WORLD).export_text() for bone in bones}}


def rebuild_backward_recoil(source_path, animation_path, definition_path, maximum_distance_cm=8.0):
    """
    /**
     * 原位制作只沿真实枪口轴后退的双臂与肩部加法动作
     * @param source_path	持枪基准动画
     * @param animation_path	已独占签出的后坐力序列
     * @param definition_path	轴向及射击间隔来源
     * @param maximum_distance_cm	Alpha 为一时的最大后退厘米数
     * @return 全帧写入与恢复校验 未通过不保存
     */
    """
    if not math.isfinite(maximum_distance_cm) or not 0 < maximum_distance_cm <= 12:
        raise RuntimeError("最大后退幅度必须在零到十二厘米之间")
    source, definition, pose, forward = _context(source_path, definition_path)
    animation = unreal.load_asset(animation_path)
    if not isinstance(animation, unreal.AnimSequence) or animation.get_skeleton() != source.get_skeleton():
        raise RuntimeError("后坐力序列及基准骨架不一致")
    require_asset_write([animation])
    if unreal.AnimationLibrary.get_animation_notify_events(animation) or unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT):
        raise RuntimeError("后坐力序列含事件或曲线 拒绝覆盖")
    tracks = [str(name) for name in source.data_model_interface.get_bone_track_names()]
    required = {"spine_02", "spine_03", "clavicle_l", "clavicle_r", "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r"}
    if not required.issubset(tracks):
        raise RuntimeError("持枪基准缺少肩部或双臂轨道")
    duration = 0.2
    frames = 48
    settle_time = min(0.09, float(definition.get_editor_property("fire_interval")) * 0.9)
    if not math.isfinite(settle_time) or settle_time <= 0:
        raise RuntimeError("装备射击间隔必须为有限正数")
    peak_time = min(0.020833333333333332, settle_time * 0.25)
    backward = forward * -maximum_distance_cm
    body_fraction = 0.25
    values = {bone: [] for bone in tracks}
    baseline = {bone: pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL) for bone in tracks}
    spine_parent = pose.get_bone_pose("spine_02", unreal.AnimPoseSpaces.WORLD)
    for frame in range(frames + 1):
        weight = recoil_envelope(frame * duration / frames, peak_time, settle_time)
        local = {bone: transform.copy() for bone, transform in baseline.items()}
        body_delta = backward * (weight * body_fraction)
        local["spine_03"].translation = baseline["spine_03"].translation + spine_parent.rotation.inversed().rotate_vector(body_delta)
        for side in ("l", "r"):
            upper_name = "upperarm_" + side
            lower_name = "lowerarm_" + side
            hand_name = "hand_" + side
            upper = pose.get_bone_pose(upper_name, unreal.AnimPoseSpaces.WORLD)
            lower = pose.get_bone_pose(lower_name, unreal.AnimPoseSpaces.WORLD)
            hand = pose.get_bone_pose(hand_name, unreal.AnimPoseSpaces.WORLD)
            clavicle = pose.get_bone_pose("clavicle_" + side, unreal.AnimPoseSpaces.WORLD)
            target = hand.translation + backward * weight
            joint, end = unreal.AnimGraphLibrary.two_bone_ik(upper.translation + body_delta, lower.translation + body_delta, hand.translation + body_delta, lower.translation + body_delta, target, False, 1.0, 1.0)
            if _length(end - target) > 0.001:
                raise RuntimeError("最大受力超出手臂可达范围 不允许拉伸")
            upper_rotation = unreal.MathLibrary.quat_find_between_vectors(lower.translation - upper.translation, joint - upper.translation - body_delta) * upper.rotation
            lower_rotation = unreal.MathLibrary.quat_find_between_vectors(hand.translation - lower.translation, end - joint) * lower.rotation
            local[upper_name].rotation = clavicle.rotation.inversed() * upper_rotation
            local[lower_name].rotation = upper_rotation.inversed() * lower_rotation
            local[hand_name].rotation = lower_rotation.inversed() * hand.rotation
        if weight == 0:
            local = {bone: transform.copy() for bone, transform in baseline.items()}
        for bone in tracks:
            values[bone].append(local[bone])
    controller = animation.controller
    controller.open_bracket("重做最大轴向后坐力双臂动画", False)
    try:
        controller.set_frame_rate(unreal.FrameRate(240, 1), False)
        controller.set_number_of_frames(unreal.FrameNumber(frames), False)
        for bone in list(animation.data_model_interface.get_bone_track_names()):
            if str(bone) not in values:
                controller.remove_bone_track(bone, False)
        existing = {str(name) for name in animation.data_model_interface.get_bone_track_names()}
        for bone, keys in values.items():
            if bone not in existing:
                controller.add_bone_track(bone, False)
            if not controller.set_bone_track_keys(bone, [key.translation for key in keys], [key.rotation for key in keys], [key.scale3d for key in keys], False):
                raise RuntimeError("后坐力轨道写入失败 尚未保存: " + bone)
    finally:
        controller.close_bracket(False)
    animation.set_editor_property("additive_anim_type", unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE)
    animation.set_editor_property("ref_pose_type", unreal.AdditiveBasePoseType.ABPT_ANIM_FRAME)
    animation.set_editor_property("ref_pose_seq", source)
    animation.set_editor_property("ref_frame_index", 0)
    report = validate_backward_recoil(source_path, animation_path, definition_path)
    if not report["passed"]:
        raise RuntimeError("后坐力验证失败 尚未保存: " + json.dumps(report))
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError("后坐力资产保存失败")
    report.update({"saved": True, "maximumDistanceCm": maximum_distance_cm, "peakTime": peak_time, "settleTime": settle_time, "keys": frames + 1})
    return report


def validate_backward_recoil(source_path, animation_path, definition_path):
    """
    /**
     * @param source_path	持枪基准动画
     * @param animation_path	待验证加法序列
     * @param definition_path	真实枪口轴来源
     * @return 全帧轴向 双手朝向 握持 首尾与下半身误差
     */
    """
    source, definition, baseline, forward = _context(source_path, definition_path)
    animation = unreal.load_asset(animation_path)
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    options.retrieve_additive_as_full_pose = True
    count = animation.data_model_interface.get_number_of_keys()
    maximum_axis_error = 0.0
    maximum_rotation = 0.0
    maximum_grip_error = 0.0
    maximum_lower_body_error = 0.0
    peak_distance = 0.0
    endpoint_error = 0.0
    alpha_reports = {alpha: {"peakBackwardCm": 0.0, "maxOffAxisCm": 0.0, "maxHandRotationDegrees": 0.0, "maxGripSeparationErrorCm": 0.0} for alpha in (0.0, 0.5, 1.0)}
    first_right = baseline.get_bone_pose("hand_r", unreal.AnimPoseSpaces.WORLD)
    first_left = baseline.get_bone_pose("hand_l", unreal.AnimPoseSpaces.WORLD)
    initial_separation = first_left.translation - first_right.translation
    lower_bones = ["root", "pelvis", "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r"]
    for frame in range(count):
        pose = animation.get_anim_pose_at_frame(frame, options)
        right = pose.get_bone_pose("hand_r", unreal.AnimPoseSpaces.WORLD)
        left = pose.get_bone_pose("hand_l", unreal.AnimPoseSpaces.WORLD)
        for alpha, metrics in alpha_reports.items():
            right_position, right_rotation = _alpha_hand_pose(baseline, pose, "r", alpha)
            left_position, left_rotation = _alpha_hand_pose(baseline, pose, "l", alpha)
            metrics["maxGripSeparationErrorCm"] = max(metrics["maxGripSeparationErrorCm"], _length(left_position - right_position - initial_separation))
            for original, position, rotation in ((first_right, right_position, right_rotation), (first_left, left_position, left_rotation)):
                delta = position - original.translation
                axial = unreal.MathLibrary.dot_vector_vector(delta, forward)
                metrics["peakBackwardCm"] = max(metrics["peakBackwardCm"], -axial)
                metrics["maxOffAxisCm"] = max(metrics["maxOffAxisCm"], _length(delta - forward * axial))
                metrics["maxHandRotationDegrees"] = max(metrics["maxHandRotationDegrees"], _angle(original.rotation, rotation))
        maximum_grip_error = max(maximum_grip_error, _length(left.translation - right.translation - initial_separation))
        for bone, original, current in (("hand_r", first_right, right), ("hand_l", first_left, left)):
            delta = current.translation - original.translation
            axial = unreal.MathLibrary.dot_vector_vector(delta, forward)
            maximum_axis_error = max(maximum_axis_error, _length(delta - forward * axial))
            maximum_rotation = max(maximum_rotation, _angle(original.rotation, current.rotation))
            peak_distance = max(peak_distance, -axial)
            if frame in (0, count - 1):
                endpoint_error = max(endpoint_error, _length(delta))
        for bone in lower_bones:
            original = baseline.get_bone_pose(bone, unreal.AnimPoseSpaces.WORLD)
            current = pose.get_bone_pose(bone, unreal.AnimPoseSpaces.WORLD)
            maximum_lower_body_error = max(maximum_lower_body_error, _length(current.translation - original.translation), _angle(original.rotation, current.rotation))
    full_pose_passed = max(maximum_axis_error, maximum_rotation, maximum_grip_error, maximum_lower_body_error, endpoint_error) < 0.01 and peak_distance > 0.0
    alpha_passed = all(metrics["maxOffAxisCm"] < 0.3 and metrics["maxHandRotationDegrees"] < 0.15 and metrics["maxGripSeparationErrorCm"] < 0.35 for metrics in alpha_reports.values())
    passed = full_pose_passed and alpha_passed
    return {"animation": animation_path, "passed": passed, "peakBackwardCm": peak_distance, "maxOffAxisCm": maximum_axis_error, "maxHandRotationDegrees": maximum_rotation, "maxGripSeparationErrorCm": maximum_grip_error, "lowerBodyMaxError": maximum_lower_body_error, "endpointErrorCm": endpoint_error, "framesAudited": count, "alphaAudit": alpha_reports}


def _unique(nodes, predicate, description):
    """/** @param nodes 候选对象 @param predicate 判定函数 @param description 报错上下文 @return 唯一对象 */"""
    matches = [node for node in nodes if predicate(node)]
    if len(matches) != 1:
        raise RuntimeError(description + "必须唯一 实际数量: " + str(len(matches)))
    return matches[0]


def _link(output, input_pin):
    """/** @param output 输出引脚 @param input_pin 输入引脚 @return 连线成功时无返回值 */"""
    if not output.is_valid() or not input_pin.is_valid() or not output.try_create_connection(input_pin):
        raise RuntimeError("后坐力合并连线失败 尚未保存")


def bind_recoil_additive_inputs(blueprint, animation):
    """
    /**
     * 维护已有加法层中的后坐力输入 不重新创建图表或落地状态机
     * @param blueprint	基础动画层
     * @param animation	最大受力加法序列
     * @return 输入绑定成功时无返回值 结构不匹配则报错
     */
    """
    graph = unreal.BlueprintEditorLibrary.find_graph(blueprint, "FullBodyAdditives")
    if graph is None:
        raise RuntimeError("原有 FullBodyAdditives 层不存在")
    editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    evaluator = _unique(list(editor.list_all_nodes()), lambda node: node.get_class().get_name() == "AnimGraphNode_SequenceEvaluator", "后坐力时间播放器")
    connected = list(evaluator.find_output_pin("Pose").list_connected_pins())
    if len(connected) != 1 or str(connected[0].get_pin_name()) != "Additive":
        raise RuntimeError("后坐力播放器必须接入唯一加法输入")
    blend = connected[0].get_owning_node()
    if blend.get_class().get_name() != "AnimGraphNode_ApplyAdditive":
        raise RuntimeError("后坐力权重节点类型错误")
    data = evaluator.get_editor_property("node")
    data.set_editor_property("sequence", animation)
    evaluator.set_editor_property("node", data)
    library = unreal.BBBBlueprintEditorLibrary
    if not library.bind_animation_node_input(evaluator, "ExplicitTime", ["WeaponRecoilTime"]):
        raise RuntimeError("后坐力时间重新绑定失败")
    if not library.bind_animation_node_input(blend, "Alpha", ["WeaponBackwardRecoilAlpha"]):
        raise RuntimeError("后坐力权重重新绑定失败")


def _create_node(editor, ending, position):
    """/** @param editor 目标图编辑器 @param ending 可用节点名 @param position 坐标 @return 新节点 */"""
    available = list(editor.list_available_nodes([]))
    name = _unique(available, lambda item: str(item).rsplit("|", 1)[-1] == ending, "节点类型 " + ending)
    node = editor.create_node_from_name(str(name), unreal.Vector2D(*position), [])
    if node is None:
        raise RuntimeError("创建加法节点失败: " + ending)
    return node


def merge_recoil_additives(interface_path, base_path, main_path, dependent_paths, animation_path):
    """
    /**
     * 将独立后坐力合入原有加法输出 保留落地状态机及其它图
     * @param interface_path	动画层接口
     * @param base_path	基础动画层
     * @param main_path	主动画蓝图
     * @param dependent_paths	需要同步编译的派生层
     * @param animation_path	标准最大受力加法动画
     * @return 结构回读和编译保存结果
     */
    """
    interface, base, main = [unreal.load_asset(path) for path in (interface_path, base_path, main_path)]
    dependents = [unreal.load_asset(path) for path in dependent_paths]
    if any(not isinstance(item, unreal.AnimBlueprint) for item in [interface, base, main] + dependents):
        raise RuntimeError("动画蓝图资产无效")
    animation = unreal.load_asset(animation_path)
    if not isinstance(animation, unreal.AnimSequence) or animation.get_editor_property("additive_anim_type") != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE:
        raise RuntimeError("需要局部空间后坐力加法序列")
    require_asset_write([interface, base, main] + dependents)
    layer = unreal.BlueprintEditorLibrary.find_graph(base, "FullBodyAdditives")
    old = unreal.BlueprintEditorLibrary.find_graph(base, "FullBodyRecoil")
    graph = unreal.BlueprintEditorLibrary.find_graph(main, "AnimGraph")
    if layer is None or old is None or graph is None:
        raise RuntimeError("预期的现有动画层不存在 拒绝重复或不完整合并")
    editor = unreal.BlueprintGraphEditor.get_graph_editor(layer)
    nodes = list(editor.list_all_nodes())
    state = _unique(nodes, lambda node: node.get_class().get_name() == "AnimGraphNode_StateMachine", "落地恢复状态机")
    root = _unique(nodes, lambda node: node.get_class().get_name() == "AnimGraphNode_Root", "原有层输出")
    if len(list(root.find_input_pin("Result").list_connected_pins())) != 1:
        raise RuntimeError("原有加法层输出结构异常")
    main_editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
    main_nodes = list(main_editor.list_all_nodes())
    snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.inspect_blueprint_graph_logical_snapshot(graph))
    layer_record = _unique(snapshot["nodes"], lambda node: node.get("animNode", {}).get("properties", {}).get("Layer") == "FullBodyRecoil", "主图后坐力调用")
    old_layer = _unique(main_nodes, lambda node: node.get_path_name() == layer_record["path"], "主图后坐力节点")
    old_blend = old_layer.find_output_pin("Pose").list_connected_pins()[0].get_owning_node()
    original_blend = old_blend.find_input_pin("Base").list_connected_pins()[0].get_owning_node()
    if old_blend.get_class().get_name() != "AnimGraphNode_ApplyAdditive" or original_blend.get_class().get_name() != "AnimGraphNode_ApplyAdditive":
        raise RuntimeError("主图加法链结构与预期不一致")
    landing_alpha = float(original_blend.find_input_pin("Alpha").get_pin_value())
    if abs(landing_alpha - 0.65) > 0.0001:
        raise RuntimeError("落地恢复原权重已变化 拒绝覆盖")
    downstream = list(old_blend.find_output_pin("Pose").list_connected_pins())
    if len(downstream) != 1:
        raise RuntimeError("后坐力输出必须有唯一后继")
    zero = _create_node(editor, "Additive标识姿势", (-950, -100))
    landing = _create_node(editor, "应用Additive动画", (-600, 0))
    evaluator = _create_node(editor, "计算“" + animation.get_name() + "”（additive）", (-600, 330))
    recoil = _create_node(editor, "应用Additive动画", (-150, 100))
    evaluator_data = evaluator.get_editor_property("node")
    evaluator_data.import_text(evaluator_data.export_text().replace("bShouldLoop=True", "bShouldLoop=False").replace("bTeleportToExplicitTime=False", "bTeleportToExplicitTime=True"))
    evaluator.set_editor_property("node", evaluator_data)
    library = unreal.BBBBlueprintEditorLibrary
    if not library.bind_animation_node_input(evaluator, "ExplicitTime", ["WeaponRecoilTime"]):
        raise RuntimeError("后坐力时间绑定失败")
    if not library.bind_animation_node_input(recoil, "Alpha", ["WeaponBackwardRecoilAlpha"]):
        raise RuntimeError("后坐力权重绑定失败")
    recoil_data = recoil.get_editor_property("node")
    clamp = recoil_data.get_editor_property("alpha_scale_bias_clamp")
    clamp.set_editor_property("interp_result", True)
    clamp.set_editor_property("interp_speed_increasing", 80.0)
    clamp.set_editor_property("interp_speed_decreasing", 40.0)
    recoil_data.set_editor_property("alpha_scale_bias_clamp", clamp)
    recoil.set_editor_property("node", recoil_data)
    landing.find_input_pin("Alpha").set_pin_value(str(landing_alpha))
    root.find_input_pin("Result").break_pin_links()
    _link(zero.find_output_pin("Pose"), landing.find_input_pin("Base"))
    _link(state.find_output_pin("Pose"), landing.find_input_pin("Additive"))
    _link(landing.find_output_pin("Pose"), recoil.find_input_pin("Base"))
    _link(evaluator.find_output_pin("Pose"), recoil.find_input_pin("Additive"))
    _link(recoil.find_output_pin("Pose"), root.find_input_pin("Result"))
    state.set_node_pos(unreal.IntPoint(-950, 120))
    root.set_node_pos(unreal.IntPoint(250, 100))
    for pin in downstream:
        pin.break_pin_links()
        _link(original_blend.find_output_pin("Pose"), pin)
    original_blend.find_input_pin("Alpha").set_pin_value("1.0")
    main_editor.remove_nodes([old_blend, old_layer])
    unreal.BlueprintEditorLibrary.remove_graph(base, old)
    for dependent in dependents:
        dependent_old = unreal.BlueprintEditorLibrary.find_graph(dependent, "FullBodyRecoil")
        if dependent_old is not None:
            unreal.BlueprintEditorLibrary.remove_graph(dependent, dependent_old)
    interface_old = unreal.BlueprintEditorLibrary.find_graph(interface, "FullBodyRecoil")
    if interface_old is None:
        raise RuntimeError("接口缺少待移除的后坐力层")
    unreal.BlueprintEditorLibrary.remove_graph(interface, interface_old)
    results = []
    for asset in [interface, base] + dependents + [main]:
        BlueprintTools.compile_blueprint(asset, warnings_as_errors=True)
        if unreal.BlueprintEditorLibrary.find_graph(asset, "FullBodyRecoil") is not None:
            raise RuntimeError("独立后坐力层移除后重新生成 尚未保存")
        results.append({"asset": asset.get_path_name(), "status": str(asset.get_editor_property("status"))})
    for asset in [interface, base] + dependents + [main]:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            raise RuntimeError("动画蓝图保存失败: " + asset.get_path_name())
    return {"saved": True, "landingAlpha": landing_alpha, "mainAlpha": 1.0, "recoilAlphaPath": ["WeaponBackwardRecoilAlpha"], "compiled": results}


def sample_recoil_runtime(action, seconds, file_prefix):
    """
    /**
     * 只读采集自然更新完成的角色姿势 不主动推进动画
     * @param action	start 或 status
     * @param seconds	游戏采样秒数
     * @param file_prefix	本任务临时报告前缀
     * @return 帧号 开火 时间 权重 播放器和骨骼采样
     */
    """
    state = getattr(builtins, "BBB_BACKWARD_RECOIL_RUNTIME_PROBE", None)
    if action == "status":
        if state is None:
            return {"status": "idle"}
        return {"status": state["status"], "error": state.get("error"), "path": state["path"], "samples": len(state["samples"]), "shots": sorted({item["shot"] for item in state["samples"] if item["shot"] > 0}), "reloadSamples": sum(item["reloading"] for item in state["samples"]), "activeRecoilSamples": sum(bool(item["players"]) for item in state["samples"])}
    if action != "start" or not 0 < seconds <= 30 or not file_prefix.replace("_", "").isalnum():
        raise RuntimeError("采样参数无效")
    if state is not None and state["status"] == "running":
        raise RuntimeError("已有后坐力采样运行中")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    if world is None or pawn is None:
        raise RuntimeError("需要本地玩家 PIE")
    mesh = pawn.get_editor_property("Mesh")
    directory = os.path.join(unreal.Paths.project_saved_dir(), "temp", file_prefix)
    path = os.path.join(directory, "runtime.json")
    if os.path.exists(path):
        raise RuntimeError("采样报告已存在 禁止覆盖")
    os.makedirs(directory, exist_ok=True)
    state = {"status": "running", "path": path, "samples": [], "start": unreal.GameplayStatics.get_time_seconds(world), "lastFrame": -1}
    setattr(builtins, "BBB_BACKWARD_RECOIL_RUNTIME_PROBE", state)

    def finish(error=None):
        """/** @param error 失败原因 @return 结束采样并写入报告 */"""
        state["status"] = "completed"
        if error is not None:
            state["status"] = "failed"
            state["error"] = str(error)
            unreal.log_error("[BBBRecoilRuntime] " + str(error))
        unreal.unregister_slate_post_tick_callback(state["handle"])
        with open(path, "w", encoding="utf-8") as output:
            json.dump({key: value for key, value in state.items() if key != "handle"}, output, ensure_ascii=False, indent=2)

    def tick(delta_seconds):
        """/** @param delta_seconds 编辑器回调间隔 @return 采集已完成的自然游戏帧 */"""
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError("被测 PIE 已结束")
            snapshot = json.loads(unreal.BBBBlueprintEditorLibrary.probe_character_animation_runtime(pawn))
            if snapshot["status"] != "ok":
                raise RuntimeError("角色自然更新快照失败")
            if snapshot["frame"] == state["lastFrame"]:
                return
            state["lastFrame"] = snapshot["frame"]
            main = mesh.get_anim_instance()
            weapon = main.try_get_weapon_anim_instance()
            layer = None
            for item in snapshot["linkedLayers"]:
                if "LocomotionLayer_Rifle" in item["class"]:
                    layer = unreal.find_object(None, item["path"])
                    break
            players = [player for item in snapshot["linkedLayers"] for player in item["players"] if "ANI_BBB_Rifle_Recoil_Backward" in player.get("asset", "")]
            row = {"frame": snapshot["frame"], "time": snapshot["worldTime"] - state["start"], "delta": snapshot["deltaSeconds"], "shot": 0, "reloading": False, "alpha": 0.0, "recoilTime": None, "players": players, "hands": {bone: mesh.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_COMPONENT).export_text() for bone in ("hand_l", "hand_r", "spine_03")}, "montages": snapshot["mainInstance"]["montage"]}
            if isinstance(weapon, unreal.BBBRifleAnimInstance):
                row["shot"] = weapon.get_fire_sequence()
                row["reloading"] = bool(weapon.is_reloading)
            if layer is not None:
                row["alpha"] = layer.get_editor_property("WeaponBackwardRecoilAlpha")
                row["recoilTime"] = layer.get_editor_property("WeaponRecoilTime")
            state["samples"].append(row)
            if row["time"] >= seconds:
                finish()
        except Exception as error:
            finish(error)

    state["handle"] = unreal.register_slate_post_tick_callback(tick)
    return {"status": "running", "path": path}


def capture_recoil_alpha_samples(source_path, animation_path, mesh_path, file_prefix):
    """
    /**
     * 在瞬态普通序列上复现加法合成 避免把差值直接播放到参考姿势
     * @param source_path	加法基准动画
     * @param animation_path	待验证的最大受力动画
     * @param mesh_path	真实骨架网格
     * @param file_prefix	本任务唯一截图前缀
     * @return 三档权重及满权重阶段截图 不创建项目资产
     */
    """
    from BBBAnimationPreviewToolset import BBBAnimationPreviewToolset
    source = unreal.load_asset(source_path)
    animation = unreal.load_asset(animation_path)
    if not file_prefix.replace("_", "").isalnum() or not isinstance(source, unreal.AnimSequence) or not isinstance(animation, unreal.AnimSequence) or source.get_skeleton() != animation.get_skeleton():
        raise RuntimeError("完整姿势截图前缀或序列无效")
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    options.retrieve_additive_as_full_pose = True
    baseline = source.get_anim_pose_at_frame(0, options)
    tracks = [str(name) for name in animation.data_model_interface.get_bone_track_names()]
    frames = animation.data_model_interface.get_number_of_frames()
    previews = []
    for alpha in (0.0, 0.5, 1.0):
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", source.get_skeleton())
        name = file_prefix + "Alpha" + str(int(alpha * 100))
        preview = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, "/Engine/Transient", unreal.AnimSequence, factory)
        if preview is None:
            raise RuntimeError("瞬态验证序列创建失败")
        controller = preview.controller
        controller.open_bracket("瞬态后坐力权重姿势验证", False)
        try:
            controller.set_frame_rate(unreal.FrameRate(240, 1), False)
            controller.set_number_of_frames(unreal.FrameNumber(frames), False)
            values = {bone: [] for bone in tracks}
            for frame in range(frames + 1):
                pose = animation.get_anim_pose_at_frame(frame, options)
                for bone in tracks:
                    original = baseline.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
                    target = pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
                    transform = original.copy()
                    transform.translation = original.translation + (target.translation - original.translation) * alpha
                    transform.rotation = _weighted_rotation(original.rotation, target.rotation, alpha)
                    values[bone].append(transform)
            for bone, keys in values.items():
                controller.add_bone_track(bone, False)
                if not controller.set_bone_track_keys(bone, [key.translation for key in keys], [key.rotation for key in keys], [key.scale3d for key in keys], False):
                    raise RuntimeError("瞬态姿势验证轨道生成失败")
        finally:
            controller.close_bracket(False)
        previews.append(preview)
    report = json.loads(BBBAnimationPreviewToolset.capture_animation_samples(mesh_path, [preview.get_path_name() for preview in previews], [0.10416666666666667], file_prefix))
    stage_report = json.loads(BBBAnimationPreviewToolset.capture_animation_samples(mesh_path, [previews[-1].get_path_name()], [0.0, 0.10416666666666667, 0.5], file_prefix + "_Stages"))
    return {"alphaSamples": report, "stages": stage_report, "projectAssetsCreated": False}
