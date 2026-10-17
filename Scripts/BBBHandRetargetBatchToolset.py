import json
import math

import unreal
import BBBControlRigAuthoringToolset as authoring
import BBBGenericEditorToolset as generic_editor
from BBBAssetWritePolicy import require_asset_write
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
    "build_hand_retarget_sequences": {
        "manifest_json": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "animation_path": {"type": "string"},
                    "template_sequence_path": {"type": "string"},
                    "mesh_path": {"type": "string"},
                    "sequence_path": {"type": "string"},
                    "grip_in_hand_r": {"$ref": "#/$defs/TransformQuaternion"},
                    "pole_in_hand_r": {"$ref": "#/$defs/TransformQuaternion"},
                    "weight": {"type": "number"},
                    "contacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_frame": {"type": "integer"},
                                "end_frame": {"type": "integer"},
                                "fade_in_frames": {"type": "integer"},
                                "fade_out_frames": {"type": "integer"},
                            },
                            "required": ["start_frame", "end_frame"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                },
                "required": [
                    "animation_path",
                    "template_sequence_path",
                    "mesh_path",
                    "sequence_path",
                    "grip_in_hand_r",
                    "contacts",
                ],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 32,
        },
    },
    "bake_hand_retarget_sequences": {
        "manifest_json": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sequence_path": {"type": "string"},
                    "animation_path": {"type": "string"},
                    "mesh_path": {"type": "string"},
                    "output_animation_path": {"type": "string"},
                },
                "required": [
                    "sequence_path",
                    "animation_path",
                    "mesh_path",
                    "output_animation_path",
                ],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 32,
        },
    },
}


_LEFT_ARM_BONES = (
    "clavicle_l",
    "upperarm_l",
    "lowerarm_l",
    "lowerarm_twist_01_l",
    "upperarm_twist_01_l",
    "hand_l",
    "ik_hand_l",
)


def _asset(path, asset_type):
    """/** @param path	资产路径 @param asset_type	预期类型 @return 类型正确的资产 */"""
    asset = unreal.load_asset(path)
    if not isinstance(asset, asset_type):
        raise RuntimeError("资产类型无效 " + path)

    return asset


def _frame_count(animation):
    """/** @param animation	动画资产 @return 帧数与原始帧率 */"""
    count = animation.data_model_interface.get_number_of_keys()
    rate = animation.data_model_interface.get_frame_rate()
    if count < 2 or count > 1200 or rate.numerator < 1 or rate.denominator < 1:
        raise RuntimeError("动画帧数或采样率超出批量范围 " + animation.get_path_name())

    return count, rate


def _vector(values, label):
    """/** @param values	三维数值 @param label	错误字段名 @return 有限向量 */"""
    if len(values) != 3 or any(not math.isfinite(float(value)) for value in values):
        raise RuntimeError(label + " 必须为三个有限数值")

    return unreal.Vector(float(values[0]), float(values[1]), float(values[2]))


def _transform(request, label):
    """/** @param request	位置旋转与缩放 @param label	错误字段名 @return 校验后的变换 */"""
    position = _vector(request.get("position", [0.0, 0.0, 0.0]), label + "位置")
    scale = _vector(request.get("scale", [1.0, 1.0, 1.0]), label + "缩放")
    rotation = request.get("rotation", [0.0, 0.0, 0.0, 1.0])
    if len(rotation) != 4 or any(not math.isfinite(float(value)) for value in rotation):
        raise RuntimeError(label + "旋转必须是四元数")

    norm = math.sqrt(sum(float(value) * float(value) for value in rotation))
    if abs(norm - 1.0) > 0.001:
        raise RuntimeError(label + "四元数必须归一化")

    result = unreal.Transform(location=position, scale=scale)
    result.rotation = unreal.Quat(*(float(value) for value in rotation))
    return result


def _contact_weight(frame, contacts, row_weight):
    """/** @param frame	当前动画帧 @param contacts	接触区间 @param row_weight	整项权重 @return 平滑接触权重 */"""
    contact_weight = 0.0
    for contact in contacts:
        start = contact["start_frame"]
        end = contact["end_frame"]
        fade_in = contact.get("fade_in_frames", 0)
        fade_out = contact.get("fade_out_frames", 0)
        weight = 1.0
        if fade_in > 0:
            value = max(0.0, min(1.0, (frame - start) / fade_in))
            weight = value * value * (3.0 - 2.0 * value)

        if fade_out > 0:
            value = max(0.0, min(1.0, (end - frame) / fade_out))
            weight = min(weight, value * value * (3.0 - 2.0 * value))

        if start <= frame <= end:
            contact_weight = max(contact_weight, weight)

    return contact_weight * row_weight


def _binding_for_mesh(sequence, mesh):
    """/** @param sequence	关卡序列 @param mesh	角色网格 @return 唯一角色绑定 */"""
    matches = []
    for binding in sequence.get_bindings():
        template = binding.get_object_template()
        if isinstance(template, unreal.SkeletalMeshActor):
            if template.skeletal_mesh_component.get_skeletal_mesh_asset() == mesh:
                matches.append(binding)

    if len(matches) != 1:
        raise RuntimeError("模板中的角色网格绑定必须唯一")

    return matches[0]


