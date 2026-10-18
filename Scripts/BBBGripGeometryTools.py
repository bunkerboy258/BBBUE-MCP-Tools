import json
import math
import os
from pathlib import Path
import re

import unreal


def _transform(value):
    """/** @param value 平移 四元数与缩放十项 @return 引擎变换 */"""
    result = unreal.Transform(location=unreal.Vector(*value[:3]), scale=unreal.Vector(*value[7:10]))
    result.rotation = unreal.Quat(*value[3:7])
    return result


def _values(value):
    """/** @param value 引擎变换 @return 平移 四元数与缩放十项 */"""
    return list(value.translation.to_tuple()) + list(value.rotation.to_tuple()) + list(value.scale3d.to_tuple())


def _output_path(output_name):
    """/** @param output_name 任务目录与报告名称 @return 无覆盖且位于项目临时目录内的路径 */"""
    if not isinstance(output_name, str) or re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", output_name) is None:
        raise RuntimeError("几何采样报告名称必须为任务目录名与文件名 两段英文数字下划线或横线")

    root = Path(unreal.Paths.project_saved_dir()).absolute() / "temp"
    destination = root / (output_name + ".json")
    for parent in (root.parent, root, destination.parent):
        is_junction = getattr(os.path, "isjunction", lambda value: False)
        if parent.is_symlink() or (parent.exists() and is_junction(parent)):
            raise RuntimeError("几何采样拒绝链接目录")

    if destination.exists():
        raise RuntimeError("几何采样拒绝覆盖已有报告: " + str(destination))

    if not destination.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("几何采样报告路径越界")

    return destination


