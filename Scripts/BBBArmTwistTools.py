import hashlib
import json
import math
import os
import shutil
import time

import unreal


def _fail(message):
    """/** 记录修复失败并中止当前操作 */"""
    unreal.log_error("[BBB][ArmTwist] " + message)
    raise RuntimeError(message)


def _quat(value):
    """/** 读取并校验单位四元数 */"""
    result = [float(value.x), float(value.y), float(value.z), float(value.w)]
    length = math.sqrt(sum(component * component for component in result))
    if not all(math.isfinite(component) for component in result) or length < 0.00001:
        _fail("骨骼旋转包含无效数值")
    return [component / length for component in result]


def _multiply(first, second):
    """/** 按先右后左的顺序组合旋转 */"""
    x, y, z, w = first
    a, b, c, d = second
    return [w * a + x * d + y * c - z * b,
            w * b - x * c + y * d + z * a,
            w * c + x * b - y * a + z * d,
            w * d - x * a - y * b - z * c]


def _inverse(value):
    """/** 返回单位四元数的逆旋转 */"""
    return [-value[0], -value[1], -value[2], value[3]]


def _error(first, second):
    """/** 返回两个旋转之间的最小角度 */"""
    dot = abs(sum(a * b for a, b in zip(first, second)))
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def _raw_tracks(animation):
    """/** 读取原始完整姿势轨道 加法差值由引擎在压缩时生成 */"""
    result = {}
    selected = {"hand_l", "hand_r", "lowerarm_twist_01_l", "lowerarm_twist_01_r"}
    for name in animation.data_model_interface.get_bone_track_names():
        bone = str(name).casefold()
        if bone not in selected:
            continue
        transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
        if not transforms:
            _fail("读取原始骨骼轨道失败 " + bone)
        result[bone] = ([value.translation for value in transforms],
                        [value.rotation for value in transforms],
                        [value.scale3d for value in transforms])
    return result


def _expand(values, count, fallback):
    """/** 展开常量轨道并拒绝不完整关键帧 */"""
    if not values:
        return [fallback] * count
    if len(values) == 1:
        return values * count
    if len(values) != count:
        _fail("原始轨道关键帧数量不匹配")
    return values


def _context(mesh_path):
    """/** 校验前臂辅助骨层级并使用骨架参考姿势建立旋转基准 */"""
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        _fail("目标网格不存在 " + mesh_path)
    skeleton = mesh.get_editor_property("skeleton")
    reference = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
    names = {str(name).casefold() for name in reference.get_bone_names()}
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    specs = []
    for side in ("l", "r"):
        parent = "lowerarm_" + side
        hand = "hand_" + side
        target = "lowerarm_twist_01_" + side
        if not {parent, hand, target}.issubset(names):
            _fail("骨架缺少前臂或手部骨骼 " + side)
        if str(subsystem.get_bone_parent(mesh, target)).casefold() != parent:
            _fail("辅助骨必须直接附属于前臂 " + target)
        if str(subsystem.get_bone_parent(mesh, hand)).casefold() != parent:
            _fail("手骨必须直接附属于前臂 " + hand)
        if list(subsystem.get_bone_children(mesh, target)):
            _fail("辅助骨存在子骨骼 无法保证手部轨迹不变 " + target)
        hand_ref = reference.get_ref_bone_pose(hand, unreal.AnimPoseSpaces.LOCAL)
        target_ref = reference.get_ref_bone_pose(target, unreal.AnimPoseSpaces.LOCAL)
        vector = hand_ref.translation
        length = vector.length()
        if length < 0.01:
            _fail("前臂参考长度无效 " + parent)
        axis = [vector.x / length, vector.y / length, vector.z / length]
        weight = sum(a * b for a, b in zip(axis, [target_ref.translation.x, target_ref.translation.y, target_ref.translation.z])) / length
        if weight < 0.05 or weight > 0.95:
            _fail("辅助骨不在前臂内部 无法自动确定扭转分配 " + target)
        specs.append({"hand": hand, "target": target, "axis": axis,
                      "weight": weight, "handRef": hand_ref, "targetRef": target_ref})
    return mesh, skeleton, specs


