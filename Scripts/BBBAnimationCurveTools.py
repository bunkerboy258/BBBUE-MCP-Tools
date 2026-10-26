import hashlib
import json
import re
import unreal


def _curves(animation):
    """/** @param animation 动画序列 @return 模型保存的原始浮点曲线 */"""
    model = animation.data_model_interface
    field = 'LegacyCurveData' if model.get_class().get_name() == 'AnimationSequencerDataModel' else 'CurveData'
    return list(model.get_editor_property(field).get_editor_property('FloatCurves'))


def _curve_values(animation):
    """/** @param animation 动画序列 @return 按引擎名称语义核对的完整曲线数据 */"""
    names = unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)
    return {str(name).casefold(): _curve_semantics(curve.export_text())
            for name, curve in zip(names, _curves(animation))}


def _curve_semantics(exported):
    """/** @param exported 引擎曲线文本 @return 保留全部有效插值参数并忽略线性键的无效切线缓存 */"""
    def key(match):
        value = match.group(0)
        if any(field in value for field in ('Time=', 'Value=', 'ArriveTangent=', 'LeaveTangent=', 'ArriveTangentWeight=', 'LeaveTangentWeight=')) and 'InterpMode=RCIM_Cubic' not in value:
            value = re.sub(r',?(?:ArriveTangent|LeaveTangent|ArriveTangentWeight|LeaveTangentWeight)=[^,()]+', '', value)
        return value
    return re.sub(r'\([^()]*\)', key, re.sub(r'CurveName="[^"]*"', '', exported))


def _bone_digest(animation, excluded_bones=()):
    """/** @param animation 动画序列 @return 所有骨轨道原始变换的摘要 */"""
    digest = hashlib.sha256()
    for bone in animation.data_model_interface.get_bone_track_names():
        if str(bone) in excluded_bones:
            continue
        digest.update(str(bone).encode('utf-8'))
        for transform in unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone):
            digest.update(transform.export_text().encode('utf-8'))
    return digest.hexdigest()


def configure_in_place_root_velocities(asset_paths, velocities, dry_run):
    """/** @param asset_paths 明确原地序列 @param velocities 动画局部索引速度 @param dry_run 只校验 @return 非根轨道保持不变的保存回读 */"""
    from BBBAssetWritePolicy import require_asset_write
    import math
    if len(asset_paths) != len(velocities) or len(set(asset_paths)) != len(asset_paths) or not asset_paths:
        raise RuntimeError('动画与速度必须唯一且一一对应')
    assets = [unreal.load_asset(path) for path in asset_paths]
    vectors = []
    for asset, velocity in zip(assets, velocities):
        if (not isinstance(asset, unreal.AnimSequence) or not asset.get_path_name().startswith('/Game/_Project/')
                or len(velocity) != 3 or any(not math.isfinite(value) for value in velocity)):
            raise RuntimeError('需要明确自有动画与有限三维速度')
        vector = unreal.Vector(*velocity)
        if not unreal.BBBMotionMatchingEditorLibrary.configure_in_place_root_velocity(asset, vector, False):
            raise RuntimeError('根轨道不满足原地或线性约束 ' + asset.get_path_name())
        vectors.append(vector)
    if not dry_run:
        require_asset_write(assets)
    reports = []
    for asset, vector in zip(assets, vectors):
        before = _bone_digest(asset, ('root',))
        if not dry_run:
            if not unreal.BBBMotionMatchingEditorLibrary.configure_in_place_root_velocity(asset, vector, True):
                raise RuntimeError('线性根轨道写入失败')
            if _bone_digest(asset, ('root',)) != before:
                raise RuntimeError('非根骨轨道出现变化 拒绝保存')
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError('原地动画保存失败')
        keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(asset, 'root')
        reports.append({'asset': asset.get_path_name(), 'velocity': list(vector.to_tuple()),
            'firstRoot': list(keys[0].translation.to_tuple()), 'lastRoot': list(keys[-1].translation.to_tuple()),
            'nonRootTracksUnchanged': True, 'dryRun': dry_run, 'saved': not dry_run})
    return reports


