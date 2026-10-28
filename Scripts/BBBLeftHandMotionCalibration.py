import json
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBFingerAnimationTools import _tracks
from BBBFingerAnimationMath import distance
from BBBAnimationTrajectoryTools import _track_metadata
from BBBControlRigAuthoringToolset import _pose
import BBBHandRetargetBatchToolset as batch


def run(recipe_path, action, write_paths):
    """/** @param recipe_path 正式制作源 @param action bake @param write_paths 明确序列与动画 @return 瞬态烘焙后原位左臂写入结果 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    if not path.is_relative_to(project / 'Content/_Project/Characters') or action != 'bake':
        raise ValueError('LEFT_HAND_MOTION_SCOPE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    jobs = data['jobs']
    expected = {j[k] for j in jobs for k in ('animation', 'sequence')}
    if set(write_paths) != expected or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise ValueError('LEFT_HAND_MOTION_WRITE_SCOPE_OR_PIE')
    mesh = unreal.load_asset(data['mesh'])
    reference = unreal.load_asset(data['reference'])
    pose = _pose(reference, mesh, 0.0)
    left = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_l', unreal.AnimPoseSpaces.WORLD)
    right = unreal.AnimPoseExtensions.get_bone_pose(pose, 'hand_r', unreal.AnimPoseSpaces.WORLD)
    relative = left.make_relative(right)
    grip = {'position':list(relative.translation.to_tuple()), 'rotation':list(relative.rotation.to_tuple()), 'scale':[1,1,1]}
    results = []
    for job in jobs:
        animation = unreal.load_asset(job['animation'])
        before = _tracks(animation)
        metadata = _track_metadata(animation)
        count, rate = batch._frame_count(animation)
        if not unreal.EditorAssetLibrary.does_asset_exist(job['sequence']):
            batch._write_item({'animation_path':job['animation'], 'template_sequence_path':data['template'],
                              'mesh_path':data['mesh'], 'sequence_path':job['sequence'], 'grip_in_hand_r':grip,
                              'contacts':[{'start_frame':0, 'end_frame':count-1, 'fade_in_frames':0, 'fade_out_frames':0}]})
        sequence = unreal.load_asset(job['sequence'])
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
            require_asset_write([animation])
            controller = animation.controller
            controller.open_bracket('校准通用持枪左臂', False)
            try:
                for name in bones:
                    old = before[name]
                    values = tracks[name]
                    if not controller.set_bone_track_keys(name, [v.translation for v in old], [v.rotation for v in values], [v.scale3d for v in old], False):
                        raise RuntimeError('LEFT_HAND_MOTION_WRITE')
            finally:
                controller.close_bracket(False)
            actual = _tracks(animation)
            if set(actual) != set(before) or _track_metadata(animation) != metadata:
                raise RuntimeError('LEFT_HAND_MOTION_METADATA')
            for name, old in before.items():
                if len(old) != len(actual[name]):
                    raise RuntimeError('LEFT_HAND_MOTION_COUNT')
                for i, (a,b) in enumerate(zip(old,actual[name])):
                    expected_rotation = tracks[name][i].rotation if name in bones else a.rotation
                    if a.translation != b.translation or a.scale3d != b.scale3d or distance(list(expected_rotation.to_tuple()),list(b.rotation.to_tuple())) > 0.01:
                        raise RuntimeError('LEFT_HAND_MOTION_READBACK: '+name)
            if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
                raise RuntimeError('LEFT_HAND_MOTION_SAVE')
            results.append({'animation':job['animation'], 'sequence':job['sequence'], 'saved':True, 'samples':count,
                            'nonLeftArmPreserved':True, 'metadataPreserved':True, 'bones':bones})
        finally:
            unreal.purge_object_references(scope, True)
    data['grip_in_hand_r'] = grip
    data['results'] = results
    data['acceptance'] = 'pending_user_review'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return json.dumps(results,ensure_ascii=False)