def sample_surface(mesh_path, animation_path, time_seconds, selected_bones, minimum_weight, material_indices, output_name, local_rotations_json="{}"):
    """
    /**
     * 只读取得零级源网格在明确骨骼姿势下的实际线性蒙皮表面
     * @param mesh_path		明确骨骼网格包路径
     * @param animation_path	明确非加法动画路径 空字符串使用参考姿势
     * @param time_seconds	动画时间秒数
     * @param selected_bones	所选骨骼及后代 空数组选全部顶点
     * @param minimum_weight	所选骨骼合计权重最低阈值
     * @param material_indices	所选有效材质槽 空数组选全部非禁用分段
     * @param output_name		任务目录名与无扩展名的报告名称
     * @param local_rotations_json	可选明确局部四元数覆盖 不改变骨长
     * @return 报告路径 数量与几何限制 不修改或保存资产
     */
    """
    if not isinstance(mesh_path, str) or re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", mesh_path) is None:
        raise RuntimeError("几何采样要求明确的 Game 网格包路径")

    if not math.isfinite(time_seconds) or time_seconds < 0:
        raise RuntimeError("几何采样时间必须是非负有限数")

    if not math.isfinite(minimum_weight) or not 0 < minimum_weight <= 1:
        raise RuntimeError("几何选取权重必须大于零且不大于一")

    selected_bones = list(selected_bones)
    material_indices = list(material_indices)
    if len(selected_bones) > 256 or any(not isinstance(name, str) or not name for name in selected_bones):
        raise RuntimeError("几何采样需要至多二百五十六个明确骨骼名称")

    if len(set(name.lower() for name in selected_bones)) != len(selected_bones):
        raise RuntimeError("几何采样拒绝重复骨骼名称")

    if len(material_indices) > 256 or any(type(index) is not int or index < 0 for index in material_indices):
        raise RuntimeError("几何采样材质槽必须为非负整数")

    rotations = json.loads(local_rotations_json)
    if not isinstance(rotations, dict) or len(rotations) > 256:
        raise RuntimeError("局部旋转覆盖必须为至多二百五十六项的字典")

    for name, value in rotations.items():
        if not isinstance(name, str) or not isinstance(value, list) or len(value) != 4 or any(type(number) not in (int, float) or not math.isfinite(number) for number in value):
            raise RuntimeError("局部旋转覆盖需要明确骨骼名称与有限四元数")

        if abs(sum(number * number for number in value) - 1.0) > 0.0001:
            raise RuntimeError("局部旋转四元数未归一化: " + name)

    destination = _output_path(output_name)
    mesh = unreal.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("几何采样目标不是骨骼网格: " + mesh_path)

    bridge = getattr(unreal, "BBBGripGeometryEditorLibrary", None)
    if bridge is None:
        raise RuntimeError("几何采样原生库尚未编译加载")

    selected = [unreal.Name(name) for name in selected_bones]
    serialized = bridge.sample_skeletal_mesh_surface(mesh, [], selected, minimum_weight, material_indices)
    if not serialized:
        raise RuntimeError("原生参考网格采样失败 请检查编辑器日志")

    reference = json.loads(serialized)
    bones = reference["bones"]
    names = {bone["name"].lower(): bone["name"] for bone in bones}
    unknown = set(name.lower() for name in rotations) - names.keys()
    if unknown:
        raise RuntimeError("局部旋转覆盖包含不存在的骨骼: " + " ".join(sorted(unknown)))

    rotations = {name.lower(): value for name, value in rotations.items()}
    local = [_transform(bone["referenceLocal"]) for bone in bones]
    animation = None
    if animation_path:
        if re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", animation_path) is None:
            raise RuntimeError("几何采样要求明确的 Game 动画包路径")

        animation = unreal.load_asset(animation_path)
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError("几何采样动画不是动画序列")

        if animation.get_editor_property("additive_anim_type") != unreal.AdditiveAnimationType.AAT_NONE:
            raise RuntimeError("几何采样拒绝独立求值加法动画 请提供已合成的明确姿势")

        if time_seconds > animation.sequence_length + 0.000001:
            raise RuntimeError("几何采样时间超出动画长度")

        options = unreal.AnimPoseEvaluationOptions()
        options.optional_skeletal_mesh = mesh
        options.should_retarget = True
        options.evaluation_type = unreal.AnimDataEvalType.RAW
        pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, min(time_seconds, animation.sequence_length), options)
        pose_names = {str(name).lower(): name for name in unreal.AnimPoseExtensions.get_bone_names(pose)}
        for index, bone in enumerate(bones):
            name = pose_names.get(bone["name"].lower())
            if name is not None:
                local[index] = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)

    if not animation_path and time_seconds != 0:
        raise RuntimeError("参考姿势采样时间必须为零")

    component = []
    for index, bone in enumerate(bones):
        override = rotations.get(bone["name"].lower())
        if override is not None:
            local[index].rotation = unreal.Quat(*override)

        parent = bone["parent"]
        if parent >= index:
            raise RuntimeError("参考骨架父子顺序无效")

        current = local[index]
        if parent >= 0:
            current = unreal.MathLibrary.compose_transforms(current, component[parent])

        component.append(current)

    result = reference
    if animation is not None or rotations:
        serialized = bridge.sample_skeletal_mesh_surface(mesh, component, selected, minimum_weight, material_indices)
        if not serialized:
            raise RuntimeError("原生姿势网格采样失败 请检查编辑器日志")

        result = json.loads(serialized)

    for bone, value in zip(result["bones"], local):
        bone["local"] = _values(value)

    result["animation"] = animation_path
    result["timeSeconds"] = time_seconds
    result["localRotationOverrides"] = rotations
    result["selectedBoneRoots"] = selected_bones
    result["minimumSelectedWeight"] = minimum_weight
    result["materialIndices"] = material_indices
    result["readOnly"] = True
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    positions = [vertex["position"] for vertex in result["vertices"]]
    bounds = None
    if positions:
        bounds = {"minimum": [min(point[axis] for point in positions) for axis in range(3)], "maximum": [max(point[axis] for point in positions) for axis in range(3)]}

    summary = {"report": str(destination), "readOnly": True, "mesh": mesh_path, "animation": animation_path,
        "vertices": len(result["vertices"]), "selectedVertices": result["selectedVertexCount"], "triangles": len(result["triangles"]),
        "bounds": bounds, "deformation": result["deformation"], "morphTargetCount": result["morphTargetCount"], "clothSectionCount": result["clothSectionCount"]}
    unreal.log("[BBBGripGeometry] 零级表面报告 " + str(destination))
    return json.dumps(summary, ensure_ascii=False)
