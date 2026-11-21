import hashlib
import json
import math

import unreal

import BBBFingerAnimationMath as qmath


DIGITS = ('index', 'middle', 'ring', 'pinky')
SIDES = ('l', 'r')
FINGER_NAMES = tuple(f'{digit}_{segment:02d}_{side}' for side in SIDES for digit in DIGITS for segment in (1, 2, 3))
MAXIMUM_FLEXION = 120.0


def dot(a, b):
    """/** @param a 第一向量 @param b 第二向量 @return 点积 */"""
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    """/** @param a 第一向量 @param b 第二向量 @return 叉积 */"""
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def sub(a, b):
    """/** @param a 第一位置 @param b 第二位置 @return 差向量 */"""
    return [x-y for x, y in zip(a, b)]


def rotate(q, v):
    """/** @param q 单位旋转 @param v 向量 @return 旋转后的向量 */"""
    return qmath.multiply(qmath.multiply(q, list(v)+[0]), qmath.inverse(q))[:3]


def shortest_swing(source, target):
    """/** @param source 单位起始方向 @param target 单位目标方向 @return 不含长轴扭转的最短摆动 */"""
    cosine = dot(source, target)
    if cosine < -0.999999:
        raise ValueError('PLANAR_SWING_ANTIPARALLEL')
    return qmath.unit(cross(source, target) + [1.0 + cosine])


def evaluated_tracks(animation, tracks, mesh, count):
    """/** @param animation 原动画 @param tracks 原生骨轨 @param mesh 实际绑定网格 @param count 采样数 @return 实际网格求值的指骨轨及原轨差 */"""
    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = True
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    result = {name: [] for name in FINGER_NAMES}
    rate = animation.data_model_interface.get_frame_rate()
    rotation_error = 0.0
    translation_error = 0.0
    for sample in range(count):
        time_seconds = sample * rate.denominator / rate.numerator
        pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, time_seconds, options)
        for name in FINGER_NAMES:
            transform = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)
            if any(abs(value - 1.0) > 0.0001 for value in transform.scale3d.to_tuple()):
                raise ValueError('PLANAR_NONUNIT_FINGER_SCALE: ' + name)
            result[name].append(transform)
            source = tracks[name][sample]
            rotation_error = max(rotation_error, qmath.distance(transform.rotation.to_tuple(), source.rotation.to_tuple()))
            translation_error = max(translation_error, (transform.translation - source.translation).length())

    if rotation_error > 0.01:
        raise ValueError('PLANAR_RETARGET_ROTATION_MAPPING_REQUIRED: ' + str(rotation_error))
    return result, {
        'maximumMeshPoseTranslationDifferenceCentimeters': translation_error,
        'maximumMeshPoseRotationDifferenceDegrees': rotation_error,
    }


def build_hinges(mesh_bones, grip_directions):
    """/** @param mesh_bones 实际网格的参考局部骨骼 @param grip_directions 每侧正确握姿的掌心方向线索 @return 每节零屈曲姿态及局部屈曲坐标 */"""
    reference = {bone['name']: bone['referenceLocal'] for bone in mesh_bones}
    parents = {bone['name']: mesh_bones[bone['parent']]['name'] for bone in mesh_bones if bone['parent'] >= 0}
    if any(name not in reference for name in FINGER_NAMES):
        raise ValueError('PLANAR_MESH_FINGER_BONES_REQUIRED')

    hinges = {}
    for side in SIDES:
        bases = [reference[f'{digit}_01_{side}'][:3] for digit in DIGITS]
        center = [sum(position[axis] for position in bases) / len(bases) for axis in range(3)]
        width = qmath.unit(sub(bases[0], bases[-1]))
        palm_normal = qmath.unit(cross(center, width))
        forward = qmath.unit(cross(width, palm_normal))
        grip_sign = dot(palm_normal, qmath.unit(grip_directions[side]))
        if abs(grip_sign) < 0.0001:
            raise ValueError('PLANAR_AMBIGUOUS_PALM_DIRECTION: ' + side)
        if grip_sign < 0.0:
            palm_normal = [-value for value in palm_normal]
        palm_hinge = qmath.unit(cross(forward, palm_normal))

        for digit in DIGITS:
            chain = [f'{digit}_{segment:02d}_{side}' for segment in (1, 2, 3)]
            parent_name = 'hand_' + side
            parent_bind = [0.0, 0.0, 0.0, 1.0]
            parent_neutral = parent_bind
            previous_direction = None
            for index, name in enumerate(chain):
                if parents.get(name) != parent_name:
                    raise ValueError('PLANAR_FINGER_PARENT_MISMATCH: ' + name)
                bind = qmath.unit(qmath.multiply(parent_bind, qmath.unit(reference[name][3:7])))
                if index < len(chain) - 1:
                    local_forward = qmath.unit(reference[chain[index + 1]][:3])
                    bind_direction = rotate(bind, local_forward)
                else:
                    local_forward = qmath.unit(rotate(qmath.inverse(bind), previous_direction))
                    bind_direction = previous_direction

                neutral = qmath.unit(qmath.multiply(shortest_swing(bind_direction, forward), bind))
                neutral_local = qmath.unit(qmath.multiply(qmath.inverse(parent_neutral), neutral))
                local_hinge = qmath.unit(rotate(qmath.inverse(neutral), palm_hinge))
                local_inward = qmath.unit(cross(local_hinge, local_forward))
                hinges[name] = (neutral_local, local_hinge, local_forward, local_inward)
                parent_name = name
                parent_bind = bind
                parent_neutral = neutral
                previous_direction = bind_direction
    return hinges


