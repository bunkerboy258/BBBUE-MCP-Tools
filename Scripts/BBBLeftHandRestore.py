import gc
import json
import math
import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBFingerAnimationTools import _tracks
from BBBRetargetInPlaceBatch import _prepare_tracks, _metadata
import BBBLeftHandMotionCalibration as calibration
import BBBHandRetargetBatchToolset as batch


def run(path, data, write_paths):
    jobs = data['jobs']
    expected = {j[k] for j in jobs for k in ('animation', 'sequence')}
    if set(write_paths) != expected or not jobs or len(jobs) > 32:
        raise ValueError('LEFT_RESTORE_SCOPE')
    targets = [unreal.load_asset(j['animation']) for j in jobs]
    sources = [unreal.load_asset(j['source']) for j in jobs]
    mesh = unreal.load_asset(data['mesh'])
    retargeter = unreal.load_asset(data['retargeter'])
    control = unreal.IKRetargeterController.get_controller(retargeter)
    source_mesh = control.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
    target_mesh = control.get_preview_mesh(unreal.RetargetSourceOrTarget.TARGET)
    if any(not isinstance(a, unreal.AnimSequence) for a in targets + sources) or not source_mesh or not target_mesh:
        raise RuntimeError('LEFT_RESTORE_INVALID_SOURCE')
    require_asset_write(targets)
    if not unreal.BBBRetargetReferenceSession.begin_saved_temp_retarget_mount():
        raise RuntimeError('LEFT_RESTORE_TEMP_MOUNT')
    paths = []
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        inputs = unreal.IKRetargetBatchOperationInputs()
        inputs.assets_to_retarget = [registry.get_asset_by_object_path(unreal.Name(a.get_path_name())) for a in sources]
        inputs.source_mesh = source_mesh
        inputs.target_mesh = target_mesh
        inputs.ik_retarget_asset = retargeter
        inputs.target_path = '/BBBLeftIKTemp/'
        inputs.include_referenced_assets = False
        inputs.overwrite_existing_files = False
        inputs.retain_additive_flags = True
        paths = [str(x.package_name) for x in unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)]
        if len(paths) != len(jobs): raise RuntimeError('LEFT_RESTORE_RETARGET_COUNT: ' + str(paths))
        by_name = {p.rsplit('/', 1)[-1]:p for p in paths}
        results = []
        for job, source, target in zip(jobs, sources, targets):
            baked = unreal.load_asset(by_name[source.get_name()])
            prepared, _, _ = _prepare_tracks(baked, target)
            prior = _tracks(target)
            before_meta = _metadata(target)
            max_right_degrees = 0.0
            for name, positions, rotations, scales in prepared:
                if name.casefold() not in {'upperarm_r', 'lowerarm_r', 'hand_r'}:
                    continue
                for old, new in zip(prior[name], rotations):
                    q = old.rotation
                    dot = abs(q.x*new.x + q.y*new.y + q.z*new.z + q.w*new.w)
                    max_right_degrees = max(max_right_degrees, math.degrees(2 * math.acos(min(1.0, dot))))
            if max_right_degrees > 1.0:
                raise RuntimeError('LEFT_RESTORE_SOURCE_MISMATCH: right arm %.3f degrees' % max_right_degrees)
            allowed = {n.casefold() for n in batch._LEFT_ARM_BONES} - {'ik_hand_l'}
            controller = target.controller
            controller.open_bracket('恢复来源左臂轨道', False)
            try:
                for name, positions, rotations, scales in prepared:
                    if name.casefold() in allowed:
                        old = prior[name]
                        if not controller.set_bone_track_keys(name, [v.translation for v in old], rotations, [v.scale3d for v in old], False):
                            raise RuntimeError('LEFT_RESTORE_WRITE ' + name)
                count, rate = batch._frame_count(target)
                _, max_pos, max_angle = calibration._sync_left_ik(target, mesh, count, rate)
            finally:
                controller.close_bracket(False)
            actual = _tracks(target)
            if _metadata(target) != before_meta or any(actual[n] != prior[n] for n in prior if n.casefold() not in allowed | {'ik_hand_l'}):
                raise RuntimeError('LEFT_RESTORE_OTHER_DATA')
            if not unreal.EditorAssetLibrary.save_loaded_asset(target, False): raise RuntimeError('LEFT_RESTORE_SAVE')
            results.append({'animation':job['animation'], 'source':job['source'], 'saved':True, 'samples':count, 'maxIKPositionCm':max_pos, 'maxIKRotationDegrees':max_angle, 'sourceRightMaxDegrees':max_right_degrees})
        data['results'] = results
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return json.dumps(results, ensure_ascii=False)
    finally:
        sources = targets = []
        gc.collect()
        for temp_path in paths:
            if unreal.EditorAssetLibrary.does_asset_exist(temp_path) and not unreal.EditorAssetLibrary.delete_asset(temp_path):
                raise RuntimeError('LEFT_RESTORE_TEMP_CLEANUP: ' + temp_path)
        if not unreal.BBBRetargetReferenceSession.end_saved_temp_retarget_mount():
            raise RuntimeError('LEFT_RESTORE_UNMOUNT')
