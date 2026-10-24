import hashlib
import json
import uuid

import unreal

from BBBFingerAnimationTools import _tracks, _signature
from BBBFingerAnimationMath import distance
from BBBAnimationTrajectoryTools import _track_metadata
from BBBManualActionNative import _channel_digest, _copy_sequence
from BBBAssetWritePolicy import require_asset_write


def _record_rotations(asset_path, job, before, bones):
    """/** @param asset_path 明确成品 @param job 正式制作记录 @param before 当前轨道 @param bones 恢复骨骼 @return 原制作旋转与来源摘要 */"""
    from pathlib import Path
    from BBBFingerAnimationMath import unit, multiply, inverse
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / job['source_record']).resolve()
    expected_parent = project / 'Content' / asset_path.split('/Animation/Sequence/')[0].removeprefix('/Game/') / 'Source/Animation'
    if path.parent != expected_parent.resolve() or not path.name.endswith('.json.source'):
        raise ValueError('FINGER_RESTORE_RECORD_SCOPE')
    encoded = path.read_bytes()
    data = json.loads(encoded.decode('utf-8-sig'))
    result = {}
    if data.get('format') == 'BBBGripAuthoring':
        if data['animation'] != asset_path or data['solution'].get('origin') != 'human_manual_edit':
            raise ValueError('FINGER_RESTORE_MANUAL_RECORD')
        for name in bones:
            result[name] = [unreal.Quat(*data['solution']['finger_rotations'][name]) for value in before[name]]
    if 'source_motion' in data:
        snapshots = [a for a in data['source_motion']['assets'] if a['asset'] == job['sample_asset']]
        if len(snapshots) != 1:
            raise ValueError('FINGER_RESTORE_SNAPSHOT_REQUIRED')
        samples = snapshots[0]['samples']
        for name in bones:
            digit, segment, side = name.split('_')
            parent = 'hand_' + side if segment == '01' else digit + '_' + ('01' if segment == '02' else '02') + '_' + side
            if len(samples) != len(before[name]) or [v['frame'] for v in samples] != list(range(len(samples))):
                raise ValueError('FINGER_RESTORE_SNAPSHOT_FRAMES')
            result[name] = [unreal.Quat(*unit(multiply(inverse(unit(s['bones'][parent]['quaternion'])), s['bones'][name]['quaternion']))) for s in samples]
    if set(result) != set(bones):
        raise ValueError('FINGER_RESTORE_RECORD_FORMAT')
    return result, hashlib.sha256(encoded).hexdigest()


def run(paths, config, action):
    """/** @param paths 明确恢复目标 @param config 未修改制作序列映射 @param action 检查或恢复 @return 仅恢复手指旋转的保存回读证据 */"""
    import traceback
    try:
        return _run(paths, config, action)
    except Exception:
        unreal.log_error(traceback.format_exc())
        raise


