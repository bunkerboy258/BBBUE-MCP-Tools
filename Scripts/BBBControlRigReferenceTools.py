import json
import math

import unreal
from BBBAssetWritePolicy import require_write_access
from BBBControlRigAuthoringToolset import _asset, _key


def restore_sequence_fk_reference(sequence_path: str, animation_path: str, mesh_path: str,
                                  controls_json: str, frames: list[int]) -> str:
    """从参考动画第0秒恢复指定FK骨骼的局部旋转 保留其它控制器和位置缩放"""
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("PIE期间禁止修改握姿序列")
    sequence = _asset(sequence_path, unreal.LevelSequence)
    animation = _asset(animation_path, unreal.AnimSequence)
    mesh = _asset(mesh_path, unreal.SkeletalMesh)
    controls = json.loads(controls_json)
    frames = list(frames)
    if not controls or len(controls) > 32 or not frames or len(frames) > 20 or len(set(frames)) != len(frames):
        raise RuntimeError("必须明确控制器到骨骼映射和不重复帧")
    if animation.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise RuntimeError("参考动画与网格骨架不一致")
    require_write_access(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    proxies = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
    if len(proxies) != 1:
        raise RuntimeError("序列必须只有一个制作Rig")
    rig = proxies[0].control_rig
    hierarchy = rig.get_hierarchy()
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = True
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, 0.0, options)
    reference = {}
    probe = unreal.new_object(unreal.SkeletalMeshComponent)
    probe.set_skeletal_mesh_asset(mesh)
    for name, bone in controls.items():
        key = _key(name, "CONTROL")
        parents = hierarchy.get_parents(key)
        if not hierarchy.contains(key) or hierarchy.get_control_settings(key).control_type != unreal.RigControlType.EULER_TRANSFORM:
            raise RuntimeError("需要实际欧拉FK控制器: " + name)
        if len(parents) != 1 or (str(parents[0].name).casefold() != str(probe.get_parent_bone(bone)).casefold() or parents[0].type != unreal.RigElementType.BONE):
            raise RuntimeError("FK_PARENT_MISMATCH: " + name + " actual=" + str([(str(p.name), str(p.type)) for p in parents]) + " expected=" + str(probe.get_parent_bone(bone)))
        reference[bone] = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
    other = [str(key.name) for key in hierarchy.get_controls()
             if str(key.name) not in controls and hierarchy.get_control_settings(key).control_type == unreal.RigControlType.EULER_TRANSFORM]
    before = {}
    for frame in frames:
        if frame < sequence.get_playback_start() or frame >= sequence.get_playback_end():
            raise RuntimeError("帧超出序列范围")
        for name in other:
            value = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame))
            before[(frame, name)] = (tuple(value.location.to_tuple()), (value.rotation.pitch, value.rotation.yaw, value.rotation.roll), tuple(value.scale.to_tuple()))
    previous_frame = unreal.LevelSequenceEditorBlueprintLibrary.get_current_time()
    maximum_error = 0.0
    with unreal.ScopedEditorTransaction("恢复指定FK骨骼的参考旋转"):
        sequence.modify()
        for frame in frames:
            unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(frame)
            unreal.LevelSequenceEditorBlueprintLibrary.force_update()
            for name, bone in controls.items():
                key = _key(name, "CONTROL")
                parent = hierarchy.get_parents(key)[0]
                offset = hierarchy.get_global_control_offset_transform(key, False).make_relative(hierarchy.get_global_transform(parent))
                rotation = (offset.rotation.inversed() * reference[bone].rotation).normalized()
                value = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame))
                value.rotation = rotation.rotator()
                unreal.ControlRigSequencerLibrary.set_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame), value, set_key=True)
                keyed = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame))
                hierarchy.set_control_value(key, unreal.RigHierarchy.make_control_value_from_euler_transform(keyed))
                if not rig.execute_event("Forwards Solve"):
                    raise RuntimeError("正向求解失败")
            unreal.LevelSequenceEditorBlueprintLibrary.force_update()
            for bone in reference:
                qa = hierarchy.get_local_transform(_key(bone)).rotation.to_tuple()
                qb = reference[bone].rotation.to_tuple()
                cosine = min(1.0, abs(sum(a*b for a,b in zip(qa,qb))) / (sum(a*a for a in qa)*sum(b*b for b in qb))**0.5)
                maximum_error = max(maximum_error, math.degrees(2.0 * math.acos(cosine)))
        for (frame, name), expected in before.items():
            value = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(value=frame))
            actual = (tuple(value.location.to_tuple()), (value.rotation.pitch, value.rotation.yaw, value.rotation.roll), tuple(value.scale.to_tuple()))
            if actual != expected:
                raise RuntimeError("非目标控制器发生变化: " + name)
        if maximum_error > 0.001:
            raise RuntimeError("参考旋转回读失败: " + str(maximum_error))
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(previous_frame)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError("序列保存失败")
    return json.dumps({"sequence": sequence_path, "reference": animation_path, "controls": controls,
                       "frames": frames, "maximumRotationErrorDegrees": maximum_error,
                       "otherControlsUnchanged": True, "saved": True}, ensure_ascii=False)