def _set_spawn_range(binding, end_frame):
    """/** @param binding	生成绑定 @param end_frame	独占结束帧 @return 无返回值 */"""
    for track in binding.find_tracks_by_type(unreal.MovieSceneSpawnTrack):
        for section in track.get_sections():
            section.set_range(0, end_frame + 1)
            channels = section.get_all_channels()
            if len(channels) != 1:
                raise RuntimeError("生成轨道必须只有一个显隐通道")

            channel = channels[0]
            for key in list(channel.get_keys()):
                channel.remove_key(key)

            channel.set_default(True)
            channel.add_key(unreal.FrameNumber(value=0), True)
            channel.add_key(unreal.FrameNumber(value=end_frame), False)


def _set_component_keys(channels, hierarchy, control_name, transforms, frames):
    """/** @param channels	控制器通道 @param hierarchy	控制层级 @param control_name	控制器 @param transforms	组件空间目标数组 @param frames	显示帧数组 @return 无返回值 */"""
    key = authoring._key(control_name, "CONTROL")
    if hierarchy.get_parents(key):
        raise RuntimeError("批量组件空间写键不支持带父级控制器 " + control_name)

    offset = hierarchy.get_global_control_offset_transform(key, True)
    suffixes = (
        "Location.X", "Location.Y", "Location.Z", "Rotation.X", "Rotation.Y",
        "Rotation.Z", "Scale.X", "Scale.Y", "Scale.Z",
    )
    targets = []
    for suffix in suffixes:
        name = control_name + "." + suffix
        if name not in channels:
            raise RuntimeError("控制器关键帧通道缺失 " + name)
        targets.append(channels[name])
    previous_rotation = None
    for frame, transform in zip(frames, transforms):
        local = transform.make_relative(offset)
        rotation = local.rotation.rotator()
        angles = [rotation.roll, rotation.pitch, rotation.yaw]
        if previous_rotation is not None:
            angles = [value + 360.0 * round((previous - value) / 360.0)
                      for value, previous in zip(angles, previous_rotation)]
        previous_rotation = angles
        values = [local.translation.x, local.translation.y, local.translation.z]
        values.extend(angles)
        values.extend([local.scale3d.x, local.scale3d.y, local.scale3d.z])
        for channel, value in zip(targets, values):
            channel.add_key(
                frame, value, 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE,
                unreal.MovieSceneKeyInterpolation.LINEAR,
            )


def _contact_ranges(row, count):
    """/** @param row	单项清单 @param count	源动画帧数 @return 合法接触区间与整项权重 */"""
    contacts = row["contacts"]
    if not contacts:
        raise RuntimeError("每条动画至少需要一个左手接触区间")

    previous_end = -1
    for contact in contacts:
        start = int(contact["start_frame"])
        end = int(contact["end_frame"])
        fade_in = int(contact.get("fade_in_frames", 0))
        fade_out = int(contact.get("fade_out_frames", 0))
        if start < 0 or end < start or end >= count:
            raise RuntimeError("接触帧区间超出动画 " + str([start, end]))
        if fade_in < 0 or fade_out < 0 or fade_in > end - start or fade_out > end - start:
            raise RuntimeError("接触淡入淡出帧数无效 " + str([start, end]))
        if start <= previous_end:
            raise RuntimeError("接触区间必须按时间排序且互不重叠")

        previous_end = end

    row_weight = float(row.get("weight", 1.0))
    if not math.isfinite(row_weight) or row_weight < 0.0 or row_weight > 1.0:
        raise RuntimeError("左手修正权重必须位于零到一之间")

    return contacts, row_weight


def _read_pose(animation, mesh, frame, rate):
    """/** @param animation	源动画 @param mesh	角色网格 @param frame	采样帧 @param rate	原始帧率 @return 骨骼组件空间姿势 */"""
    time_seconds = frame * rate.denominator / rate.numerator
    pose = authoring._pose(animation, mesh, time_seconds)
    names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(pose)]
    transforms = {
        name.casefold(): unreal.AnimPoseExtensions.get_bone_pose(
            pose,
            name,
            unreal.AnimPoseSpaces.WORLD,
        )
        for name in names
    }
    if not transforms:
        raise RuntimeError("动画姿势为空 帧 " + str(frame))

    return transforms


def _validate_contact_reach(pose, target, pole=None):
    """/** @param pose	原始姿势 @param target	左手目标 @param pole	肘部极向目标 @return 可达性通过 */"""
    shoulder = pose.get("upperarm_l")
    elbow = pose.get("lowerarm_l")
    wrist = pose.get("hand_l")
    if shoulder is None or elbow is None or wrist is None:
        raise RuntimeError("动画缺少左臂 IK 所需骨骼")

    first_length = (elbow.translation - shoulder.translation).length()
    second_length = (wrist.translation - elbow.translation).length()
    distance = (target.translation - shoulder.translation).length()
    if first_length <= 0.01 or second_length <= 0.01:
        raise RuntimeError("左臂骨长无效")
    if distance > first_length + second_length - 0.1:
        raise RuntimeError("左手接触目标超出当前姿势的手臂可达范围")
    if distance < abs(first_length - second_length) + 0.1:
        raise RuntimeError("左手接触目标过近 无法稳定求解肘部")

    arm_axis = target.translation - shoulder.translation
    axis_length = arm_axis.length()
    if axis_length < 0.1:
        raise RuntimeError("左手接触目标与肩部重合")
    axis = unreal.Vector(
        arm_axis.x / axis_length,
        arm_axis.y / axis_length,
        arm_axis.z / axis_length,
    )
    pole_position = elbow.translation
    if pole is not None:
        pole_position = pole.translation

    elbow_direction = pole_position - shoulder.translation
    projection = (
        elbow_direction.x * axis.x
        + elbow_direction.y * axis.y
        + elbow_direction.z * axis.z
    )
    pole_direction = elbow_direction - axis * projection
    if pole_direction.length() < 0.1:
        raise RuntimeError("肘部 Pole Vector 与手臂轴线重合 请提供 pole_in_hand_r")


