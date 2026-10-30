import json
import re
from pathlib import Path

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBAnimationCurveTools import _curve_values, _curve_semantics, _shifted_curve, _write_shifted_curves, _bone_digest, _animation_metadata


def apply_curves(animation, curves):
    """/** @param animation	明确目标 @param curves	正式完整浮点曲线文本 @return 全键与插值回读 */"""
    prepared = []
    expected = {}
    for name, text in curves.items():
        curve = unreal.FloatCurve()
        curve.import_text(text)
        item = _shifted_curve(curve, 0)
        if item['name'].casefold() != name.casefold():
            raise RuntimeError('METADATA_CURVE_NAME_MISMATCH')
        prepared.append(item)
        expected[name.casefold()] = _curve_semantics(text)
    for name in unreal.AnimationLibrary.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT):
        identifier = unreal.AnimationCurveIdentifier()
        identifier.set_curve_identifier(name, unreal.RawCurveTrackTypes.RCT_FLOAT)
        if not animation.controller.remove_curve(identifier, False):
            raise RuntimeError('METADATA_CURVE_REMOVE_FAILED')
    _write_shifted_curves(animation, prepared)
    for name, text in curves.items():
        identifier = unreal.AnimationCurveIdentifier()
        identifier.set_curve_identifier(name, unreal.RawCurveTrackTypes.RCT_FLOAT)
        color = re.search(r'Color=\(R=([^,]+),G=([^,]+),B=([^,]+),A=([^\)]+)\)', text)
        if color:
            animation.controller.set_curve_color(identifier, unreal.LinearColor(*[float(v) for v in color.groups()]), False)
        comment = re.search(r'Comment=("(?:\\.|[^"\\])*")', text)
        if comment:
            animation.controller.set_curve_comment(identifier, json.loads(comment.group(1)), False)
    if _curve_values(animation) != expected:
        raise RuntimeError('METADATA_CURVE_READBACK_FAILED')
    return expected


def apply_profile(animation, recipe_path):
    """/** @param animation	烘焙目标 @param recipe_path	正式元数据源 @return 应用曲线与预览并保留骨轨 */"""
    root = Path(unreal.Paths.project_dir()).resolve()
    path = (root / recipe_path).resolve()
    if not path.is_relative_to(root / 'Content/_Project') or path.parent.parts[-2:] != ('Source', 'Animation'):
        raise RuntimeError('METADATA_PROFILE_SCOPE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBAnimationMetadata':
        raise RuntimeError('METADATA_PROFILE_FORMAT')
    jobs = [job for job in data['jobs'] if job['animation'] == animation.get_path_name().split('.')[0]]
    if len(jobs) != 1:
        raise RuntimeError('METADATA_PROFILE_UNIQUE_OUTPUT')
    job = jobs[0]
    mesh = unreal.load_asset(job['preview_mesh']) if job.get('preview_mesh') else None
    if job.get('preview_mesh') and (not isinstance(mesh, unreal.SkeletalMesh) or mesh.get_editor_property('skeleton') != animation.get_skeleton()):
        raise RuntimeError('METADATA_PROFILE_PREVIEW_SKELETON')
    require_asset_write([animation])
    if 'float_curves' in job:
        apply_curves(animation, job['float_curves'])
    if mesh:
        animation.set_preview_skeletal_mesh(mesh)


def process(recipe_path, action, write_paths, job_index):
    """
    /**
     * 从正式制作源恢复曲线和同骨架预览网格
     * @param recipe_path	自有 Source/Animation 制作源
     * @param action	inspect 或 bake
     * @param write_paths	唯一目标
     * @param job_index	明确任务
     * @return 保持骨轨和通知的保存回读证据
     */
    """
    root = Path(unreal.Paths.project_dir()).resolve()
    path = (root / recipe_path).resolve()
    if not path.is_relative_to(root / 'Content/_Project') or path.parent.parts[-2:] != ('Source', 'Animation'):
        raise RuntimeError('METADATA_SOURCE_SCOPE')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBAnimationMetadata' or action not in ('inspect', 'bake'):
        raise RuntimeError('METADATA_SOURCE_FORMAT_OR_ACTION')
    if not isinstance(job_index, int) or job_index < 0 or job_index >= len(data['jobs']):
        raise RuntimeError('METADATA_JOB_INDEX')
    job = data['jobs'][job_index]
    if set(write_paths) != {job['animation']}:
        raise RuntimeError('METADATA_WRITE_SCOPE')
    animation = unreal.load_asset(job['animation'])
    if not isinstance(animation, unreal.AnimSequence) or not job['animation'].startswith('/Game/_Project/'):
        raise RuntimeError('METADATA_SEQUENCE_REQUIRED')
    getter = getattr(animation, 'get_preview_mesh', None)
    before_preview = getter().get_path_name() if getter and getter() else None
    if action == 'inspect':
        return {'animation': job['animation'], 'preview_before': before_preview,
                'preview_methods': [name for name in dir(animation) if 'preview' in name], 'curves': _curve_values(animation)}
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('METADATA_PIE_FORBIDDEN')
    mesh = unreal.load_asset(job['preview_mesh']) if job.get('preview_mesh') else None
    if job.get('preview_mesh') and (not isinstance(mesh, unreal.SkeletalMesh) or mesh.get_editor_property('skeleton') != animation.get_skeleton()):
        raise RuntimeError('METADATA_PREVIEW_SKELETON')
    require_asset_write([animation])
    bones = _bone_digest(animation)
    metadata = _animation_metadata(animation)
    apply_profile(animation, recipe_path)
    if _bone_digest(animation) != bones or _animation_metadata(animation) != metadata:
        raise RuntimeError('METADATA_NONCURVE_DATA_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(animation, False):
        raise RuntimeError('METADATA_SAVE_FAILED')
    result = {'animation': job['animation'], 'bones_preserved': True, 'metadata_preserved': True,
              'preview_mesh': job.get('preview_mesh'), 'curve_count': len(_curve_values(animation)), 'saved': True}
    job['result'] = result
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
