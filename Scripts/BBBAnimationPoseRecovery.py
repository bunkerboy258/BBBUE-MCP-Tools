import json
import math
from pathlib import Path

import unreal
from BBBAssetWritePolicy import require_asset_write


def restore_animation_bone_tracks(source_path, animation_path):
    """/** @param source_path\t已核验完整骨轨源 @param animation_path\t空骨轨目标 @return 原位保存回读 */"""
    source = unreal.load_asset(source_path)
    target = unreal.load_asset(animation_path)
    if not isinstance(source, unreal.AnimSequence) or not isinstance(target, unreal.AnimSequence) or source == target:
        raise RuntimeError('ANIMATION_RECOVERY_ASSET_TYPE')
    if not animation_path.startswith('/Game/_Project/') or source.get_skeleton() != target.get_skeleton():
        raise RuntimeError('ANIMATION_RECOVERY_SCOPE_OR_SKELETON')
    if source.data_model_interface.get_number_of_keys() != target.data_model_interface.get_number_of_keys():
        raise RuntimeError('ANIMATION_RECOVERY_KEY_COUNT')
    source_rate = source.data_model_interface.get_frame_rate()
    target_rate = target.data_model_interface.get_frame_rate()
    if (source_rate.numerator,source_rate.denominator) != (target_rate.numerator,target_rate.denominator):
        raise RuntimeError('ANIMATION_RECOVERY_FRAME_RATE')
    names = source.data_model_interface.get_bone_track_names()
    if not names or target.data_model_interface.get_bone_track_names():
        raise RuntimeError('ANIMATION_RECOVERY_REQUIRES_COMPLETE_SOURCE_EMPTY_TARGET')
    values = {str(n): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source,n)) for n in names}
    require_asset_write([target])
    target.controller.open_bracket('从完整制作输入恢复空骨轨', False)
    try:
        for bone, poses in values.items():
            if not target.controller.add_bone_curve(bone, False) or not target.controller.set_bone_track_keys(
                    bone, [v.translation for v in poses], [v.rotation for v in poses], [v.scale3d for v in poses], False):
                raise RuntimeError('ANIMATION_RECOVERY_TRACK_WRITE: ' + bone)
    finally:
        target.controller.close_bracket(False)
    for bone, poses in values.items():
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(target,bone)
        if len(actual) != len(poses) or any((a.translation-b.translation).length()>0.00001
                or (a.scale3d-b.scale3d).length()>0.00001
                or abs(sum(x*y for x,y in zip(a.rotation.to_tuple(),b.rotation.to_tuple())))<0.999999 for a,b in zip(actual,poses)):
            raise RuntimeError('ANIMATION_RECOVERY_TRACK_READBACK: ' + bone)
    if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
        raise RuntimeError('ANIMATION_RECOVERY_SAVE')
    return {'asset': animation_path, 'source': source_path, 'boneTracks': len(values), 'saved': True}


def rebuild_weapon_aim_additive(neutral_path, target_path, asset_path, reference_path):
    """/** @param neutral_path\t中性源 @param target_path\t瞄准源 @param asset_path\t加法 @param reference_path\t参考 @return 原位重建结果 */"""
    neutral, target, animation, reference = [unreal.load_asset(p) for p in (neutral_path,target_path,asset_path,reference_path)]
    if not all(isinstance(a,unreal.AnimSequence) for a in (neutral,target,animation,reference)):
        raise RuntimeError('AIM_RECOVERY_SEQUENCE_REQUIRED')
    if not neutral.data_model_interface.get_bone_track_names() or not target.data_model_interface.get_bone_track_names():
        raise RuntimeError('AIM_RECOVERY_NONEMPTY_SOURCE_REQUIRED')
    require_asset_write([animation,reference])
    if not unreal.BBBWeaponAimEditorLibrary.build_aim_additive(animation,neutral,target,reference):
        raise RuntimeError('AIM_RECOVERY_NATIVE_BUILD')
    for value in (reference,animation):
        if not unreal.EditorAssetLibrary.save_loaded_asset(value,False):
            raise RuntimeError('AIM_RECOVERY_SAVE')
    return {'asset':asset_path,'reference':reference_path,'boneTracks':len(animation.data_model_interface.get_bone_track_names()),'saved':True}


def restore_saved_grip_pose(weapon_root, recipe_path):
    """
    /**
     * 从已保存的正式握姿解恢复静态骨轨
     * @param weapon_root\t明确型号根
     * @param recipe_path\t型号内正式握姿制作源
     * @return 保存及全骨轨回读结果
     */
    """
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    expected = project / 'Content' / weapon_root.removeprefix('/Game/') / 'Source/Animation'
    if not weapon_root.startswith('/Game/_Project/') or path.parent != expected.resolve():
        raise RuntimeError('GRIP_RECOVERY_SOURCE_SCOPE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBGripAuthoring' or data.get('weapon_root') != weapon_root:
        raise RuntimeError('GRIP_RECOVERY_SOURCE_TYPE')
    solution = data.get('solution', {})
    if not solution.get('passed') or len(solution.get('local_pose', {})) < 60:
        raise RuntimeError('GRIP_RECOVERY_COMPLETE_SOLUTION_REQUIRED')
    asset_path = data['animation']
    if asset_path.rsplit('/', 1)[0] != weapon_root + '/Animation/Sequence':
        raise RuntimeError('GRIP_RECOVERY_OUTPUT_SCOPE')
    animation = unreal.load_asset(asset_path)
    if not isinstance(animation, unreal.AnimSequence):
        raise RuntimeError('GRIP_RECOVERY_ANIMATION_REQUIRED')
    keys = animation.data_model_interface.get_number_of_keys()
    if keys < 2 or keys > 3:
        raise RuntimeError('GRIP_RECOVERY_STATIC_KEY_RANGE_REQUIRED')
    poses = {}
    for bone, values in solution['local_pose'].items():
        if len(values) != 10 or not all(math.isfinite(v) for v in values):
            raise RuntimeError('GRIP_RECOVERY_INVALID_TRANSFORM: ' + bone)
        pose = unreal.Transform(location=unreal.Vector(*values[:3]), scale=unreal.Vector(*values[7:]))
        pose.rotation = unreal.Quat(*values[3:7])
        poses[bone] = pose
    require_asset_write([animation])
    controller = animation.controller
    existing = {str(name) for name in animation.data_model_interface.get_bone_track_names()}
    if existing:
        raise RuntimeError('GRIP_RECOVERY_REQUIRES_EMPTY_OUTPUT')
    controller.open_bracket('从正式握姿制作源恢复空骨轨', False)
    try:
        for bone, pose in poses.items():
            if not controller.add_bone_curve(bone, False):
                raise RuntimeError('GRIP_RECOVERY_ADD_TRACK: ' + bone)
            if not controller.set_bone_track_keys(bone, [pose.translation] * keys,
                    [pose.rotation] * keys, [pose.scale3d] * keys, False):
                raise RuntimeError('GRIP_RECOVERY_WRITE_TRACK: ' + bone)
    finally:
        controller.close_bracket(False)
    for bone, pose in poses.items():
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone)
        if len(actual) != keys or any((value.translation-pose.translation).length() > 0.0001
                or abs(sum(a*b for a,b in zip(value.rotation.to_tuple(),pose.rotation.to_tuple()))) < 0.999999
                for value in actual):
            raise RuntimeError('GRIP_RECOVERY_READBACK: ' + bone)
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('GRIP_RECOVERY_SAVE_FAILED')
    return {'asset': asset_path, 'boneTracks': len(poses), 'keys': keys, 'source': recipe_path,
            'calibrationChanged': False, 'saved': True}