def _prepare(animation, skeleton, specs):
    """/** 从手骨相对参考姿势提取轴向旋转并沿时间展开角度 */"""
    if not isinstance(animation, unreal.AnimSequence):
        _fail("目标资产不是动画序列")
    if animation.get_editor_property("skeleton") != skeleton:
        _fail("动画骨架与目标网格不一致 " + animation.get_path_name())
    model = animation.data_model_interface
    if model.get_number_of_transform_curves() != 0:
        _fail("动画包含编辑层变换曲线 需要先明确烘焙策略 " + animation.get_path_name())
    count = model.get_number_of_keys()
    if count < 1:
        _fail("动画没有有效关键帧")
    tracks = _raw_tracks(animation)
    result = {"asset": animation.get_path_name(), "keys": count,
              "additiveType": str(animation.get_editor_property("additive_anim_type")),
              "basePose": str(animation.get_editor_property("ref_pose_type")),
              "baseAnimation": str(animation.get_editor_property("ref_pose_seq")),
              "requiresRepair": False, "bones": {}}
    generated = {}
    for spec in specs:
        hand = spec["hand"]
        target = spec["target"]
        if hand not in tracks:
            _fail("动画缺少手骨轨道 " + animation.get_path_name() + " " + hand)
        hand_ref = _quat(spec["handRef"].rotation)
        target_ref = spec["targetRef"]
        hand_rotations = _expand(tracks[hand][1], count, spec["handRef"].rotation)
        original = tracks.get(target, ([], [], []))
        current = _expand(original[1], count, target_ref.rotation)
        rotations = []
        angles = []
        errors = []
        previous = None
        for index, rotation in enumerate(hand_rotations):
            delta = _multiply(_quat(rotation), _inverse(hand_ref))
            projection = sum(delta[component] * spec["axis"][component] for component in range(3))
            if math.hypot(projection, delta[3]) < 0.00001:
                _fail("手腕摆动接近一百八十度 无法稳定分解扭转 " + animation.get_path_name())
            angle = (2.0 * math.atan2(projection, delta[3]) + math.pi) % (2.0 * math.pi) - math.pi
            if previous is not None:
                angle += round((previous - angle) / (2.0 * math.pi)) * 2.0 * math.pi
            previous = angle
            half = angle * spec["weight"] * 0.5
            twist = [component * math.sin(half) for component in spec["axis"]] + [math.cos(half)]
            corrected = _multiply(twist, _quat(target_ref.rotation))
            rotations.append(unreal.Quat(*corrected))
            angles.append(math.degrees(angle))
            errors.append(_error(_quat(current[index]), corrected))
        max_step = max([abs(b - a) * spec["weight"] for a, b in zip(angles, angles[1:])] or [0.0])
        if max_step > 90.0:
            _fail("辅助骨相邻帧跳变超过九十度 " + animation.get_path_name())
        generated[target] = (
            _expand(original[0], count, target_ref.translation),
            rotations,
            _expand(original[2], count, target_ref.scale3d),
        )
        result["bones"][target] = {"trackExists": target in tracks, "weight": spec["weight"],
                                    "maximumCorrectionDegrees": max(errors),
                                    "averageCorrectionDegrees": sum(errors) / count,
                                    "handTwistRangeDegrees": [min(angles), max(angles)],
                                    "maximumStepDegrees": max_step}
        if target not in tracks or max(errors) > 0.05:
            result["requiresRepair"] = True
    return result, generated, tracks


