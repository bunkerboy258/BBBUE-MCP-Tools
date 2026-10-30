import math

import unreal
from BBBAssetWritePolicy import require_asset_write


def _tracks(animation):
    """/** @param animation	明确序列 @return 非空完整原始轨道 */"""
    values = {str(name): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
              for name in animation.data_model_interface.get_bone_track_names()}
    if not values or any(len(rows) != animation.data_model_interface.get_number_of_keys() for rows in values.values()):
        raise RuntimeError('SCALED_ADDITIVE_INCOMPLETE_TRACKS')
    if any(abs(sum(v * v for v in pose.rotation.to_tuple()) - 1) > 0.001
           or any(abs(v) < 1e-6 for v in pose.scale3d.to_tuple()) for rows in values.values() for pose in rows):
        raise RuntimeError('SCALED_ADDITIVE_INVALID_TRANSFORM')
    return values


def _power(value, amplitude):
    """/** @param value	旋转差 @param amplitude	幅度 @return 最短弧角度倍增 */"""
    value = value.normalized()
    if value.w < 0:
        value = unreal.Quat(-value.x, -value.y, -value.z, -value.w)
    half = math.acos(min(1.0, max(-1.0, value.w)))
    sine = math.sin(half)
    if abs(sine) < 1e-8:
        return unreal.Quat(0, 0, 0, 1)
    factor = math.sin(half * amplitude) / sine
    return unreal.Quat(value.x * factor, value.y * factor, value.z * factor, math.cos(half * amplitude)).normalized()


def _components(local, parents):
    """/** @param local	局部变换 @param parents	父骨映射 @return 组件空间旋转 */"""
    result = {}
    def resolve(name):
        if name in result:
            return result[name]
        parent = parents[name]
        value = local[name].rotation
        if parent:
            value = resolve(parent) * value
        result[name] = value.normalized()
        return result[name]
    for name in local:
        resolve(name)
    return result


