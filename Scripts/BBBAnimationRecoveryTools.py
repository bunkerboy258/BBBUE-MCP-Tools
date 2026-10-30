import os
import pathlib
import re
import json

import unreal


def load_reference_file(path):
    """/** @param path 已有自动保存或带校验清单的参考包 @return 通过原生独立挂载加载的只读动画 */"""
    import hashlib
    saved = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())).resolve()
    root = saved / 'temp/AnimationRecoverySources/ArchiveReference/Content'
    source = pathlib.Path(path).resolve()
    if source.is_relative_to(root):
        manifest = json.loads((root.parent / 'sources.json').read_text(encoding='utf-8'))
        entry = manifest['files'].get(source.relative_to(root).as_posix())
        if not entry or hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('参考包缺少有效源文件校验 ' + path)
        skeletons = [row['object_path'] for row in manifest['files'].values() if row.get('class') == 'Skeleton']
        if skeletons:
            unreal.BBBMotionMatchingEditorLibrary.inspect_configuration(str(root), skeletons)
        assets = unreal.BBBMotionMatchingEditorLibrary.load_reference_animation_sequences(str(root), [entry['object_path']])
        if len(assets) != 1 or not isinstance(assets[0], unreal.AnimSequence):
            raise RuntimeError('参考包不是可读动画 ' + path)
        return assets[0]
    return _load_autosaves([path])[path]


def _load_autosaves(paths):
    """/** @param paths 明确自动保存包列表 @return 一次独立挂载取得的只读动画映射 */"""
    root = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())).resolve() / 'Autosaves' / 'Game'
    object_paths = []
    for path in paths:
        source = pathlib.Path(path).resolve()
        if not source.is_file() or source.suffix.lower() != '.uasset' or not source.is_relative_to(root):
            raise RuntimeError('只允许当前项目已有自动保存动画包 ' + path)
        relative = source.relative_to(root).as_posix()[:-7]
        name = re.sub(r'_Auto\d+$', '', source.stem)
        object_paths.append('/Game/' + relative + '.' + name)
    fixture = root.parents[1] / 'temp' / 'AnimationRecoverySources' / 'ReferenceContent'
    content_root = root
    if fixture.is_dir():
        for path in paths:
            staged = fixture / pathlib.Path(path).resolve().relative_to(root)
            if not staged.is_file() or not os.path.samefile(path, staged):
                raise RuntimeError('恢复参考索引不是原自动保存文件的只读硬链接 ' + path)
        content_root = fixture
        skeleton_paths = ['/Game/' + file.relative_to(fixture).as_posix()[:-7]
                          for file in fixture.rglob('*Skeleton.uasset')]
        if skeleton_paths:
            unreal.BBBMotionMatchingEditorLibrary.inspect_configuration(str(content_root), skeleton_paths)
    assets = unreal.BBBMotionMatchingEditorLibrary.load_reference_animation_sequences(str(content_root), object_paths)
    packages = [asset.get_outer() for asset in assets if isinstance(asset, unreal.AnimSequence)]
    if packages:
        unreal.EditorLoadingAndSavingUtils.fully_load_packages(packages)
    if len(assets) != len(paths) or any(not isinstance(asset, unreal.AnimSequence) for asset in assets):
        raise RuntimeError('自动保存包不是可读动画 ' + str(paths))
    return dict(zip(paths, assets))