def inspect(asset_paths, bone_names):
    """/** @param asset_paths 动画序列 @param bone_names 同源比对骨骼 @return 原始曲线与完整局部骨轨道摘要 */"""
    results = []
    for path in asset_paths:
        animation = unreal.load_asset(path)
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError('需要动画序列 ' + path)
        model = animation.data_model_interface
        rate = model.get_frame_rate()
        tracks = set(str(n) for n in model.get_bone_track_names())
        signatures = {}
        for bone in bone_names:
            if bone not in tracks:
                continue
            transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone)
            values = [[round(float(v), 3) for v in (
                *t.translation.to_tuple(), *t.rotation.to_tuple(), *t.scale3d.to_tuple())] for t in transforms]
            signatures[bone] = {'keys': len(values), 'digest': hashlib.sha256(json.dumps(values).encode()).hexdigest()}
        results.append({'asset': animation.get_path_name(), 'length': animation.get_play_length(),
                        'rate': [rate.numerator, rate.denominator], 'bone_signatures': signatures,
                        'curves': {str(n): c.export_text() for n, c in zip(
                            unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT),
                            _curves(animation))}})
    return json.dumps(results, ensure_ascii=False)


def rename(asset_paths, old_name, new_name, dry_run):
    """/** @param asset_paths 自有资产 @param old_name 原名 @param new_name 新名 @param dry_run 只检查 @return 原位改名与保存结果 */"""
    from BBBAssetWritePolicy import require_write_access
    if not old_name.strip() or not new_name.strip() or old_name.casefold() == new_name.casefold():
        raise RuntimeError('曲线名称无效')
    prepared = []
    for path in asset_paths:
        if not path.startswith('/Game/_Project/'):
            raise RuntimeError('只允许自有资产 ' + path)
        asset = unreal.load_asset(path)
        count = 0
        if isinstance(asset, unreal.AnimSequence):
            names = [str(n) for n in unreal.AnimationLibrary.get_animation_curve_names(asset, unreal.RawCurveTrackTypes.RCT_FLOAT)]
            count = sum(n.casefold() == old_name.casefold() for n in names)
            if count and any(n.casefold() == new_name.casefold() for n in names):
                raise RuntimeError('新旧曲线同时存在 拒绝覆盖 ' + path)
        if isinstance(asset, unreal.AnimBlueprint):
            count = unreal.BBBBlueprintEditorLibrary.rename_animation_curve_references(asset, old_name, new_name, True)
            if count < 0:
                raise RuntimeError('蓝图引用核对失败 ' + path)
        if count:
            if not dry_run:
                require_write_access(asset)
            prepared.append((asset, count))
    results = []
    for asset, count in prepared:
        if not dry_run:
            asset.modify()
            if isinstance(asset, unreal.AnimSequence):
                old_id = unreal.AnimationCurveIdentifier()
                old_id.set_curve_identifier(old_name, unreal.RawCurveTrackTypes.RCT_FLOAT)
                new_id = unreal.AnimationCurveIdentifier()
                new_id.set_curve_identifier(new_name, unreal.RawCurveTrackTypes.RCT_FLOAT)
                before = [re.sub(r'CurveName="[^"]*"', '', c.export_text()) for c in _curves(asset)]
                if not asset.controller.rename_curve(old_id, new_id, False):
                    raise RuntimeError('动画曲线改名失败 ' + asset.get_path_name())
                after_names = [str(n).casefold() for n in unreal.AnimationLibrary.get_animation_curve_names(asset, unreal.RawCurveTrackTypes.RCT_FLOAT)]
                if old_name.casefold() in after_names or new_name.casefold() not in after_names:
                    raise RuntimeError('曲线名称回读不一致 ' + asset.get_path_name())
                if before != [re.sub(r'CurveName="[^"]*"', '', c.export_text()) for c in _curves(asset)]:
                    raise RuntimeError('曲线改名改变了原始数据 ' + asset.get_path_name())
            if isinstance(asset, unreal.AnimBlueprint):
                if unreal.BBBBlueprintEditorLibrary.rename_animation_curve_references(asset, old_name, new_name, False) != count:
                    raise RuntimeError('蓝图引用数量变化')
                if unreal.BBBBlueprintEditorLibrary.rename_animation_curve_references(asset, old_name, new_name, True) != 0:
                    raise RuntimeError('蓝图旧曲线引用残留')
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
                raise RuntimeError('曲线改名保存失败 ' + asset.get_path_name())
        results.append({'asset': asset.get_path_name(), 'references': count, 'saved': not dry_run})
    return json.dumps({'dry_run': dry_run, 'scanned': len(asset_paths), 'changed': results}, ensure_ascii=False)


