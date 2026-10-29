import gc
import json
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBFingerAnimationTools import _tracks
from BBBFingerAnimationMath import distance
from BBBRetargetInPlaceBatch import _metadata as _track_metadata
from BBBControlRigAuthoringToolset import _pose
import BBBHandRetargetBatchToolset as batch


def _sync_left_ik(animation, mesh, count, rate):
    """Rebuild the helper in its actual parent space from the evaluated left hand."""
    component = unreal.new_object(unreal.SkeletalMeshComponent)
    component.set_skeletal_mesh_asset(mesh)
    parent = str(component.get_parent_bone('ik_hand_l'))
    if not parent or parent.casefold() == 'none':
        raise RuntimeError('LEFT_HAND_IK_PARENT_MISSING')
    keys = []
    for frame in range(count):
        pose = _pose(animation, mesh, frame * rate.denominator / rate.numerator)
        hand = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_l', unreal.AnimPoseSpaces.WORLD)
        parent_pose = unreal.AnimPoseExtensions.get_bone_pose(pose, parent, unreal.AnimPoseSpaces.WORLD)
        keys.append(hand.make_relative(parent_pose))
    controller = animation.controller
    original_scales = [v.scale3d for v in _tracks(animation)['ik_hand_l']]
    if not controller.set_bone_track_keys('ik_hand_l', [v.translation for v in keys],
            [v.rotation for v in keys], original_scales, False):
        raise RuntimeError('LEFT_HAND_IK_WRITE')
    max_position = max_angle = 0.0
    for frame in range(count):
        pose = _pose(animation, mesh, frame * rate.denominator / rate.numerator)
        hand = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_l', unreal.AnimPoseSpaces.WORLD)
        helper = unreal.AnimPoseExtensions.get_bone_pose(pose, 'ik_hand_l', unreal.AnimPoseSpaces.WORLD)
        max_position = max(max_position, (hand.translation-helper.translation).length())
        a, b = hand.rotation, helper.rotation
        dot = abs(a.x*b.x+a.y*b.y+a.z*b.z+a.w*b.w)
        import math
        max_angle = max(max_angle, math.degrees(2 * math.acos(min(1.0, dot))))
    if max_position > 0.05 or max_angle > 0.1:
        raise RuntimeError('LEFT_HAND_IK_ALIGNMENT: %.6fcm %.6fdeg' % (max_position, max_angle))
    return keys, max_position, max_angle