def _fit_contact_shoulder(pose, target, hierarchy):
    """/** @param pose	当前组件姿势 @param target	混合后的接触目标 @param hierarchy	骨骼层级 @return 左锁骨修正角度 */"""
    clavicle = pose["clavicle_l"]
    shoulder = pose["upperarm_l"]
    elbow = pose["lowerarm_l"]
    wrist = pose["hand_l"]
    reach = (elbow.translation - shoulder.translation).length()
    reach += (wrist.translation - elbow.translation).length()
    safe_reach = reach - 1.0
    if (target.translation - shoulder.translation).length() <= safe_reach:
        return 0.0

    offset = shoulder.translation - clavicle.translation
    direction = target.translation - clavicle.translation
    offset_length = offset.length()
    direction_length = direction.length()
    if offset_length < 0.1 or direction_length < 0.1:
        raise RuntimeError("锁骨长度或接触方向无效")
    first = offset / offset_length
    second = direction / direction_length
    dot = max(-1.0, min(1.0, first.x * second.x + first.y * second.y + first.z * second.z))
    axis = unreal.Vector(
        first.y * second.z - first.z * second.y,
        first.z * second.x - first.x * second.z,
        first.x * second.y - first.y * second.x,
    )
    axis_length = axis.length()
    if axis_length < 0.00001:
        raise RuntimeError("锁骨无法通过旋转接近手部目标")
    axis = axis / axis_length
    high = min(math.acos(dot), math.radians(35.0))
    low = 0.0
    for _ in range(24):
        angle = (low + high) * 0.5
        sine = math.sin(angle * 0.5)
        delta = unreal.Quat(axis.x * sine, axis.y * sine, axis.z * sine, math.cos(angle * 0.5))
        location = clavicle.translation + delta.rotate_vector(offset)
        if (target.translation - location).length() > safe_reach:
            low = angle
        if (target.translation - location).length() <= safe_reach:
            high = angle
    sine = math.sin(high * 0.5)
    delta = unreal.Quat(axis.x * sine, axis.y * sine, axis.z * sine, math.cos(high * 0.5))
    location = clavicle.translation + delta.rotate_vector(offset)
    if (target.translation - location).length() > safe_reach + 0.001:
        raise RuntimeError("接触目标需要超过35度的锁骨修正")

    origin = clavicle.translation
    keys = [authoring._key("clavicle_l")]
    keys.extend(hierarchy.get_children(keys[0], True))
    for key in keys:
        name = str(key.name).casefold()
        if key.type != unreal.RigElementType.BONE or name not in pose:
            continue
        transform = pose[name]
        transform.translation = origin + delta.rotate_vector(transform.translation - origin)
        transform.rotation = delta * transform.rotation
    return math.degrees(high)


def _clear_control_keys(track):
    """/** @param track	控制绑定轨道 @return 清除旧关键帧 */"""
    for section in track.get_sections():
        for channel in section.get_all_channels():
            for key in list(channel.get_keys()):
                channel.remove_key(key)


def _transform_readback_error(actual, expected, offset):
    """/** @param actual	控制器读回值 @param expected	组件空间目标 @param offset	控制器偏移 @return 位置及旋转误差 */"""
    local = expected.make_relative(offset)
    actual_rotation = actual.rotation.quaternion()
    difference = actual_rotation * local.rotation.inversed()
    angle = math.degrees(2.0 * math.acos(min(1.0, abs(difference.w))))
    position = (actual.location - local.translation).length()
    return position, angle


def _delete_failed_output(asset, path):
    """/** @param asset 本次新建资产 @param path 输出路径 @return 清理完成 */"""
    if asset is not None:
        unreal.EditorAssetLibrary.delete_loaded_asset(asset)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        raise RuntimeError("失败输出未能清理 " + path)


