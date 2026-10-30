import math

import unreal


BONES = (
    "root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head",
    "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l",
    "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r", "foot_l", "foot_r",
)
CURVES = (
    "DisableAimIK", "DisableLHandIK", "DisableLeftHandIK",
    "DisableLHandPoseOverride", "DisableRHandPoseOverride",
    "DisableLeftHandPoseOverride", "DisableRightHandPoseOverride",
)


def vector(value):
    """/** @param value 引擎向量 @return 有限三轴坐标 */"""
    result = [float(value.x), float(value.y), float(value.z)]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("表现探针读取到非有限向量")
    return result


def transform(value):
    """/** @param value 引擎变换 @return 有限位置与四元数 */"""
    rotation = [float(getattr(value.rotation, axis)) for axis in ("x", "y", "z", "w")]
    if not all(math.isfinite(item) for item in rotation):
        raise ValueError("表现探针读取到非有限旋转")
    return {"position": vector(value.translation), "rotation": rotation}


def snapshot(mesh, main, runtime):
    """
    /**
     * 只读记录角色最终上半身姿态及既有瞄准事实
     * @param mesh\t角色骨骼组件
     * @param main\t角色主动画实例
     * @param runtime\t本帧原生角色快照
     * @return 带缺失项标记的表现快照 不主动求值或写入被测对象
     */
    """
    result = {"componentBones": {}, "missingBones": [], "layers": []}
    for name in BONES:
        if mesh.get_bone_index(name) < 0:
            result["missingBones"].append(name)
            continue
        result["componentBones"][name] = transform(mesh.get_socket_transform(
            name, unreal.RelativeTransformSpace.RTS_COMPONENT,
        ))
    result["meshWorld"] = transform(mesh.get_world_transform())
    result["aiming"] = main.is_aiming()
    result["running"] = main.is_running()
    result["fireIntent"] = main.has_fire_intent()
    result["hasMuzzle"] = main.has_muzzle()
    result["aimTargetComponent"] = vector(main.get_aim_target_component_space())
    result["muzzleInHandR"] = transform(main.try_get_muzzle_transform_hand_r_space())
    result["hasLeftHandTarget"] = main.has_left_hand_ik_target()
    result["leftHandTargetInHandR"] = vector(main.get_left_hand_ik_position())
    result["mainCurves"] = {name: float(main.get_curve_value(name)) for name in CURVES}
    for layer in runtime.get("linkedLayers", []):
        instance = unreal.load_object(None, layer["path"])
        values = {"path": layer["path"], "missingProperties": []}
        for name in ("WeaponAimAlpha", "LocomotionAimIKAlpha", "WeaponAimFollowSpeed",
                     "WeaponBackwardRecoilAlpha", "WeaponRecoilTime"):
            try:
                values[name] = float(instance.get_editor_property(name))
            except Exception:
                values["missingProperties"].append(name)
        values["curves"] = {name: float(instance.get_curve_value(name)) for name in CURVES}
        result["layers"].append(values)
    return result