def _protected_digest(animation, targets):
    """/** 对非目标轨道和动画事件生成签名 防止修复范围外的数据变化 */"""
    model = animation.data_model_interface
    native_hash = unreal.BBBBlueprintEditorLibrary.get_animation_protected_data_hash(animation, sorted(targets))
    if not native_hash:
        _fail("非目标动画数据校验失败")
    values = [native_hash]
    values.append(model.get_frame_rate().export_text())
    values.append(str(model.get_number_of_keys()))
    values.extend(event.export_text() for event in unreal.AnimationLibrary.get_animation_notify_events(animation))
    values.extend(marker.export_text() for marker in unreal.AnimationLibrary.get_animation_sync_markers(animation))
    for name in ("additive_anim_type", "ref_pose_type", "ref_pose_seq", "ref_frame_index",
                 "enable_root_motion", "force_root_lock", "root_motion_root_lock", "rate_scale"):
        value = animation.get_editor_property(name)
        if isinstance(value, unreal.Object):
            value = value.get_path_name()
        values.append(name + str(value))
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _report(prefix, result):
    """/** 将完整诊断写入独立报告并只返回摘要 */"""
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "ArmTwist"))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, prefix + "_" + str(time.time_ns()) + ".json")
    with open(path, "w", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=4)
    summary = {key: value for key, value in result.items() if key != "assets"}
    summary["reportPath"] = path
    return json.dumps(summary, ensure_ascii=False)


def audit(animation_paths, mesh_path):
    """
    /**
     * 审计指定动画的前臂扭转轨道
     * @param animation_paths	动画资产路径
     * @param mesh_path		目标骨骼网格
     * @return 审计摘要及完整报告路径
     */
    """
    mesh, skeleton, specs = _context(mesh_path)
    rows = []
    for path in animation_paths:
        animation = unreal.load_asset(path)
        row, generated, tracks = _prepare(animation, skeleton, specs)
        row["protectedDataSha256"] = _protected_digest(animation, {spec["target"] for spec in specs})
        rows.append(row)
    candidates = [row["asset"] for row in rows if row["requiresRepair"]]
    result = {"mesh": mesh.get_path_name(), "assetCount": len(rows),
              "candidateCount": len(candidates), "candidates": candidates, "assets": rows}
    unreal.log("[BBB][ArmTwist] 审计完成 动画数量 {} 待修复 {}".format(len(rows), len(candidates)))
    return _report("Audit", result)


def rebuild(animation_paths, mesh_path, dry_run=True):
    """
    /**
     * 校验签出状态后原位重建前臂辅助骨旋转
     * @param animation_paths	动画资产路径
     * @param mesh_path		目标骨骼网格
     * @param dry_run		仅预检开关
     * @return 修复摘要及完整报告路径
     */
    """
    if dry_run:
        return audit(animation_paths, mesh_path)
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        _fail("PIE 运行期间禁止写入动画")
    mesh, skeleton, specs = _context(mesh_path)
    targets = {spec["target"] for spec in specs}
    prepared = []
    for path in dict.fromkeys(animation_paths):
        animation = unreal.load_asset(path)
        row, generated, tracks = _prepare(animation, skeleton, specs)
        package_path = animation.get_path_name().split(".", 1)[0]
        if not package_path.startswith("/Game/"):
            _fail("只允许修改项目内容目录内的动画")
        filename = os.path.abspath(os.path.join(unreal.Paths.project_content_dir(), package_path[6:] + ".uasset"))
        state = unreal.SourceControl.query_file_state(filename)
        if not state.is_valid or state.is_checked_out_other or state.is_conflicted or state.is_deleted:
            _fail("资产版本控制状态不允许修改 " + filename)
        if not state.is_checked_out and not state.is_added:
            _fail("资产尚未独占签出 " + filename)
        if animation.get_package() in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages():
            _fail("目标动画存在未保存修改 " + package_path)
        prepared.append((animation, row, generated, tracks, filename))
    backup_directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "ArmTwist", "Backup_" + str(time.time_ns())))
    rows = []
    repaired = []
    for animation, row, generated, tracks, filename in prepared:
        if not row["requiresRepair"]:
            rows.append(row)
            continue
        relative = os.path.relpath(filename, os.path.abspath(unreal.Paths.project_content_dir()))
        backup = os.path.join(backup_directory, relative)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(filename, backup)
        digest = _protected_digest(animation, targets)
        controller = animation.controller
        controller.open_bracket("重建前臂扭转轨道", False)
        try:
            for target, data in generated.items():
                if target not in tracks:
                    if not controller.add_bone_track(target, False):
                        _fail("创建辅助骨轨道失败 " + target)
                if not controller.set_bone_track_keys(target, data[0], data[1], data[2], False):
                    _fail("写入辅助骨轨道失败 " + target)
        finally:
            controller.close_bracket(False)
        verification, expected, actual = _prepare(animation, skeleton, specs)
        if verification["requiresRepair"] or digest != _protected_digest(animation, targets):
            _fail("动画写入后验证失败 未保存 " + animation.get_path_name())
        for target in targets:
            for channel in (0, 2):
                original = _expand(tracks.get(target, ([], [], []))[channel], row["keys"],
                                   generated[target][channel][0])
                current = _expand(actual[target][channel], row["keys"], generated[target][channel][0])
                if any((first - second).length() > 0.0001 for first, second in zip(original, current)):
                    _fail("辅助骨平移或缩放意外变化 未保存 " + target)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            _fail("动画保存失败 " + animation.get_path_name())
        row["backup"] = backup
        row["protectedDataSha256"] = digest
        row["verification"] = verification
        rows.append(row)
        repaired.append(animation.get_path_name())
        unreal.log("[BBB][ArmTwist] 已修复并验证 " + animation.get_path_name())
    return _report("Repair", {"assetCount": len(rows), "repairedCount": len(repaired),
                               "repairedAssets": repaired, "backupDirectory": backup_directory,
                               "assets": rows})


