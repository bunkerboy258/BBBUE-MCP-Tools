import hashlib
import json

import unreal

import BBBFingerAnimationMath as geometry


def _asset(path):
    """/** @param path 明确动画路径 @return 绝对非加法序列 */"""
    value = unreal.load_asset(path)
    if not isinstance(value, unreal.AnimSequence) or value.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE:
        raise ValueError('FINGER_ABSOLUTE_SEQUENCE_REQUIRED: ' + path)
    return value


def _tracks(animation):
    """/** @param animation 动画 @return 实际全部局部骨轨 */"""
    return {str(name): list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
            for name in animation.data_model_interface.get_bone_track_names()}


def _signature(tracks):
    """/** @param tracks 实际骨轨 @return 全精度变换摘要 */"""
    return hashlib.sha256(repr({name: [list(t.translation.to_tuple()) + list(t.rotation.to_tuple()) + list(t.scale3d.to_tuple())
                                      for t in values] for name, values in sorted(tracks.items())}).encode()).hexdigest()


def calibrate(config):
    """/** @param config 明确中性与卷曲参考及数值限制 @return 可复用骨架关节配置 不修改资产 */"""
    neutral = _asset(config['neutral_animation'])
    curled = _asset(config['curled_animation'])
    skeleton = neutral.get_editor_property('skeleton')
    if curled.get_editor_property('skeleton') != skeleton:
        raise ValueError('FINGER_CALIBRATION_SKELETON_MISMATCH')
    rest, grip = _tracks(neutral), _tracks(curled)
    overrides = config.get('overrides', {})
    rules, unresolved = {}, []
    for side in ('l', 'r'):
        for digit in ('index', 'middle', 'ring', 'pinky'):
            for segment in ('01', '02', '03'):
                name = digit + '_' + segment + '_' + side
                if name in overrides:
                    rules[name] = overrides[name]
                    continue
                if segment == '01':
                    unresolved.append({'bone': name, 'reason': '显式提供掌面法线在参考指根坐标中的展开轴与允许范围'})
                    continue
                if name not in rest or name not in grip:
                    unresolved.append({'bone': name, 'reason': '参考缺少骨轨'})
                    continue
                a = list(rest[name][0].rotation.to_tuple())
                delta = geometry.unit(geometry.multiply(geometry.inverse(a), list(grip[name][0].rotation.to_tuple())))
                if delta[3] < 0:
                    delta = [-v for v in delta]
                angle = geometry.distance(delta, [0, 0, 0, 1])
                if angle < config['minimum_calibration_degrees']:
                    unresolved.append({'bone': name, 'reason': '参考屈曲差不足 需要显式校准轴'})
                    continue
                rules[name] = {'kind': 'hinge', 'neutral': a, 'axis': geometry.unit(delta[:3]),
                               'limits_degrees': config['hinge_limits_degrees'], 'tolerance_degrees': config['tolerance_degrees']}
    return {'skeleton': skeleton.get_path_name(), 'rules': rules, 'unresolved': unresolved,
            'thumb': '拇指仅使用显式独立校准 不继承四指规则', 'referenceReviewRequired': True}