def run(recipe_path, action, write_paths):
    """/** @param recipe_path 正式制作源 @param action bake @param write_paths 明确序列与动画 @return 瞬态烘焙后原位左臂写入结果 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    if not path.is_relative_to(project / 'Content/_Project/Characters') or action != 'bake':
        raise ValueError('LEFT_HAND_MOTION_SCOPE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('mode') == 'restore_original':
        import BBBLeftHandRestore
        import importlib
        return importlib.reload(BBBLeftHandRestore).run(path, data, write_paths)
    jobs = data['jobs']
    expected = {j[k] for j in jobs for k in ('animation', 'sequence')}
    if set(write_paths) != expected or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('LEFT_HAND_MOTION_WRITE_SCOPE_OR_PIE')
    mesh = unreal.load_asset(data['mesh'])
    grip = data.get('grip_in_hand_r')
    if not isinstance(grip, dict):
        raise RuntimeError('LEFT_HAND_AUTHORED_GRIP_MISSING: ' + recipe_path)
    batch._transform(grip, '正式制作源右手空间握持目标')
    results = []
    for job in jobs:
        animation = unreal.load_asset(job['animation'])
        before = _tracks(animation)
        metadata = _track_metadata(animation)
        count, rate = batch._frame_count(animation)
        if data.get('mode') == 'ik_sync':
            ik_scope = unreal.new_object(unreal.LevelSequence, name='IKScope_'+uuid.uuid4().hex)
            transient = unreal.SystemLibrary.duplicate_object(animation, ik_scope, 'Animation')
            keys, max_pos, max_angle = _sync_left_ik(transient, mesh, count, rate)
            require_asset_write([animation])
            controller = animation.controller
            controller.set_bone_track_keys('ik_hand_l', [v.translation for v in keys], [v.rotation for v in keys], [v.scale3d for v in before['ik_hand_l']], False)
            actual = _tracks(animation)
            if _track_metadata(animation) != metadata or any(actual[n] != before[n] for n in before if n != 'ik_hand_l'):
                raise RuntimeError('LEFT_HAND_IK_OTHER_DATA')
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('LEFT_HAND_IK_SAVE')
            results.append({'animation':job['animation'], 'sequence':job['sequence'], 'saved':True, 'samples':count, 'maxIKPositionCm':max_pos, 'maxIKRotationDegrees':max_angle})
            unreal.purge_object_references(ik_scope, True)
            del transient, ik_scope, animation, before, actual, controller, keys
            gc.collect()
            unreal.SystemLibrary.collect_garbage()
            continue
        if not unreal.EditorAssetLibrary.does_asset_exist(job['sequence']):
            batch._write_item({'animation_path':job['animation'], 'template_sequence_path':data['template'],
                              'mesh_path':data['mesh'], 'sequence_path':job['sequence'], 'grip_in_hand_r':grip,
                              'weight':job.get('weight', 1.0), 'contacts':[{'start_frame':0, 'end_frame':count-1, 'fade_in_frames':0, 'fade_out_frames':0}]})
        sequence = unreal.load_asset(job['sequence'])
        rig_binding = batch._binding_for_mesh(sequence, mesh)
        rig_tracks = rig_binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
        if len(rig_tracks) != 1:
            raise RuntimeError('LEFT_HAND_SEQUENCE_INVALID_RIG')
        channels = {str(c.channel_name): c for sec in rig_tracks[0].get_sections() for c in sec.get_all_channels()}
        required = ('hand_l_ik_ctrl.', 'elbow_l_pv_ctrl.', 'source_')
        checked = {n: c for n, c in channels.items() if n.casefold().startswith(required)}
        if len(checked) < 36 or any(len(c.get_keys()) != count for c in checked.values()):
            raise RuntimeError('LEFT_HAND_SEQUENCE_INCOMPLETE: missing or incomplete control keys')
        scope = unreal.new_object(unreal.LevelSequence, name='BBBLeftHandBake_'+uuid.uuid4().hex)
        try:
            copied = unreal.SystemLibrary.duplicate_object(sequence, scope, 'Sequence')
            copied.set_playback_end(count-1)
            baked = unreal.SystemLibrary.duplicate_object(animation, scope, 'Animation')
            binding = batch._binding_for_mesh(copied, mesh)
            options = unreal.AnimSeqExportOption()
            options.export_transforms = True
            options.export_attribute_curves = False
            options.export_material_curves = False
            options.export_morph_targets = False
            world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
            if not unreal.SequencerTools.export_anim_sequence(world, copied, baked, options, binding, False):
                raise RuntimeError('LEFT_HAND_MOTION_EXPORT')
            tracks = _tracks(baked)
            bones = [n for n in batch._LEFT_ARM_BONES if n in before]
            if any(n not in tracks or len(tracks[n]) != len(before[n]) for n in bones):
                raise RuntimeError('LEFT_HAND_MOTION_KEYS')
            # Validate the complete candidate in memory before touching the saved asset.
            candidate = unreal.SystemLibrary.duplicate_object(animation, scope, 'Candidate')
            controller = candidate.controller
            controller.open_bracket('校准通用持枪左臂候选', False)
            try:
                for name in bones:
                    old = before[name]
                    values = tracks[name]
                    positions = [v.translation for v in values] if name == 'ik_hand_l' else [v.translation for v in old]
                    if not controller.set_bone_track_keys(name, positions, [v.rotation for v in values], [v.scale3d for v in old], False):
                        raise RuntimeError('LEFT_HAND_MOTION_CANDIDATE_WRITE')
                ik_keys, max_pos, max_angle = _sync_left_ik(candidate, mesh, count, rate)
            finally:
                controller.close_bracket(False)
            candidate_tracks = _tracks(candidate)
            if set(candidate_tracks) != set(before) or _track_metadata(candidate) != metadata:
                raise RuntimeError('LEFT_HAND_MOTION_CANDIDATE_METADATA')
            if any(candidate_tracks[n] != before[n] for n in before if n not in bones):
                raise RuntimeError('LEFT_HAND_MOTION_CANDIDATE_OTHER_TRACK')
            require_asset_write([animation])
            controller = animation.controller
            controller.open_bracket('校准通用持枪左臂', False)
            try:
                for name in bones:
                    values = candidate_tracks[name]
                    if not controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                        raise RuntimeError('LEFT_HAND_MOTION_WRITE')
            finally:
                controller.close_bracket(False)
            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('LEFT_HAND_MOTION_METADATA')
            for name, old in before.items():
                if len(old) != len(actual[name]):
                    raise RuntimeError('LEFT_HAND_MOTION_COUNT')
                for a,b in zip(candidate_tracks[name], actual[name]):
                    qa, qb = list(a.rotation.to_tuple()), list(b.rotation.to_tuple())
                    rot_error = min(distance(qa, qb), distance(qa, [-v for v in qb]))
                    if (a.translation-b.translation).length() > 0.001 or (a.scale3d-b.scale3d).length() > 0.0001 or rot_error > 0.01:
                        raise RuntimeError('LEFT_HAND_MOTION_READBACK: ' + name)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('LEFT_HAND_MOTION_SAVE')
            results.append({'animation':job['animation'], 'sequence':job['sequence'], 'saved':True, 'samples':count,
                            'nonLeftArmPreserved':True, 'metadataPreserved':True, 'bones':bones, 'targetWeight':job.get('weight', 1.0)})
        finally:
            unreal.purge_object_references(scope, True)
        # Sequencer scripting creates many temporary UObject wrappers per sampled key.
        # Release those between saved animations instead of accumulating across a batch.
        del copied, baked, candidate, candidate_tracks, binding, options, scope, sequence, animation, before, tracks, actual, controller, rig_binding, rig_tracks, channels, checked
        gc.collect()
        unreal.SystemLibrary.collect_garbage()
    data['grip_in_hand_r'] = grip
    data['results'] = results
    data['acceptance'] = 'pending_user_review'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return json.dumps(results,ensure_ascii=False)
