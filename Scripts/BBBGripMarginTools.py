import json
import math
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _key, _pose, _set_pose, _transform, _read_transform


def _from_values(values):
    """/** @param values 十分量变换 @return 引擎变换 */"""
    return _transform({'position': values[:3], 'rotation': values[3:7], 'scale': values[7:10]})


def _context(recipe):
    """/** @param recipe 制作参数 @return 共享求解数据 */"""
    mesh = _asset(recipe['mesh'], unreal.SkeletalMesh)
    rig = _asset(recipe['rig'], unreal.ControlRigBlueprint).create_control_rig()
    rig.request_init()
    rig.execute_event('Forwards Solve')
    reference = _pose(_asset(recipe['extra_animations'][0], unreal.AnimSequence), mesh, 0.0)
    spine = unreal.AnimPoseExtensions.get_bone_pose(reference, 'spine_03', unreal.AnimPoseSpaces.WORLD)
    offset = spine.rotation.inversed().rotate_vector(unreal.Vector(*recipe['retract_component_cm']))
    weapons = []
    for row in recipe['weapons']:
        data = json.loads((Path(unreal.Paths.project_dir()) / row['recipe']).read_text(encoding='utf-8-sig'))
        component = data['solution']['component_pose']
        fire_path = Path(unreal.Paths.project_dir()) / row['recipe'].replace('_HandGrip_Authoring', '_FireGrip_Authoring')
        fire = json.loads(fire_path.read_text(encoding='utf-8-sig'))
        fire_component = fire['solution']['component_pose']
        weapons.append({'name': row['name'], 'data': data,
                        'contact': _from_values(component['hand_l']).make_relative(_from_values(component['hand_r'])),
                        'fire': {'name': row['name'], 'data': fire,
                                 'contact': _from_values(fire_component['hand_l']).make_relative(_from_values(fire_component['hand_r']))}})
    return {'mesh': mesh, 'rig': rig, 'offset': offset, 'weapons': weapons}


def _solve(context, pose, weapon=None, shifted=True, perturb_cm=0.0, local_overrides=None):
    """/** @param context 求解环境 @param pose 原姿势 @param weapon 专属握姿 @param shifted 是否收枪 @return 源控制与求解后姿势 */"""
    rig = context['rig']
    hierarchy = rig.get_hierarchy()
    _set_pose(rig, pose)
    for name, value in (local_overrides or {}).items():
        hierarchy.set_local_transform(_key(name), value)
    names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(pose)]
    if weapon is not None:
        for name, values in weapon['data']['solution']['local_pose'].items():
            if any(name.startswith(prefix) for prefix in ('thumb_', 'index_', 'middle_', 'ring_', 'pinky_')):
                hierarchy.set_local_transform(_key(name), _from_values(values))
    source = {name: hierarchy.get_global_transform(_key(name)) for name in names}
    values = {}
    for side in ('r', 'l'):
        values['clavicle_' + side + '_ctrl'] = source['clavicle_' + side]
        values['elbow_' + side + '_pv_ctrl'] = source['lowerarm_' + side]
        values['hand_' + side + '_ik_ctrl'] = source['hand_' + side]
    right = _transform(_read_transform(source['hand_r']))
    if shifted:
        right.translation = right.translation + source['spine_03'].rotation.rotate_vector(context['offset'])
    if perturb_cm:
        direction = source['hand_l'].translation - source['upperarm_l'].translation
        right.translation = right.translation + direction / direction.length() * perturb_cm
    values['hand_r_ik_ctrl'] = right
    def execute():
        for name, value in source.items():
            key = _key('source_' + name, 'CONTROL')
            if hierarchy.contains(key):
                hierarchy.set_global_transform(key, value)
        for name, value in values.items():
            hierarchy.set_global_transform(_key(name, 'CONTROL'), value)
        if not rig.execute_event('Forwards Solve'):
            raise RuntimeError('GRIP_MARGIN_SOLVE_FAILED')
    execute()
    grip = weapon
    if grip is None:
        grip = next(row for row in context['weapons'] if row['name'] == 'FAL')
    if weapon is not None:
        forearm = hierarchy.get_global_transform(_key('lowerarm_r')).rotation
        delta = unreal.Quat(*weapon['data']['calibration']['right_wrist_delta'])
        right.rotation = forearm * delta * forearm.inversed() * right.rotation
    values['hand_r_ik_ctrl'] = right
    values['hand_l_ik_ctrl'] = unreal.MathLibrary.compose_transforms(grip['contact'], right)
    execute()
    solved = {name: hierarchy.get_global_transform(_key(name)) for name in names}
    local = {name: hierarchy.get_local_transform(_key(name)) for name in names}
    metrics = {}
    for side in ('l', 'r'):
        shoulder = solved['upperarm_' + side].translation
        elbow = solved['lowerarm_' + side].translation
        wrist = solved['hand_' + side].translation
        first = (elbow - shoulder).length()
        second = (wrist - elbow).length()
        distance = (wrist - shoulder).length()
        cosine = (distance * distance - first * first - second * second) / (2 * first * second)
        metrics[side] = {'ratio': distance / (first + second), 'bend_degrees': math.degrees(math.acos(max(-1, min(1, cosine)))),
                         'target_error_cm': (wrist - values['hand_' + side + '_ik_ctrl'].translation).length()}
    return {'source': source, 'controls': values, 'solved': solved, 'local': local, 'metrics': metrics}