def _write_item(row):
    """/** @param row	单项动画与输出配置 @return 序列关键帧及保存回读报告 */"""
    source_path = row["animation_path"]
    template_path = row["template_sequence_path"]
    mesh_path = row["mesh_path"]
    sequence_path = row["sequence_path"]
    if not sequence_path.startswith("/Game/_Project/"):
        raise RuntimeError("输出序列必须位于 /Game/_Project/")
    if unreal.EditorAssetLibrary.does_asset_exist(sequence_path):
        raise RuntimeError("拒绝覆盖已有序列 " + sequence_path)

    animation = _asset(source_path, unreal.AnimSequence)
    template = _asset(template_path, unreal.LevelSequence)
    mesh = _asset(mesh_path, unreal.SkeletalMesh)
    count, rate = _frame_count(animation)
    contacts, row_weight = _contact_ranges(row, count)
    grip = _transform(row["grip_in_hand_r"], "右手空间握持目标")
    pole_offset = None
    if row.get("pole_in_hand_r") is not None:
        pole_offset = _transform(row["pole_in_hand_r"], "右手空间肘部 Pole Vector")

    if animation.get_editor_property("skeleton") != mesh.get_editor_property("skeleton"):
        raise RuntimeError("动画与角色网格骨架不一致")

    require_asset_write([], destinations=[sequence_path])
    folder = sequence_path.rsplit("/", 1)[0]
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        if not unreal.EditorAssetLibrary.make_directory(folder):
            raise RuntimeError("创建输出序列目录失败 " + folder)

    sequence = unreal.EditorAssetLibrary.duplicate_asset(template_path, sequence_path)
    if not isinstance(sequence, unreal.LevelSequence):
        raise RuntimeError("复制关卡序列模板失败")

    try:
        tick_numerator = rate.numerator * max(1, math.ceil(24000 / rate.numerator))
        sequence.set_tick_resolution_directly(unreal.FrameRate(numerator=tick_numerator, denominator=1))
        sequence.set_display_rate(rate)
        sequence.set_playback_start(0)
        sequence.set_playback_end(count)
        binding = _binding_for_mesh(sequence, mesh)
        animation_tracks = binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack)
        rig_tracks = binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
        if len(animation_tracks) != 1 or len(rig_tracks) != 1:
            raise RuntimeError("模板必须包含唯一源动画轨道和 Control Rig 轨道")

        animation_sections = animation_tracks[0].get_sections()
        rig_sections = rig_tracks[0].get_sections()
        if len(animation_sections) != 1 or len(rig_sections) != 1:
            raise RuntimeError("模板动画轨道片段必须唯一")
        animation_section = animation_sections[0]
        parameters = animation_section.get_editor_property("params")
        parameters.animation = animation
        parameters.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(1.0)
        parameters.first_loop_start_frame_offset = unreal.FrameNumber(value=0)
        parameters.start_frame_offset = unreal.FrameNumber(value=0)
        parameters.end_frame_offset = unreal.FrameNumber(value=0)
        parameters.reverse = False
        animation_section.set_editor_property("params", parameters)
        animation_section.set_is_active(False)
        animation_section.set_range(0, count)
        rig_sections[0].set_range(0, count)
        for current in sequence.get_bindings():
            _set_spawn_range(current, count)
            for track in current.get_tracks():
                for section in track.get_sections():
                    if isinstance(track, unreal.MovieScene3DAttachTrack):
                        section.set_range(0, count)
                    if isinstance(track, unreal.MovieScene3DTransformTrack):
                        section.set_range(0, count)

        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        proxies = [
            proxy
            for proxy in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
            if proxy.track == rig_tracks[0]
        ]
        if len(proxies) != 1:
            raise RuntimeError("模板 Control Rig 实例必须唯一")

        rig = proxies[0].control_rig
        hierarchy = rig.get_hierarchy()
        controls = {
            str(key.name).casefold(): str(key.name)
            for key in hierarchy.get_controls()
        }
        source_controls = {
            name[len("source_"):].casefold(): name
            for name in controls.values()
            if name.casefold().startswith("source_")
        }
        required = {"hand_l_ik_ctrl", "elbow_l_pv_ctrl"}
        if not required.issubset(controls):
            raise RuntimeError("模板缺少左手 IK 或肘部控制器")

        bone_names = [
            str(name)
            for name in unreal.AnimPoseExtensions.get_bone_names(
                authoring._pose(animation, mesh, 0.0)
            )
        ]
        missing = [
            name
            for name in bone_names
            if name.casefold() not in source_controls
        ]
        if missing:
            raise RuntimeError("模板缺少原姿势骨骼控制器 " + ",".join(missing[:12]))

        _clear_control_keys(rig_tracks[0])
        channels = {str(channel.channel_name): channel
                    for section in rig_tracks[0].get_sections()
                    for channel in section.get_all_channels()}
        frame_numbers = [unreal.FrameNumber(value=frame) for frame in range(count)]
        hand_expectations = []
        pole_expectations = []
        source_values = {name: [] for name in bone_names}
        shoulder_angles = []
        for frame in range(count):
            pose = _read_pose(animation, mesh, frame, rate)
            right_hand = pose.get("hand_r")
            left_hand = pose.get("hand_l")
            elbow = pose.get("lowerarm_l")
            if right_hand is None or left_hand is None or elbow is None:
                raise RuntimeError("源动画缺少左右手或左肘骨骼")

            target = unreal.Transform(
                location=right_hand.transform_location(grip.translation),
                scale=grip.scale3d,
            )
            target.rotation = right_hand.rotation * grip.rotation
            pole = elbow
            if pole_offset is not None:
                pole = unreal.Transform(
                    location=right_hand.transform_location(pole_offset.translation),
                    scale=pole_offset.scale3d,
                )
                pole.rotation = right_hand.rotation * pole_offset.rotation

            alpha = _contact_weight(frame, contacts, row_weight)
            blended_hand = left_hand.lerp(target, alpha)
            shoulder_angle = 0.0
            if alpha > 0.0:
                shoulder_angle = _fit_contact_shoulder(pose, blended_hand, hierarchy)
                _validate_contact_reach(pose, blended_hand, pole)
            shoulder_angles.append(shoulder_angle)

            for bone_name in bone_names:
                source_values[bone_name].append(pose[bone_name.casefold()])
            hand_expectations.append(blended_hand)
            pole_expectations.append(pole)
            if frame % 30 == 0:
                unreal.log(
                    "[BBBHandRetargetBatch] 写入 {} 帧 {}/{}".format(
                        sequence_path,
                        frame + 1,
                        count,
                    )
                )

        for bone_name, transforms in source_values.items():
            _set_component_keys(
                channels, hierarchy, source_controls[bone_name.casefold()],
                transforms, frame_numbers,
            )
        _set_component_keys(
            channels, hierarchy, controls["hand_l_ik_ctrl"],
            hand_expectations, frame_numbers,
        )
        _set_component_keys(
            channels, hierarchy, controls["elbow_l_pv_ctrl"],
            pole_expectations, frame_numbers,
        )
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        hand_actuals = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transforms(
            sequence,
            rig,
            controls["hand_l_ik_ctrl"],
            frame_numbers,
        )
        pole_actuals = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transforms(
            sequence,
            rig,
            controls["elbow_l_pv_ctrl"],
            frame_numbers,
        )
        if len(hand_actuals) != count or len(pole_actuals) != count:
            raise RuntimeError("左手与肘部控制器关键帧回读数量不一致")
        hand_offset = hierarchy.get_global_control_offset_transform(
            authoring._key(controls["hand_l_ik_ctrl"], "CONTROL"),
            True,
        )
        pole_offset_transform = hierarchy.get_global_control_offset_transform(
            authoring._key(controls["elbow_l_pv_ctrl"], "CONTROL"),
            True,
        )
        max_hand_position_error = 0.0
        max_hand_rotation_error = 0.0
        max_pole_position_error = 0.0
        for actual, expected in zip(hand_actuals, hand_expectations):
            position_error, rotation_error = _transform_readback_error(
                actual,
                expected,
                hand_offset,
            )
            max_hand_position_error = max(max_hand_position_error, position_error)
            max_hand_rotation_error = max(max_hand_rotation_error, rotation_error)

        for actual, expected in zip(pole_actuals, pole_expectations):
            position_error, _ = _transform_readback_error(
                actual,
                expected,
                pole_offset_transform,
            )
            max_pole_position_error = max(max_pole_position_error, position_error)
        if max_hand_position_error > 0.05 or max_hand_rotation_error > 0.05:
            raise RuntimeError("左手目标控制关键帧回读超出精度")
        if max_pole_position_error > 0.05:
            raise RuntimeError("肘部 Pole Vector 关键帧回读超出精度")

        keyed_channels = sum(
            len(channel.get_keys())
            for section in rig_tracks[0].get_sections()
            for channel in section.get_all_channels()
        )
        expected_channels = (count * (len(bone_names) + 2) * 9)
        if keyed_channels < expected_channels:
            raise RuntimeError("Control Rig 全姿势关键帧未完整写入")
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError("批量左手重定向序列保存失败")

        saved = _asset(sequence_path, unreal.LevelSequence)
        if saved.get_playback_end() != count:
            raise RuntimeError("保存后序列帧数回读不一致")

        return {
            "sequence": sequence_path,
            "sourceAnimation": source_path,
            "frames": count,
            "sampleRate": [rate.numerator, rate.denominator],
            "controls": ["hand_l_ik_ctrl", "elbow_l_pv_ctrl"],
            "sourceBoneControls": len(bone_names),
            "keyedChannels": keyed_channels,
            "maximumHandTargetErrorCm": max_hand_position_error,
            "maximumHandRotationErrorDegrees": max_hand_rotation_error,
            "maximumPolePositionErrorCm": max_pole_position_error,
            "maximumClavicleAdjustmentDegrees": max(shoulder_angles),
            "contactIntervals": contacts,
            "saved": True,
        }
    except Exception as error:
        unreal.log_error("[BBBHandRetargetBatch] 制作失败 " + sequence_path + " " + str(error))
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        raise