def preview_retarget(source_paths, retargeter_path, target_path='', apply=False, reference_content_directory='', reference_skeleton_path=''):
    """/** @param source_paths 原始动画 @param retargeter_path 当前重定向器 @return 隔离烘焙核对或通过证据门槛后的原位恢复 */"""
    import uuid
    if not source_paths or len(source_paths) > 8:
        raise RuntimeError('恢复来源每次支持一至八条同目录动画')
    retargeter = unreal.load_asset(retargeter_path)
    controller = unreal.IKRetargeterController.get_controller(retargeter)
    source_mesh = controller.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
    target_mesh = controller.get_preview_mesh(unreal.RetargetSourceOrTarget.TARGET)
    source_skeleton = source_mesh.get_editor_property('skeleton')
    if not target_path.startswith('/Game/_Project/') or len(set(source_paths)) != len(source_paths):
        raise RuntimeError('恢复目标必须属于自有资产且来源不能重复')
    if not reference_content_directory and any(unreal.load_asset(path).get_editor_property('skeleton') != source_skeleton for path in source_paths):
        raise RuntimeError('候选源与重定向器骨架不匹配')
    saved = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())).resolve()
    fixture = saved / 'temp' / 'AnimationRecoveryPreview' / uuid.uuid4().hex / 'Content'
    fixture.mkdir(parents=True)
    content = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
    skeleton_path = source_skeleton.get_path_name().split('.', 1)[0]
    if reference_content_directory:
        content = pathlib.Path(reference_content_directory).resolve()
        skeleton_path = reference_skeleton_path
    for path in [*source_paths, skeleton_path]:
        if not path.startswith('/Game/') or '..' in path.split('/'):
            raise RuntimeError('恢复来源必须是明确包路径')
        relative = path.removeprefix('/Game/') + '.uasset'
        original = content / relative
        staged = fixture / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        os.link(original, staged)
    created = []
    try:
        references = unreal.BBBRetargetReferenceSession.begin_reference_retarget_session(str(fixture), skeleton_path, source_paths)
        if len(references) != len(source_paths):
            raise RuntimeError('恢复候选参考会话加载失败')
        reference_root = '/' + references[0].get_path_name().split('/')[1]
        if not reference_root.startswith('/BBBReference_'):
            raise RuntimeError('恢复候选挂载根异常')
        source_bones = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(unreal.AnimPoseExtensions.get_reference_pose(references[0].get_editor_property('skeleton')))]
        mesh_bones = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(unreal.AnimPoseExtensions.get_reference_pose(source_skeleton))]
        if source_bones != mesh_bones:
            raise RuntimeError('恢复参考与重定向器源骨名顺序不符')
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = [registry.get_asset_by_object_path(unreal.Name(asset.get_path_name())) for asset in references]
        inputs.source_mesh = source_mesh
        inputs.target_mesh = target_mesh
        inputs.ik_retarget_asset = retargeter
        inputs.target_path = reference_root + '/Generated'
        inputs.include_referenced_assets = False
        inputs.overwrite_existing_files = False
        inputs.retain_additive_flags = True
        created = [str(row.package_name) for row in unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)]
        if len(created) != len(source_paths):
            raise RuntimeError('恢复候选烘焙数量不符')
        results = []
        folder = target_path.rsplit('/', 1)[0]
        for source_index, source_path in enumerate(source_paths):
            name = source_path.rsplit('/', 1)[1]
            baked_path = next(path for path in created if path.rsplit('/', 1)[1] == name)
            results.append(_apply_verified_candidate(source_path, retargeter_path, folder + '/' + name,
                                                    baked_path, target_mesh, saved, apply, True, references[source_index]))
        return results[0] if len(results) == 1 else results
    finally:
        if created and not unreal.EditorAssetLibrary.delete_loaded_assets([unreal.load_asset(path) for path in created]):
            raise RuntimeError('恢复预览临时动画未能清理 ' + str(created))
        unreal.BBBRetargetReferenceSession.end_reference_retarget_session()


def _apply_verified_candidate(source_path, retargeter_path, target_path, baked_path, target_mesh, saved, apply, allow_authoring=False, reference_source=None):
    """/** @param baked_path 隔离源烘焙 @return 在目标原数据模型内核验并恢复 不更换正式数据模型 */"""
    baked = unreal.load_asset(baked_path)
    root_source = _preserve_verified_reference_root(baked, reference_source, target_path, saved)
    result = _apply_candidate_model(source_path, retargeter_path, target_path, baked, target_mesh, saved, apply, allow_authoring, reference_source)
    result['root_source'] = root_source
    return result