def _trimmed_frame_alignment(source, target):
    """/** @param source 基准动作 @param target 首尾裁帧的同源动作 @return 原始根骨与骨盆逐帧核验的时间映射 */"""
    import math
    if not hasattr(source.data_model_interface, 'get_frame_rate') or not hasattr(target.data_model_interface, 'get_frame_rate'):
        raise RuntimeError('裁帧曲线复制需要原始动画数据模型')
    source_rate = source.data_model_interface.get_frame_rate()
    target_rate = target.data_model_interface.get_frame_rate()
    if min(source_rate.numerator, source_rate.denominator, target_rate.numerator, target_rate.denominator) <= 0:
        raise RuntimeError('原始动画采样率必须为正')
    if source_rate.numerator * target_rate.denominator != target_rate.numerator * source_rate.denominator:
        raise RuntimeError('裁帧曲线复制要求相同采样率')
    fps = source_rate.numerator / source_rate.denominator
    source_tracks = {bone: list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, bone))
                     for bone in ('root', 'pelvis')}
    target_tracks = {bone: list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(target, bone))
                     for bone in ('root', 'pelvis')}
    if any(not values for values in [*source_tracks.values(), *target_tracks.values()]):
        raise RuntimeError('同源裁帧核验需要完整根骨与骨盆轨道')
    source_count = len(source_tracks['root'])
    target_count = len(target_tracks['root'])
    if min(source_count, target_count) < 2 or len(source_tracks['pelvis']) != source_count or len(target_tracks['pelvis']) != target_count:
        raise RuntimeError('同源裁帧核验需要等长且至少两帧的原始骨轨道')
    if abs(source_count - target_count) > 8:
        raise RuntimeError('首尾帧差超过八帧 拒绝推断同源时间映射')
    candidates = []
    for offset in range(min(8, source_count - 2) + 1):
        count = min(source_count - offset, target_count)
        if count < min(source_count, target_count) - 8:
            continue
        position_error = 0.0
        rotation_error = 0.0
        score = 0.0
        for bone in ('pelvis',):
            for left, right in zip(source_tracks[bone][offset:offset + count], target_tracks[bone][:count]):
                distance = (left.translation - right.translation).length()
                a = left.rotation.to_tuple()
                b = right.rotation.to_tuple()
                norm = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
                if not math.isfinite(distance) or not math.isfinite(norm) or norm <= 0.0:
                    raise RuntimeError('原始轨道存在无效变换')
                angle = math.degrees(2.0 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(a, b))) / norm)))
                position_error = max(position_error, distance)
                rotation_error = max(rotation_error, angle)
                score += distance * distance + angle * angle
        candidates.append((score / count, offset, count, position_error, rotation_error))
    best = min(candidates)
    if best[3] > 0.1 or best[4] > 0.1:
        raise RuntimeError('骨盆不满足同源逐帧对应 ' + target.get_path_name()
                           + ' position=' + str(best[3]) + ' rotation=' + str(best[4]))
    root_position_error = 0.0
    root_rotation_error = 0.0
    for left, right in zip(source_tracks['root'][best[1]:best[1] + best[2]], target_tracks['root'][:best[2]]):
        distance = (left.translation - right.translation).length()
        if not math.isfinite(distance):
            raise RuntimeError('根轨道位置无效')
        root_position_error = max(root_position_error, distance)
        a = left.rotation.to_tuple()
        b = right.rotation.to_tuple()
        norm = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
        if not math.isfinite(norm) or norm <= 0.0:
            raise RuntimeError('根轨道旋转无效')
        root_rotation_error = max(root_rotation_error, math.degrees(2.0 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(a, b))) / norm))))
    return {'source_frame_offset': best[1], 'source_time_offset': best[1] / fps,
            'verified_target_end_time': (best[2] - 1) / fps,
            'max_position_error_cm': best[3], 'max_rotation_error_degrees': best[4],
            'root_motion_matches': root_position_error <= 0.1 and root_rotation_error <= 0.1,
            'root_max_position_error_cm': root_position_error,
            'root_max_rotation_error_degrees': root_rotation_error}