def set_sequence_control_local_keys(sequence_path, keys_json):
    """写入明确控制器局部增量并回读 不重建轨道或修改控制器偏移"""
    from BBBControlRigAuthoringToolset import _transform, _read_transform
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("PIE期间禁止修改制作序列")
    sequence = _asset(sequence_path, unreal.LevelSequence)
    requests = json.loads(keys_json)
    if not requests or len(requests) > 600:
        raise RuntimeError("必须明确一至六百个局部关键帧")
    require_write_access(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    proxies = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
    if len(proxies) != 1:
        raise RuntimeError("序列必须只有一个制作Rig")
    rig = proxies[0].control_rig
    hierarchy = rig.get_hierarchy()
    seen = set()
    for row in requests:
        pair = (row['frame'], row['control'])
        if pair in seen or not sequence.get_playback_start() <= row['frame'] < sequence.get_playback_end():
            raise RuntimeError("关键帧重复或超出范围")
        seen.add(pair)
        key = _key(row['control'], 'CONTROL')
        if not hierarchy.contains(key) or hierarchy.get_control_settings(key).control_type != unreal.RigControlType.EULER_TRANSFORM:
            raise RuntimeError("需要已有欧拉变换控制器")
        if set(row['value']) != {'position', 'rotation', 'scale'}:
            raise RuntimeError("必须提供完整局部增量")
        _transform(row['value'])
    actuals = []
    with unreal.ScopedEditorTransaction("写入指定控制器局部增量"):
        sequence.modify()
        for row in requests:
            transform = _transform(row['value'])
            value = unreal.EulerTransform(location=transform.translation, rotation=transform.rotation.rotator(), scale=transform.scale3d)
            frame = unreal.FrameNumber(value=row['frame'])
            unreal.ControlRigSequencerLibrary.set_local_control_rig_euler_transform(sequence, rig, row['control'], frame, value, set_key=True)
            actual = unreal.ControlRigSequencerLibrary.get_local_control_rig_euler_transform(sequence, rig, row['control'], frame)
            read = unreal.Transform(location=actual.location, rotation=actual.rotation, scale=actual.scale)
            qa,qb = read.rotation.to_tuple(),transform.rotation.to_tuple()
            cosine = abs(sum(a*b for a,b in zip(qa,qb)))/(sum(a*a for a in qa)*sum(b*b for b in qb))**0.5
            if (read.translation-transform.translation).length() > 0.00001 or (read.scale3d-transform.scale3d).length() > 0.00001 or cosine < 0.999999999:
                raise RuntimeError("控制器局部关键帧回读失败")
            actuals.append({'frame':row['frame'],'control':row['control'],'value':_read_transform(read)})
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError("序列保存失败")
    return json.dumps({'sequence':sequence_path,'keys':actuals,'readback':True,'saved':True},ensure_ascii=False)