def _preview(recipe, context, index, write_paths):
    """/** @param recipe 制作参数 @param context 求解环境 @param index 武器索引 @param write_paths 写入范围 @return 序列和逐姿势指标 */"""
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring
    weapon = context['weapons'][index]
    data = weapon['data']
    sequence_path = data['weapon_root'] + '/Animation/work/LS_GripMargin'
    if set(write_paths) != {sequence_path, recipe['rig']}:
        raise RuntimeError('GRIP_MARGIN_PREVIEW_SCOPE')
    first = _pose(_asset(recipe['extra_animations'][0], unreal.AnimSequence), context['mesh'], 0.0)
    names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(first)]
    blueprint = _asset(recipe['rig'], unreal.ControlRigBlueprint)
    if not blueprint.hierarchy.contains(_key('source_root', 'CONTROL')):
        authoring.add_pose_controls(recipe['rig'], names, 'ApplyShoulder_r')
        context = _context(recipe)
    if not unreal.EditorAssetLibrary.does_asset_exist(sequence_path):
        authoring.create_control_rig_sequence(sequence_path, recipe['mesh'], 10.0, 30)
        spawn = _from_values(data['calibration']['spawn_offset'])
        authoring.create_sequence_attachment(sequence_path, weapon['name'], data['weapon_mesh'], data['attachment_socket'],
                                             json.dumps(_read_transform(spawn)), json.dumps([[0, 301]]), '')
    sequence = _asset(sequence_path, unreal.LevelSequence)
    sequence.set_playback_end(301)
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                section.set_range(0, 301)
                if isinstance(track, unreal.MovieSceneSpawnTrack):
                    channel = section.get_all_channels()[0]
                    for existing in list(channel.get_keys()):
                        channel.remove_key(existing)
                    channel.set_default(True)
                    channel.add_key(unreal.FrameNumber(value=0), True)
                    channel.add_key(unreal.FrameNumber(value=301), False)
    keys = []
    metrics = []
    sources = [recipe['extra_animations'][0], recipe['extra_animations'][3], recipe['extra_animations'][4]]
    for i, source_path in enumerate(sources):
        pose = _pose(_asset(source_path, unreal.AnimSequence), context['mesh'], 0.0)
        for variant in range(2):
            frame = i * 60 + variant * 30
            baked = source_path in recipe.get('results', {})
            result = _solve(context, pose, weapon, bool(variant) and not baked, 5.0 if baked and variant else 0.0)
            values = {'source_' + name: value for name, value in result['source'].items()}
            values.update(result['controls'])
            for key_frame in (frame, min(frame + 29, 150)):
                keys.extend({'frame': key_frame, 'control': name, 'value': _read_transform(value)} for name, value in values.items())
            metrics.append({'frame': frame, 'source': source_path, 'retracted': baked or bool(variant),
                            'perturb_cm': 5.0 if baked and variant else 0.0, **result['metrics']})
    if len(recipe.get('results', {})) == len(recipe['animations']):
        recoil_recipe = json.loads((Path(unreal.Paths.project_dir()) / 'Content/_Project/Characters/BBBC_UA/Source/Animation/WeaponRecoil_BodyPose_Authoring.json.source').read_text(encoding='utf-8-sig'))
        jobs = [job for job in recoil_recipe['bake_jobs'] if job['output'].startswith(data['weapon_root'] + '/')]
        if len(jobs) != 1:
            raise RuntimeError('GRIP_MARGIN_RECOIL_NOT_UNIQUE')
        recoil = _asset(jobs[0]['output'], unreal.AnimSequence)
        reference = recoil.get_editor_property('ref_pose_seq')
        if recoil.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE or not reference:
            raise RuntimeError('GRIP_MARGIN_RECOIL_REFERENCE')
        tracks = {str(name): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(recoil, name)) for name in recoil.data_model_interface.get_bone_track_names()}
        reference_tracks = {name: unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(reference, name)[recoil.get_editor_property('ref_frame_index')] for name in tracks}
        for stance, source_path in enumerate(sources[1:]):
            pose = _pose(_asset(source_path, unreal.AnimSequence), context['mesh'], 0.0)
            for sample in range(recoil.data_model_interface.get_number_of_keys()):
                overrides = {}
                for name, rows in tracks.items():
                    current = unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.LOCAL)
                    base = reference_tracks[name]
                    delta = rows[sample]
                    value = _transform(_read_transform(current))
                    value.rotation = delta.rotation * base.rotation.inversed() * current.rotation
                    value.translation = current.translation + delta.translation - base.translation
                    value.scale3d = unreal.Vector(*[a * b / c for a, b, c in zip(current.scale3d.to_tuple(), delta.scale3d.to_tuple(), base.scale3d.to_tuple())])
                    overrides[name] = value
                result = _solve(context, pose, weapon['fire'], False, local_overrides=overrides)
                frame = 180 + stance * 30 + sample
                values = {'source_' + name: value for name, value in result['source'].items()}
                values.update(result['controls'])
                keys.extend({'frame': frame, 'control': name, 'value': _read_transform(value)} for name, value in values.items())
                metrics.append({'frame': frame, 'source': source_path, 'recoil': jobs[0]['output'], 'recoil_frame': sample, **result['metrics']})
        neutral = _pose(_asset(sources[0], unreal.AnimSequence), context['mesh'], 0.0)
        raised = _pose(_asset(sources[1], unreal.AnimSequence), context['mesh'], 0.0)
        for sample in range(31):
            overrides = {name: unreal.AnimPoseExtensions.get_bone_pose(neutral, name, unreal.AnimPoseSpaces.LOCAL).lerp(unreal.AnimPoseExtensions.get_bone_pose(raised, name, unreal.AnimPoseSpaces.LOCAL), sample / 30.0) for name in names}
            result = _solve(context, neutral, weapon, False, local_overrides=overrides)
            frame = 240 + sample
            values = {'source_' + name: value for name, value in result['source'].items()}
            values.update(result['controls'])
            keys.extend({'frame': frame, 'control': name, 'value': _read_transform(value)} for name, value in values.items())
            metrics.append({'frame': frame, 'aim_blend': sample / 30.0, **result['metrics']})
        for row in metrics:
            if row['l']['ratio'] > 0.90 or row['l']['bend_degrees'] < 35 or max(row[side]['target_error_cm'] for side in ('l', 'r')) > 0.02:
                raise RuntimeError('GRIP_MARGIN_FINAL_PREVIEW_FAILED: ' + weapon['name'] + ' ' + json.dumps(row))
    authoring.configure_sequence_rig(sequence_path, recipe['rig'], json.dumps(keys), False, recipe['mesh'])
    return {'sequence': sequence_path, 'metrics': metrics}


