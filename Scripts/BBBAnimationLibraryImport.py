import contextlib
import json
import math
import os

import unreal

from BBBAssetWritePolicy import require_asset_write


def _sample_rate(row):
    """/** @param row\t单条导入请求 @return 明确的一至二百四十帧整数采样率 */"""
    rate = row.get("sample_rate", 30)
    if type(rate) is not int or not 1 <= rate <= 240:
        raise RuntimeError("动画采样率必须是一至二百四十的整数")
    return rate


@contextlib.contextmanager
def legacy_fbx_import():
    """/** @return 单次操作使用原生 FBX 工厂并恢复原导入开关 */"""
    name = "Interchange.FeatureFlags.Import.FBX"
    previous = unreal.SystemLibrary.get_console_variable_bool_value(name)
    unreal.SystemLibrary.execute_console_command(None, name + " 0")
    try:
        yield
    finally:
        unreal.SystemLibrary.execute_console_command(None, name + (" 1" if previous else " 0"))


def import_animation_library_batch(requests_json):
    """
    /**
     * @param requests_json\t明确源文件 新动画路径 共享骨架 网格及导入旋转
     * @return\t逐项保存结果 不覆盖现有动画
     */
    """
    requests = json.loads(requests_json)
    if not isinstance(requests, list) or not 1 <= len(requests) <= 16:
        raise RuntimeError("每批需要一至十六条明确动画")
    paths = [row["asset_path"] for row in requests]
    if len(set(paths)) != len(paths):
        raise RuntimeError("动画目标路径重复")
    rates = [_sample_rate(row) for row in requests]
    prepared = []
    for row, rate in zip(requests, rates):
        path = row["asset_path"]
        source = row["source_file"]
        if not os.path.isabs(source) or not os.path.isfile(source) or not source.lower().endswith(".fbx"):
            raise RuntimeError("动画源必须为存在的 FBX 绝对路径")
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("目标已存在 禁止覆盖: " + path)
        skeleton = unreal.load_asset(row["skeleton_path"])
        mesh = unreal.load_asset(row["mesh_path"])
        if not isinstance(skeleton, unreal.Skeleton) or not isinstance(mesh, unreal.SkeletalMesh) or mesh.skeleton != skeleton:
            raise RuntimeError("动画源骨架与网格不一致")
        angles = [float(row.get(key, 0)) for key in ("import_pitch", "import_yaw", "import_roll")]
        if not all(math.isfinite(value) for value in angles):
            raise RuntimeError("导入旋转必须为有限数值")
        prepared.append((row, skeleton, mesh, angles, rate))
    require_asset_write([], paths)
    results = []
    with legacy_fbx_import():
        for row, skeleton, mesh, angles, rate in prepared:
            path = row["asset_path"]
            options = unreal.FbxImportUI()
            options.automated_import_should_detect_type = False
            options.mesh_type_to_import = unreal.FBXImportType.FBXIT_ANIMATION
            options.original_import_type = unreal.FBXImportType.FBXIT_ANIMATION
            options.import_mesh = False
            options.import_animations = True
            options.import_materials = False
            options.import_textures = False
            options.skeleton = skeleton
            data = options.anim_sequence_import_data
            data.set_editor_property("use_default_sample_rate", False)
            data.set_editor_property("custom_sample_rate", rate)
            data.set_editor_property("import_custom_attribute", True)
            data.set_editor_property("import_rotation", unreal.Rotator(pitch=angles[0], yaw=angles[1], roll=angles[2]))
            task = unreal.AssetImportTask()
            task.filename = row["source_file"]
            task.destination_path, task.destination_name = path.rsplit("/", 1)
            task.automated = True
            task.replace_existing = False
            task.save = False
            task.factory = unreal.FbxFactory()
            task.options = options
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            objects = list(task.get_objects())
            if len(objects) != 1 or not isinstance(objects[0], unreal.AnimSequence):
                raise RuntimeError("单动作文件没有生成唯一动画: " + row["source_file"])
            animation = objects[0]
            if animation.get_outermost().get_path_name() != path or animation.get_editor_property("skeleton") != skeleton:
                raise RuntimeError("导入动画路径或骨架错误")
            animation.set_preview_skeletal_mesh(mesh)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError("动画保存失败: " + path)
            results.append({"asset": path, "seconds": animation.get_play_length(), "keys": animation.data_model_interface.get_number_of_keys(), "rotation": angles, "sampleRate": rate})
    return json.dumps({"saved": results}, ensure_ascii=False)