def _validate_additive_reference(animation, source):
    """/** @param animation 烘焙目标 @param source 原动画 @return 加法参考配置有效 */"""
    additive_type = animation.get_editor_property("additive_anim_type")
    if additive_type == unreal.AdditiveAnimationType.AAT_NONE:
        return None

    if additive_type != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE:
        raise RuntimeError("批量烘焙暂不支持非 Local Space Base Additive " + str(additive_type))

    reference_type = animation.get_editor_property("ref_pose_type")
    if reference_type not in (
        unreal.AdditiveBasePoseType.ABPT_LOCAL_ANIM_FRAME,
        unreal.AdditiveBasePoseType.ABPT_ANIM_FRAME,
    ):
        raise RuntimeError("批量烘焙要求 Additive 使用明确动画帧参考姿势")
    if reference_type == unreal.AdditiveBasePoseType.ABPT_ANIM_FRAME:
        reference = animation.get_editor_property("ref_pose_seq")
        if reference not in (source, animation):
            raise RuntimeError("批量烘焙的 Selected Anim Frame 参考必须是自身源动画")

    reference_frame = int(animation.get_editor_property("ref_frame_index"))
    source_count, _ = _frame_count(source)
    if reference_frame < 0 or reference_frame >= source_count:
        raise RuntimeError("Additive 参考帧超出源动画")

    return reference_frame