def _weapon_margins(context, solved):
    """/** @param context 正式武器握点 @param solved 共同身体姿势 @return 各武器最坏伸展余量 */"""
    bones = solved['solved']
    shoulder = bones['upperarm_l'].translation
    elbow = bones['lowerarm_l'].translation
    wrist = bones['hand_l'].translation
    arm_length = (elbow - shoulder).length() + (wrist - elbow).length()
    result = []
    for weapon in [variant for row in context['weapons'] for variant in (row, row['fire'])]:
        right = _transform(_read_transform(bones['hand_r']))
        forearm = bones['lowerarm_r'].rotation
        delta = unreal.Quat(*weapon['data']['calibration']['right_wrist_delta'])
        right.rotation = forearm * delta * forearm.inversed() * right.rotation
        left = unreal.MathLibrary.compose_transforms(weapon['contact'], right)
        distance = (left.translation - shoulder).length()
        result.append({'weapon': weapon['name'], 'ratio': distance / arm_length,
                       'role': weapon['data'].get('grip_role', 'hold'),
                       'reserve_cm': arm_length - distance, 'perturbed_ratio': (distance + 5.0) / arm_length})
    return result


def _audit_range(recipe, context, start):
    """/** @param recipe 正式动画清单 @param context 求解环境 @param start 起始索引 @return 每段五点和固定扰动的预检查 */"""
    rows = []
    for animation_path in recipe['animations'][start:start + 30]:
        animation = _asset(animation_path, unreal.AnimSequence)
        worst = {'ratio': 0}
        right_min = 180.0
        for alpha in (0, 0.25, 0.5, 0.75, 1):
            pose = _pose(animation, context['mesh'], animation.get_play_length() * alpha)
            solved = _solve(context, pose, shifted=animation_path not in recipe.get('results', {}))
            right_min = min(right_min, solved['metrics']['r']['bend_degrees'])
            for row in _weapon_margins(context, solved):
                if row['ratio'] > worst['ratio']:
                    worst = dict(row, time=animation.get_play_length() * alpha)
        rows.append({'animation': animation_path, 'worst': worst, 'minimum_right_bend': right_min})
    return rows


