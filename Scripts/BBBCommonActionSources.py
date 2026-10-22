import hashlib
import json
import uuid
from pathlib import Path

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset


def is_finger(name):
    """/** @param name\t骨名 @return\t是否为手指骨 */"""
    return str(name).lower().startswith(('thumb_', 'index_', 'middle_', 'ring_', 'pinky_'))


def load_catalog(recipe_path):
    """/** @param recipe_path\t公共动作制作源 @return\t路径及已校验目录映射 */"""
    project = Path(unreal.Paths.project_dir()).resolve()
    path = (project / recipe_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('format') != 'BBBCommonWeaponActions' or data.get('schema') != 1 or not data.get('approval'):
        raise RuntimeError('COMMON_ACTION_CATALOG_FORMAT')
    root = data['character_root']
    if path.parent != (project / 'Content' / root.removeprefix('/Game/') / 'Source/Animation').resolve():
        raise RuntimeError('COMMON_ACTION_CATALOG_SCOPE')
    return path, data


def source_for(data):
    """/** @param data\t型号制作源 @return\t唯一公共输入要求 */"""
    _, catalog = load_catalog(data['baseline_catalog'])
    keys = catalog['weapons'][data['weapon_root']]
    key = keys[data['action']]
    row = catalog['baselines'][key]
    if data['animation'] != row['animation']:
        raise RuntimeError('COMMON_ACTION_SOURCE_MUST_MATCH_CATALOG')
    return row


def inspect_catalog(recipe_path, write_paths):
    """/** @param recipe_path\t公共目录制作源 @param write_paths\t只读检查的明确占用范围 @return\t全部底稿和型号入口完整性 */"""
    from BBBManualActionAuthoring import _digest, _source
    _, data = load_catalog(recipe_path)
    if set(write_paths) != {row['animation'] for row in data['baselines'].values()}:
        raise RuntimeError('COMMON_CATALOG_INSPECT_SCOPE')
    for row in data['baselines'].values():
        animation = _asset(row['animation'], unreal.AnimSequence)
        if _digest(animation) != row['validation']['animation_digest']:
            raise RuntimeError('COMMON_CATALOG_BASELINE_INVALID')
        if row['finger_policy'] == 'exclude' and any(is_finger(n) for n in animation.data_model_interface.get_bone_track_names()):
            raise RuntimeError('COMMON_CATALOG_EXCLUDED_FINGER_TRACKS')
        if unreal.AnimationLibrary.get_animation_notify_events(animation):
            raise RuntimeError('COMMON_CATALOG_BASELINE_HAS_NOTIFIES')
    count = 0
    for root, actions in data['manual_recipes'].items():
        for action, path in actions.items():
            _, recipe = _source(path)
            if recipe['weapon_root'] != root or recipe['action'] != action:
                raise RuntimeError('COMMON_CATALOG_MANUAL_RECIPE_SCOPE')
            reference = _asset(recipe['animation'], unreal.AnimSequence)
            fingers = _asset(recipe['finger_animation'], unreal.AnimSequence)
            if reference.get_editor_property('skeleton') != fingers.get_editor_property('skeleton'):
                raise RuntimeError('COMMON_CATALOG_SKELETON_MISMATCH')
            if abs(fingers.get_play_length() * recipe['source_time_scale'] - reference.get_play_length()) > 0.0001:
                raise RuntimeError('COMMON_CATALOG_TIME_SCALE: ' + root)
            count += 1
    return {'baselines': len(data['baselines']), 'weapons': len(data['weapons']), 'manual_recipes': count,
            'finger_policy': 'per_baseline', 'baseline_notifies': 0, 'explicit_timing_verified': True, 'assetModified': False}


def adopt_saved(recipe_path, write_paths):
    """/** @param recipe_path\t公共制作源 @param write_paths\t明确公共包占用 @return\t采纳已保存公共手调而不覆盖各枪Offset */"""
    from BBBManualActionAuthoring import _digest, _save
    path, data = load_catalog(recipe_path)
    if set(write_paths) != {row['animation'] for row in data['baselines'].values()}:
        raise RuntimeError('COMMON_ADOPT_SCOPE')
    updated = []
    for row in data['baselines'].values():
        animation = _asset(row['animation'], unreal.AnimSequence)
        source = _asset(row['source'], unreal.AnimSequence)
        if abs(animation.get_play_length() - row['validation']['seconds']) > 0.0001:
            raise RuntimeError('COMMON_ADOPT_LENGTH_REQUIRES_EXPLICIT_MAPPING')
        expected_skeleton = source.get_editor_property('skeleton')
        if row.get('retargeter'):
            expected_skeleton = _asset(row['target_mesh'], unreal.SkeletalMesh).get_editor_property('skeleton')
        if animation.get_editor_property('skeleton') != expected_skeleton:
            raise RuntimeError('COMMON_ADOPT_SKELETON')
        if row['finger_policy'] == 'exclude' and any(is_finger(n) for n in animation.data_model_interface.get_bone_track_names()):
            raise RuntimeError('COMMON_ADOPT_FINGER_POLICY')
        if unreal.AnimationLibrary.get_animation_notify_events(animation):
            raise RuntimeError('COMMON_ADOPT_FINGER_OR_NOTIFY')
        signature = _digest(animation)
        if signature != row['validation']['animation_digest']:
            row['validation']['animation_digest'] = signature
            row['validation']['body_edited_in_common_asset'] = True
            row['validation'].pop('body_track_error_cm', None)
            updated.append(row['animation'])
    _save(path, data)
    return {'adopted_common_animations': updated, 'assetModified': False, 'next': 'prepare_action_then_bake_each_affected_weapon'}


def build(recipe_path, write_paths):
    """/** @param recipe_path\t公共制作源 @param write_paths\t明确公共输出包 @return\t不含手指的正式公共动作及回读 */"""
    from BBBManualActionAuthoring import _digest, _save
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('COMMON_ACTION_PIE_FORBIDDEN')
    path, data = load_catalog(recipe_path)
    rows = list(data['baselines'].values())
    if set(write_paths) != {r['animation'] for r in rows}:
        raise RuntimeError('COMMON_ACTION_WRITE_SCOPE')
    reports = []
    for row in rows:
        source = _asset(row['source'], unreal.AnimSequence)
        destination = row['animation']
        if not destination.startswith(data['character_root'] + '/Animation/UsedAnimation/'):
            raise RuntimeError('COMMON_ACTION_DESTINATION_SCOPE')
        expected = [str(n) for n in source.data_model_interface.get_bone_track_names() if not is_finger(n)]
        if row.get('validation'):
            output = _asset(destination, unreal.AnimSequence)
            if _digest(source) != row['validation']['source_digest'] or _digest(output) != row['validation']['animation_digest']:
                raise RuntimeError('COMMON_ACTION_CHANGED_REQUIRES_EXPLICIT_REBUILD')
            reports.append(row['validation'])
            continue
        require_asset_write([], destinations=[destination])
        output = None
        if unreal.EditorAssetLibrary.does_asset_exist(destination):
            if row.get('state') != 'creating':
                raise RuntimeError('COMMON_ACTION_UNOWNED_DESTINATION: ' + destination)
            output = _asset(destination, unreal.AnimSequence)
        if output is None:
            row['state'] = 'creating'
            _save(path, data)
            output = unreal.EditorAssetLibrary.duplicate_asset(row['source'], destination)
        if output is None:
            raise RuntimeError('COMMON_ACTION_CREATE')
        require_asset_write([output])
        controller = output.controller
        controller.open_bracket('建立不含手指覆盖的公共动作底稿', False)
        try:
            for bone in list(output.data_model_interface.get_bone_track_names()):
                if is_finger(bone) and not controller.remove_bone_track(bone, False):
                    raise RuntimeError('COMMON_ACTION_REMOVE_FINGER: ' + str(bone))
        finally:
            controller.close_bracket(False)
        unreal.AnimationLibrary.remove_all_animation_notify_tracks(output)
        names = [str(n) for n in output.data_model_interface.get_bone_track_names()]
        if names != expected:
            raise RuntimeError('COMMON_ACTION_BONE_SET')
        for bone in expected:
            a = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, bone)
            b = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(output, bone)
            if len(a) != len(b) or any(x.export_text() != y.export_text() for x, y in zip(a, b)):
                raise RuntimeError('COMMON_ACTION_BODY_CHANGED: ' + bone)
        if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('COMMON_ACTION_SAVE')
        row['validation'] = {'animation': destination, 'source_digest': _digest(source),
                             'animation_digest': _digest(output), 'body_bones': len(expected),
                             'body_track_error_cm': 0.0, 'finger_tracks': 0,
                             'seconds': output.get_play_length()}
        row['state'] = 'ready'
        reports.append(row['validation'])
        _save(path, data)
    return {'common_baselines': reports, 'runtimeModified': False}


