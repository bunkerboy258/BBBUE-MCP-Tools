import json
import math

import unreal
from BBBAssetWritePolicy import require_asset_write


def bake_pose_transition(source_sequence_path: str, target_sequence_path: str, asset_path: str,
                        ground_bone_names: list[str], seconds: float = 1.7) -> str:
    """
    /**
     * 从同骨架两端姿态烘焙完整过渡 保持肢体长度并约束接触点高度
     * @param source_sequence_path	起始姿态序列 取首帧
     * @param target_sequence_path	结束姿态序列 取末帧
     * @param asset_path	原位新建或重建的自有动画序列
     * @param ground_bone_names	不得低于地面的骨骼名称
     * @param seconds	过渡秒数
     * @return 全骨骼烘焙与地面高度回读结果
     */
    """
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间禁止烘焙姿态过渡')
    source = unreal.load_asset(source_sequence_path)
    target = unreal.load_asset(target_sequence_path)
    if not asset_path.startswith('/Game/_Project/') or asset_path in (source_sequence_path, target_sequence_path):
        raise RuntimeError('过渡目标必须为独立自有资产')
    if not isinstance(source, unreal.AnimSequence) or not isinstance(target, unreal.AnimSequence) or source.get_skeleton() != target.get_skeleton():
        raise RuntimeError('两端姿态必须为同骨架普通动画')
    if not math.isfinite(seconds) or not 0.2 <= seconds <= 4 or not 1 <= len(ground_bone_names) <= 12:
        raise RuntimeError('过渡时长或接触骨骼数量无效')
    options = unreal.AnimPoseEvaluationOptions()
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    options.should_retarget = False
    start = source.get_anim_pose_at_frame(0, options)
    end = target.get_anim_pose_at_time(target.get_play_length(), options)
    names = list(source.data_model_interface.get_bone_track_names())
    end_names = {str(name) for name in end.get_bone_names()}
    if not set(ground_bone_names) <= {str(name) for name in names}:
        raise RuntimeError('起始姿态缺少指定接触骨骼')
    first = {str(name): start.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL) for name in names}
    last = {str(name): end.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL) if str(name) in end_names else first[str(name)] for name in names}
    count = round(seconds * 60)
    poses, lifts = [], []
    for index in range(count + 1):
        alpha = index / count
        alpha = alpha * alpha * (3 - 2 * alpha)
        pose = start.copy()
        for name in names:
            a, b = first[str(name)], last[str(name)]
            qa, qb = a.rotation, b.rotation
            left, right = [qa.x, qa.y, qa.z, qa.w], [qb.x, qb.y, qb.z, qb.w]
            dot = sum(x * y for x, y in zip(left, right))
            if dot < 0:
                right, dot = [-value for value in right], -dot
            weight_a, weight_b = 1 - alpha, alpha
            if dot < 0.9995:
                angle = math.acos(min(1, dot))
                weight_a, weight_b = math.sin((1 - alpha) * angle) / math.sin(angle), math.sin(alpha * angle) / math.sin(angle)
            q = [weight_a * x + weight_b * y for x, y in zip(left, right)]
            norm = math.sqrt(sum(value * value for value in q))
            location = a.translation
            if str(name) == 'pelvis':
                location = a.translation * (1 - alpha) + b.translation * alpha
            pose.set_bone_pose(unreal.Transform(location=location, rotation=unreal.Quat(*[value / norm for value in q]).rotator(), scale=a.scale3d), name, unreal.AnimPoseSpaces.LOCAL)
        poses.append(pose)
        lifts.append(max(0.0, 0.5 - min(pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation.z for name in ground_bone_names)))
    for iteration in range(5):
        previous = lifts[:]
        for index in range(1, count):
            lifts[index] = max(previous[index], (previous[index - 1] + 2 * previous[index] + previous[index + 1]) / 4)
    existing = unreal.load_asset(asset_path) if unreal.EditorAssetLibrary.does_asset_exist(asset_path) else None
    require_asset_write([existing] if existing else [], [] if existing else [asset_path])
    asset = existing or unreal.EditorAssetLibrary.duplicate_asset(source_sequence_path, asset_path)
    if not isinstance(asset, unreal.AnimSequence) or asset.get_skeleton() != source.get_skeleton():
        raise RuntimeError('过渡目标类型或骨架无效')
    controller = asset.controller
    controller.open_bracket('烘焙接触高度连续的姿态过渡', False)
    try:
        controller.remove_all_bone_tracks(False)
        controller.set_frame_rate(unreal.FrameRate(60, 1), False)
        controller.set_number_of_frames(unreal.FrameNumber(count), False)
        for pose, lift in zip(poses, lifts):
            pelvis = pose.get_bone_pose('pelvis', unreal.AnimPoseSpaces.LOCAL)
            pelvis.translation += unreal.Vector(0, 0, lift)
            pose.set_bone_pose(pelvis, 'pelvis', unreal.AnimPoseSpaces.LOCAL)
        for name in names:
            values = [pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL) for pose in poses]
            if not controller.add_bone_track(name, False) or not controller.set_bone_track_keys(name, [value.translation for value in values], [value.rotation for value in values], [value.scale3d for value in values], False):
                raise RuntimeError('过渡骨骼轨道写入失败: ' + str(name))
    finally:
        controller.close_bracket(False)
    asset.set_editor_property('enable_root_motion', False)
    minimum = min(asset.get_anim_pose_at_frame(index, options).get_bone_pose(name, unreal.AnimPoseSpaces.WORLD).translation.z for index in range(count + 1) for name in ground_bone_names)
    if minimum < 0.49 or not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError('过渡接触高度或保存校验失败')
    return json.dumps({'asset': asset_path, 'bones': len(names), 'keys': count + 1, 'seconds': asset.get_play_length(),
                       'minimumContactBoneHeightCm': minimum, 'maximumSupportCorrectionCm': max(lifts), 'saved': True})
