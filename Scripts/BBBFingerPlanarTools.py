import hashlib
import json
import math

import unreal

import BBBFingerAnimationMath as qmath


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


def solve(before, skeleton, component, settings):
    """/** @param before 原生局部骨轨 @param skeleton 实际骨架 @param component 父骨查询组件 @param settings 硬约束配置 @return 四指24骨完整旋转及最终方向误差 */"""
    count = len(before['hand_l'])
    names = [f'{digit}_{segment}_{side}' for side in ('l', 'r') for digit in ('index', 'middle', 'ring', 'pinky') for segment in ('01', '02', '03')]
    if any(name not in before or len(before[name]) != count for name in names):
        raise ValueError('PLANAR_FINGER_TRACKS_REQUIRED')
    reference = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
    parents = {}
    ref_local = {}
    def parent(name):
        if name not in parents:
            parents[name] = str(component.get_parent_bone(name))
        return parents[name]
    def reference_local(name):
        if name not in ref_local:
            ref_local[name] = unreal.AnimPoseExtensions.get_bone_pose(reference, name, unreal.AnimPoseSpaces.LOCAL)
        return ref_local[name]
    def fk(name, side, cache, sample, rotations=None):
        if name == 'hand_' + side:
            return [0, 0, 0], [0, 0, 0, 1]
        if name in cache:
            return cache[name]
        p, q = fk(parent(name), side, cache, sample, rotations)
        t = reference_local(name) if sample is None else before.get(name, [reference_local(name)])[sample if name in before else 0]
        if any(abs(v-1)>0.0001 for v in t.scale3d.to_tuple()):
            raise ValueError('PLANAR_NONUNIT_FINGER_SCALE')
        local = list(t.rotation.to_tuple())
        if rotations and name in rotations:
            local = rotations[name]
        offset = rotate(q, list(t.translation.to_tuple()))
        result = ([a+b for a, b in zip(p, offset)], qmath.unit(qmath.multiply(q, local)))
        cache[name] = result
        return result
    result = {name: [] for name in names}
    maximum = 0.0
    maximum_root_twist = 0.0
    maximum_root_spread = 0.0
    maximum_input_root_twist = 0.0
    maximum_input_root_curl = 0.0
    maximum_input_root_spread = 0.0
    for side in ('l', 'r'):
        ref = {}
        for name in [n for n in names if n.endswith('_'+side)]:
            fk(name, side, ref, None)
        bases = [ref[d+'_01_'+side][0] for d in ('index', 'middle', 'ring', 'pinky')]
        forward = qmath.unit([sum(p[a] for p in bases)/4 for a in range(3)])
        width = qmath.unit(sub(bases[0], bases[-1]))
        normal = qmath.unit(cross(forward, width))
        forward = qmath.unit(cross(width, normal))
        # 掌心朝向由明确的正确握姿确定 左右手分别读取
        ref_grip = settings['grip_directions'][side]
        if dot(normal, ref_grip) < 0:
            normal = [-v for v in normal]
        width = qmath.unit(cross(normal, forward))
        for sample in range(count):
            templates = {}
            for digit in ('index', 'middle', 'ring', 'pinky'):
                chain = [f'{digit}_{segment}_{side}' for segment in ('01', '02', '03')]
                incoming = qmath.unit(sub(ref[chain[2]][0], ref[chain[1]][0]))
                for index, name in enumerate(chain):
                    local_axis = rotate(qmath.inverse(ref[name][1]), incoming)
                    if index < 2:
                        local_axis = list(before[chain[index+1]][sample].translation.to_tuple())
                    local_axis = qmath.unit(local_axis)
                    rest_direction = qmath.unit(rotate(ref[name][1], local_axis))
                    neutral = qmath.unit(qmath.multiply(shortest_swing(rest_direction, forward), ref[name][1]))
                    templates[name] = (local_axis, neutral)
            original = {}
            for name in [n for n in names if n.endswith('_'+side)]:
                fk(name, side, original, sample)
            target_rotations = {}
            for digit in ('index', 'middle', 'ring', 'pinky'):
                chain = [f'{digit}_{segment}_{side}' for segment in ('01', '02', '03')]
                root_delta = qmath.unit(qmath.multiply(original[chain[0]][1], qmath.inverse(templates[chain[0]][1])))
                if math.hypot(dot(root_delta[:3], forward), root_delta[3]) < 0.000001:
                    raise ValueError('PLANAR_INPUT_ROOT_TWIST_SINGULAR')
                unused, input_twist = qmath.split(root_delta, forward)
                maximum_input_root_twist = max(maximum_input_root_twist, abs(input_twist))
                directions = [qmath.unit(sub(original[chain[i+1]][0], original[chain[i]][0])) for i in (0, 1)]
                directions.append(rotate(original[chain[2]][1], templates[chain[2]][0]))
                original_spread = math.degrees(math.atan2(dot(width, directions[0]), dot(forward, directions[0])))
                unspread = qmath.axis_angle(normal, -original_spread)
                aligned_directions = [rotate(unspread, direction) for direction in directions]
                angles = [math.degrees(math.atan2(dot(normal, d), dot(forward, d))) for d in aligned_directions]
                maximum_input_root_curl = max(maximum_input_root_curl, abs(angles[0]))
                maximum_input_root_spread = max(maximum_input_root_spread, abs(original_spread))
                spread = min(settings['root_spread_degrees'], max(-settings['root_spread_degrees'], original_spread))
                maximum_root_spread = max(maximum_root_spread, abs(spread))
                spread_rotation = qmath.axis_angle(normal, spread)
                bends = [0.0]
                for index in (1, 2):
                    delta = (angles[index]-angles[index-1]+180)%360-180
                    bends.append(min(120.0, max(0.0, delta)))
                total = 0.0
                for index, name in enumerate(chain):
                    total += bends[index]
                    radians = math.radians(total)
                    direction = [math.cos(radians)*a+math.sin(radians)*b for a, b in zip(forward, normal)]
                    direction = rotate(spread_rotation, direction)
                    swing = qmath.multiply(spread_rotation, qmath.axis_angle(width, -total))
                    if index == 0:
                        swing = shortest_swing(forward, direction)
                        unused, twist = qmath.split(swing, forward)
                        maximum_root_twist = max(maximum_root_twist, abs(twist))
                    absolute = qmath.unit(qmath.multiply(swing, templates[name][1]))
                    parent_q = target_rotations.get(parent(name), original.get(parent(name), ([0,0,0],[0,0,0,1]))[1])
                    local_q = qmath.unit(qmath.multiply(qmath.inverse(parent_q), absolute))
                    result[name].append(local_q)
                    target_rotations[name] = absolute
            checked = {}
            overrides = {name: result[name][-1] for name in names if name.endswith('_'+side)}
            for name in overrides:
                fk(name, side, checked, sample, overrides)
                d = rotate(checked[name][1], templates[name][0])
                digit = name.split('_')[0]
                root_name = digit+'_01_'+side
                root_direction = rotate(checked.get(root_name, original[root_name])[1], templates[root_name][0])
                root_spread = math.degrees(math.atan2(dot(width, root_direction), max(0.000001, dot(forward, root_direction))))
                chain_width = rotate(qmath.axis_angle(normal, root_spread), width)
                maximum = max(maximum, abs(dot(d, chain_width)))
    if maximum > 0.00001:
        raise RuntimeError('PLANAR_CHAIN_DIRECTION_FAILED')
    if maximum_root_twist > 0.00001:
        raise RuntimeError('PLANAR_ROOT_AXIAL_TWIST_FAILED')
    return result, {'maximumOutOfPlaneSine': maximum, 'maximumRootAxialTwistDegrees': maximum_root_twist, 'maximumRootSpreadDegrees': maximum_root_spread, 'maximumInputRootAxialTwistDegrees': maximum_input_root_twist, 'maximumInputRootCurlDegrees': maximum_input_root_curl, 'maximumInputRootSpreadDegrees': maximum_input_root_spread}