def _preserve_verified_reference_root(candidate, source, target_path, saved):
    """/** @param candidate 隔离候选 @param source 原始来源 @return 仅在故障前摘要匹配时保留原始根轨道 */"""
    proof = json.loads((saved / 'temp/AnimationRecoverySources/expected-signatures.json').read_text(encoding='utf-8')).get(target_path)
    if not source or not proof or 'root' not in proof['bone_signatures']:
        return None
    expected = proof['bone_signatures']['root']
    if _candidate_fingerprints(candidate, ['root'])['bone_signatures'].get('root') == expected:
        return {'method': 'retargeted_root'}
    old = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(candidate, 'root'))
    original = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, 'root'))
    if len(old) != len(original):
        return {'method': 'retargeted_root', 'reference_count_mismatch': True}
    control = candidate.controller
    for position_name, positions, rotation_name, rotations in [('reference', original, 'reference', original),
                                                              ('retargeted', old, 'reference', original),
                                                              ('reference', original, 'retargeted', old)]:
        if not control.set_bone_track_keys('root', [v.translation for v in positions], [v.rotation for v in rotations], [v.scale3d for v in old], False):
            raise RuntimeError('隔离候选根轨道来源核验写入失败')
        actual = _candidate_fingerprints(candidate, ['root'])['bone_signatures']['root']
        if actual == expected or _probe_quantized_fingerprint(candidate, 'root', expected['digest'])['matched']:
            return {'method': 'verified_reference_components', 'position': position_name, 'rotation': rotation_name}
    if not control.set_bone_track_keys('root', [v.translation for v in old], [v.rotation for v in old], [v.scale3d for v in old], False):
        raise RuntimeError('隔离候选根轨道回退失败')
    return {'method': 'retargeted_root', 'reference_fingerprint_mismatch': True}


def _candidate_fingerprints(animation, bone_names):
    """/** @param animation 已加载隔离候选 @param bone_names 明确骨名 @return 与故障前记录同算法的原始骨轨摘要 */"""
    import hashlib
    model = animation.data_model_interface
    names = {str(name) for name in model.get_bone_track_names()}
    signatures = {}
    for bone in bone_names:
        if bone not in names:
            continue
        transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone)
        values = [[round(float(value), 3) for value in (*t.translation.to_tuple(), *t.rotation.to_tuple(), *t.scale3d.to_tuple())] for t in transforms]
        signatures[bone] = {'keys': len(values), 'digest': hashlib.sha256(json.dumps(values).encode()).hexdigest()}
    rate = model.get_frame_rate()
    return {'asset': animation.get_path_name(), 'length': animation.get_play_length(), 'rate': [rate.numerator, rate.denominator],
            'bone_signatures': signatures, 'bone_track_names': sorted(names)}


