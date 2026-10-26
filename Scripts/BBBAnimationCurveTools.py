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
        if ('Time=' in value or 'Value=' in value) and 'InterpMode=RCIM_Cubic' not in value:
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
    for target in targets:
        if target == source:
            raise RuntimeError('源与目标必须不同')
        if abs(source.get_play_length() - target.get_play_length()) > 0.00001:
            raise RuntimeError('不同长度的动画禁止直接复制曲线 ' + target.get_path_name())
        if not dry_run:
            require_write_access(target)
    source_curves = _curves(source)
    names = list(unreal.AnimationLibrary.get_animation_curve_names(source, unreal.RawCurveTrackTypes.RCT_FLOAT))
    expected = _curve_values(source)
    results = []
    for target in targets:
        if not dry_run:
            bones_before = _bone_digest(target)
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
            if any(actual.get(name) != value for name, value in expected.items()):
                raise RuntimeError('曲线完整回读不一致 ' + target.get_path_name())
            if _bone_digest(target) != bones_before:
                raise RuntimeError('曲线复制改变了骨骼轨道 ' + target.get_path_name())
            if not unreal.EditorAssetLibrary.save_loaded_asset(target, False):
                raise RuntimeError('曲线复制保存失败')
        results.append({'asset': target.get_path_name(), 'curves': [str(n) for n in names], 'saved': not dry_run,
                        'bone_tracks_unchanged': True if not dry_run else None})
    return json.dumps({'source': source.get_path_name(), 'dry_run': dry_run, 'targets': results}, ensure_ascii=False)