def capture(animation_path, mesh_path, time_seconds, focus_bone, camera_offset, file_name):
    """
    /**
     * 在临时角色上渲染动画姿势供修复前后对照
     * @param animation_path	动画资产路径
     * @param mesh_path		目标网格路径
     * @param time_seconds	采样时间
     * @param focus_bone		相机关注骨骼
     * @param camera_offset	相机相对关注点的偏移
     * @param file_name		输出图像名称
     * @return 图像路径和拍摄参数
     */
    """
    if len(camera_offset) != 3 or os.path.basename(file_name) != file_name or not file_name.endswith(".png"):
        _fail("截图参数无效")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        _fail("姿势截图需要启用渲染的 PIE 世界")
    mesh, skeleton, specs = _context(mesh_path)
    animation = unreal.load_asset(animation_path)
    if not isinstance(animation, unreal.AnimSequence) or animation.get_editor_property("skeleton") != skeleton:
        _fail("截图动画骨架不匹配")
    actor = None
    camera = None
    try:
        origin = unreal.Vector(0.0, 0.0, 10000.0)
        actor = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
            world, unreal.SkeletalMeshActor, unreal.Transform(location=origin))
        if actor is None:
            _fail("创建临时预览角色失败")
        actor.set_actor_enable_collision(False)
        component = actor.skeletal_mesh_component
        component.set_skeletal_mesh_asset(mesh)
        if not unreal.BBBBlueprintEditorLibrary.evaluate_animation_preview_pose(component, animation, time_seconds):
            _fail("动画预览求值失败")
        if component.get_bone_index(focus_bone) < 0:
            _fail("相机关注骨骼不存在")
        target = component.get_socket_location(focus_bone)
        location = target + unreal.Vector(*camera_offset)
        rotation = unreal.MathLibrary.find_look_at_rotation(location, target)
        camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
            world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
        if camera is None:
            _fail("创建临时截图相机失败")
        capture_component = camera.capture_component2d
        render_target = unreal.RenderingLibrary.create_render_target2d(
            world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        capture_component.set_editor_property("texture_target", render_target)
        capture_component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        capture_component.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
        capture_component.set_editor_property("show_only_actors", [actor])
        capture_component.set_editor_property("fov_angle", 45.0)
        settings = capture_component.get_editor_property("post_process_settings")
        settings.set_editor_property("override_auto_exposure_method", True)
        settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        settings.set_editor_property("override_auto_exposure_bias", True)
        settings.set_editor_property("auto_exposure_bias", 10.0)
        capture_component.set_editor_property("post_process_settings", settings)
        capture_component.capture_scene()
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "ArmTwist", "Captures"))
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            _fail("截图文件已经存在 " + path)
        unreal.RenderingLibrary.export_render_target(world, render_target, directory, file_name)
        if not os.path.isfile(path) or os.path.getsize(path) < 1024:
            _fail("截图没有有效输出 请检查渲染宿主")
        return json.dumps({"imagePath": path, "animation": animation_path, "mesh": mesh_path,
                           "time": time_seconds, "focusBone": focus_bone, "cameraOffset": list(camera_offset)})
    finally:
        if camera is not None:
            camera.destroy_actor()
        if actor is not None:
            actor.destroy_actor()