def _apply_candidate_model(source_path, retargeter_path, target_path, baked, target_mesh, saved, apply, allow_authoring=False, reference_source=None):
    """/** @param baked 隔离烘焙结果 @return 通过故障前摘要门槛后保存骨轨并核对原元数据 */"""
    names = ['root', 'pelvis', 'clavicle_l', 'upperarm_l', 'upperarm_twist_01_l', 'lowerarm_l', 'lowerarm_twist_01_l', 'hand_l', 'ik_hand_l', 'clavicle_r', 'upperarm_r', 'lowerarm_r', 'hand_r', 'ik_hand_gun', 'foot_l', 'foot_r']
    candidate = _candidate_fingerprints(baked, names)
    proof_file = saved / 'temp' / 'AnimationRecoverySources' / 'expected-signatures.json'
    expected = json.loads(proof_file.read_text(encoding='utf-8')).get(target_path)
    authoring = None
    left = {'clavicle_l', 'upperarm_l', 'lowerarm_l', 'lowerarm_twist_01_l', 'upperarm_twist_01_l', 'hand_l', 'ik_hand_l'}
    if allow_authoring and expected and any(candidate['bone_signatures'].get(bone) != signature
            and not _probe_quantized_fingerprint(baked, bone, signature['digest'])['matched']
            for bone, signature in expected['bone_signatures'].items() if bone in left):
        authoring = _replay_left_authoring(baked, target_path, target_mesh)
        if authoring:
            candidate = _candidate_fingerprints(baked, names)
    result = {'dryRun': not apply, 'source': source_path, 'retargeter': retargeter_path,
              'candidate': candidate, 'authoring_source': authoring, 'production_assets_modified': False}
    if not apply:
        return result
    if not expected or len(expected['bone_signatures']) < 10:
        result.pop('candidate')
        result['recovery_status'] = 'missing_approved_fingerprint'
        return result
    different = [bone for bone, signature in expected['bone_signatures'].items()
                 if candidate['bone_signatures'].get(bone) != signature]
    rounding_proof = {bone: _probe_quantized_fingerprint(baked, bone,
                     expected['bone_signatures'][bone]['digest']) for bone in different}
    unexplained = [bone for bone in different if not rounding_proof[bone]['matched']
                   or candidate['bone_signatures'].get(bone, {}).get('keys') != expected['bone_signatures'][bone]['keys']]
    root_alignment = None
    if 'root' in unexplained:
        root_alignment = _verify_saved_root_alignment(baked, target_path, saved, reference_source)
        if root_alignment.get('verified'):
            unexplained.remove('root')
    partial_root = (unexplained == ['root'] and root_alignment and root_alignment.get('reason') == 'missing_saved_alignment')
    if (unexplained and not partial_root) or candidate['rate'] != expected['rate'] or abs(candidate['length'] - expected['length']) > 0.00001:
        result.pop('candidate')
        result['recovery_status'] = 'fingerprint_mismatch'
        result['different_bones'] = different
        result['quantization_probe'] = rounding_proof
        result['root_alignment_proof'] = root_alignment
        return result
    target = unreal.load_asset(target_path)
    from BBBAssetWritePolicy import require_write_access
    from BBBRetargetInPlaceBatch import _metadata
    require_write_access(target)
    if target.get_editor_property('skeleton') != target_mesh.get_editor_property('skeleton'):
        raise RuntimeError('恢复目标骨架与烘焙目标不同')
    if target.data_model_interface.get_number_of_keys() != baked.data_model_interface.get_number_of_keys():
        raise RuntimeError('恢复目标关键帧数量不同')
    before = _metadata(target)
    requested = [str(name) for name in baked.data_model_interface.get_bone_track_names() if not partial_root or str(name) != 'root']
    copied = unreal.BBBBlueprintEditorLibrary.copy_animation_bone_tracks(baked, target, requested)
    if copied != len(requested):
        raise RuntimeError('原生恢复骨轨或回读失败')
    if _metadata(target) != before:
        raise RuntimeError('恢复改变目标元数据 拒绝保存')
    if not unreal.EditorAssetLibrary.save_loaded_asset(target, False) or _metadata(target) != before:
        raise RuntimeError('恢复保存或元数据回读失败')
    result.pop('candidate')
    result.update({'asset': target_path, 'recovery_status': 'partial_missing_root' if partial_root else 'restored', 'tracks': copied,
                   'keys': target.data_model_interface.get_number_of_keys(), 'metadata_preserved': True,
                   'verification': 'saved_root_alignment_bound' if root_alignment and root_alignment.get('verified') else ('bounded_quantization_rounding' if different else 'exact_quantized_sha256'),
                   'rounding_proof': rounding_proof,
                   'root_alignment_proof': root_alignment,
                   'unverified_tracks': ['root'] if partial_root else [],
                   'production_assets_modified': True})
    return result