def rebuild(source, animation_path, base_path, source_reference_frame, amplitude, mesh_path, rotation_space):
    """
    /**
     * 提取明确源基准的加法并写入当前角色基准
     * @param source	有完整骨轨的原始或重定向射击输入
     * @param animation_path	已有自有输出
     * @param base_path	当前角色加法基准
     * @param source_reference_frame	源原始基准帧或负一读取其有效参考序列
     * @param amplitude	有限正幅度
     * @param mesh_path	同骨架层级来源
     * @param rotation_space	按来源或明确的网格及局部空间提取
     * @return 原位保存及逐帧幅度回读
     */
    """
    target = unreal.load_asset(animation_path)
    base = unreal.load_asset(base_path)
    if not isinstance(target, unreal.AnimSequence) or not isinstance(base, unreal.AnimSequence):
        raise RuntimeError('SCALED_ADDITIVE_SEQUENCE_REQUIRED')
    if source == target or target == base or not animation_path.startswith('/Game/_Project/'):
        raise RuntimeError('SCALED_ADDITIVE_OUTPUT_SCOPE')
    if not math.isfinite(amplitude) or not 0 < amplitude <= 5:
        raise RuntimeError('SCALED_ADDITIVE_AMPLITUDE')
    if rotation_space not in ('source', 'mesh', 'local'):
        raise RuntimeError('SCALED_ADDITIVE_ROTATION_SPACE')
    if source.get_skeleton() != target.get_skeleton() or source.get_skeleton() != base.get_skeleton():
        raise RuntimeError('SCALED_ADDITIVE_SKELETON')
    if unreal.AnimationLibrary.get_animation_notify_events(target) or unreal.AnimationLibrary.get_animation_curve_names(target, unreal.RawCurveTrackTypes.RCT_FLOAT):
        raise RuntimeError('SCALED_ADDITIVE_OUTPUT_HAS_EVENTS_OR_CURVES')
    tracks = _tracks(source)
    if source.data_model_interface.get_number_of_keys() > 1200 or not -1 <= source_reference_frame < source.data_model_interface.get_number_of_keys():
        raise RuntimeError('SCALED_ADDITIVE_FRAME_RANGE')
    if source.get_editor_property('additive_anim_type') not in (unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE,
            unreal.AdditiveAnimationType.AAT_ROTATION_OFFSET_MESH_SPACE):
        raise RuntimeError('SCALED_ADDITIVE_SOURCE_TYPE')
    neutral = _tracks(base)
    if set(tracks) != set(neutral):
        raise RuntimeError('SCALED_ADDITIVE_BASE_TRACK_SET')
    source_base = {name: rows[source_reference_frame] for name, rows in tracks.items()}
    if source_reference_frame == -1:
        reference = source.get_editor_property('ref_pose_seq')
        if not isinstance(reference, unreal.AnimSequence) or reference == source:
            raise RuntimeError('SCALED_ADDITIVE_VALID_REFERENCE_REQUIRED')
        reference_tracks = _tracks(reference)
        frame = source.get_editor_property('ref_frame_index')
        if set(reference_tracks) != set(tracks) or not 0 <= frame < reference.data_model_interface.get_number_of_keys():
            raise RuntimeError('SCALED_ADDITIVE_REFERENCE_FRAME')
        source_base = {name: rows[frame] for name, rows in reference_tracks.items()}
    names = {name.casefold(): name for name in tracks}
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh) or mesh.get_editor_property('skeleton') != source.get_skeleton():
        raise RuntimeError('SCALED_ADDITIVE_MESH_SKELETON')
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    parents = {name: names.get(str(subsystem.get_bone_parent(mesh, name)).casefold()) for name in tracks}
    destination_base = {name: rows[0] for name, rows in neutral.items()}
    source_component = _components(source_base, parents)
    base_component = _components(destination_base, parents)
    mesh_space = source.get_editor_property('additive_anim_type') == unreal.AdditiveAnimationType.AAT_ROTATION_OFFSET_MESH_SPACE
    if rotation_space != 'source':
        mesh_space = rotation_space == 'mesh'
    prepared = {name: [] for name in tracks}
    peak = 0.0
    for index in range(source.data_model_interface.get_number_of_keys()):
        local = {name: rows[index] for name, rows in tracks.items()}
        components = _components(local, parents)
        desired = {}
        for name in tracks:
            delta = local[name].rotation * source_base[name].rotation.inversed()
            if mesh_space:
                delta = components[name] * source_component[name].inversed()
            peak = max(peak, math.degrees(2 * math.acos(min(1.0, abs(delta.normalized().w)))))
            desired[name] = _power(delta, amplitude) * destination_base[name].rotation
            if mesh_space:
                desired[name] = _power(delta, amplitude) * base_component[name]
        for name in tracks:
            position = destination_base[name].translation + (local[name].translation - source_base[name].translation) * amplitude
            scale = unreal.Vector(*[b * (1 + (v / r - 1) * amplitude) for b, v, r in zip(
                destination_base[name].scale3d.to_tuple(), local[name].scale3d.to_tuple(), source_base[name].scale3d.to_tuple())])
            value = unreal.Transform(location=position, scale=scale)
            value.rotation = desired[name].normalized()
            if mesh_space and parents[name]:
                value.rotation = (desired[parents[name]].inversed() * desired[name]).normalized()
            if not all(math.isfinite(v) for v in (*position.to_tuple(), *scale.to_tuple(), *value.rotation.to_tuple())):
                raise RuntimeError('SCALED_ADDITIVE_NONFINITE')
            prepared[name].append(value)
    if peak < 0.001:
        raise RuntimeError('SCALED_ADDITIVE_ZERO_MOTION')
    require_asset_write([target])
    target.controller.open_bracket('重建明确幅度射击加法', False)
    try:
        target.controller.set_frame_rate(source.data_model_interface.get_frame_rate(), False)
        target.controller.set_number_of_frames(unreal.FrameNumber(source.data_model_interface.get_number_of_keys() - 1), False)
        existing = {str(name) for name in target.data_model_interface.get_bone_track_names()}
        for name in existing - set(prepared):
            target.controller.remove_bone_track(name, False)
        for name, rows in prepared.items():
            if name not in existing and not target.controller.add_bone_curve(name, False):
                raise RuntimeError('SCALED_ADDITIVE_ADD_TRACK: ' + name)
            if not target.controller.set_bone_track_keys(name, [v.translation for v in rows], [v.rotation for v in rows], [v.scale3d for v in rows], False):
                raise RuntimeError('SCALED_ADDITIVE_SET_TRACK: ' + name)
    finally:
        target.controller.close_bracket(False)
    target.set_editor_property('additive_anim_type', unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE)
    target.set_editor_property('ref_pose_type', unreal.AdditiveBasePoseType.ABPT_ANIM_FRAME)
    target.set_editor_property('ref_pose_seq', base)
    target.set_editor_property('ref_frame_index', 0)
    maximum_error = 0.0
    readback = {}
    for name, expected in prepared.items():
        actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(target, name)
        readback[name] = actual
        if len(actual) != len(expected):
            raise RuntimeError('SCALED_ADDITIVE_READBACK_COUNT')
        for left, right in zip(actual, expected):
            maximum_error = max(maximum_error, (left.translation - right.translation).length(), (left.scale3d - right.scale3d).length())
            if abs(sum(a * b for a, b in zip(left.rotation.to_tuple(), right.rotation.to_tuple()))) < 0.999999:
                raise RuntimeError('SCALED_ADDITIVE_READBACK_ROTATION')
    measured_peak = 0.0
    for index in range(source.data_model_interface.get_number_of_keys()):
        actual_components = _components({name: rows[index] for name, rows in readback.items()}, parents)
        input_components = _components({name: rows[index] for name, rows in tracks.items()}, parents)
        for name in tracks:
            actual_delta = readback[name][index].rotation * destination_base[name].rotation.inversed()
            expected_delta = tracks[name][index].rotation * source_base[name].rotation.inversed()
            if mesh_space:
                actual_delta = actual_components[name] * base_component[name].inversed()
                expected_delta = input_components[name] * source_component[name].inversed()
            expected_delta = _power(expected_delta, amplitude)
            measured_peak = max(measured_peak, math.degrees(2 * math.acos(min(1.0, abs(actual_delta.normalized().w)))))
            if abs(sum(a * b for a, b in zip(actual_delta.normalized().to_tuple(), expected_delta.to_tuple()))) < 0.999999:
                raise RuntimeError('SCALED_ADDITIVE_AMPLITUDE_READBACK: ' + name)
    if maximum_error > 0.0001 or not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
        raise RuntimeError('SCALED_ADDITIVE_READBACK_OR_SAVE')
    return {'animation': animation_path, 'source': source.get_path_name(), 'reference': base_path, 'amplitude': amplitude,
            'source_peak_degrees': peak, 'scaled_peak_degrees': measured_peak, 'maximum_readback_error': maximum_error,
            'keys': target.data_model_interface.get_number_of_keys(), 'bones': len(prepared), 'saved': True}