def inspect_pie_arms():
    """/** 读取实际角色各网格的手臂姿势及活动动画用于比较源姿势和最终姿势 */"""
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        _fail("手臂检查需要 PIE 世界")
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    if pawn is None:
        _fail("本地角色不存在")
    report = json.loads(unreal.BBBBlueprintEditorLibrary.probe_character_animation_runtime(pawn))
    rows = []
    for component in pawn.get_components_by_class(unreal.SkeletalMeshComponent):
        mesh = component.get_skeletal_mesh_asset()
        if mesh is None:
            continue
        bones = {}
        for side in ("l", "r"):
            for prefix in ("upperarm_", "lowerarm_", "hand_", "lowerarm_twist_01_"):
                bone = prefix + side
                index = component.get_bone_index(bone)
                if index < 0:
                    continue
                transform = component.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_COMPONENT)
                parent = str(component.get_parent_bone(bone))
                parent_transform = component.get_socket_transform(parent, unreal.RelativeTransformSpace.RTS_COMPONENT)
                local = unreal.MathLibrary.make_relative_transform(transform, parent_transform)
                reference = component.get_ref_pose_transform(index)
                bones[bone] = {"component": transform.export_text(), "local": local.export_text(),
                               "quaternion": _quat(local.rotation), "referenceQuaternion": _quat(reference.rotation),
                               "worldPosition": str(component.get_socket_location(bone))}
        rows.append({"component": component.get_path_name(), "mesh": mesh.get_path_name(),
                     "visible": bool(component.is_visible()), "bones": bones})
    result = {"pawn": pawn.get_path_name(), "facts": report.get("facts"),
              "linkedLayers": report.get("linkedLayers"), "assets": rows}
    return _report("RuntimeArms", result)