def _verify_saved_root_alignment(candidate, target_path, saved, reference_source=None):
    """/** @param candidate 隔离候选 @param target_path 目标 @return 利用故障前同源对齐记录和已验证参考根轨给出误差上界 */"""
    import math
    file = saved / 'temp/AnimationRecoverySources/root-alignments.json'
    if not file.is_file():
        return {'verified': False, 'reason': 'missing_saved_alignment'}
    record = json.loads(file.read_text(encoding='utf-8')).get(target_path)
    if not record:
        return {'verified': False, 'reason': 'missing_saved_alignment'}
    reference = unreal.load_asset(record['reference'])
    names = {str(name) for name in reference.data_model_interface.get_bone_track_names()}
    if 'root' not in names:
        return {'verified': False, 'reason': 'reference_not_restored'}
    expected = json.loads((saved / 'temp/AnimationRecoverySources/expected-signatures.json').read_text(encoding='utf-8'))[record['reference']]['bone_signatures']['root']
    if _candidate_fingerprints(reference, ['root'])['bone_signatures']['root'] != expected and not _probe_quantized_fingerprint(reference, 'root', expected['digest'])['matched']:
        return {'verified': False, 'reason': 'reference_fingerprint_mismatch'}
    actual = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(candidate, 'root'))
    known = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(reference, 'root'))
    alignment = record['alignment']
    offset = alignment['source_frame_offset']
    if offset not in (0, 1) or len(actual) != len(known) + offset:
        return {'verified': False, 'reason': 'incomplete_saved_frame_coverage'}
    initial_anchor = 'identity' if offset == 1 else 'complete_saved_coverage'
    source_scale = None
    source_scale_residual = 0.0
    source_values = None
    if offset == 1 and (actual[0].translation.length() > .00001 or abs(abs(actual[0].rotation.w) - 1) > .0000001):
        if reference_source is None:
            return {'verified': False, 'reason': 'missing_initial_root_source'}
        source_values = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(reference_source, 'root'))
        if len(source_values) != len(actual):
            return {'verified': False, 'reason': 'initial_source_frame_count_mismatch'}
        initial = source_values[0]
        a, b = actual[0].rotation.to_tuple(), initial.rotation.to_tuple()
        denominator = sum(sum(component * component for component in value.translation.to_tuple()) for value in source_values[offset:])
        if denominator <= .000001:
            return {'verified': False, 'reason': 'initial_source_scale_underdetermined'}
        source_scale = sum(sum(x*y for x,y in zip(left.translation.to_tuple(), right.translation.to_tuple()))
                           for left,right in zip(actual[offset:], source_values[offset:])) / denominator
        source_scale_residual = max((left.translation - right.translation * source_scale).length()
                                    for left,right in zip(actual, source_values))
        if not math.isfinite(source_scale) or source_scale <= 0 or source_scale_residual > .001 or abs(abs(sum(x*y for x,y in zip(a,b))) - 1) > .0000001:
            return {'verified': False, 'reason': 'initial_source_uniform_scale_mismatch', 'scale_residual_cm': source_scale_residual}
        initial_anchor = 'immutable_source_uniform_scale'
    position_error = 0.0
    rotation_error = 0.0
    for left, right in zip(actual[offset:], known):
        position_error = max(position_error, (left.translation - right.translation).length())
        a, b = left.rotation.to_tuple(), right.rotation.to_tuple()
        norm = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b))
        if not math.isfinite(norm) or norm <= 0:
            return {'verified': False, 'reason': 'invalid_reference_rotation'}
        rotation_error = max(rotation_error, math.degrees(2*math.acos(min(1.0, abs(sum(x*y for x,y in zip(a,b))) / norm))))
    position_bound = position_error + alignment['root_max_position_error_cm']
    rotation_bound = rotation_error + alignment['root_max_rotation_error_degrees']
    if source_values is not None:
        covered_radius = max(value.translation.length() for value in source_values[offset:])
        initial_bound = ((position_bound + 2 * source_scale_residual) / covered_radius
                         * source_values[0].translation.length() + 2 * source_scale_residual)
        position_bound = max(position_bound, initial_bound)
    return {'verified': position_bound <= .02 and rotation_bound <= .02,
            'reference': record['reference'], 'frame_offset': offset,
            'saved_max_position_error_cm': alignment['root_max_position_error_cm'],
            'candidate_reference_error_cm': position_error, 'position_error_upper_bound_cm': position_bound,
            'rotation_error_upper_bound_degrees': rotation_bound,
            'initial_root_anchor': initial_anchor, 'source_uniform_scale': source_scale,
            'source_uniform_scale_residual_cm': source_scale_residual}