def solve(tracks, hinges):
    """/** @param tracks 网格实际求值的原始指骨旋转 @param hinges 实际网格的单轴关节 @return 重建后的逐帧指骨局部旋转 */"""
    rotations = {}
    for name, (neutral, axis, forward, inward) in hinges.items():
        values = []
        inverse_neutral = qmath.inverse(neutral)
        for transform in tracks[name]:
            delta = qmath.multiply(inverse_neutral, qmath.unit(transform.rotation.to_tuple()))
            direction = rotate(delta, forward)
            along = dot(direction, forward)
            toward_palm = dot(direction, inward)
            angle = 0.0
            if math.hypot(along, toward_palm) > 1e-8:
                angle = math.degrees(math.atan2(toward_palm, along))
            flexion = min(MAXIMUM_FLEXION, max(0.0, angle))
            values.append(qmath.unit(qmath.multiply(neutral, qmath.axis_angle(axis, flexion))))
        rotations[name] = values
    return rotations


def audit(tracks, hinges):
    """/** @param tracks 实际局部骨轨 @param hinges 网格单轴关节 @return 全指节离轴旋转及屈曲范围 */"""
    off_axis = 0.0
    reverse = 0.0
    peak = 0.0
    root_peak = 0.0
    for name, (neutral, axis, _forward, _inward) in hinges.items():
        for transform in tracks[name]:
            delta = qmath.multiply(qmath.inverse(neutral), qmath.unit(transform.rotation.to_tuple()))
            signed_axis = dot(delta[:3], axis)
            residual = sub(delta[:3], [signed_axis * value for value in axis])
            off_axis = max(off_axis, math.degrees(2.0 * math.asin(min(1.0, math.hypot(*residual)))))
            angle = math.degrees(2.0 * math.atan2(signed_axis, delta[3]))
            angle = (angle + 180.0) % 360.0 - 180.0
            reverse = max(reverse, -angle)
            peak = max(peak, angle)
            if '_01_' in name:
                root_peak = max(root_peak, angle)
    return {
        'maximumOffAxisDegrees': off_axis,
        'maximumReverseFlexionDegrees': reverse,
        'maximumFlexionDegrees': peak,
        'maximumRootFlexionDegrees': root_peak,
    }