def prepare_base(data, sequence):
    """/** @param data\t公共输入与型号输出分离的制作源 @param sequence\t保留手调的型号序列 @return\t公共身体底稿接入和手调保留证明 */"""
    from BBBControlRigAuthoringToolset import _mesh_binding, _pose, _key
    from BBBManualActionAuthoring import _digest
    import BBBManualActionNative as native
    reference = _asset(data['animation'], unreal.AnimSequence)
    signature = _digest(reference)
    if data.get('common_base', {}).get('source_digest') == signature and data['common_base'].get('source_time_scale') == data['source_time_scale']:
        data['source_track_digest'] = signature
        return data['common_base']
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    if abs(source.get_play_length() * data['source_time_scale'] - reference.get_play_length()) > 0.0001:
        raise RuntimeError('COMMON_BASE_LENGTH')
    rate = sequence.get_display_rate()
    expected_rate = reference.data_model_interface.get_frame_rate()
    if rate.numerator * expected_rate.denominator != expected_rate.numerator * rate.denominator:
        raise RuntimeError('COMMON_BASE_DISPLAY_RATE')
    binding = _mesh_binding(sequence, mesh)
    tracks = binding.find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1:
        raise RuntimeError('COMMON_BASE_SINGLE_CONTROL_TRACK')
    track = tracks[0]
    bases = [s for s in track.get_sections() if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE]
    if len(bases) != 1:
        raise RuntimeError('COMMON_BASE_SINGLE_ABSOLUTE')
    proxies = [p for p in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence) if p.track == track]
    if len(proxies) != 1:
        raise RuntimeError('COMMON_BASE_RIG_INSTANCE')
    hierarchy = proxies[0].control_rig.get_hierarchy()
    names = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(_pose(reference, mesh, 0)) if not is_finger(n)]
    controls = {'source_' + n: n for n in names}
    controls.update({kind + '_' + side + suffix: bone + '_' + side for side in ('r', 'l')
                     for kind, suffix, bone in [('clavicle', '_ctrl', 'clavicle'), ('hand', '_ik_ctrl', 'hand'), ('elbow', '_pv_ctrl', 'lowerarm')]})
    values = {name: [] for name in controls}
    count = source.data_model_interface.get_number_of_keys()
    for frame in range(count):
        pose = _pose(reference, mesh, frame * rate.denominator / rate.numerator * data['source_time_scale'])
        for name, bone in controls.items():
            transform = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD)
            offset = hierarchy.get_global_control_offset_transform(_key(name, 'CONTROL'), True)
            values[name].append(transform.make_relative(offset))
    suffixes = ('Location.X', 'Location.Y', 'Location.Z', 'Rotation.X', 'Rotation.Y', 'Rotation.Z', 'Scale.X', 'Scale.Y', 'Scale.Z')
    def preserved_rows(target):
        rows = []
        for b in target.get_bindings():
            for t in b.get_tracks():
                for section in t.get_sections():
                    body_base = isinstance(t, unreal.MovieSceneControlRigParameterTrack) and section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE
                    for channel in section.get_all_channels():
                        name = str(channel.channel_name)
                        if body_base and name.split('.')[0] in controls:
                            continue
                        keys = []
                        for key in channel.get_keys():
                            stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                            keys.append([stamp.frame_number.value, stamp.sub_frame, str(key.get_value())])
                        rows.append([b.get_id().export_text(), name, str(channel.get_default()), keys])
        return hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    def write_base(target):
        base = [s for s in _mesh_binding(target, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)[0].get_sections()
                if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE][0]
        base.set_is_locked(False)
        channels = {str(c.channel_name): c for c in base.get_all_channels()}
        for name, transforms in values.items():
            targets = [channels[name + '.' + suffix] for suffix in suffixes]
            for channel in targets:
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
            previous = None
            for frame, transform in enumerate(transforms):
                rotation = transform.rotation.rotator()
                angles = [rotation.roll, rotation.pitch, rotation.yaw]
                if previous is not None:
                    angles = [a + 360 * round((b - a) / 360) for a, b in zip(angles, previous)]
                previous = angles
                numbers = list(transform.translation.to_tuple()) + angles + list(transform.scale3d.to_tuple())
                for channel, number in zip(targets, numbers):
                    channel.add_key(unreal.FrameNumber(value=frame), number, 0.0, unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)
        base.set_is_locked(True)
    require_asset_write([sequence])
    preserved = preserved_rows(sequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBCommonBase_' + uuid.uuid4().hex)
    try:
        copied = native._copy_sequence(sequence, scope, 'Sequence')
        native._export(copied, source, mesh, scope, 'Initialize', False)
        write_base(copied)
        for section in _mesh_binding(copied, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)[0].get_sections():
            if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE:
                section.set_is_active(False)
        baseline = native._export(copied, source, mesh, scope, 'CommonOnly')
        maximum = 0.0
        for frame in range(count):
            time = frame * rate.denominator / rate.numerator
            a = _pose(reference, mesh, time * data['source_time_scale'])
            b = _pose(baseline, mesh, time)
            for bone in names:
                if bone.lower().startswith('ik_hand_'):
                    continue
                left = unreal.AnimPoseExtensions.get_bone_pose(a, bone, unreal.AnimPoseSpaces.WORLD)
                right = unreal.AnimPoseExtensions.get_bone_pose(b, bone, unreal.AnimPoseSpaces.WORLD)
                error = (left.translation - right.translation).length()
                maximum = max(maximum, error)
                cosine = abs(sum(x * y for x, y in zip(left.rotation.to_tuple(), right.rotation.to_tuple())))
                if error > 0.05 or cosine < 0.99999:
                    raise RuntimeError('COMMON_BASE_PREVIEW: %s frame=%d cm=%f cosine=%f' % (bone, frame, error, cosine))
        write_base(sequence)
        if preserved_rows(sequence) != preserved:
            raise RuntimeError('COMMON_BASE_LOST_MANUAL_KEYS_OR_ATTACHMENTS')
        for animation_track in binding.find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack):
            for section in animation_track.get_sections():
                params = section.get_editor_property('params')
                params.animation = reference
                params.play_rate = unreal.MovieSceneTimeWarpExtensions.make_time_warp(data['source_time_scale'])
                section.set_editor_property('params', params)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('COMMON_BASE_SAVE')
        data['source_track_digest'] = signature
        data['common_base'] = {'source': data['animation'], 'source_digest': signature, 'frames': count,
                               'source_time_scale': data['source_time_scale'],
                               'body_preview_error_cm': maximum, 'preserved_channel_digest': preserved,
                               'manual_additive_and_fingers_preserved': True, 'runtimeModified': False}
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
        return data['common_base']
    finally:
        unreal.purge_object_references(scope, True)