def _replay_left_authoring(animation, target_path, mesh):
    """/** @param animation 隔离候选 @param target_path 正式目标标识 @param mesh 原目标网格 @return 重放既有完整控制键制作源 不修改正式资产 */"""
    import uuid
    from BBBFingerAnimationTools import _tracks
    import BBBHandRetargetBatchToolset as batch
    from BBBLeftHandMotionCalibration import _sync_left_ik
    content = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
    recipes = content / '_Project/Characters/BBBC_UA/Source/Animation'
    matches = {}
    for file in recipes.glob('*LeftHandMotion.json.source'):
        data = json.loads(file.read_text(encoding='utf-8-sig'))
        if data.get('mode') in ('restore_original', 'ik_sync'):
            continue
        for job in data.get('jobs', []):
            if job.get('animation') == target_path and unreal.EditorAssetLibrary.does_asset_exist(job['sequence']):
                matches[job['sequence']] = str(file)
    if not matches:
        return None
    if len(matches) != 1:
        return {'status': 'ambiguous_authoring_sequences', 'sequences': sorted(matches)}
    sequence_path, recipe = next(iter(matches.items()))
    source = unreal.load_asset(sequence_path)
    count, rate = batch._frame_count(animation)
    scope = unreal.new_object(unreal.LevelSequence, name='RecoveryAuthoring_' + uuid.uuid4().hex)
    destination = animation
    animation = unreal.SystemLibrary.duplicate_object(unreal.load_asset(target_path), scope, 'Candidate')
    if unreal.BBBBlueprintEditorLibrary.copy_animation_bone_tracks(destination, animation, []) != len(destination.data_model_interface.get_bone_track_names()):
        raise RuntimeError('正式数据模型隔离候选准备失败')
    before = {name: list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, name))
              for name in batch._LEFT_ARM_BONES}
    try:
        sequence = unreal.SystemLibrary.duplicate_object(source, scope, 'Sequence')
        sequence.set_playback_end(count - 1)
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        binding = batch._binding_for_mesh(sequence, mesh)
        rig_tracks = binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
        if len(rig_tracks) != 1:
            raise RuntimeError('恢复制作源不是唯一控制轨道')
        checked = [channel for section in rig_tracks[0].get_sections() for channel in section.get_all_channels()
                   if str(channel.channel_name).casefold().startswith(('hand_l_ik_ctrl.', 'elbow_l_pv_ctrl.', 'source_'))]
        key_counts = sorted({len(channel.get_keys()) for channel in checked})
        if len(checked) < 36 or any(len(channel.get_keys()) not in (count, count + 1) for channel in checked):
            return {'status': 'authoring_key_count_mismatch', 'sequence': sequence_path, 'keys': count, 'channel_key_counts': key_counts,
                    'sections': len(rig_tracks[0].get_sections()),
                    'channel_names': [str(c.channel_name) for sec in rig_tracks[0].get_sections() for c in sec.get_all_channels()][:12]}
        baked = unreal.SystemLibrary.duplicate_object(animation, scope, 'Animation')
        options = unreal.AnimSeqExportOption()
        options.export_transforms = True
        options.export_attribute_curves = False
        options.export_material_curves = False
        options.export_morph_targets = False
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not unreal.SequencerTools.export_anim_sequence(world, sequence, baked, options, binding, False):
            raise RuntimeError('恢复既有制作源瞬态烘焙失败')
        tracks = _tracks(baked)
        controller = animation.controller
        controller.open_bracket('重放既有制作源至隔离候选', False)
        try:
            for name in batch._LEFT_ARM_BONES:
                if name not in before or name not in tracks or len(tracks[name]) != len(before[name]):
                    raise RuntimeError('恢复制作源左臂轨道不完整 ' + name)
                values, old = tracks[name], before[name]
                positions = [v.translation for v in values] if name == 'ik_hand_l' else [v.translation for v in old]
                if not controller.set_bone_track_keys(name, positions, [v.rotation for v in values], [v.scale3d for v in old], False):
                    raise RuntimeError('恢复制作源候选写入失败 ' + name)
            _sync_left_ik(animation, mesh, count, rate)
        finally:
            controller.close_bracket(False)
        saved = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())).resolve()
        expected = json.loads((saved / 'temp/AnimationRecoverySources/expected-signatures.json').read_text(encoding='utf-8'))[target_path]['bone_signatures']['ik_hand_l']['digest']
        proof = _probe_quantized_fingerprint(animation, 'ik_hand_l', expected)
        return {'status': 'replayed', 'sequence': sequence_path, 'recipe': recipe, 'keys': count,
                'ik_source': 'original_data_model_bracket', 'ik_proof': proof}
    finally:
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        if unreal.BBBBlueprintEditorLibrary.copy_animation_bone_tracks(animation, destination, list(batch._LEFT_ARM_BONES)) != len(batch._LEFT_ARM_BONES):
            raise RuntimeError('隔离候选左臂回传失败')
        unreal.purge_object_references(scope, True)