def run(paths, config, action):
    """/** @param paths 明确动画 @param config 掌空间硬约束 @param action 检查或写入 @return 全骨轨保存回读证据 */"""
    from BBBFingerAnimationTools import _asset, _tracks, _signature
    from BBBAnimationTrajectoryTools import _track_metadata
    from BBBAssetWritePolicy import require_asset_write

    if action not in ('inspect', 'repair') or not paths or len(paths)>128 or len(set(paths))!=len(paths):
        raise ValueError('PLANAR_ACTION_INVALID')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('PLANAR_PIE_ACTIVE')
    mesh = unreal.load_asset(config['mesh_path'])
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise ValueError('PLANAR_MESH_REQUIRED')
    component = unreal.new_object(unreal.SkeletalMeshComponent)
    component.set_skeletal_mesh_asset(mesh)
    grip = _asset(config['reference_animation'])
    if grip.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise ValueError('PLANAR_REFERENCE_SKELETON_MISMATCH')
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(grip, 0, unreal.AnimPoseEvaluationOptions())
    settings = {'grip_directions': {}, 'root_spread_degrees': float(config.get('root_spread_degrees', 3.0))}
    if not math.isfinite(settings['root_spread_degrees']) or not 0 <= settings['root_spread_degrees'] <= 5:
        raise ValueError('PLANAR_ROOT_SPREAD_LIMIT_ZERO_TO_FIVE')
    for side in ('l', 'r'):
        hand = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_'+side, unreal.AnimPoseSpaces.WORLD)
        directions = []
        for digit in ('middle', 'ring', 'pinky'):
            a = unreal.AnimPoseExtensions.get_bone_pose(pose, digit+'_02_'+side, unreal.AnimPoseSpaces.WORLD).translation
            b = unreal.AnimPoseExtensions.get_bone_pose(pose, digit+'_03_'+side, unreal.AnimPoseSpaces.WORLD).translation
            directions.append(list(hand.rotation.inversed().rotate_vector(b-a).to_tuple()))
        settings['grip_directions'][side] = [sum(d[i] for d in directions) for i in range(3)]
    plan_config = {k:config[k] for k in ('mesh_path', 'reference_animation', 'geometry_chain')}
    plan_config.update(root_spread_degrees=settings['root_spread_degrees'], algorithm='actual_axis_root_planar_only')
    plan = hashlib.sha256(json.dumps(plan_config, sort_keys=True).encode()).hexdigest()
    prepared, reports = [], []
    for path in paths:
        animation = _asset(path)
        if animation.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
            raise ValueError('PLANAR_SKELETON_MISMATCH')
        before = _tracks(animation)
        if len(before.get('hand_l', [])) > 10000:
            raise ValueError('PLANAR_SAMPLE_LIMIT')
        transform_curves = {str(name).casefold() for name in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)}
        finger_names = {f'{digit}_{segment}_{side}' for digit in ('index', 'middle', 'ring', 'pinky') for segment in ('01', '02', '03') for side in ('l', 'r')}
        if transform_curves & finger_names:
            raise ValueError('PLANAR_TRANSFORM_CURVE_REQUIRES_COMPOSED_POSE')
        signature = _signature(before)
        output, error = solve(before, animation.get_editor_property('skeleton'), component, settings)
        metadata = _track_metadata(animation)
        if action == 'repair' and (config.get('expected_plan_signature') != plan or config.get('expected_signatures', {}).get(path) != signature):
            raise ValueError('PLANAR_INSPECT_REQUIRED')
        prepared.append((animation, before, output, metadata))
        reports.append({'asset':path,'signature':signature,'changedBones':list(output),'samples':len(before['hand_l']), **error})
    if action == 'repair':
        dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(animation.get_outermost().get_path_name() in dirty for animation, before, output, metadata in prepared):
            raise ValueError('PLANAR_TARGET_DIRTY')
        require_asset_write([a for a, b, o, m in prepared])
        for index, (animation, before, output, metadata) in enumerate(prepared):
            controller = animation.controller
            controller.open_bracket('硬约束四指同向平面内卷曲', False)
            try:
                for name, rotations in output.items():
                    track = before[name]
                    if not controller.set_bone_track_keys(name, [t.translation for t in track], [unreal.Quat(*q) for q in rotations], [t.scale3d for t in track], False):
                        raise RuntimeError('PLANAR_WRITE_FAILED')
            finally:
                controller.close_bracket(False)
            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('PLANAR_METADATA_CHANGED')
            for name in before:
                if len(actual[name]) != len(before[name]):
                    raise RuntimeError('PLANAR_KEY_COUNT_CHANGED')
                for sample, (a, b) in enumerate(zip(before[name],actual[name])):
                    expected = output[name][sample] if name in output else list(a.rotation.to_tuple())
                    if (a.translation-b.translation).length()>0.0001 or (a.scale3d-b.scale3d).length()>0.0001 or qmath.distance(expected,list(b.rotation.to_tuple()))>0.01:
                        raise RuntimeError('PLANAR_READBACK_FAILED: '+name)
            repeated, error = solve(actual, animation.get_editor_property('skeleton'), component, settings)
            if error['maximumInputRootAxialTwistDegrees'] > 0.01:
                raise RuntimeError('PLANAR_ROOT_TWIST_READBACK_FAILED')
            if error['maximumInputRootCurlDegrees'] > 0.01 or error['maximumInputRootSpreadDegrees'] > settings['root_spread_degrees'] + 0.01:
                raise RuntimeError('PLANAR_ROOT_RANGE_READBACK_FAILED')
            repeat_error = max(qmath.distance(q, output[name][sample]) for name, values in repeated.items() for sample, q in enumerate(values))
            if repeat_error>0.05:
                raise RuntimeError('PLANAR_REPEAT_CHANGED: '+str(repeat_error))
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation,False):
                raise RuntimeError('PLANAR_SAVE_FAILED')
            reports[index].update(saved=True,readback=True,metadataPreserved=True,signature=_signature(actual),repeatErrorDegrees=repeat_error,readbackRootAxialTwistDegrees=error['maximumInputRootAxialTwistDegrees'],readbackRootCurlDegrees=error['maximumInputRootCurlDegrees'],readbackRootSpreadDegrees=error['maximumInputRootSpreadDegrees'])
    return json.dumps({'action':action,'planSignature':plan,'assets':reports,'constraint':'四指统一前向 中末节只向掌心弯曲 无侧弯无轴向扭转','thumbModified':False},ensure_ascii=False)
