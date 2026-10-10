import json

import unreal


def restore_from_source(source_path, destination_path):
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("PIE 期间禁止恢复动画")
    source = unreal.EditorAssetLibrary.load_asset(source_path)
    if not isinstance(source, unreal.AnimSequence):
        raise RuntimeError("源必须是动画序列")

    # 目标存在时先删后复制 不存在时直接复制 使骨骼轨道 曲线 通知与全部动画设置与源一致
    destination = unreal.EditorAssetLibrary.load_asset(destination_path)
    if destination is not None:
        if not isinstance(destination, unreal.AnimSequence):
            raise RuntimeError("目标必须是动画序列")
        if source.get_editor_property("skeleton") != destination.get_editor_property("skeleton"):
            raise RuntimeError("源与目标骨架不一致")
        from BBBAssetWritePolicy import require_write_access
        require_write_access(destination)
        if not unreal.EditorAssetLibrary.delete_asset(destination_path):
            raise RuntimeError("删除旧目标动画失败 " + destination_path)
    restored = unreal.EditorAssetLibrary.duplicate_asset(source_path, destination_path)
    if restored is None:
        raise RuntimeError("从源复制动画失败 " + source_path)
    if not unreal.EditorAssetLibrary.save_loaded_asset(restored, False):
        raise RuntimeError("恢复后的动画保存失败")

    restored = unreal.EditorAssetLibrary.load_asset(destination_path)
    report = {"source": source_path, "destination": destination_path,
        "skeleton": restored.get_editor_property("skeleton").get_path_name(),
        "length": restored.get_play_length(),
        "lengthMatches": abs(restored.get_play_length() - source.get_play_length()) < 0.0001}
    if not report["lengthMatches"]:
        raise RuntimeError("恢复后的动画时长与源不一致")
    return json.dumps(report, ensure_ascii=False)


def replace_montage_references(montage_path, replacements_json):
    from BBBAssetWritePolicy import require_write_access

    montage = unreal.load_asset(montage_path)
    require_write_access(montage)
    replacements = {}
    for key, value in json.loads(replacements_json).items():
        asset = unreal.load_asset(value)
        if asset is None:
            raise RuntimeError("替换动画不存在 " + value)
        replacements[key] = asset
    slots = list(montage.get_editor_property("slot_anim_tracks"))
    count = 0
    for slot in slots:
        slot_name = str(slot.get_editor_property("slot_name"))
        track = slot.get_editor_property("anim_track")
        segments = list(track.get_editor_property("anim_segments"))
        for segment in segments:
            target = replacements.get("slot:" + slot_name)
            source = segment.get_editor_property("anim_reference")
            if target is None and source is not None:
                path = source.get_path_name().split(".")[0]
                target = replacements.get(path)
            if target is None:
                continue
            if source is not None and abs(source.get_play_length() - target.get_play_length()) > 0.0001:
                raise RuntimeError("替换动画时长不一致")
            segment.set_editor_property("anim_reference", target)
            count += 1
        track.set_editor_property("anim_segments", segments)
        slot.set_editor_property("anim_track", track)
    montage.set_editor_property("slot_anim_tracks", slots)
    if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
        raise RuntimeError("蒙太奇保存失败")
    return json.dumps({"replaced": count})


def hold_tracks(animation_path, bone_names, source_frame, identity_transform):
    from BBBAssetWritePolicy import require_write_access

    animation = unreal.load_asset(animation_path)
    require_write_access(animation)
    count = animation.data_model_interface.get_number_of_keys()
    transform_curves = {str(name).casefold(): name for name in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)}
    float_curves = {str(name).casefold() for name in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)}
    if any(str(name).casefold() in transform_curves and str(name).casefold() in float_curves for name in bone_names):
        raise RuntimeError("目标骨骼与浮点曲线重名 禁止模糊删除")
    controller = animation.controller
    controller.open_bracket("固定指定骨骼轨道", False)
    try:
        for name in bone_names:
            values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
            value = unreal.Transform() if identity_transform else values[min(source_frame, len(values) - 1)]
            # 固定骨骼时同时清除该骨骼的旧变换修正 其它曲线和通知保持不变
            curve = transform_curves.get(str(name).casefold())
            if curve is not None:
                unreal.AnimationLibrary.remove_curve(animation, curve, False)
                remaining = {str(item).casefold() for item in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)}
                if str(name).casefold() in remaining:
                    raise RuntimeError("固定骨骼的变换修正删除失败 " + str(name))
            if not controller.set_bone_track_keys(name, [value.translation] * count, [value.rotation] * count, [value.scale3d] * count, False):
                raise RuntimeError("固定骨骼轨道失败 " + name)
    finally:
        controller.close_bracket(False)
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError("动画保存失败")
    return json.dumps({"asset": animation_path, "bones": list(bone_names)})