def clone_retargeter_for_source_mesh(template_path, source_mesh_path, source_rig_path, retargeter_path):
    """
    /**
     * @param template_path\t已审核重定向器 只读
     * @param source_mesh_path\t新源网格
     * @param source_rig_path\t新源 Rig
     * @param retargeter_path\t新重定向器
     * @return\t保留目标姿势和操作栈的源网格适配结果
     */
    """
    for path in (source_rig_path, retargeter_path):
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("新资产已存在: " + path)
    require_asset_write([], [source_rig_path, retargeter_path])
    template = unreal.load_asset(template_path)
    mesh = unreal.load_asset(source_mesh_path)
    if not isinstance(template, unreal.IKRetargeter) or not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("模板或源网格类型错误")
    source_side = unreal.RetargetSourceOrTarget.SOURCE
    target_side = unreal.RetargetSourceOrTarget.TARGET
    original = unreal.IKRetargeterController.get_controller(template)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder, name = source_rig_path.rsplit("/", 1)
    rig = tools.duplicate_asset(name, folder, original.get_ik_rig(source_side))
    rig_controller = unreal.IKRigController.get_controller(rig)
    if not rig_controller.set_skeletal_mesh(mesh):
        raise RuntimeError("新源网格与模板链不兼容")
    folder, name = retargeter_path.rsplit("/", 1)
    asset = tools.duplicate_asset(name, folder, template)
    controller = unreal.IKRetargeterController.get_controller(asset)
    controller.set_ik_rig(source_side, rig)
    controller.assign_ik_rig_to_all_ops(source_side, rig)
    controller.set_preview_mesh(source_side, mesh)
    controller.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
    controller.auto_align_all_bones(source_side, unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN)
    target = unreal.IKRigController.get_controller(controller.get_ik_rig(target_side))
    mappings = {str(chain.chain_name): str(controller.get_source_chain(chain.chain_name)) for chain in target.get_retarget_chains()}
    if any(name != source for name, source in mappings.items()):
        raise RuntimeError("新重定向器同名映射不完整")
    for item in (rig, asset):
        if not unreal.EditorAssetLibrary.save_loaded_asset(item, False):
            raise RuntimeError("新源适配资产保存失败")
    return json.dumps({"sourceRig": source_rig_path, "retargeter": retargeter_path, "mappings": mappings}, ensure_ascii=False)


def audit_animation_library_batch(pairs_json, mesh_path):
    """
    /**
     * @param pairs_json\t源与目标动画的明确对应关系
     * @param mesh_path\t目标预览网格
     * @return\t全帧有限值 IK 跟随 曲线 通知和时长核验
     */
    """
    pairs = json.loads(pairs_json)
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 16:
        raise RuntimeError("每批需要一至十六对动画")
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("目标网格无效")
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    options.incorporate_root_motion_into_pose = True
    options.optional_skeletal_mesh = mesh
    checks = (("root", "ik_foot_root"), ("root", "ik_hand_root"), ("hand_r", "ik_hand_gun"), ("foot_l", "ik_foot_l"), ("foot_r", "ik_foot_r"), ("hand_l", "ik_hand_l"), ("hand_r", "ik_hand_r"))
    reports = []
    for row in pairs:
        source = unreal.load_asset(row["source"])
        target = unreal.load_asset(row["target"])
        if not isinstance(source, unreal.AnimSequence) or not isinstance(target, unreal.AnimSequence) or target.get_editor_property("skeleton") != mesh.skeleton:
            raise RuntimeError("动画对应或目标骨架无效")
        if abs(source.get_play_length() - target.get_play_length()) > 0.001:
            raise RuntimeError("动画时长改变: " + row["target"])
        source_curves = sorted(str(name) for name in unreal.AnimationLibrary.get_animation_curve_names(source, unreal.RawCurveTrackTypes.RCT_FLOAT))
        target_curves = sorted(str(name) for name in unreal.AnimationLibrary.get_animation_curve_names(target, unreal.RawCurveTrackTypes.RCT_FLOAT))
        if source_curves != target_curves:
            raise RuntimeError("浮点曲线名称改变: " + row["target"])
        curve_error = 0.0
        for name in source_curves:
            source_times, source_values = unreal.AnimationLibrary.get_float_keys(source, name)
            target_times, target_values = unreal.AnimationLibrary.get_float_keys(target, name)
            if len(source_times) != len(target_times):
                raise RuntimeError("曲线键数量改变: " + name)
            for left, right in zip(source_times, target_times):
                if abs(left - right) > 0.001:
                    raise RuntimeError("曲线键时间改变: " + name)
            curve_error = max([curve_error] + [abs(left - right) for left, right in zip(source_values, target_values)])
        source_notifies = len(unreal.AnimationLibrary.get_animation_notify_events(source))
        target_notifies = len(unreal.AnimationLibrary.get_animation_notify_events(target))
        if source_notifies != target_notifies or curve_error > 0.001:
            raise RuntimeError("曲线值或通知数量改变")
        keys = target.data_model_interface.get_number_of_keys()
        tracks = {str(name).casefold() for name in target.data_model_interface.get_bone_track_names()}
        if any(helper not in tracks for parent, helper in checks):
            raise RuntimeError("目标辅助 IK 骨轨道缺失: " + row["target"])
        max_position = 0.0
        max_rotation = 0.0
        for frame in range(keys):
            pose = target.get_anim_pose_at_frame(frame, options)
            for parent, helper in checks:
                left = pose.get_bone_pose(parent, unreal.AnimPoseSpaces.WORLD)
                right = pose.get_bone_pose(helper, unreal.AnimPoseSpaces.WORLD)
                values = [right.translation.x, right.translation.y, right.translation.z, right.rotation.x, right.rotation.y, right.rotation.z, right.rotation.w]
                if not all(math.isfinite(value) for value in values):
                    raise RuntimeError("目标包含非有限骨骼变换")
                max_position = max(max_position, (left.translation - right.translation).length())
                dot = abs(left.rotation.x * right.rotation.x + left.rotation.y * right.rotation.y + left.rotation.z * right.rotation.z + left.rotation.w * right.rotation.w)
                max_rotation = max(max_rotation, math.degrees(2 * math.acos(min(1.0, dot))))
        if max_position > 0.02 or max_rotation > 0.05:
            raise RuntimeError("目标辅助 IK 骨没有正确跟随: " + row["target"])
        reports.append({"source": row["source"], "target": row["target"], "frames": keys, "curves": len(source_curves), "notifies": source_notifies, "ikPositionCm": max_position, "ikRotationDegrees": max_rotation})
    return json.dumps({"verified": reports}, ensure_ascii=False)