def _restore_non_left_arm_tracks(source, baked, mesh, allowed_bones):
    """/** @param source	原动画 @param baked	导出结果 @param mesh	角色网格 @param allowed_bones	左臂轨道白名单 @return 实际写入轨道名 */"""
    source_count, _ = _frame_count(source)
    baked_count, _ = _frame_count(baked)
    if source_count != baked_count:
        raise RuntimeError("烘焙输出与源动画帧数不一致")

    _validate_additive_reference(baked, source)
    source_pose = authoring._pose(source, mesh, 0.0)
    bone_names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(source_pose)]
    allowed = {name.casefold() for name in allowed_bones}
    controller = baked.controller
    changed_bones = []
    for name in bone_names:
        source_values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, name)
        baked_values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(baked, name)
        if not source_values:
            if name.casefold() in allowed:
                if len(baked_values) != baked_count:
                    raise RuntimeError("左臂烘焙轨道帧数无效 " + name)

                positions = []
                rotations = []
                scales = []
                for pose_value in baked_values:
                    positions.append(pose_value.translation)
                    rotations.append(pose_value.rotation)
                    scales.append(pose_value.scale3d)
                if not controller.set_bone_track_keys(name, positions, rotations, scales, False):
                    raise RuntimeError("左臂烘焙轨道回写失败 " + name)
                changed_bones.append(name)

            if name.casefold() not in allowed and baked_values:
                if not controller.remove_bone_track(name, False):
                    raise RuntimeError("移除烘焙新增的非左臂轨道失败 " + name)

            continue
        if len(source_values) != source_count or len(baked_values) != baked_count:
            raise RuntimeError("骨骼轨道帧数与源动画不一致 " + name)

        if name.casefold() in allowed:
            positions = []
            rotations = []
            scales = []
            for pose_value in baked_values:
                positions.append(pose_value.translation)
                rotations.append(pose_value.rotation)
                scales.append(pose_value.scale3d)

            changed_bones.append(name)
        if name.casefold() not in allowed:
            positions = [value.translation for value in source_values]
            rotations = [value.rotation for value in source_values]
            scales = [value.scale3d for value in source_values]

        if not controller.set_bone_track_keys(name, positions, rotations, scales, False):
            raise RuntimeError("左手烘焙轨道回写失败 " + name)

    return sorted(changed_bones)


def _validate_bake(source, baked, mesh, allowed_bones):
    """/** @param source\t原动画 @param baked\t最终动画 @param mesh\t角色网格 @param allowed_bones\t左臂轨道白名单 @return 逐帧变更报告 */"""
    source_count, rate = _frame_count(source)
    baked_count, baked_rate = _frame_count(baked)
    if (
        source_count != baked_count
        or rate.numerator != baked_rate.numerator
        or rate.denominator != baked_rate.denominator
    ):
        raise RuntimeError("烘焙结果的帧数或帧率与源动画不一致")
    if abs(source.get_play_length() - baked.get_play_length()) > 0.0001:
        raise RuntimeError("烘焙结果时长与源动画不一致")

    allowed = {name.casefold() for name in allowed_bones}
    max_position = 0.0
    max_rotation = 0.0
    modified = set()
    for frame in range(source_count):
        time_seconds = frame * rate.denominator / rate.numerator
        before = authoring._pose(source, mesh, time_seconds)
        after = authoring._pose(baked, mesh, time_seconds)
        before_names = {
            str(name).casefold(): name
            for name in unreal.AnimPoseExtensions.get_bone_names(before)
        }
        after_names = {
            str(name).casefold(): name
            for name in unreal.AnimPoseExtensions.get_bone_names(after)
        }
        if before_names.keys() != after_names.keys():
            raise RuntimeError("烘焙结果的骨骼集合与源动画不一致")

        for normalized, name in before_names.items():
            first = unreal.AnimPoseExtensions.get_bone_pose(
                before,
                name,
                unreal.AnimPoseSpaces.LOCAL,
            )
            second = unreal.AnimPoseExtensions.get_bone_pose(
                after,
                after_names[normalized],
                unreal.AnimPoseSpaces.LOCAL,
            )
            position_error = (first.translation - second.translation).length()
            dot = abs(
                first.rotation.x * second.rotation.x
                + first.rotation.y * second.rotation.y
                + first.rotation.z * second.rotation.z
                + first.rotation.w * second.rotation.w
            )
            rotation_error = math.degrees(2.0 * math.acos(min(1.0, dot)))
            if normalized not in allowed and (
                position_error > 0.05 or rotation_error > 0.1
            ):
                raise RuntimeError(
                    "烘焙改变左臂以外的骨骼 "
                    + str(name)
                    + " 帧 "
                    + str(frame)
                )

            max_position = max(max_position, position_error)
            max_rotation = max(max_rotation, rotation_error)
            if normalized in allowed and (
                position_error > 0.05 or rotation_error > 0.1
            ):
                modified.add(str(name))

    if not modified:
        raise RuntimeError("烘焙没有产生左臂目标修正")
    if max_position > 40.0 or max_rotation > 150.0:
        raise RuntimeError(
            "左臂修正幅度异常 位置 {:.3f}cm 旋转 {:.3f}度".format(
                max_position, max_rotation,
            )
        )

    return {
        "frames": source_count,
        "changedLeftArmBones": sorted(modified),
        "maximumLocalPositionErrorCm": max_position,
        "maximumLocalRotationErrorDegrees": max_rotation,
    }