def _run(paths, config, action):
    """/** @param paths 明确目标 @param config 来源映射 @param action 操作 @return 官方求值及逐轨证据 */"""
    jobs = config.get('restore_sequences') or config['restore_records']
    if action not in ('inspect', 'repair') or set(paths) != set(jobs) or not 1 <= len(paths) <= 16:
        raise ValueError('FINGER_SEQUENCE_RESTORE_SCOPE')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('FINGER_SEQUENCE_RESTORE_PIE')
    allowed = {f'{d}_{j}_{s}' for d in ('index', 'middle', 'ring', 'pinky') for j in ('01', '02', '03') for s in ('l', 'r')}
    prepared = []
    reports = []
    plans = []
    for path in paths:
        animation = unreal.load_asset(path)
        sequence = unreal.load_asset(jobs[path]['sequence']) if 'sequence' in jobs[path] else None
        if not isinstance(animation, unreal.AnimSequence) or ('sequence' in jobs[path] and not isinstance(sequence, unreal.LevelSequence)):
            raise ValueError('FINGER_SEQUENCE_RESTORE_ASSETS')
        bones = jobs[path].get('bones', sorted(allowed))
        if not bones or set(bones) - allowed:
            raise ValueError('FINGER_SEQUENCE_RESTORE_BONES')
        if sequence is None:
            before = _tracks(animation)
            metadata = _track_metadata(animation)
            rotations, channel_signature = _record_rotations(path, jobs[path], before, bones)
        else:
            candidates = [b for b in sequence.get_bindings() if isinstance(b.get_object_template(), unreal.SkeletalMeshActor)
                          and b.get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset().get_editor_property('skeleton') == animation.get_editor_property('skeleton')]
            if len(candidates) != 1:
                raise ValueError('FINGER_SEQUENCE_RESTORE_BINDING')
            original_binding = candidates[0]
            channel_signature = _channel_digest(sequence)
            before = _tracks(animation)
            metadata = _track_metadata(animation)
            scope = unreal.new_object(unreal.LevelSequence, name='BBBFingerRestore_' + uuid.uuid4().hex)
            try:
                copied = _copy_sequence(sequence, scope, 'Sequence')
                original_rate = copied.get_display_rate()
                original_end_seconds = copied.get_playback_end()*original_rate.denominator/original_rate.numerator
                rate = animation.data_model_interface.get_frame_rate()
                copied.set_display_rate(rate)
                copied.set_playback_start(0)
                copied.set_playback_end(len(next(iter(before.values()))) - 1)
                if animation.get_play_length() >= original_end_seconds - 0.00001:
                    for item in copied.get_bindings():
                        for track in item.get_tracks():
                            for section in track.get_sections():
                                if section.has_end_frame() and section.get_end_frame() == copied.get_playback_end():
                                    section.set_end_frame(copied.get_playback_end()+1)
                binding = next(b for b in copied.get_bindings() if b.get_id().export_text() == original_binding.get_id().export_text())
                baked = unreal.SystemLibrary.duplicate_object(animation, scope, 'Animation')
                baked.controller.remove_all_bone_tracks(False)
                options = unreal.AnimSeqExportOption()
                options.export_transforms = True
                options.export_morph_targets = False
                options.export_attribute_curves = False
                options.export_material_curves = False
                world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
                if not unreal.SequencerTools.export_anim_sequence(world, copied, baked, options, binding, False):
                    raise RuntimeError('FINGER_SEQUENCE_RESTORE_EXPORT')
                source = _tracks(baked)
                if any(name not in before or name not in source or len(before[name]) != len(source[name]) for name in bones):
                    raise RuntimeError('FINGER_SEQUENCE_RESTORE_KEYS')
                rotations = {name: [value.rotation for value in source[name]] for name in bones}
            finally:
                unreal.purge_object_references(scope, True)
            if _channel_digest(sequence) != channel_signature:
                raise RuntimeError('FINGER_SEQUENCE_RESTORE_SOURCE_CHANGED')
        signature = _signature(before)
        prepared.append((animation, before, rotations, metadata))
        plans.append({'asset':path, 'sequence':jobs[path].get('sequence', jobs[path].get('source_record')), 'channels':channel_signature, 'bones':bones, 'metadata':metadata})
        reports.append({'asset':path, 'sourceSequence':jobs[path].get('sequence', jobs[path].get('source_record')), 'signature':signature, 'bones':bones, 'samples':len(before[bones[0]])})
    plan = hashlib.sha256(json.dumps(plans, sort_keys=True).encode()).hexdigest()
    if action == 'repair':
        if config.get('expected_plan_signature') != plan or any(config.get('expected_signatures', {}).get(r['asset']) != r['signature'] for r in reports):
            raise ValueError('FINGER_SEQUENCE_RESTORE_INSPECT_REQUIRED')
        require_asset_write([a for a, b, r, m in prepared])
        for index, (animation, before, rotations, metadata) in enumerate(prepared):
            controller = animation.controller
            controller.open_bracket('从正式制作序列恢复原手指旋转', False)
            try:
                for name, values in rotations.items():
                    original = before[name]
                    if not controller.set_bone_track_keys(name, [v.translation for v in original], values, [v.scale3d for v in original], False):
                        raise RuntimeError('FINGER_SEQUENCE_RESTORE_WRITE')
            finally:
                controller.close_bracket(False)
            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('FINGER_SEQUENCE_RESTORE_METADATA')
            maximum = 0.0
            for name, values in before.items():
                if len(values) != len(actual[name]):
                    raise RuntimeError('FINGER_SEQUENCE_RESTORE_COUNT')
                for sample, (a, b) in enumerate(zip(values, actual[name])):
                    expected = rotations[name][sample] if name in rotations else a.rotation
                    error = distance(list(expected.to_tuple()), list(b.rotation.to_tuple()))
                    maximum = max(maximum, error)
                    if a.translation != b.translation or a.scale3d != b.scale3d or error > 0.01:
                        raise RuntimeError('FINGER_SEQUENCE_RESTORE_READBACK: '+name)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('FINGER_SEQUENCE_RESTORE_SAVE')
            reports[index].update(saved=True, metadataPreserved=True, nonTargetPreserved=True, maximumRotationErrorDegrees=maximum, signature=_signature(actual))
    return json.dumps({'action':action, 'planSignature':plan, 'assets':reports, 'storage':'transient_only'}, ensure_ascii=False)