def _shifted_curve(curve, offset):
    """/** @param curve 完整浮点曲线 @param offset 已核验源时间偏移 @return 保留键插值与切线的平移副本 */"""
    exported = curve.export_text()
    start = exported.index('FloatCurve=') + len('FloatCurve=')
    depth = 0
    end = start
    for index in range(start, len(exported)):
        depth += (exported[index] == '(') - (exported[index] == ')')
        if depth == 0:
            end = index + 1
            break
    original = exported[start:end]
    if any(value != 'RCCE_Constant' for value in re.findall(r'(?:PreInfinityExtrap|PostInfinityExtrap)=([A-Za-z_]+)', original)):
        raise RuntimeError('裁帧曲线复制仅接受常量外推曲线')
    rich = unreal.RichCurve()
    rich.import_text(original)
    keys = []
    for source_key in rich.get_editor_property('Keys'):
        key = type(source_key)()
        key.import_text(source_key.export_text())
        key.set_editor_property('Time', source_key.get_editor_property('Time') - offset)
        keys.append(key)
    rich.set_editor_property('Keys', keys)
    name = re.search(r'CurveName="([^"]+)"', exported)
    flags = re.search(r'CurveTypeFlags=(\d+)', exported)
    if name is None or flags is None:
        raise RuntimeError('原始曲线名称或标志缺失')
    return {'name': name.group(1), 'flags': int(flags.group(1)), 'keys': keys,
            'expected': exported[:start] + rich.export_text() + exported[end:]}


def _write_shifted_curves(target, curves):
    """/** @param target 已授权目标 @param curves 已平移的完整曲线 @return 写入完成并保持原始键语义 */"""
    existing = {str(name).casefold() for name in unreal.AnimationLibrary.get_animation_curve_names(target, unreal.RawCurveTrackTypes.RCT_FLOAT)}
    controller = target.controller
    controller.open_bracket('Transfer aligned animation curves', False)
    try:
        for curve in curves:
            name = curve['name']
            identifier = unreal.AnimationCurveIdentifier()
            identifier.set_curve_identifier(name, unreal.RawCurveTrackTypes.RCT_FLOAT)
            flags = curve['flags']
            if str(name).casefold() not in existing and not controller.add_curve(identifier, flags, False):
                raise RuntimeError('创建裁帧曲线失败 ' + str(name))
            if not controller.set_curve_flags(identifier, flags, False):
                raise RuntimeError('写入曲线标志失败 ' + str(name))
            if not controller.set_curve_keys(identifier, curve['keys'], False):
                raise RuntimeError('写入平移曲线键失败 ' + str(name))
    finally:
        controller.close_bracket(False)


def _aligned_curve_equal(expected, actual):
    """/** @param expected 平移后的完整语义 @param actual 数据模型回读语义 @return 仅允许时间序列化的一微秒误差 */"""
    def separate(value):
        times = []
        def key(match):
            text = match.group(0)
            if 'Time=' not in text and 'Value=' not in text and text != '()':
                return text
            time = re.search(r'Time=([^,()]+)', text)
            times.append(float(time.group(1)) if time else 0.0)
            return re.sub(r',?Time=[^,()]+', '', text).replace('(,', '(')
        return re.sub(r'\([^()]*\)', key, value), times
    left, left_times = separate(expected)
    right, right_times = separate(actual)
    return (left == right and len(left_times) == len(right_times)
            and all(abs(a - b) <= 0.00000101 for a, b in zip(left_times, right_times)))