def _bake_range(path, recipe, context, start, write_paths):
    """/** @param path 制作源 @param recipe 动画清单 @param context 共同求解器 @param start 起始索引 @param write_paths 明确写入范围 @return 全帧回读与非手臂轨道保护证据 */"""
    from BBBAnimationTrajectoryTools import _track_metadata
    from BBBDualArmBodyPoseTools import _digest_tracks
    if not 0 <= start < len(recipe['animations']):
        raise RuntimeError('GRIP_MARGIN_BAKE_INDEX')
    requested = recipe['animations'][start:start + 10]
    if set(requested) != set(write_paths):
        raise RuntimeError('GRIP_MARGIN_BAKE_SCOPE')
    results = recipe.setdefault('results', {})
    changed = []
    allowed = {'upperarm_l', 'lowerarm_l', 'hand_l', 'upperarm_r', 'lowerarm_r', 'hand_r', 'ik_hand_l', 'ik_hand_r', 'ik_hand_gun'}
    for animation_path in requested:
        animation = _asset(animation_path, unreal.AnimSequence)
        if animation_path in results:
            if _digest_tracks(animation) != results[animation_path]['output_digest']:
                raise RuntimeError('GRIP_MARGIN_CHANGED_AFTER_BAKE: ' + animation_path)
            changed.append(dict(results[animation_path], skipped=True))
            continue
        require_asset_write([animation])
        model = animation.data_model_interface
        count = model.get_number_of_keys()
        rate = model.get_frame_rate()
        metadata = _track_metadata(animation)
        tracks = {str(name): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)) for name in model.get_bone_track_names()}
        prepared = {name: [] for name in tracks if name.lower() in allowed}
        original_digest = _digest_tracks(animation)
        worst = {'ratio': 0}
        for frame in range(count):
            time = min(animation.get_play_length(), frame * rate.denominator / rate.numerator)
            solved = _solve(context, _pose(animation, context['mesh'], time))
            if max(row['target_error_cm'] for row in solved['metrics'].values()) > 0.02:
                raise RuntimeError('GRIP_MARGIN_UNREACHABLE: %s frame %d' % (animation_path, frame))
            for row in _weapon_margins(context, solved):
                if row['ratio'] > worst['ratio']:
                    worst = dict(row, frame=frame)
            if worst['perturbed_ratio'] > 0.90:
                raise RuntimeError('GRIP_MARGIN_RESERVE_FAILED: ' + animation_path + ' ' + json.dumps(worst))
            for name in prepared:
                value = solved['local'][name]
                if not name.startswith('ik_'):
                    value.translation = tracks[name][frame].translation
                value.scale3d = tracks[name][frame].scale3d
                prepared[name].append(value)
        animation.controller.open_bracket('Bake Rifle grip reach reserve', False)
        try:
            for name, values in prepared.items():
                if not animation.controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                    raise RuntimeError('GRIP_MARGIN_WRITE_FAILED: ' + name)
        finally:
            animation.controller.close_bracket(False)
        if _track_metadata(animation) != metadata:
            raise RuntimeError('GRIP_MARGIN_METADATA_CHANGED')
        for name, original in tracks.items():
            actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
            expected = prepared.get(name, original)
            if len(actual) != len(expected):
                raise RuntimeError('GRIP_MARGIN_READBACK_COUNT')
            for value, target in zip(actual, expected):
                if (value.translation - target.translation).length() > 0.001 or (value.scale3d - target.scale3d).length() > 0.001 or abs((value.rotation * target.rotation.inversed()).w) < 0.99999:
                    raise RuntimeError('GRIP_MARGIN_READBACK: ' + name)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('GRIP_MARGIN_SAVE_FAILED')
        result = {'animation': animation_path, 'frames': count, 'worst': worst, 'input_digest': original_digest,
                  'output_digest': _digest_tracks(animation), 'other_tracks_and_metadata_preserved': True}
        results[animation_path] = result
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        changed.append(result)
    return changed