def run(paths, config, action):
    """/** @param paths 明确动画 @param config 单轴屈曲配置 @param action 检查或写入 @return 全骨轨保存回读证据 */"""
    from BBBFingerAnimationTools import _asset, _tracks, _signature
    from BBBAnimationTrajectoryTools import _track_metadata
    from BBBAssetWritePolicy import require_asset_write

    if action not in ('inspect', 'repair') or not paths or len(paths) > 128 or len(set(paths)) != len(paths):
        raise ValueError('PLANAR_ACTION_INVALID')
    if 'root_spread_degrees' in config:
        raise ValueError('PLANAR_ROOT_SPREAD_REMOVED: 四指指根仅允许向掌心屈曲')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('PLANAR_PIE_ACTIVE')
    mesh = unreal.load_asset(config['mesh_path'])
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise ValueError('PLANAR_MESH_REQUIRED')
    skeleton = mesh.get_editor_property('skeleton')
    grip = _asset(config['reference_animation'])
    if grip.get_editor_property('skeleton') != skeleton:
        raise ValueError('PLANAR_REFERENCE_SKELETON_MISMATCH')

    options = unreal.AnimPoseEvaluationOptions()
    options.optional_skeletal_mesh = mesh
    options.should_retarget = True
    options.evaluation_type = unreal.AnimDataEvalType.RAW
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(grip, 0.0, options)
    sampled = unreal.BBBGripGeometryEditorLibrary.sample_skeletal_mesh_surface(
        mesh, [], [unreal.Name('hand_l'), unreal.Name('hand_r')], 1.0, [])
    grip_directions = {}
    for side in SIDES:
        hand = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_' + side, unreal.AnimPoseSpaces.WORLD)
        directions = []
        for digit in ('middle', 'ring', 'pinky'):
            a = unreal.AnimPoseExtensions.get_bone_pose(pose, f'{digit}_02_{side}', unreal.AnimPoseSpaces.WORLD).translation
            b = unreal.AnimPoseExtensions.get_bone_pose(pose, f'{digit}_03_{side}', unreal.AnimPoseSpaces.WORLD).translation
            directions.append(hand.rotation.inversed().rotate_vector(b - a).to_tuple())
        grip_directions[side] = [sum(direction[axis] for direction in directions) for axis in range(3)]

    hinges = build_hinges(json.loads(sampled)['bones'], grip_directions)
    plan_config = {
        'mesh_path': mesh.get_path_name(),
        'reference_animation': grip.get_path_name(),
        'algorithm': 'mesh_bind_inward_hinge_all_segments',
        'maximum_flexion_degrees': MAXIMUM_FLEXION,
        'hinges': hinges,
    }
    plan = hashlib.sha256(json.dumps(plan_config, sort_keys=True).encode()).hexdigest()
    if action == 'repair' and config.get('expected_plan_signature') != plan:
        raise ValueError('PLANAR_INSPECT_REQUIRED')

    prepared, reports = [], []
    for path in paths:
        animation = _asset(path)
        if animation.get_editor_property('skeleton') != skeleton:
            raise ValueError('PLANAR_SKELETON_MISMATCH: ' + path)
        before = _tracks(animation)
        count = animation.data_model_interface.get_number_of_keys()
        if not 1 <= count <= 10000 or any(len(before.get(name, ())) != count for name in FINGER_NAMES):
            raise ValueError('PLANAR_FINGER_TRACK_COUNT_INVALID: ' + path)
        transform_curves = {
            str(name).casefold() for name in unreal.AnimationLibrary.get_animation_curve_names(
                animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)
        }
        if transform_curves.intersection(FINGER_NAMES):
            raise ValueError('PLANAR_TRANSFORM_CURVE_REQUIRES_COMPOSED_POSE: ' + path)

        signature = _signature(before)
        if action == 'repair' and config.get('expected_signatures', {}).get(path) != signature:
            raise ValueError('PLANAR_INSPECT_REQUIRED: ' + path)
        evaluated, evaluation_error = evaluated_tracks(animation, before, mesh, count)
        output = solve(evaluated, hinges)
        prepared.append((animation, before, output, _track_metadata(animation)))
        reports.append({
            'asset': path,
            'signature': signature,
            'changedBones': list(output),
            'samples': count,
            'input': audit(evaluated, hinges),
            **evaluation_error,
        })

    if action == 'repair':
        dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(animation.get_outermost().get_path_name() in dirty for animation, _, _, _ in prepared):
            raise ValueError('PLANAR_TARGET_DIRTY')
        require_asset_write([animation for animation, _, _, _ in prepared])
        for report, (animation, before, output, metadata) in zip(reports, prepared):
            controller = animation.controller
            controller.open_bracket('烘焙四指全指节单轴向内屈曲', False)
            try:
                for name, rotations in output.items():
                    track = before[name]
                    if not controller.set_bone_track_keys(
                            name, [key.translation for key in track], [unreal.Quat(*q) for q in rotations],
                            [key.scale3d for key in track], False):
                        raise RuntimeError('PLANAR_WRITE_FAILED: ' + name)
            finally:
                controller.close_bracket(False)

            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('PLANAR_METADATA_CHANGED')
            for name, original in before.items():
                if len(actual[name]) != len(original):
                    raise RuntimeError('PLANAR_KEY_COUNT_CHANGED: ' + name)
                for sample, (a, b) in enumerate(zip(original, actual[name])):
                    expected = output[name][sample] if name in output else a.rotation.to_tuple()
                    if ((a.translation - b.translation).length() > 0.0001
                            or (a.scale3d - b.scale3d).length() > 0.0001
                            or qmath.distance(expected, b.rotation.to_tuple()) > 0.01):
                        raise RuntimeError(f'PLANAR_READBACK_FAILED: {name} frame {sample}')

            evaluated, _ = evaluated_tracks(animation, actual, mesh, report['samples'])
            measured = audit(evaluated, hinges)
            if (measured['maximumOffAxisDegrees'] > 0.01 or measured['maximumReverseFlexionDegrees'] > 0.01
                    or measured['maximumFlexionDegrees'] > MAXIMUM_FLEXION + 0.01):
                raise RuntimeError('PLANAR_HINGE_READBACK_FAILED: ' + json.dumps(measured))
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('PLANAR_SAVE_FAILED: ' + report['asset'])
            report.update(saved=True, readback=True, metadataPreserved=True, signature=_signature(actual), readbackHinges=measured)

    return json.dumps({
        'action': action,
        'planSignature': plan,
        'assets': reports,
        'constraint': '双手四指从指根到末节只允许向掌心单轴屈曲',
        'thumbModified': False,
    }, ensure_ascii=False)