def copy(source_path, target_paths, dry_run, source_content_directory=''):
    """/** @param source_path 基准序列 @param target_paths 同源同长序列 @param dry_run 只检查 @return 原始曲线复制与保存结果 */"""
    from BBBAssetWritePolicy import require_write_access
    targets = []
    for path in target_paths:
        if not path.startswith('/Game/_Project/'):
            raise RuntimeError('只允许自有目标')
        target = unreal.load_asset(path)
        if not isinstance(target, unreal.AnimSequence):
            raise RuntimeError('目标必须为不同的动画序列 ' + path)
        targets.append(target)
    source = None
    if source_content_directory:
        sources = unreal.BBBMotionMatchingEditorLibrary.load_reference_animation_sequences(source_content_directory, [source_path])
        source = sources[0] if sources else None
    if not source_content_directory:
        source = unreal.load_asset(source_path)
    if not isinstance(source, unreal.AnimSequence):
        raise RuntimeError('源资产必须为动画序列')
    alignments = {}
    shifted = {}
    for target in targets:
        if target == source:
            raise RuntimeError('源与目标必须不同')
        if abs(source.get_play_length() - target.get_play_length()) > 0.00001:
            alignment = _trimmed_frame_alignment(source, target)
            if not dry_run and not alignment['root_motion_matches']:
                raise RuntimeError('同源动作的根轨道不同 需要先显式修正并回读 ' + target.get_path_name())
            alignments[target.get_path_name()] = alignment
            shifted[target.get_path_name()] = [_shifted_curve(curve, alignment['source_time_offset']) for curve in _curves(source)]
        if not dry_run:
            require_write_access(target)
    source_curves = _curves(source)
    names = list(unreal.AnimationLibrary.get_animation_curve_names(source, unreal.RawCurveTrackTypes.RCT_FLOAT))
    expected = _curve_values(source)
    results = []
    for target in targets:
        target_curves = shifted.get(target.get_path_name())
        target_expected = expected
        if target_curves is not None:
            target_expected = {curve['name'].casefold(): _curve_semantics(curve['expected']) for curve in target_curves}
        if not dry_run:
            bones_before = _bone_digest(target)
            if target_curves is not None:
                _write_shifted_curves(target, target_curves)
            if target_curves is None:
                if unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(source, target) != len(source_curves):
                    raise RuntimeError('曲线复制数量不一致')
            for name, curve in zip(names, source_curves):
                identifier = unreal.AnimationCurveIdentifier()
                identifier.set_curve_identifier(name, unreal.RawCurveTrackTypes.RCT_FLOAT)
                exported = curve.export_text()
                color = re.search(r'Color=\(R=([^,]+),G=([^,]+),B=([^,]+),A=([^\)]+)\)', exported)
                if color:
                    target.controller.set_curve_color(identifier, unreal.LinearColor(*[float(v) for v in color.groups()]), False)
                comment = re.search(r'Comment=("(?:\\.|[^"\\])*")', exported)
                if comment:
                    target.controller.set_curve_comment(identifier, json.loads(comment.group(1)), False)
            actual = _curve_values(target)
            mismatches = [name for name, value in target_expected.items()
                          if (not _aligned_curve_equal(value, actual.get(name, '')) if target_curves is not None else actual.get(name) != value)]
            if mismatches:
                mismatch = mismatches[0]
                wanted = target_expected[mismatch]
                observed = actual.get(mismatch, '')
                position = next((index for index, pair in enumerate(zip(wanted, observed)) if pair[0] != pair[1]), min(len(wanted), len(observed)))
                raise RuntimeError('曲线完整回读不一致 ' + target.get_path_name() + ' curve=' + mismatch
                                   + ' expected=' + wanted[max(0, position - 80):position + 180]
                                   + ' actual=' + observed[max(0, position - 80):position + 180])
            if _bone_digest(target) != bones_before:
                raise RuntimeError('曲线复制改变了骨骼轨道 ' + target.get_path_name())
            if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
                raise RuntimeError('曲线复制保存失败')
        results.append({'asset': target.get_path_name(), 'curves': [str(n) for n in names], 'saved': not dry_run,
                        'bone_tracks_unchanged': True if not dry_run else None,
                        'alignment': alignments.get(target.get_path_name())})
    return json.dumps({'source': source.get_path_name(), 'dry_run': dry_run, 'targets': results}, ensure_ascii=False)