def process(recipe_path, action, write_paths, job_index):
    """/** @param recipe_path 制作参数 @param action 明确操作 @param write_paths 写入范围 @param job_index 项目索引 @return 保存与回读证据 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    if path.parent != project / 'Content/_Project/Characters/BBBC_UA/Source/Animation':
        raise RuntimeError('GRIP_MARGIN_RECIPE_SCOPE')
    recipe = json.loads(path.read_text(encoding='utf-8-sig'))
    if recipe.get('format') != 'BBBGripMargin' or recipe.get('schema') != 1:
        raise RuntimeError('GRIP_MARGIN_RECIPE_FORMAT')
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('GRIP_MARGIN_EDITOR_REQUIRED')
    if action == 'prepare_action':
        return _preview(recipe, _context(recipe), job_index, write_paths)
    if action == 'finalize':
        return _render_sequence(recipe, job_index)
    if action == 'bake':
        return _bake_range(path, recipe, _context(recipe), job_index, write_paths)
    if action == 'inspect':
        if job_index == -2:
            import BBBGripCaptureTools
            return list(BBBGripCaptureTools._CAPTURES.values())[-1]
        if len(write_paths) == 1 and write_paths[0].endswith('/LS_GripMargin'):
            return _verify_sequence(recipe, write_paths[0])
        if job_index >= 0:
            return _audit_range(recipe, _context(recipe), job_index)
        reports = []
        paths = set()
        for entry in unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path(recipe['database_root'], True):
            if str(entry.asset_class_path.asset_name) != 'PoseSearchDatabase':
                continue
            database = entry.get_asset()
            report = json.loads(unreal.BBBMotionMatchingEditorLibrary.inspect_database(database, False))
            if not report.get('success'):
                raise RuntimeError('GRIP_MARGIN_DATABASE: ' + json.dumps(report))
            paths.update(value.split('.')[0] for value in report['animationPaths'])
            reports.append({'database': database.get_path_name(), 'count': report['animationCount']})
        recipe['animations'] = sorted(paths | set(recipe['extra_animations']))
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return {'databases': reports, 'animations': recipe['animations']}
    if action == 'capture':
        if job_index >= 0:
            return _sync_weapon_grips(recipe, _context(recipe), job_index, write_paths)
        blueprint = _asset(recipe['template_rig'], unreal.ControlRigBlueprint)
        graph = blueprint.get_controller().get_graph()
        nodes = []
        for node in graph.get_nodes():
            name = str(node.get_name())
            if name == 'BasePose':
                continue
            defaults = {}
            for pin in node.get_pins():
                if str(pin.get_name()) in ('ExecutePin', 'CachedIndex'):
                    continue
                defaults[str(pin.get_name())] = pin.get_default_value()
            nodes.append({'name': name, 'struct': node.get_script_struct().get_path_name(), 'defaults': defaults})
        links = []
        for link in graph.get_links():
            source = link.get_source_pin().get_pin_path()
            target = link.get_target_pin().get_pin_path()
            if source.startswith('BasePose.') or target.startswith('BasePose.'):
                continue
            links.append([source, target])
        links.append(['Forward.ExecutePin', 'ApplyShoulder_r.ExecutePin'])
        return {'nodes': nodes, 'links': links}
    raise RuntimeError('GRIP_MARGIN_UNKNOWN_ACTION')


def _verify_sequence(recipe, sequence_path):
    """/** @param recipe 正式网格 @param sequence_path 实际关卡序列 @return 官方导出后逐帧关节余量与翻转检查 */"""
    import uuid
    from BBBManualActionNative import _export
    sequence = _asset(sequence_path, unreal.LevelSequence)
    mesh = _asset(recipe['mesh'], unreal.SkeletalMesh)
    source = _asset(recipe['extra_animations'][0], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBGripMarginVerify_' + uuid.uuid4().hex)
    try:
        animation = _export(sequence, source, mesh, scope, 'Evaluated', duplicate=False)
        count = animation.data_model_interface.get_number_of_keys()
        rate = animation.data_model_interface.get_frame_rate()
        times = [min(animation.get_play_length(), frame * rate.denominator / rate.numerator) for frame in range(count)]
        names = ['spine_03', 'upperarm_l', 'lowerarm_l', 'hand_l', 'upperarm_r', 'lowerarm_r', 'hand_r']
        samples = json.loads(unreal.BBBBlueprintEditorLibrary.sample_animation_component_poses(animation, mesh, times, names))
        maximum_ratio = 0.0
        minimum_bend = 180.0
        maximum_plane_step = 0.0
        previous = None
        for frame, sample in enumerate(samples):
            bones = {name: _transform(value) for name, value in sample['bones'].items()}
            shoulder = bones['upperarm_l'].translation
            elbow = bones['lowerarm_l'].translation
            wrist = bones['hand_l'].translation
            first = (elbow - shoulder).length()
            second = (wrist - elbow).length()
            distance = (wrist - shoulder).length()
            ratio = distance / (first + second)
            bend = math.degrees(math.acos(max(-1, min(1, (distance * distance - first * first - second * second) / (2 * first * second)))))
            maximum_ratio = max(maximum_ratio, ratio)
            minimum_bend = min(minimum_bend, bend)
            plane = unreal.MathLibrary.cross_vector_vector(elbow - shoulder, wrist - elbow)
            plane = bones['spine_03'].rotation.inversed().rotate_vector(plane / plane.length())
            if previous is not None:
                cosine = sum(a * b for a, b in zip(plane.to_tuple(), previous.to_tuple()))
                maximum_plane_step = max(maximum_plane_step, math.degrees(math.acos(max(-1, min(1, cosine)))))
            previous = plane
            if ratio > 0.901 or bend < 35:
                raise RuntimeError('GRIP_MARGIN_SEQUENCE_FRAME_FAILED: %s frame %d ratio %f bend %f' % (sequence_path, frame, ratio, bend))
        if maximum_plane_step > 45:
            raise RuntimeError('GRIP_MARGIN_SEQUENCE_ELBOW_DISCONTINUITY: ' + str(maximum_plane_step))
        return {'sequence': sequence_path, 'frames': count, 'official_sequencer_export': True,
                'maximum_reach_ratio': maximum_ratio, 'minimum_elbow_bend': minimum_bend,
                'maximum_elbow_plane_step_degrees': maximum_plane_step, 'temporary_package_saved': False}
    finally:
        unreal.purge_object_references(scope, True)


def _sync_weapon_grips(recipe, context, index, write_paths):
    """/** @param recipe 正式身体参考 @param context 求解环境 @param index 武器索引 @param write_paths 专属握姿范围 @return 原握点及手指保持证据 */"""
    from BBBDualArmBodyPoseTools import _sync_grip, _digest_tracks
    from BBBAnimationTrajectoryTools import _track_metadata
    from BBBGripFireAuthoring import hold_signature
    weapon = context['weapons'][index]
    variants = [weapon, weapon['fire']]
    expected = {variant['data'][key] for variant in variants for key in ('animation', 'sequence', 'rig')}
    if set(write_paths) != expected:
        raise RuntimeError('GRIP_MARGIN_GRIP_SCOPE')
    pose = _pose(_asset(recipe['extra_animations'][0], unreal.AnimSequence), context['mesh'], 0.0)
    allowed = {'upperarm_l', 'lowerarm_l', 'hand_l', 'upperarm_r', 'lowerarm_r', 'hand_r', 'ik_hand_l', 'ik_hand_r', 'ik_hand_gun'}
    results = []
    project = Path(unreal.Paths.project_dir()).resolve()
    for variant in variants:
        data = variant['data']
        source_path = project / recipe['weapons'][index]['recipe']
        if data.get('grip_role') == 'fire':
            source_path = project / str(source_path.relative_to(project)).replace('_HandGrip_Authoring', '_FireGrip_Authoring')
        animation = _asset(data['animation'], unreal.AnimSequence)
        metadata = _track_metadata(animation)
        tracks = {str(name): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)) for name in animation.data_model_interface.get_bone_track_names()}
        solved = _solve(context, pose, variant, False)
        prepared = {}
        for name, values in tracks.items():
            if name.lower() not in allowed:
                continue
            rows = []
            for original in values:
                value = _transform(_read_transform(solved['local'][name]))
                if not name.startswith('ik_'):
                    value.translation = original.translation
                value.scale3d = original.scale3d
                rows.append(value)
            prepared[name] = rows
        require_asset_write([animation])
        animation.controller.open_bracket('Synchronize Rifle grip body reference', False)
        try:
            for name, values in prepared.items():
                if not animation.controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                    raise RuntimeError('GRIP_MARGIN_GRIP_WRITE')
        finally:
            animation.controller.close_bracket(False)
        if _track_metadata(animation) != metadata:
            raise RuntimeError('GRIP_MARGIN_GRIP_METADATA')
        for name, old in tracks.items():
            actual = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name)
            for left, right in zip(actual, prepared.get(name, old)):
                if (left.translation - right.translation).length() > 0.001 or abs((left.rotation * right.rotation.inversed()).w) < 0.99999:
                    raise RuntimeError('GRIP_MARGIN_GRIP_READBACK: ' + name)
        if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
            raise RuntimeError('GRIP_MARGIN_GRIP_SAVE')
        data['reference_animation'] = recipe['extra_animations'][0]
        if data.get('grip_role') == 'fire':
            hold = json.loads((project / data['hold_recipe']).read_text(encoding='utf-8-sig'))
            data['hold_signature'] = hold_signature(hold, project)
        _sync_grip({'sequence': data['weapon_root'] + '/Animation/work/LS_GripMargin'}, data, source_path)
        results.append({'animation': data['animation'], 'metrics': solved['metrics'], 'fingers_and_contacts_preserved': True,
                        'output_digest': _digest_tracks(animation)})
    return results



def _render_sequence(recipe, index):
    """/** @param recipe 序列制作参数 @param index 武器索引 @return 跨编辑器帧渲染活动 */"""
    import uuid
    import BBBGripCaptureTools
    from BBBMcpCapabilities import register_activity
    context = _context(recipe)
    weapon = context['weapons'][index]
    sequence_path = weapon['data']['weapon_root'] + '/Animation/work/LS_GripMargin'
    sequence = _asset(sequence_path, unreal.LevelSequence)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(60)
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    identifier = uuid.uuid4().hex
    record = {'status': 'pending', 'sequence': sequence_path, 'images': [], 'temporaryActorsDestroyed': False}
    BBBGripCaptureTools._CAPTURES[identifier] = record
    directory = Path(unreal.Paths.project_saved_dir()) / 'temp/RifleGripMargin'
    directory.mkdir(parents=True, exist_ok=True)
    def render():
        player, sequence_actor = unreal.LevelSequencePlayer.create_level_sequence_player(world, sequence, unreal.MovieSceneSequencePlaybackSettings())
        camera = actors.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(), transient=True)
        light = actors.spawn_actor_from_class(unreal.PointLight, unreal.Vector(), transient=True)
        try:
            light_component = light.get_component_by_class(unreal.PointLightComponent)
            light_component.set_intensity(3000)
            light_component.set_attenuation_radius(2000)
            light_component.set_cast_shadows(False)
            target = unreal.RenderingLibrary.create_render_target2d(world, 800, 800, unreal.TextureRenderTargetFormat.RTF_RGBA8)
            capture = camera.capture_component2d
            capture.set_editor_property('texture_target', target)
            capture.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
            capture.set_editor_property('capture_every_frame', False)
            capture.set_editor_property('capture_on_movement', False)
            capture.set_editor_property('always_persist_rendering_state', True)
            capture.set_editor_property('primitive_render_mode', unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
            capture.set_editor_property('fov_angle', 45)
            settings = unreal.PostProcessSettings()
            for name in ('auto_exposure_method', 'auto_exposure_apply_physical_camera_exposure', 'auto_exposure_bias', 'dynamic_global_illumination_method', 'reflection_method', 'motion_blur_amount', 'ambient_cubemap_intensity'):
                settings.set_editor_property('override_' + name, True)
            settings.auto_exposure_method = unreal.AutoExposureMethod.AEM_MANUAL
            settings.auto_exposure_apply_physical_camera_exposure = False
            settings.auto_exposure_bias = 1
            settings.set_editor_property('override_scene_color_tint', True)
            settings.scene_color_tint = unreal.LinearColor(0.015625, 0.015625, 0.015625, 1)
            settings.dynamic_global_illumination_method = unreal.DynamicGlobalIlluminationMethod.NONE
            settings.reflection_method = unreal.ReflectionMethod.NONE
            settings.motion_blur_amount = 0
            settings.ambient_cubemap = unreal.load_asset('/Engine/EngineResources/GrayLightTextureCube')
            settings.ambient_cubemap_intensity = 1
            capture.set_editor_property('post_process_settings', settings)
            capture.set_editor_property('post_process_blend_weight', 1)
            for frame in (60, 90):
                params = unreal.MovieSceneSequencePlaybackParams()
                params.time = frame / 30.0
                params.position_type = unreal.MovieScenePositionType.TIME
                params.update_method = unreal.UpdatePositionMethod.PLAY
                player.set_playback_position(params)
                visible = []
                character = None
                for binding in sequence.get_bindings():
                    binding_id = unreal.MovieSceneObjectBindingID()
                    binding_id.set_editor_property('guid', binding.get_id())
                    for bound in player.get_bound_objects(binding_id):
                        if isinstance(bound, unreal.SkeletalMeshActor):
                            visible.append(bound)
                            if bound.skeletal_mesh_component.get_skeletal_mesh_asset() == context['mesh']:
                                character = bound.skeletal_mesh_component
                if character is None:
                    raise RuntimeError('GRIP_MARGIN_SEQUENCE_CHARACTER_MISSING')
                capture.clear_show_only_components()
                for visible_actor in visible:
                    capture.show_only_actor_components(visible_actor)
                for view, offset in [('front', [30, 140, 25]), ('top', [20, 50, 150]), ('right', [-120, 70, 35])]:
                    center = character.get_socket_location('spine_03') + unreal.Vector(0, 15, 0)
                    location = center + unreal.Vector(*offset)
                    camera.set_actor_location(location, False, True)
                    camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, center), True)
                    light.set_actor_location(location, False, True)
                    for tick in range(20):
                        player.set_playback_position(params)
                        capture.capture_scene()
                        yield
                    name = weapon['name'] + '_' + str(frame) + '_' + view + '_' + identifier[:6] + '.png'
                    unreal.RenderingLibrary.export_render_target(world, target, str(directory), name)
                    record['images'].append(str(directory / name))
                    record.setdefault('poses', {})[str(frame)] = {bone: _read_transform(character.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_COMPONENT)) for bone in ('upperarm_l', 'lowerarm_l', 'hand_l', 'hand_r')}
                    yield
        finally:
            player.stop()
            for actor in (light, camera, sequence_actor):
                actors.destroy_actor(actor)
            record['temporaryActorsDestroyed'] = True
    iterator = render()
    handle = None
    def advance(delta_seconds):
        """/** @param delta_seconds 编辑器帧间隔 @return 渲染活动进度 */"""
        try:
            next(iterator)
        except StopIteration:
            record['status'] = 'completed'
            unreal.unregister_slate_post_tick_callback(handle)
        except Exception as error:
            record['status'] = 'failed'
            record['error'] = str(error)
            iterator.close()
            unreal.unregister_slate_post_tick_callback(handle)
    register_activity('grip_margin_render:' + identifier, lambda: dict(record))
    handle = unreal.register_slate_post_tick_callback(advance)
    return {'capture_id': identifier, **record}
