import json
import math
import gc
import os
import uuid
import json

import unreal


def _animation(path):
    asset = unreal.load_asset(path)
    if not isinstance(asset, unreal.AnimSequence):
        raise RuntimeError("动画序列不存在或类型错误: " + path)
    return asset


def _rate(animation):
    rate = animation.data_model_interface.get_frame_rate()
    return rate.numerator, rate.denominator


def _root_track(animation):
    names = [str(name) for name in animation.data_model_interface.get_bone_track_names()]
    root = next((name for name in names if name.casefold() == "root"), None)
    if root is None:
        raise RuntimeError("动画缺少 Root 轨道: " + animation.get_path_name())
    keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, root)
    if len(keys) != animation.data_model_interface.get_number_of_keys():
        raise RuntimeError("Root 轨道帧数错误: " + animation.get_path_name())
    return root, keys


def _metadata(animation):
    import BBBAnimationTrajectoryTools

    settings = (
        "force_root_lock",
        "root_motion_root_lock",
        "rate_scale",
        "interpolation",
        "compression_error_threshold_scale",
        "curve_compression_settings",
        "bone_compression_settings",
    )
    return {
        "animation": BBBAnimationTrajectoryTools._track_metadata(animation),
        "settings": {name: str(animation.get_editor_property(name)) for name in settings},
    }


def _root_delta(before, after):
    if len(before) != len(after):
        raise RuntimeError("Root 轨道关键帧数量不同")
    position = 0.0
    rotation = 0.0
    for left, right in zip(before, after):
        position = max(position, (left.translation - right.translation).length())
        dot = abs(left.rotation.x * right.rotation.x + left.rotation.y * right.rotation.y
                  + left.rotation.z * right.rotation.z + left.rotation.w * right.rotation.w)
        rotation = max(rotation, math.degrees(2.0 * math.acos(min(1.0, dot))))
    return position, rotation


def _prepare_tracks(baked, target):
    baked_model = baked.data_model_interface
    target_model = target.data_model_interface
    baked_names = [str(name) for name in baked_model.get_bone_track_names()]
    target_names = [str(name) for name in target_model.get_bone_track_names()]
    if set(baked_names) != set(target_names):
        raise RuntimeError("烘焙与目标的骨骼轨道集合不同: " + target.get_path_name())
    if len(baked_names) > 128:
        raise RuntimeError("骨骼轨道超过单项安全上限: " + target.get_path_name())
    if baked_model.get_number_of_keys() != target_model.get_number_of_keys() or _rate(baked) != _rate(target):
        raise RuntimeError("烘焙与目标的帧数或帧率不同: " + target.get_path_name())
    if abs(baked.get_play_length() - target.get_play_length()) > 0.00001:
        raise RuntimeError("烘焙与目标的时长不同: " + target.get_path_name())
    if baked.get_editor_property("skeleton") != target.get_editor_property("skeleton"):
        raise RuntimeError("烘焙与目标的骨架不同: " + target.get_path_name())
    if baked.get_editor_property("additive_anim_type") != target.get_editor_property("additive_anim_type"):
        raise RuntimeError("烘焙与目标的加法模式不同: " + target.get_path_name())
    _, baked_root = _root_track(baked)
    _, target_root = _root_track(target)
    root_position, root_rotation = _root_delta(baked_root, target_root)
    prepared = []
    count = target_model.get_number_of_keys()
    for name in baked_names:
        keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(baked, name)
        if len(keys) != count:
            raise RuntimeError("烘焙骨骼帧数不同: " + name)
        positions = []
        rotations = []
        scales = []
        for key in keys:
            position = key.translation
            rotation = key.rotation
            scale = key.scale3d
            values = (position.x, position.y, position.z, rotation.x, rotation.y, rotation.z,
                      rotation.w, scale.x, scale.y, scale.z)
            if any(not math.isfinite(value) for value in values):
                raise RuntimeError("烘焙骨骼含非有限数值: " + name)
            if abs(sum(value * value for value in values[3:7]) - 1.0) > 0.001:
                raise RuntimeError("烘焙骨骼四元数无效: " + name)
            if any(value <= 0.0 for value in values[7:]):
                raise RuntimeError("烘焙骨骼缩放无效: " + name)
            positions.append(position)
            rotations.append(rotation)
            scales.append(scale)
        prepared.append((name, positions, rotations, scales))
    return prepared, root_position, root_rotation


def _replace_tracks(target, prepared):
    before = _metadata(target)
    controller = target.controller
    controller.open_bracket("按已审核重定向器替换骨骼轨道", False)
    try:
        for name, positions, rotations, scales in prepared:
            if not controller.set_bone_track_keys(name, positions, rotations, scales, False):
                raise RuntimeError("骨骼轨道写入失败: " + name)
    finally:
        controller.close_bracket(False)
    for name, positions, rotations, scales in prepared:
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(target, name)
        if len(actual) != len(positions):
            raise RuntimeError("骨骼轨道回读帧数不同: " + name)
        for index, value in enumerate(actual):
            if (value.translation - positions[index]).length() > 0.001:
                raise RuntimeError("骨骼轨道回读位置不同: " + name)
            if (value.scale3d - scales[index]).length() > 0.001:
                raise RuntimeError("骨骼轨道回读缩放不同: " + name)
            left = value.rotation
            right = rotations[index]
            dot = abs(left.x * right.x + left.y * right.y + left.z * right.z + left.w * right.w)
            if 1.0 - min(1.0, dot) > 0.0001:
                raise RuntimeError("骨骼轨道回读旋转不同: " + name)
    if _metadata(target) != before:
        raise RuntimeError("替换时旧目标元数据改变: " + target.get_path_name())
    if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
        raise RuntimeError("目标动画保存失败: " + target.get_path_name())
    if _metadata(target) != before:
        raise RuntimeError("保存后旧目标元数据改变: " + target.get_path_name())
    return len(prepared)