def run(asset_paths, profile_json, action):
    """/** @param asset_paths 明确序列数组 @param profile_json 唯一校准或执行配置 @param action 校准检查或修复 @return 原生骨轨核验和未修改元数据证据 */"""
    import importlib
    from BBBAnimationTrajectoryTools import _track_metadata
    from BBBAssetWritePolicy import require_asset_write

    importlib.reload(geometry)
    config = json.loads(profile_json)
    if action == 'calibrate':
        return json.dumps(calibrate(config), ensure_ascii=False)
    if action not in ('inspect', 'repair') or not asset_paths or len(asset_paths) > 128 or len(set(asset_paths)) != len(asset_paths):
        raise ValueError('FINGER_BATCH_INVALID')
    rules = config['rules']
    if not rules or any(name.split('_')[0] not in ('index', 'middle', 'ring', 'pinky', 'thumb') or name[-4:-2] not in ('01', '02', '03') or name[-1] not in ('l', 'r') for name in rules):
        raise ValueError('FINGER_RULE_BONES_INVALID')
    for rule in rules.values():
        geometry.process([], rule, set())
    if config.get('visual') and not 1 <= config['visual'].get('maximum_frames', 2) <= 4:
        raise ValueError('FINGER_VISUAL_FRAME_LIMIT')
    if action == 'repair' and not config.get('reference_reviewed'):
        raise ValueError('FINGER_REFERENCE_REVIEW_REQUIRED')
    if action == 'repair' and config.get('unresolved'):
        raise ValueError('FINGER_CALIBRATION_UNRESOLVED')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('FINGER_PIE_ACTIVE')
    prepared, reports = [], []
    for path in asset_paths:
        animation = _asset(path)
        if animation.get_editor_property('skeleton').get_path_name() != config['skeleton']:
            raise ValueError('FINGER_SKELETON_MISMATCH: ' + path)
        before = _tracks(animation)
        transform_curves = {str(n).casefold() for n in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_TRANSFORM)}
        if any(name.casefold() in transform_curves for name in rules):
            raise ValueError('FINGER_TRANSFORM_CURVE_REQUIRES_COMPOSED_POSE')
        count = animation.data_model_interface.get_number_of_keys()
        if count > 10000 or any(name not in before or len(before[name]) != count for name in rules):
            raise ValueError('FINGER_TRACK_COUNT_INVALID: ' + path)
        changes, problems, temporal = {}, [], []
        for name, rule in rules.items():
            excluded = set()
            for start, end in config.get('exceptions', {}).get(path, {}).get(name, []):
                if not 0 <= start <= end < count:
                    raise ValueError('FINGER_EXCEPTION_RANGE_INVALID')
                excluded.update(range(start, end + 1))
            rotations = [list(t.rotation.to_tuple()) for t in before[name]]
            values, errors = geometry.process(rotations, rule, excluded)
            peak_before = max((geometry.distance(a, b) for a, b in zip(rotations, rotations[1:])), default=0)
            peak_after = max((geometry.distance(a, b) for a, b in zip(values, values[1:])), default=0)
            temporal.append({'bone': name, 'peakStepBeforeDegrees': peak_before, 'peakStepAfterDegrees': peak_after})
            if action == 'repair' and peak_after > rule.get('maximum_step_degrees', 180) and peak_after > peak_before + rule['tolerance_degrees']:
                raise ValueError('FINGER_TEMPORAL_REVIEW_REQUIRED: ' + name)
            if errors:
                problems.append({'bone': name, 'samples': len(errors), 'worst': max(errors, key=lambda e: max(e['offAxisDegrees'], e['limitExcessDegrees'])),
                                 'ranges': _ranges([e['frame'] for e in errors])})
                changes[name] = values
        fingerprint = _signature(before)
        if action == 'repair' and config.get('expected_signatures', {}).get(path) != fingerprint:
            raise ValueError('FINGER_INSPECT_SIGNATURE_REQUIRED: ' + path)
        prepared.append((animation, before, changes, _track_metadata(animation)))
        reports.append({'asset': path, 'signature': fingerprint, 'problems': problems, 'changedBones': list(changes),
                        'temporal': temporal,
                        'scope': list(rules), 'thumbChecked': any(name.startswith('thumb_') for name in rules), 'visualAcceptance': 'pending'})
        if config.get('visual') and problems:
            reports[-1]['visual'] = _review(path, animation, before, changes, problems, config['visual'])
    if action == 'repair':
        targets = [animation for animation, before, changes, metadata in prepared if changes]
        dirty = {p.get_path_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
        if any(a.get_outermost().get_path_name() in dirty for a in targets):
            raise ValueError('FINGER_TARGET_DIRTY')
        if targets:
            require_asset_write(targets)
        for index, (animation, before, changes, metadata) in enumerate(prepared):
            if not changes:
                continue
            controller = animation.controller
            controller.open_bracket('修正明确指骨局部旋转', False)
            try:
                for name, rotations in changes.items():
                    values = before[name]
                    if not controller.set_bone_track_keys(name, [t.translation for t in values], [unreal.Quat(*q) for q in rotations], [t.scale3d for t in values], False):
                        raise RuntimeError('FINGER_WRITE_FAILED: ' + name)
            finally:
                controller.close_bracket(False)
            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('FINGER_METADATA_CHANGED')
            for name, originals in before.items():
                if len(actual[name]) != len(originals):
                    raise RuntimeError('FINGER_SAMPLE_COUNT_CHANGED')
                for frame, (old, new) in enumerate(zip(originals, actual[name])):
                    expected = changes[name][frame] if name in changes else list(old.rotation.to_tuple())
                    if (old.translation-new.translation).length() > 0.0001 or (old.scale3d-new.scale3d).length() > 0.0001 or geometry.distance(expected, list(new.rotation.to_tuple())) > 0.01:
                        raise RuntimeError('FINGER_READBACK_FAILED: ' + name)
                if name in changes:
                    unused, remaining = geometry.process([list(t.rotation.to_tuple()) for t in actual[name]], rules[name],
                                                        {f for start, end in config.get('exceptions', {}).get(reports[index]['asset'], {}).get(name, []) for f in range(start, end+1)})
                    if remaining:
                        raise RuntimeError('FINGER_REPAIR_REMAINS_INVALID: ' + name)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('FINGER_SAVE_FAILED')
            reports[index].update({'saved': True, 'readback': True, 'metadataPreserved': True, 'signature': _signature(actual)})
    return json.dumps({'action': action, 'assets': reports, 'sequenceLayersChecked': False,
                       'note': '只处理绝对动画骨轨 Sequencer与运行混合需单独检查'}, ensure_ascii=False)


def _ranges(frames):
    """/** @param frames 有序异常帧 @return 连续闭区间 */"""
    result = []
    for frame in frames:
        if result and result[-1][1] + 1 == frame:
            result[-1][1] = frame
            continue
        result.append([frame, frame])
    return result


def _review(path, animation, before, changes, problems, settings):
    """/** @param path 动画路径 @param animation 原生序列 @param before 原骨轨 @param changes 候选旋转 @param problems 异常帧 @param settings 明确网格与绘图解释器 @return 原生蒙皮的原始及候选三视图 不代替保存回读 */"""
    import subprocess
    import uuid
    from pathlib import Path
    from BBBGripGeometryTools import sample_surface

    python = Path(settings['python_executable'])
    if not python.is_file() or python.stem.lower() not in ('python', 'pythonw'):
        raise ValueError('FINGER_VISUAL_PYTHON_INVALID')
    name = 'FingerAnimation_' + uuid.uuid4().hex
    outputs = []
    rate = animation.data_model_interface.get_frame_rate()
    for frame in sorted({p['worst']['frame'] for p in problems})[:settings.get('maximum_frames', 2)]:
        for label, rotations in [('before', {}), ('candidate', {bone: values[frame] for bone, values in changes.items()})]:
            output = name + '/' + str(frame) + '_' + label
            sampled = json.loads(sample_surface(settings['mesh_path'], path, frame * rate.denominator / rate.numerator,
                                                ['hand_l', 'hand_r'], 0.5, [], output, json.dumps(rotations)))
            script = Path(__file__).with_name('BBBFingerAnimationReview.py')
            process = subprocess.run([str(python), '-B', str(script), sampled['report']], capture_output=True, text=True, encoding='utf-8', timeout=60)
            if process.returncode:
                raise RuntimeError('FINGER_VISUAL_FAILED: ' + process.stderr[-1500:])
            outputs.append({'frame': frame, 'kind': label, 'images': json.loads(process.stdout)})
            Path(sampled['report']).unlink()
    return {'samples': outputs, 'candidateOnly': True, 'visualAcceptance': 'pending', 'temporaryDirectory': name}