def _notify_signature(animation):
    """/** @param animation\t动画资产 @return 通知名称类型与时间签名 */"""
    values = []
    for event in unreal.AnimationLibrary.get_animation_notify_events(animation):
        notify = event.get_editor_property("notify")
        state = event.get_editor_property("notify_state_class")
        class_path = ""
        if notify is not None:
            class_path = notify.get_class().get_path_name()
        if state is not None:
            class_path = state.get_class().get_path_name()
        values.append(
            (
                str(event.get_editor_property("notify_name")),
                class_path,
                round(unreal.AnimationLibrary.get_anim_notify_event_trigger_time(event), 6),
                round(unreal.AnimationLibrary.get_anim_notify_event_duration(event), 6),
                state is not None,
            )
        )

    return sorted(values)


def _float_curve_signature(animation):
    """/** @param animation\t动画资产 @return 浮点曲线及原始关键帧签名 */"""
    result = {}
    for name in unreal.AnimationLibrary.get_animation_curve_names(
        animation,
        unreal.RawCurveTrackTypes.RCT_FLOAT,
    ):
        curve_name = str(name)
        keys = generic_editor._float_curve_key_details(
            animation,
            curve_name,
        )
        for key in keys:
            if "cubic" not in key["interp_mode"].casefold():
                key["arrive_tangent"] = 0.0
                key["leave_tangent"] = 0.0
        result[curve_name.casefold()] = keys

    return result