def run(source_paths, retargeter_path, target_folder, dry_run=False):
    from BBBAssetWritePolicy import require_asset_write

    if not source_paths or len(source_paths) > 32 or len(set(source_paths)) != len(source_paths):
        raise RuntimeError("每批必须提供一至三十二条互不重复的源动画")
    if not target_folder.startswith("/Game/_Project/") or target_folder.endswith("/"):
        raise RuntimeError("目标必须是明确的项目目录")
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止重定向覆盖动画")
    retargeter = unreal.load_asset(retargeter_path)
    if not isinstance(retargeter, unreal.IKRetargeter):
        raise RuntimeError("IK 重定向器无效")
    rig = unreal.IKRetargeterController.get_controller(retargeter)
    source_mesh = rig.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
    target_mesh = rig.get_preview_mesh(unreal.RetargetSourceOrTarget.TARGET)
    if source_mesh is None or target_mesh is None:
        raise RuntimeError("重定向器缺少源或目标网格")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    sources = []
    targets = []
    data = []
    for source_path in source_paths:
        source = _animation(source_path)
        target_path = target_folder + "/" + source.get_name()
        target = _animation(target_path)
        if source.get_editor_property("skeleton") != source_mesh.get_editor_property("skeleton"):
            raise RuntimeError("源动画骨架与重定向器不一致: " + source_path)
        if target.get_editor_property("skeleton") != target_mesh.get_editor_property("skeleton"):
            raise RuntimeError("目标动画骨架与重定向器不一致: " + target_path)
        if source.data_model_interface.get_number_of_keys() != target.data_model_interface.get_number_of_keys():
            raise RuntimeError("源与目标关键帧数不同: " + target_path)
        if _rate(source) != _rate(target) or abs(source.get_play_length() - target.get_play_length()) > 0.00001:
            raise RuntimeError("源与目标帧率或时长不同: " + target_path)
        if source.get_editor_property("additive_anim_type") != target.get_editor_property("additive_anim_type"):
            raise RuntimeError("源与目标加法模式不同: " + target_path)
        _, source_root = _root_track(source)
        _, target_root = _root_track(target)
        if len(source_root) != len(target_root):
            raise RuntimeError("源与目标 Root 帧数不同: " + target_path)
        asset_data = registry.get_asset_by_object_path(unreal.Name(source.get_path_name()))
        if not asset_data.is_valid():
            raise RuntimeError("源动画注册信息无效: " + source_path)
        sources.append(asset_data)
        targets.append(target)
        data.append({"source": source_path, "target": target_path, "keys": len(target_root)})
    if dry_run:
        return json.dumps({"dryRun": True, "count": len(data), "items": data}, ensure_ascii=False)
    require_asset_write(targets, [])
    temporary_root = "/Game/_Project/Characters/BBBC_UA/Animation/OtherAnimation/GameAnimationSample/RetargetBatchWorking"
    temporary_folder = temporary_root + "/" + uuid.uuid4().hex
    temporary_directory = os.path.join(unreal.Paths.project_content_dir(),
        "_Project", "Characters", "BBBC_UA", "Animation", "OtherAnimation", "GameAnimationSample",
        "RetargetBatchWorking", temporary_folder.rsplit("/", 1)[-1])
    temporary_paths = [temporary_folder + "/" + target.get_name() for target in targets]
    if any(unreal.EditorAssetLibrary.does_asset_exist(path) for path in temporary_paths):
        raise RuntimeError("本批临时烘焙路径已占用 拒绝覆盖")
    inputs = unreal.IKRetargetBatchOperationInputs()
    inputs.assets_to_retarget = sources
    inputs.source_mesh = source_mesh
    inputs.target_mesh = target_mesh
    inputs.ik_retarget_asset = retargeter
    inputs.target_path = temporary_folder
    inputs.include_referenced_assets = False
    inputs.overwrite_existing_files = False
    inputs.retain_additive_flags = True
    reports = []
    failure = ""
    baked = None
    prepared = None
    try:
        created = [str(result.package_name) for result in unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)]
        if sorted(created) != sorted(temporary_paths):
            raise RuntimeError("重定向输出数量或路径与本批输入不同")
        for target, temporary_path in zip(targets, temporary_paths):
            baked = _animation(temporary_path)
            prepared, root_position, root_rotation = _prepare_tracks(baked, target)
            changed = _replace_tracks(target, prepared)
            reports.append({"asset": target.get_path_name().split(".")[0], "tracks": changed,
                            "rootPositionCm": root_position, "rootRotationDegrees": root_rotation})
    except Exception as error:
        failure = str(error)
    finally:
        baked = None
        prepared = None
        gc.collect()
        failed_cleanup = []
        for path in temporary_paths:
            if unreal.EditorAssetLibrary.does_asset_exist(path) and not unreal.EditorAssetLibrary.delete_asset(path):
                failed_cleanup.append(path)
        if not failed_cleanup and os.path.isdir(temporary_directory):
            os.rmdir(temporary_directory)
        if failed_cleanup:
            raise RuntimeError("批次故障=" + failure + " 本批临时动画清理失败: " + str(failed_cleanup))
    if failure:
        raise RuntimeError("批次已保存 " + str(len(reports)) + " 条: " + failure)
    return json.dumps({"saved": len(reports), "items": reports, "temporaryCleared": True}, ensure_ascii=False)