def limit_hand_swing(animation_paths, mesh_path, maximum_swing_degrees, dry_run):
    """
    /**
     * 保留手腕轴向扭转并限制相对参考姿势的摆动
     * @param animation_paths	显式动画路径
     * @param mesh_path		目标网格
     * @param maximum_swing_degrees	最大摆动角度
     * @param dry_run		仅预检开关
     * @return 修复和验证报告
     */
    """
    if maximum_swing_degrees < 10.0 or maximum_swing_degrees > 80.0:
        _fail("手腕摆动限制必须在十至八十度之间")
    if not dry_run and unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        _fail("PIE 运行期间禁止修改动画")
    mesh, skeleton, specs = _context(mesh_path)
    spec = specs[0]
    hand = spec["hand"]
    reference = _quat(spec["handRef"].rotation)
    rows = []
    for path in animation_paths:
        animation = unreal.load_asset(path)
        audit_row, twist_tracks, tracks = _prepare(animation, skeleton, specs)
        rotations = []
        angles = []
        changed = 0
        for current in tracks[hand][1]:
            delta = _multiply(_quat(current), _inverse(reference))
            projection = sum(delta[index] * spec["axis"][index] for index in range(3))
            length = math.hypot(projection, delta[3])
            if length < 0.00001:
                _fail("手腕摆动接近奇异姿势")
            twist = [component * projection / length for component in spec["axis"]] + [delta[3] / length]
            swing = _multiply(delta, _inverse(twist))
            if swing[3] < 0.0:
                swing = [-component for component in swing]
            angle = 2.0 * math.acos(max(-1.0, min(1.0, swing[3])))
            angles.append(math.degrees(angle))
            if math.degrees(angle) <= maximum_swing_degrees + 0.001:
                rotations.append(current)
                continue
            changed += 1
            sine = math.sqrt(sum(component * component for component in swing[:3]))
            half = math.radians(maximum_swing_degrees) * 0.5
            limited = [component * math.sin(half) / sine for component in swing[:3]] + [math.cos(half)]
            corrected = _multiply(_multiply(limited, twist), reference)
            rotations.append(unreal.Quat(*corrected))
        row = {"asset": animation.get_path_name(), "hand": hand, "changedKeys": changed,
               "sourceSwingRangeDegrees": [min(angles), max(angles)],
               "maximumSwingDegrees": maximum_swing_degrees, "dryRun": dry_run}
        if dry_run or not changed:
            rows.append(row)
            continue
        package_path = animation.get_path_name().split(".", 1)[0]
        if not package_path.startswith("/Game/"):
            _fail("只允许修改项目动画")
        filename = os.path.abspath(os.path.join(unreal.Paths.project_content_dir(), package_path[6:] + ".uasset"))
        state = unreal.SourceControl.query_file_state(filename)
        if not state.is_valid or state.is_checked_out_other or state.is_conflicted or state.is_deleted:
            _fail("版本控制状态不允许修改动画")
        if not state.is_checked_out and not state.is_added:
            _fail("动画必须先独占签出")
        if animation.get_package() in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages():
            _fail("动画存在未保存修改")
        digest = _protected_digest(animation, {hand})
        backup = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "ArmTwist",
                                               "WristBackup_" + str(time.time_ns()), package_path[6:] + ".uasset"))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(filename, backup)
        data = tracks[hand]
        if not animation.controller.set_bone_track_keys(hand, data[0], rotations, data[2], False):
            _fail("手骨轨道写入失败")
        if _protected_digest(animation, {hand}) != digest:
            _fail("手骨以外的动画数据意外变化 未保存")
        after = _raw_tracks(animation)[hand]
        error = max(_error(_quat(expected), _quat(actual)) for expected, actual in zip(rotations, after[1]))
        if error > 0.01 or any((a - b).length() > 0.0001 for channel in (0, 2) for a, b in zip(data[channel], after[channel])):
            _fail("手腕修正后回读不一致 未保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            _fail("手腕修正保存失败")
        row["backup"] = backup
        row["protectedDataSha256"] = digest
        row["maximumReadbackErrorDegrees"] = error
        rows.append(row)
        unreal.log("[BBB][WristSwing] 修正并验证 " + animation.get_path_name())
    return _report("WristSwing", {"assetCount": len(rows), "maximumSwingDegrees": maximum_swing_degrees,
                                   "dryRun": dry_run, "assets": rows})


def capture_pie_bone(focus_bone, camera_offset, file_name):
    """/** 围绕本地角色指定骨骼拍摄实际运行姿势 */"""
    if len(camera_offset) != 3 or os.path.basename(file_name) != file_name or not file_name.endswith(".png"):
        _fail("截图参数无效")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    if world is None:
        _fail("运行时截图需要 PIE 世界")
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    if pawn is None:
        _fail("本地角色不存在")
    mesh = pawn.get_editor_property("mesh")
    if mesh.get_bone_index(focus_bone) < 0:
        _fail("关注骨骼不存在")
    target = mesh.get_socket_location(focus_bone)
    location = target + unreal.Vector(*camera_offset)
    rotation = unreal.MathLibrary.find_look_at_rotation(location, target)
    camera = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor(
        world, unreal.SceneCapture2D, unreal.Transform(location=location, rotation=rotation))
    if camera is None:
        _fail("创建运行时截图相机失败")
    try:
        component = camera.capture_component2d
        render_target = unreal.RenderingLibrary.create_render_target2d(
            world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        component.set_editor_property("texture_target", render_target)
        component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        component.set_editor_property("fov_angle", 45.0)
        component.capture_scene()
        directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), "Diagnostics", "ArmTwist", "Captures"))
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, file_name)
        if os.path.exists(path):
            _fail("截图文件已经存在")
        unreal.RenderingLibrary.export_render_target(world, render_target, directory, file_name)
        return json.dumps({"imagePath": path, "focusBone": focus_bone})
    finally:
        camera.destroy_actor()


if __name__ == "__bbb_editor_script__":
    import importlib
    import sys

    if "BBBArmTwistTools" in sys.modules:
        importlib.reload(sys.modules["BBBArmTwistTools"])