@unreal.uclass()
class BBBHandRetargetBatchToolset(unreal.ToolsetDefinition):
    """
    /**
     * 批量生成左手 IK 重定向序列并烘焙私有动画
     */
    """

    @mcp_tool
    @staticmethod
    def build_hand_retarget_sequences(manifest_json: str, write_paths: list[str]) -> str:
        """
        /**
         * 从明确的源动画与接触区间批量建立可编辑重定向序列
         * @param manifest_json	动画 序列 网格 握持变换及接触帧数组
         * @param write_paths	与清单输出序列逐项匹配的写入路径
         * @return 每项序列路径 控制器和保存回读结果
         */
        """
        manifest = json.loads(manifest_json)
        if not isinstance(manifest, list) or not manifest or len(manifest) > 32:
            raise RuntimeError("批量清单必须为一到三十二项")

        output_paths = [row["sequence_path"] for row in manifest]
        if len(set(path.casefold() for path in output_paths)) != len(output_paths):
            raise RuntimeError("批量清单包含重复输出序列路径")
        if sorted(path.casefold() for path in output_paths) != sorted(
            path.casefold() for path in write_paths
        ):
            raise RuntimeError("批量写入范围与清单不一致")

        results = []
        for row in manifest:
            existed_before = unreal.EditorAssetLibrary.does_asset_exist(row["sequence_path"])
            try:
                results.append(_write_item(row))
            except Exception as error:
                unreal.log_error(
                    "[BBBHandRetargetBatch] 序列失败 {} {}".format(
                        row.get("sequence_path", ""),
                        error,
                    )
                )
                results.append(
                    {
                        "sequence": row.get("sequence_path", ""),
                        "sourceAnimation": row.get("animation_path", ""),
                        "saved": False,
                        "error": str(error),
                    }
                )
            if not results[-1]["saved"] and not existed_before:
                _delete_failed_output(None, row["sequence_path"])

        return json.dumps(results, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def bake_hand_retarget_sequences(manifest_json: str, write_paths: list[str]) -> str:
        """
        /**
         * 烘焙左手重定向序列并只替换左臂骨骼轨道
         * @param manifest_json	源动画 序列 网格和目标动画路径数组
         * @param write_paths	与清单烘焙目标逐项匹配的写入路径
         * @return 帧数 根运动曲线通知与左臂轨道核验
         */
        """
        manifest = json.loads(manifest_json)
        if not isinstance(manifest, list) or not manifest or len(manifest) > 32:
            raise RuntimeError("批量清单必须为一到三十二项")

        requested_outputs = [row["output_animation_path"] for row in manifest]
        if len(set(path.casefold() for path in requested_outputs)) != len(requested_outputs):
            raise RuntimeError("批量清单包含重复输出动画路径")
        if sorted(path.casefold() for path in requested_outputs) != sorted(
            path.casefold() for path in write_paths
        ):
            raise RuntimeError("批量写入范围与清单不一致")

        results = []
        for row in manifest:
            output_path = row["output_animation_path"]
            source_path = row["animation_path"]
            created = None
            try:
                if not output_path.startswith("/Game/_Project/"):
                    raise RuntimeError("输出动画必须位于 /Game/_Project/")
                if unreal.EditorAssetLibrary.does_asset_exist(output_path):
                    raise RuntimeError("拒绝覆盖已有输出动画 " + output_path)

                source = _asset(source_path, unreal.AnimSequence)
                sequence = _asset(row["sequence_path"], unreal.LevelSequence)
                mesh = _asset(row["mesh_path"], unreal.SkeletalMesh)
                _binding_for_mesh(sequence, mesh)
                allowed_bones = _LEFT_ARM_BONES
                source_notifies = unreal.AnimationLibrary.get_animation_notify_events(source)
                source_root_motion = source.get_editor_property("enable_root_motion")
                source_additive = source.get_editor_property("additive_anim_type")
                additive_properties = {
                    name: source.get_editor_property(name)
                    for name in (
                        "additive_anim_type",
                        "ref_pose_type",
                        "ref_pose_seq",
                        "ref_frame_index",
                    )
                }
                require_asset_write([], destinations=[output_path])
                folder = output_path.rsplit("/", 1)[0]
                if not unreal.EditorAssetLibrary.does_directory_exist(folder):
                    if not unreal.EditorAssetLibrary.make_directory(folder):
                        raise RuntimeError("创建烘焙输出目录失败 " + folder)

                created = unreal.EditorAssetLibrary.duplicate_asset(source_path, output_path)
                if not isinstance(created, unreal.AnimSequence):
                    raise RuntimeError("复制源动画失败")

                authoring.BBBControlRigAuthoringToolset.bake_control_rig_animation(
                    row["sequence_path"],
                    output_path,
                    row["mesh_path"],
                )
                created = _asset(output_path, unreal.AnimSequence)
                if additive_properties["ref_pose_seq"] == source:
                    additive_properties["ref_pose_seq"] = created
                for name, value in additive_properties.items():
                    created.set_editor_property(name, value)

                changed = _restore_non_left_arm_tracks(
                    source,
                    created,
                    mesh,
                    allowed_bones,
                )
                if created.get_editor_property("enable_root_motion") != source_root_motion:
                    raise RuntimeError("烘焙改变了源动画 Root Motion 设置")
                if created.get_editor_property("additive_anim_type") != source_additive:
                    raise RuntimeError("烘焙改变了源动画 Additive 类型")

                result = _validate_bake(source, created, mesh, allowed_bones)
                result["sequence"] = row["sequence_path"]
                result["sourceAnimation"] = source_path
                result["outputAnimation"] = output_path
                result["rootMotion"] = source_root_motion
                result["additiveType"] = str(source_additive)
                source_curves = _float_curve_signature(source)
                baked_curves = _float_curve_signature(created)
                if source_curves != baked_curves:
                    differing = next(
                        name for name in sorted(source_curves.keys() | baked_curves.keys())
                        if source_curves.get(name) != baked_curves.get(name)
                    )
                    raise RuntimeError(
                        "烘焙结果浮点曲线关键帧与源动画不一致 " + differing
                        + " 源=" + str(source_curves.get(differing))[:700]
                        + " 输出=" + str(baked_curves.get(differing))[:700]
                    )
                result["floatCurves"] = [
                    str(name)
                    for name in unreal.AnimationLibrary.get_animation_curve_names(
                        created,
                        unreal.RawCurveTrackTypes.RCT_FLOAT,
                    )
                ]
                source_notify_signature = _notify_signature(source)
                baked_notify_signature = _notify_signature(created)
                if source_notify_signature != baked_notify_signature:
                    raise RuntimeError("烘焙结果通知类型或时间与源动画不一致")
                result["notifyCount"] = len(baked_notify_signature)
                result["trackBones"] = changed
                result["saved"] = unreal.EditorAssetLibrary.save_loaded_asset(
                    created,
                    False,
                )
                if not result["saved"]:
                    raise RuntimeError("保存烘焙结果失败")

                readback = _asset(output_path, unreal.AnimSequence)
                result["savedLength"] = readback.get_play_length()
                if readback.get_editor_property("enable_root_motion") != source_root_motion:
                    raise RuntimeError("保存后 Root Motion 设置与源动画不一致")
                for name, value in additive_properties.items():
                    if readback.get_editor_property(name) != value:
                        raise RuntimeError("保存后 Additive 设置与源动画不一致 " + name)
                if _float_curve_signature(source) != _float_curve_signature(readback):
                    raise RuntimeError("保存后浮点曲线关键帧与源动画不一致")
                if _notify_signature(source) != _notify_signature(readback):
                    raise RuntimeError("保存后通知类型或时间与源动画不一致")
                result["savedPoseReadback"] = _validate_bake(
                    source,
                    readback,
                    mesh,
                    allowed_bones,
                )
                results.append(result)
            except Exception as error:
                if created is not None:
                    _delete_failed_output(created, output_path)

                unreal.log_error(
                    "[BBBHandRetargetBatch] 烘焙失败 {} {}".format(
                        output_path,
                        error,
                    )
                )
                results.append(
                    {
                        "sourceAnimation": source_path,
                        "outputAnimation": output_path,
                        "saved": False,
                        "error": str(error),
                    }
                )

        return json.dumps(results, ensure_ascii=False)


_registration = Registration([BBBHandRetargetBatchToolset])