def _probe_quantized_fingerprint(animation, bone, expected_digest):
    """/** @param animation 只读候选 @param bone 差异骨轨 @param expected_digest 故障前摘要 @return 有界量化边界诊断 不改资产 */"""
    import hashlib
    import itertools
    import math
    transforms = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(animation, bone)
    raw = [[*t.translation.to_tuple(), *t.rotation.to_tuple(), *t.scale3d.to_tuple()] for t in transforms]
    values = [[round(float(value), 3) for value in row] for row in raw]
    choices = []
    for frame, row in enumerate(raw):
        for component, value in enumerate(row):
            current = values[frame][component]
            if component in (3, 4, 5, 6) and 0 < abs(value) <= 0.0000001 and current == 0:
                alternate = math.copysign(0.0, -math.copysign(1.0, current))
                choices.append((frame, component, alternate, 'signed_zero'))
            boundary = (math.floor(value * 1000) + 0.5) / 1000
            if abs(value - boundary) <= 0.000001:
                alternate = round(boundary + (0.00001 if value <= boundary else -0.00001), 3)
                if alternate != current:
                    choices.append((frame, component, alternate, 'rounding_boundary'))
    result = {'ambiguous_components': len(choices), 'matched': False}
    zero_columns = [component for component in range(10) if all(abs(row[component]) <= .0000001 for row in raw)]
    if len(zero_columns) <= 6:
        for signs in itertools.product((0, 1, -1), repeat=len(zero_columns)):
            for component, sign in zip(zero_columns, signs):
                for frame in range(len(raw)):
                    values[frame][component] = math.copysign(0.0, sign) if sign else round(float(raw[frame][component]), 3)
            if hashlib.sha256(json.dumps(values).encode()).hexdigest() == expected_digest:
                result.update({'matched': True, 'zero_column_tolerance': .0000001,
                               'signed_zero_columns': [{'component': component, 'sign': sign} for component, sign in zip(zero_columns, signs) if sign]})
                return result
    for selected in ([choice for choice in choices if choice[3] == 'rounding_boundary'], choices):
        if len(selected) > 10:
            continue
        values = [[round(float(value), 3) for value in row] for row in raw]
        for bits in itertools.product((False, True), repeat=len(selected)):
            for enabled, (frame, component, alternate, kind) in zip(bits, selected):
                values[frame][component] = alternate if enabled else round(float(raw[frame][component]), 3)
            if hashlib.sha256(json.dumps(values).encode()).hexdigest() == expected_digest:
                result.update({'matched': True, 'rounding_boundary_tolerance': 0.000001,
                               'changed_components': [list(choice) + [raw[choice[0]][choice[1]]] for enabled, choice in zip(bits, selected) if enabled]})
                return result
    return result
