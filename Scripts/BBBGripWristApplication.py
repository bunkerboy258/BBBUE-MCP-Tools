import json
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write


def bake_recipe(recipe, apply):
    """/** @param recipe 唯一制作源 @param apply 是否写入正式握姿 @return 旧目标朝向到位置双骨 IK 的腕部换算证据 */"""
    from BBBGripManualAuthoring import _pose
    from BBBGripAuthoringToolset import _transform, _values

    mesh = unreal.load_asset(recipe['character_mesh'])
    animation = unreal.load_asset(recipe['animation'])
    reference = unreal.load_asset(recipe['reference_animation'])
    definition = unreal.load_asset(recipe['definition'])
    weapon = unreal.load_asset(recipe['weapon_mesh'])
    names = ['clavicle_l', 'upperarm_l', 'lowerarm_l', 'upperarm_r', 'lowerarm_r', 'hand_l', 'hand_r']
    base = _pose(reference, names, mesh)
    grip = _pose(animation, names, mesh)
    calibration = recipe['calibration']
    right_local = (unreal.Quat(*calibration['right_wrist_delta']) * base['hand_r']['local'].rotation).normalized()
    right_parent = (base['hand_r']['component'].rotation * base['hand_r']['local'].rotation.inversed()).normalized()
    right = _transform(_values(base['hand_r']['component']))
    right.rotation = (right_parent * right_local).normalized()
    attachment = mesh.find_socket(recipe['attachment_socket'])
    left_socket = weapon.find_socket(recipe['left_socket'])
    pole_socket = mesh.find_socket('LeftHandIKJointTarget')
    if attachment is None or left_socket is None or pole_socket is None or str(pole_socket.bone_name).lower() != 'clavicle_l':
        raise RuntimeError('WRIST_APPLICATION_SOCKET_REQUIRED')
    surface = json.loads(unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(weapon, [], [], 0.5, []))
    parent = next(bone for bone in surface['bones'] if bone['name'].lower() == str(left_socket.bone_name).lower())
    parent_transform = _transform(parent['component'])
    socket_local = unreal.Transform(location=left_socket.relative_location, rotation=left_socket.relative_rotation, scale=left_socket.relative_scale)
    attach_local = unreal.Transform(location=attachment.relative_location, rotation=attachment.relative_rotation, scale=attachment.relative_scale)
    socket_right = socket_local * parent_transform * definition.get_editor_property('spawn_offset') * attach_local
    target_right = socket_right.translation + definition.get_editor_property('left_hand_ik_offset')
    target = unreal.MathLibrary.transform_location(right, target_right)
    desired = (right.rotation * socket_right.rotation * unreal.Quat(*calibration['left_ik_rotation'])).normalized()
    pole = unreal.MathLibrary.transform_location(base['clavicle_l']['component'], pole_socket.relative_location)
    shoulder, elbow, wrist = [base[name]['component'].translation for name in ['upperarm_l', 'lowerarm_l', 'hand_l']]
    solved_elbow, solved_end = unreal.AnimGraphLibrary.two_bone_ik(shoulder, elbow, wrist, pole, target, False, 1.0, 1.2)
    if (solved_end - target).length() > 0.01:
        raise RuntimeError('WRIST_APPLICATION_TARGET_UNREACHABLE: ' + recipe['weapon_root'])
    swing = unreal.MathLibrary.quat_find_between_vectors(wrist - elbow, solved_end - solved_elbow)
    solver_path = '/Game/_Project/Characters/BBBC_UA/Animation/UsedAnimation/blueprints/ABP_BBB_LocomotionLayer_Base.ABP_BBB_LocomotionLayer_Base:FullBody_SkeletalControls.AnimGraphNode_TwoBoneIK_0'
    solver = unreal.load_object(None, solver_path)
    if solver is None:
        raise RuntimeError('WRIST_APPLICATION_SOLVER_REQUIRED')
    solver_node = solver.get_editor_property('node')
    if solver_node.get_editor_property('bTakeRotationFromEffectorSpace'):
        raise RuntimeError('WRIST_APPLICATION_REQUIRES_POSE_ROTATION')
    maintain_relative = bool(solver_node.get_editor_property('bMaintainEffectorRelRot'))
    lower_rotation = base['lowerarm_l']['component'].rotation
    if maintain_relative:
        lower_rotation = (swing * lower_rotation).normalized()
    left_local = (lower_rotation.inversed() * desired).normalized()
    actual = (lower_rotation * left_local).normalized()
    values_a, values_b = actual.to_tuple(), desired.to_tuple()
    dot = min(1.0, abs(sum(a * b for a, b in zip(values_a, values_b))) / (sum(a * a for a in values_a) * sum(b * b for b in values_b)) ** 0.5)
    import math
    error = math.degrees(2.0 * math.acos(dot))
    report = {'animation': recipe['animation'], 'targetPositionErrorCm': (solved_end - target).length(),
              'targetRotationErrorDegrees': error, 'leftLocalRotation': list(left_local.to_tuple()),
              'rightLocalRotation': list(right_local.to_tuple()), 'desiredHandRRotation': list((right.rotation.inversed() * desired).normalized().to_tuple()),
              'sourceLeftIKRotation': calibration['left_ik_rotation'], 'maintainEffectorRelativeRotation': maintain_relative, 'applied': False}
    if error > 0.001:
        raise RuntimeError('WRIST_APPLICATION_ROTATION_MISMATCH: ' + str(error))
    if apply:
        require_asset_write([animation])
        controller = animation.controller
        count = animation.data_model_interface.get_number_of_keys()
        controller.open_bracket('将旧握持角度烘焙为位置IK的腕部局部旋转', False)
        try:
            for name, rotation in [('hand_l', left_local), ('hand_r', right_local)]:
                local = grip[name]['local']
                if not controller.set_bone_track_keys(name, [local.translation] * count, [rotation] * count, [local.scale3d] * count, False):
                    raise RuntimeError('WRIST_APPLICATION_WRITE_FAILED: ' + name)
        finally:
            controller.close_bracket(False)
        readback = _pose(animation, names, mesh)
        for name, rotation in [('hand_l', left_local), ('hand_r', right_local)]:
            qa, qb = readback[name]['local'].rotation.to_tuple(), rotation.to_tuple()
            cosine = abs(sum(a * b for a, b in zip(qa, qb))) / (sum(a * a for a in qa) * sum(b * b for b in qb)) ** 0.5
            if cosine < 0.99999999:
                raise RuntimeError('WRIST_APPLICATION_READBACK_FAILED: ' + name)
        for name in ['upperarm_l', 'lowerarm_l', 'upperarm_r', 'lowerarm_r']:
            if (readback[name]['local'].translation - grip[name]['local'].translation).length() > 0.001:
                raise RuntimeError('WRIST_APPLICATION_ARM_POSITION_CHANGED: ' + name)
        read_rotation = (lower_rotation * readback['hand_l']['local'].rotation).normalized()
        qa, qb = read_rotation.to_tuple(), desired.to_tuple()
        cosine = min(1.0, abs(sum(a * b for a, b in zip(qa, qb))) / (sum(a * a for a in qa) * sum(b * b for b in qb)) ** 0.5)
        report['bakedReadbackRotationErrorDegrees'] = math.degrees(2 * math.acos(cosine))
        if report['bakedReadbackRotationErrorDegrees'] > 0.001:
            raise RuntimeError('WRIST_APPLICATION_BAKED_ROTATION_MISMATCH')
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('WRIST_APPLICATION_SAVE_FAILED')
        report['applied'] = True
    return report


def bake_wrist_applications(weapon_roots, recipe_paths, apply):
    """/** @param weapon_roots 明确武器根 @param recipe_paths 对应唯一制作源 @param apply 是否写入 @return 全部预检后的逐枪腕部烘焙报告 */"""
    from BBBGripAuthoringToolset import _safe_file, _recipe, _write_recipe
    if len(weapon_roots) != len(recipe_paths) or not 1 <= len(weapon_roots) <= 14:
        raise RuntimeError('WRIST_APPLICATION_SCOPE_REQUIRED')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE_ACTIVE')
    project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())).resolve()
    recipes = []
    for root, path in zip(weapon_roots, recipe_paths):
        source = _safe_file(project, root, path)
        recipe = _recipe(source, root)
        recipes.append((source, recipe))
    reports = [bake_recipe(recipe, False) for source, recipe in recipes]
    if apply:
        reports = []
        for source, recipe in recipes:
            report = bake_recipe(recipe, True)
            recipe['wrist_application'] = {'format': 'BBBGripPositionIKWrist', **report}
            _write_recipe(source, recipe, project)
            reports.append(report)
    return {'applied': apply, 'count': len(reports), 'results': reports, 'sequencesModified': False, 'runtimeAcceptance': 'pending'}


