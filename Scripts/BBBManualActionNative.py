import uuid
import hashlib
import json
import math

import unreal

from BBBAssetWritePolicy import require_asset_write
from BBBControlRigAuthoringToolset import _asset, _mesh_binding
from BBBManualActionAuthoring import _source, _save, _digest


def repair_timeline_range(sequence):
    """Repair invalid editor ranges without altering animation channels or valid zoom."""
    before = {'view': [sequence.get_view_range_start(), sequence.get_view_range_end()],
              'work': [sequence.get_work_range_start(), sequence.get_work_range_end()]}
    invalid = any(not all(math.isfinite(v) for v in bounds) or bounds[1] <= bounds[0]
                  for bounds in before.values())
    if not invalid:
        return {'repaired': False, **before}
    signature = _channel_digest(sequence)
    playback = [sequence.get_playback_start(), sequence.get_playback_end()]
    rate = sequence.get_display_rate()
    start, end = [frame * rate.denominator / rate.numerator for frame in playback]
    if end <= start:
        raise RuntimeError('TIMELINE_INVALID_PLAYBACK_RANGE')
    margin = max((end - start) * 0.05, rate.denominator / rate.numerator)
    bounds = [start - margin, end + margin]
    require_asset_write([sequence])
    editors = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
    closed_editors = editors.close_all_editors_for_asset(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
    sequence.set_work_range_start(bounds[0])
    sequence.set_work_range_end(bounds[1])
    sequence.set_view_range_start(bounds[0])
    sequence.set_view_range_end(bounds[1])
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('TIMELINE_RANGE_SAVE')
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(playback[0])
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    after = {'view': [sequence.get_view_range_start(), sequence.get_view_range_end()],
             'work': [sequence.get_work_range_start(), sequence.get_work_range_end()]}
    if any(not all(math.isfinite(v) for v in values) or values[1] <= values[0] for values in after.values()):
        raise RuntimeError('TIMELINE_RANGE_READBACK')
    if _channel_digest(sequence) != signature or playback != [sequence.get_playback_start(), sequence.get_playback_end()]:
        raise RuntimeError('TIMELINE_CHANNELS_CHANGED')
    return {'repaired': True, 'before': {key: [v if math.isfinite(v) else str(v) for v in values]
                                        for key, values in before.items()},
            **after, 'closed_asset_editors': closed_editors,
            'channels_preserved': True, 'playback_preserved': True}


def sync_reload_timing(path, data, write_paths):
    """Apply explicit magazine frame timing to both configured montages, retaining notify instances."""
    if data['action'] != 'reload' or unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('RELOAD_TIMING_EDITOR_ONLY')
    single = data.get('single_reload_application_timing')
    timing = single or data['rifle_reload_timing']
    fps = float(timing['display_fps'])
    out_time, in_time = ((timing['held_object_frames'][0] / fps, timing['load_frame'] / fps) if single
                         else (timing['magazine_out_frame'] / fps, timing['magazine_in_frame'] / fps))
    duration = _asset(data['output_animation'], unreal.AnimSequence).get_play_length() if single else None
    if single and (not data.get('runtime_applied') or in_time >= duration):
        raise RuntimeError('SINGLE_RELOAD_REQUIRES_APPLIED_BAKE')
    scale = float(data['source_time_scale']) if timing.get('time_space') == 'common_source' else 1.0
    if not math.isfinite(scale) or scale <= 0:
        raise RuntimeError('RELOAD_TIMING_SOURCE_SCALE')
    out_time, in_time = out_time / scale, in_time / scale
    if not 0 < out_time < in_time or not all(math.isfinite(v) for v in (out_time, in_time)):
        raise RuntimeError('RELOAD_TIMING_FRAME_RANGE')
    definition = _asset(data['definition'], unreal.DataAsset)
    owners = [definition.get_editor_property(name) for name in ('character_reload_montage', 'equipment_reload_montage')]
    if set(write_paths) != {owner.get_path_name().split('.')[0] for owner in owners}:
        raise RuntimeError('RELOAD_TIMING_WRITE_SCOPE')
    from BBBManualActionAuthoring import _single_segment
    library = unreal.AnimationLibrary
    reports = []
    metadata = ('TriggerWeightThreshold', 'MontageTickType', 'NotifyTriggerChance',
                'NotifyFilterType', 'NotifyFilterLOD', 'bCanBeFilteredViaRequest',
                'bTriggerOnDedicatedServer', 'bTriggerOnFollower')
    for role, owner in zip(('character', 'weapon'), owners):
        segment = _single_segment(owner)
        if role == 'character' and abs(segment.get_editor_property('anim_play_rate') - 1.0) > 1e-6:
            raise RuntimeError('RELOAD_TIMING_REQUIRES_UNIT_RATE')
        original = list(library.get_animation_notify_events(owner))
        native = json.loads(unreal.BBBHandPoseLayerEditorLibrary.inspect_animation_notify_timing(owner))['events']
        track_names = list(library.get_animation_notify_track_names(owner))
        plans = []
        time_scale = duration / owner.get_play_length() if single and role == 'weapon' else 1.0
        for event, row in zip(original, native):
            state = event.get_editor_property('notify_state_class')
            notify = state or event.get_editor_property('notify')
            name = notify.get_class().get_name() if notify else ''
            matches = [str(t) for t in track_names if any(
                (e.get_editor_property('notify_state_class') or e.get_editor_property('notify')) == notify
                for e in library.get_animation_notify_events_for_track(owner, t))]
            if len(matches) != 1:
                raise RuntimeError('RELOAD_TIMING_TRACK_IDENTITY')
            track = matches[0]
            start, end = row['nativeTriggerTime'], row['nativeEndTriggerTime']
            new_start, new_end = start * time_scale, end * time_scale
            if single and role == 'character' and name == 'BBBCharacterHeldObjectDisplayAnimNotifyState':
                new_start, new_end = out_time, in_time
            elif role == 'character' and name == 'BBBCharacterOldMagazineDisplayAnimNotifyState':
                new_start = out_time
            elif role == 'character' and name == 'BBBCharacterNewMagazineDisplayAnimNotifyState':
                new_end = in_time
            elif role == 'weapon' and name == 'BBBEquipmentBoneVisibilityDisplayAnimNotifyState':
                new_start, new_end = (start * time_scale if single else out_time), in_time
            elif role == 'weapon' and name in ('BBBRifleLoadMagazineLogicAnimNotifyState', 'BBBEquipmentLoadAmmoLogicAnimNotifyState'):
                new_start, new_end = in_time, min(duration, in_time + 1/fps) if single else in_time + (end - start)
            elif single and role == 'weapon' and name in (
                    'BBBEquipmentReloadLifecycleLogicAnimNotifyState', 'BBBRifleReloadLifecycleLogicAnimNotifyState'):
                new_end = duration
            elif single and role == 'weapon' and name == 'BBBEquipmentBlockFireLogicAnimNotifyState':
                new_end = duration - 1/fps
            elif single and role == 'weapon' and name == 'BBBEquipmentAllowFireLogicAnimNotify':
                new_start = new_end = duration - 1/fps
            elif role == 'weapon' and 'reload_end_seconds' in timing and name in (
                    'BBBRifleReloadLifecycleLogicAnimNotifyState', 'BBBEquipmentReloadLifecycleLogicAnimNotifyState',
                    'BBBEquipmentBlockFireLogicAnimNotifyState'):
                new_end = float(timing['reload_end_seconds'])
            elif role == 'weapon' and 'reload_end_seconds' in timing and name == 'BBBEquipmentAllowFireLogicAnimNotify':
                new_start = new_end = float(timing['reload_end_seconds'])
            elif not single and track == 'BBB_MagazineOutAudio':
                new_start = new_end = out_time
            elif track == 'BBB_MagazineInAudio':
                new_start = new_end = in_time
            if new_end < new_start or new_end > (duration if single else owner.get_play_length()) + 1e-5:
                raise RuntimeError('RELOAD_TIMING_NOTIFY_RANGE')
            plans.append((event, notify, state is not None, track, new_start, new_end,
                          abs(new_start-start)>1e-5 or abs(new_end-end)>1e-5))
        kinds = [p[1].get_class().get_name() for p in plans if p[1] is not None]
        required_kinds = (('BBBCharacterOldMagazineDisplayAnimNotifyState', 'BBBCharacterNewMagazineDisplayAnimNotifyState')
                          if role == 'character' else ('BBBEquipmentBoneVisibilityDisplayAnimNotifyState',))
        if single and role == 'character':
            if not kinds or any(kind != 'BBBCharacterHeldObjectDisplayAnimNotifyState' for kind in kinds):
                raise RuntimeError('SINGLE_RELOAD_HELD_OBJECT_NOTIFIES_REQUIRED')
        elif any(kinds.count(kind) != 1 for kind in required_kinds):
            raise RuntimeError('RELOAD_TIMING_REQUIRES_MAGAZINE_RELOAD')
        if role == 'weapon' and sum(kinds.count(kind) for kind in
                ('BBBRifleLoadMagazineLogicAnimNotifyState', 'BBBEquipmentLoadAmmoLogicAnimNotifyState')) != 1:
            raise RuntimeError('RELOAD_TIMING_LOAD_EVENT_REQUIRED')
        changed_tracks = {p[3] for p in plans if p[6]}
        require_asset_write([owner])
        if changed_tracks or (single and role == 'weapon'):
            owner.modify()
            if single and role == 'weapon':
                slots = list(owner.get_editor_property('slot_anim_tracks'))
                slot = slots[0]
                anim_track = slot.get_editor_property('anim_track')
                segments = list(anim_track.get_editor_property('anim_segments'))
                segments[0].set_editor_property('anim_play_rate',
                    segments[0].get_editor_property('anim_reference').get_play_length() / duration)
                anim_track.set_editor_property('anim_segments', segments)
                slot.set_editor_property('anim_track', anim_track)
                owner.set_editor_property('slot_anim_tracks', slots)
                output = _asset(data['output_animation'], unreal.AnimSequence)
                owner.controller.set_frame_rate(output.data_model_interface.get_frame_rate())
                owner.controller.set_number_of_frames(unreal.FrameNumber(value=output.data_model_interface.get_number_of_keys()-1))
                if abs(owner.get_play_length() - duration) > 0.00001:
                    raise RuntimeError('SINGLE_RELOAD_WEAPON_LENGTH')
            for track in changed_tracks:
                library.remove_animation_notify_events_by_track(owner, track)
                for event, notify, is_state, event_track, start, end, changed in plans:
                    if event_track != track:
                        continue
                    if is_state:
                        library.add_animation_notify_state_event_object(owner, start, end-start, notify, track)
                    else:
                        library.add_animation_notify_event_object(owner, start, notify, track)
            actual = list(library.get_animation_notify_events(owner))
            for event, notify, is_state, track, start, end, changed in plans:
                matches = [e for e in actual if (e.get_editor_property('notify_state_class') or e.get_editor_property('notify')) == notify]
                if len(matches) != 1:
                    raise RuntimeError('RELOAD_TIMING_INSTANCE_IDENTITY')
                if track in changed_tracks:
                    for prop in metadata:
                        if matches[0].get_editor_property(prop) != event.get_editor_property(prop):
                            raise RuntimeError('RELOAD_TIMING_METADATA_CHANGED: ' + prop)
            if not unreal.EditorAssetLibrary.save_loaded_asset(owner, False):
                raise RuntimeError('RELOAD_TIMING_SAVE')
        after = json.loads(unreal.BBBHandPoseLayerEditorLibrary.inspect_animation_notify_timing(owner))['events']
        if len(after) != len(plans):
            raise RuntimeError('RELOAD_TIMING_EVENT_COUNT')
        for event, notify, is_state, track, start, end, changed in plans:
            rows = [r for r in after if r['notifyInstance'] == notify.get_path_name()]
            if len(rows) != 1 or abs(rows[0]['nativeTriggerTime']-start)>1e-5 or abs(rows[0]['nativeEndTriggerTime']-end)>1e-5:
                raise RuntimeError('RELOAD_TIMING_READBACK')
        reports.append({'montage': owner.get_path_name(), 'changed_tracks': sorted(changed_tracks),
                        'notify_instances_preserved': True, 'events': after})
    data.pop('reload_timing_request', None)
    data['reload_timing_applied'] = {'out_frame': out_time * fps, 'in_frame': in_time * fps, 'fps': fps}
    if single:
        single['weapon_timing_sync_pending'] = False
        data['reload_timing_applied'].update(single_load=True, seconds=duration)
    _save(path, data)
    return {'timing': data['reload_timing_applied'], 'montages': reports, 'manual_keys_modified': False}


def prepare_right_wrist_preview(data, sequence):
    """Show the runtime parent-bone wrist correction; export removes it to avoid double application."""
    if not data.get('runtime_right_wrist_preview'):
        return
    definition = _asset(data['definition'], unreal.DataAsset)
    delta = definition.get_editor_property('right_hand_grip_rotation_offset').quaternion().normalized()
    tag = 'BBB_RuntimeRightWristPreview'
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    graph = asset.get_controller()
    names = ('RuntimeWristRead', 'RuntimeWristRotation', 'RuntimeWristApply')
    existing = graph.get_graph().find_node_by_name(names[2])
    encoded = json.dumps(list(delta.to_tuple()))
    if (existing is not None and unreal.EditorAssetLibrary.get_metadata_tag(sequence, tag) == encoded
            and float(graph.get_graph().find_pin('RuntimeWristApply.Weight').get_default_value()) == 1.0):
        return
    require_asset_write([asset, sequence])
    signature = _channel_digest(sequence)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBWristPreview_' + uuid.uuid4().hex)
    try:
        before = _export(sequence, source, mesh, scope, 'BeforeWrist')
        if existing is None:
            specs = [(names[0], '/Script/ControlRig.RigUnit_GetTransform', {'Item': '(Type=Bone,Name="hand_r")', 'Space': 'LocalSpace'}),
                     (names[1], '/Script/RigVM.RigVMFunction_MathQuaternionMul', {}),
                     (names[2], '/Script/ControlRig.RigUnit_SetTransform', {'Item': '(Type=Bone,Name="hand_r")', 'Space': 'LocalSpace', 'bPropagateToChildren': 'True'})]
            for name, struct, defaults in specs:
                if graph.add_unit_node_from_struct_path(struct, 'Execute', unreal.Vector2D(1600, 1000), name, False, False) is None:
                    raise RuntimeError('WRIST_PREVIEW_NODE: ' + name)
                for prop, value in defaults.items():
                    if not graph.set_pin_default_value(name + '.' + prop, value, True, False, False, False):
                        raise RuntimeError('WRIST_PREVIEW_PIN: ' + prop)
            graph.break_link('Apply_ik_hand_l.ExecutePin', 'FKApply_thumb_01_l.ExecutePin', False)
            links = [('Apply_ik_hand_l.ExecutePin', names[2]+'.ExecutePin'),
                     (names[2]+'.ExecutePin', 'FKApply_thumb_01_l.ExecutePin'),
                     (names[0]+'.Transform.Rotation', names[1]+'.B'),
                     (names[1]+'.Result', names[2]+'.Value.Rotation'),
                     (names[0]+'.Transform.Translation', names[2]+'.Value.Translation'),
                     (names[0]+'.Transform.Scale3D', names[2]+'.Value.Scale3D')]
            for start, end in links:
                if not graph.add_link(start, end, False, False):
                    raise RuntimeError('WRIST_PREVIEW_LINK: ' + start + ' -> ' + end)
        value = '(X=%s,Y=%s,Z=%s,W=%s)' % delta.to_tuple()
        if not graph.set_pin_default_value(names[1]+'.A', value, True, False, False, False):
            raise RuntimeError('WRIST_PREVIEW_DELTA')
        graph.set_pin_default_value('RuntimeWristApply.Weight', '1.0', True, False, False, False)
        asset.recompile_vm()
        unreal.EditorAssetLibrary.set_metadata_tag(sequence, tag, encoded)
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
        after = _export(sequence, source, mesh, scope, 'AfterWrist')
        error = _compare(before, after)
        if _channel_digest(sequence) != signature:
            raise RuntimeError('WRIST_PREVIEW_KEYS_CHANGED')
        for item in (asset, sequence):
            if not unreal.EditorAssetLibrary.save_loaded_asset(item, False):
                raise RuntimeError('WRIST_PREVIEW_SAVE')
        data['right_wrist_preview'] = {'runtime_delta': list(delta.to_tuple()), 'raw_bake_error_cm': error,
                                      'all_channel_keys_preserved': True, 'export_compensation': 'inverse_parent_bone_delta'}
    finally:
        unreal.purge_object_references(scope, True)


def refresh_magazine_preview_timing(data, sequence):
    """Refresh existing magazine lifetime ranges without rebuilding bindings or authored transforms."""
    if not data.pop('preview_timing_request', False):
        return
    from BBBManualActionAuthoring import _notify_events, _single_segment, _weapon_preview_animation
    definition = _asset(data['definition'], unreal.DataAsset)
    character = definition.get_editor_property('character_reload_montage')
    weapon = definition.get_editor_property('equipment_reload_montage')
    segment = _single_segment(weapon)
    signature = _channel_digest(sequence)
    require_asset_write([sequence])
    rate = sequence.get_display_rate()
    fps = rate.numerator / rate.denominator
    updated = []
    for state, start, end in _notify_events(character):
        if state is None:
            continue
        kind = state.get_class().get_name()
        label = {'BBBCharacterOldMagazineDisplayAnimNotifyState': 'OldMagazine',
                 'BBBCharacterNewMagazineDisplayAnimNotifyState': 'NewMagazine'}.get(kind)
        if label is None:
            continue
        bindings = [b for b in sequence.get_bindings() if b.get_name() == label]
        if len(bindings) != 1:
            raise RuntimeError('PREVIEW_MAGAZINE_BINDING')
        sections = [s for t in bindings[0].find_tracks_by_type(unreal.MovieSceneBindingLifetimeTrack) for s in t.get_sections()]
        if len(sections) != 1:
            raise RuntimeError('PREVIEW_MAGAZINE_LIFETIME')
        bounds = [math.ceil(start*fps-0.0001), math.ceil(end*fps-0.0001)]
        sections[0].set_range(*bounds)
        for row in data['weapon_preview']['magazines']:
            if row['label'] == label:
                row['ranges'] = [bounds]
        updated.append({'label': label, 'frames': bounds})
    _, visibility = _weapon_preview_animation(data, segment.get_editor_property('anim_reference'), weapon,
                                              segment.get_editor_property('anim_play_rate'))
    data['weapon_preview']['bone_visibility'] = visibility
    if _channel_digest(sequence) != signature:
        raise RuntimeError('PREVIEW_MAGAZINE_KEYS_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('PREVIEW_MAGAZINE_SAVE')
    data['preview_timing_refresh'] = {'lifetimes': updated, 'all_control_and_transform_keys_preserved': True}


def apply_baked_animation(path, data, write_paths):
    """Apply a confirmed bake to the existing single montage segment without resetting blend/notify settings."""
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('ACTION_APPLY_PIE_FORBIDDEN')
    if data.get('bake_result', {}).get('animation') != data['output_animation']:
        raise RuntimeError('ACTION_APPLY_REQUIRES_BAKE_RESULT')
    definition = _asset(data['definition'], unreal.DataAsset)
    from BBBManualActionAuthoring import ACTION_MONTAGE_FIELDS
    montage = definition.get_editor_property(ACTION_MONTAGE_FIELDS[data['action']][0])
    if set(write_paths) != {montage.get_path_name().split('.')[0]}:
        raise RuntimeError('ACTION_APPLY_WRITE_SCOPE')
    output = _asset(data['output_animation'], unreal.AnimSequence)
    if output.get_editor_property('skeleton') != montage.get_editor_property('skeleton'):
        raise RuntimeError('ACTION_APPLY_SKELETON')
    from BBBManualActionAuthoring import _single_segment
    _single_segment(montage)
    require_asset_write([montage])
    montage.modify()
    slots = list(montage.get_editor_property('slot_anim_tracks'))
    slot = slots[0]
    track = slot.get_editor_property('anim_track')
    segments = list(track.get_editor_property('anim_segments'))
    segment = segments[0]
    segment.set_editor_property('anim_reference', output)
    segment.set_editor_property('anim_start_time', 0.0)
    segment.set_editor_property('anim_end_time', output.get_play_length())
    segment.set_editor_property('anim_play_rate', 1.0)
    track.set_editor_property('anim_segments', segments)
    slot.set_editor_property('anim_track', track)
    montage.set_editor_property('slot_anim_tracks', slots)
    rate = output.data_model_interface.get_frame_rate()
    montage.controller.set_frame_rate(rate)
    montage.controller.set_number_of_frames(unreal.FrameNumber(value=output.data_model_interface.get_number_of_keys()-1))
    if abs(montage.get_play_length()-output.get_play_length()) > 1e-5:
        raise RuntimeError('ACTION_APPLY_LENGTH')
    if not unreal.EditorAssetLibrary.save_loaded_asset(montage, False):
        raise RuntimeError('ACTION_APPLY_SAVE')
    data.pop('apply_baked_request', None)
    data['runtime_applied'] = True
    data['runtime_montage'] = montage.get_path_name().split('.')[0]
    data['bake_result']['visualAcceptance'] = 'user_confirmed'
    data['bake_result']['runtimeReferenceChanged'] = True
    _save(path, data)
    return {'animation': output.get_path_name(), 'montage': montage.get_path_name(),
            'length': montage.get_play_length(), 'existing_blend_settings_preserved': True}


def reset_unkeyed_finger_offsets(data, sequence):
    """Reset explicitly requested unkeyed finger rotation offsets, retaining every key."""
    if not data.pop('reset_unkeyed_finger_offsets_request', False):
        return
    require_asset_write([sequence])
    sections = [s for b in sequence.get_bindings() for t in b.get_tracks() for s in t.get_sections()]
    def capture():
        result = {}
        for section in sections:
            for channel in section.get_all_channels():
                keys = []
                for key in channel.get_keys():
                    time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                    keys.append([time.frame_number.value, time.sub_frame, str(key.get_value())])
                result[section.get_path_name() + ':' + str(channel.channel_name)] = {
                    'default': str(channel.get_default()) if hasattr(channel, 'has_default') and channel.has_default() else None,
                    'keys': keys}
        return result
    expected = capture()
    changed = []
    for section in sections:
        if section.get_blend_type().blend_type != unreal.MovieSceneBlendType.ADDITIVE:
            continue
        for channel in section.get_all_channels():
            name = str(channel.channel_name)
            if name.startswith('fk_') and '.Rotation.' in name and not channel.get_keys() and channel.has_default():
                value = channel.get_default()
                if abs(float(value)) > 0.0001:
                    changed.append({'channel': name, 'before': value, 'after': 0.0})
                    channel.set_default(0.0)
                    expected[section.get_path_name() + ':' + name]['default'] = str(channel.get_default())
    if capture() != expected:
        raise RuntimeError('FINGER_OFFSET_UNRELATED_CHANNEL_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('FINGER_OFFSET_SAVE')
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    unreal.LevelSequenceEditorBlueprintLibrary.force_update()
    data['finger_offset_repair'] = {'defaults_reset': changed, 'all_keys_and_other_defaults_preserved': True}


def freeze_right_wrist_rotation(data, sequence):
    """Hold the displayed initial wrist orientation using native Offset rotation keys only."""
    if not data.get('freeze_right_wrist_rotation_request'):
        return
    from BBBControlRigAuthoringToolset import _pose, _key
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    sections = [s for b in sequence.get_bindings() for t in b.get_tracks()
                if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()]
    bases = [s for s in sections if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ABSOLUTE]
    layers = [s for s in sections if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(bases) != 1 or len(layers) != 1:
        raise RuntimeError('WRIST_HOLD_SINGLE_BASE_OFFSET')
    channels = {str(c.channel_name): c for c in bases[0].get_all_channels()}
    targets = ['hand_r_ik_ctrl.Rotation.' + axis for axis in ('X', 'Y', 'Z')]
    rate = sequence.get_display_rate()
    count = sequence.get_playback_end()
    rig = _asset(data['rig'], unreal.ControlRigBlueprint)
    offset = rig.hierarchy.get_global_control_offset_transform(_key('hand_r_ik_ctrl', 'CONTROL'), True)
    encoded = unreal.EditorAssetLibrary.get_metadata_tag(sequence, 'BBB_RuntimeRightWristPreview')
    delta = unreal.Quat(*json.loads(encoded)) if encoded else unreal.Quat()
    scope = unreal.new_object(unreal.LevelSequence, name='BBBWristHold_' + uuid.uuid4().hex)
    try:
        before = _export(sequence, source, mesh, scope, 'Before')
        first = _pose(before, mesh, 0.0)
        parent = unreal.AnimPoseExtensions.get_bone_pose(first, 'lowerarm_r', unreal.AnimPoseSpaces.WORLD).rotation
        hand = unreal.AnimPoseExtensions.get_bone_pose(first, 'hand_r', unreal.AnimPoseSpaces.WORLD).rotation
        desired = (parent * delta * parent.inversed() * hand).normalized()
        rows = []
        for frame in range(count):
            time = min(frame * rate.denominator / rate.numerator, source.get_play_length())
            pose = _pose(before, mesh, time)
            parent = unreal.AnimPoseExtensions.get_bone_pose(pose, 'lowerarm_r', unreal.AnimPoseSpaces.WORLD).rotation
            raw = (parent * delta.inversed() * parent.inversed() * desired).normalized()
            local = unreal.Transform(rotation=raw.rotator()).make_relative(offset).rotation.rotator()
            values = [local.roll, local.pitch, local.yaw]
            for i, name in enumerate(targets):
                channel = channels[name]
                bounds = channel.compute_effective_range()
                bounds.set_start_seconds(time)
                bounds.set_end_seconds(time + rate.denominator / rate.numerator)
                sampled = channel.evaluate_keys(bounds, rate)
                if not sampled:
                    raise RuntimeError('WRIST_HOLD_BASE_EVALUATION')
                values[i] -= float(sampled[0])
                if rows:
                    values[i] += 360 * round((rows[-1][i] - values[i]) / 360)
            rows.append(values)
        def unrelated(target):
            values = []
            for b in target.get_bindings():
                for t in b.get_tracks():
                    for s in t.get_sections():
                        additive = isinstance(t, unreal.MovieSceneControlRigParameterTrack) and s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE
                        for c in s.get_all_channels():
                            if additive and str(c.channel_name) in targets:
                                continue
                            values.append((str(c.channel_name), str(c.get_default()) if hasattr(c, 'get_default') else None,
                                [(k.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).frame_number.value, k.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE).sub_frame, str(k.get_value())) for k in c.get_keys()]))
            return values
        def write(target):
            layer = [s for b in target.get_bindings() for t in b.get_tracks()
                     if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()
                     if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE][0]
            layer.set_is_locked(False)
            channels = {str(c.channel_name): c for c in layer.get_all_channels()}
            for i, name in enumerate(targets):
                channel = channels[name]
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
                channel.set_default(rows[0][i])
                for frame, row in enumerate(rows):
                    channel.add_key(unreal.FrameNumber(value=frame), row[i], 0.0,
                                    unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)
        candidate = _copy_sequence(sequence, scope, 'WristDraft')
        _export(candidate, source, mesh, scope, 'Initialize', False)
        write(candidate)
        after = _export(candidate, source, mesh, scope, 'After')
        maximum, position = 0.0, 0.0
        for frame in range(count):
            time = min(frame * rate.denominator / rate.numerator, source.get_play_length())
            a, b = _pose(before, mesh, time), _pose(after, mesh, time)
            parent = unreal.AnimPoseExtensions.get_bone_pose(b, 'lowerarm_r', unreal.AnimPoseSpaces.WORLD).rotation
            hand = unreal.AnimPoseExtensions.get_bone_pose(b, 'hand_r', unreal.AnimPoseSpaces.WORLD).rotation
            actual = (parent * delta * parent.inversed() * hand).normalized()
            cosine = abs(sum(x*y for x, y in zip(actual.to_tuple(), desired.to_tuple())))
            maximum = max(maximum, math.degrees(2*math.acos(min(1.0, cosine))))
            for bone in ('hand_r', 'hand_l', 'lowerarm_l', 'upperarm_l'):
                pa = unreal.AnimPoseExtensions.get_bone_pose(a, bone, unreal.AnimPoseSpaces.WORLD)
                pb = unreal.AnimPoseExtensions.get_bone_pose(b, bone, unreal.AnimPoseSpaces.WORLD)
                position = max(position, (pa.translation - pb.translation).length())
            if maximum > 0.1 or position > 0.02:
                raise RuntimeError('WRIST_HOLD_POSE: frame=%d degrees=%f cm=%f' % (frame, maximum, position))
        preserved = unrelated(sequence)
        require_asset_write([sequence])
        write(sequence)
        if unrelated(sequence) != preserved:
            raise RuntimeError('WRIST_HOLD_UNRELATED_KEYS_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('WRIST_HOLD_SAVE')
        data.pop('freeze_right_wrist_rotation_request')
        data['right_wrist_rotation_hold'] = {'reference_frame': 0, 'frames': count,
            'display_rotation_error_degrees': maximum, 'preserved_position_error_cm': position,
            'only_offset_rotation_changed': True, 'native_keys': True}
    finally:
        unreal.purge_object_references(scope, True)


def configure_visible_controls(data, sequence):
    """/** @param data\t显式可见控制器列表 @param sequence\t当前制作序列 @return\t保留全部关键帧的控制器显示过滤 */"""
    if 'visible_controls' not in data:
        return None
    asset = _asset(data['rig'], unreal.ControlRigBlueprint)
    allowed = set(data['visible_controls'])
    keys = asset.hierarchy.get_controls()
    names = {str(key.name) for key in keys}
    if not allowed or not allowed <= names or any(name.startswith('source_') for name in allowed):
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_SCOPE')
    signature = _channel_digest(sequence)
    require_asset_write([asset])
    hierarchies = [asset.hierarchy] + [p.control_rig.get_hierarchy() for p in unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)]
    for hierarchy in hierarchies:
        for key in keys:
            settings = hierarchy.get_control_settings(key)
            settings.shape_visible = str(key.name) in allowed
            hierarchy.set_control_settings(key, settings, False, True, False)
        actual = {str(key.name) for key in keys if hierarchy.get_control_settings(key).shape_visible}
        if actual != allowed:
            raise RuntimeError('ACTION_VISIBLE_CONTROLS_READBACK')
    if _channel_digest(sequence) != signature:
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_CHANGED_KEYS')
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
        raise RuntimeError('ACTION_VISIBLE_CONTROLS_SAVE')
    return {'visible_controls': sorted(allowed), 'all_keys_preserved': True, 'controls_deleted': False}


def _channel_digest(sequence, excluded_sections=()):
    """/** @param sequence\t现有制作序列 @return\t全部通道时间值及默认值摘要 */"""
    rows = []
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                if section in excluded_sections:
                    continue
                channels = []
                for channel in section.get_all_channels():
                    keys = []
                    for key in channel.get_keys():
                        stamp = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                        keys.append([stamp.frame_number.value, stamp.sub_frame, str(key.get_value())])
                    default = None
                    if hasattr(channel, 'get_default'):
                        default = str(channel.get_default())
                    channels.append([str(channel.channel_name), default, keys])
                rows.append([binding.get_id().export_text(), section.get_path_name(), channels])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def copy_offset_keys(path, data, sequence):
    """/** @param path\t目标制作源 @param data\t显式Offset输入 @param sequence\t目标LS @return\t只复制原生叠加键及切线 不烘焙 */"""
    if not data.get('offset_source_recipe'):
        return None
    if data.get('offset_copy'):
        return data['offset_copy']
    _, source_data = _source(data['offset_source_recipe'])
    if source_data['action'] != data['action'] or source_data['animation'] != data['animation'] or source_data['sequence'] == data['sequence']:
        raise RuntimeError('OFFSET_COPY_ACTION_SOURCE')
    source = _asset(source_data['sequence'], unreal.LevelSequence)
    for getter in ('get_display_rate', 'get_tick_resolution'):
        left, right = getattr(source, getter)(), getattr(sequence, getter)()
        if left.numerator * right.denominator != right.numerator * left.denominator:
            raise RuntimeError('OFFSET_COPY_FRAME_RATE: ' + getter)
    def layer(target):
        sections = [s for b in target.get_bindings() for t in b.get_tracks()
                    if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()
                    if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(sections) != 1:
            raise RuntimeError('OFFSET_COPY_SINGLE_LAYER')
        return sections[0]
    fields = ('interpolation_mode', 'tangent_mode', 'tangent_weight_mode', 'arrive_tangent', 'leave_tangent', 'arrive_tangent_weight', 'leave_tangent_weight')
    def snapshot(section):
        values = {}
        for channel in section.get_all_channels():
            keys = []
            for key in channel.get_keys():
                time = key.get_time(unreal.MovieSceneTimeUnit.DISPLAY_RATE)
                keys.append({'frame': time.frame_number.value, 'sub': time.sub_frame, 'value': key.get_value(),
                             **{f: getattr(key, 'get_' + f)() for f in fields}})
            values[str(channel.channel_name)] = {'default': channel.get_default() if channel.has_default() else None, 'keys': keys}
        return values
    source_layer, target_layer = layer(source), layer(sequence)
    values = snapshot(source_layer)
    signature = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    channels = {str(c.channel_name): c for c in target_layer.get_all_channels()}
    if set(values) != set(channels) or source_layer.get_start_frame() != target_layer.get_start_frame() or source_layer.get_end_frame() != target_layer.get_end_frame():
        raise RuntimeError('OFFSET_COPY_CHANNELS_OR_RANGE')
    preserved = _channel_digest(sequence, [target_layer])
    require_asset_write([sequence])
    target_layer.set_is_locked(False)
    for name, row in values.items():
        channel = channels[name]
        for key in list(channel.get_keys()):
            channel.remove_key(key)
        if row['default'] is None:
            channel.remove_default()
        else:
            channel.set_default(row['default'])
        for row_key in row['keys']:
            key = channel.add_key(unreal.FrameNumber(value=row_key['frame']), row_key['value'], row_key['sub'], unreal.MovieSceneTimeUnit.DISPLAY_RATE)
            for field in fields:
                getattr(key, 'set_' + field)(row_key[field])
    if snapshot(target_layer) != values or _channel_digest(sequence, [target_layer]) != preserved:
        raise RuntimeError('OFFSET_COPY_READBACK_OR_BASE_CHANGED')
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('OFFSET_COPY_SAVE')
    result = {'source_sequence': source_data['sequence'], 'source_digest': signature,
              'key_count': sum(len(r['keys']) for r in values.values()),
              'keyed_channels': sum(bool(r['keys']) for r in values.values()),
              'tangents_preserved': True, 'base_and_attachments_preserved': True, 'baked': False}
    data['offset_copy'] = result
    data['runtime_applied'] = False
    _save(path, data)
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    return result


def match_reload_phase_offset(data, sequence):
    """/** @param data\t分段换弹制作源 @param sequence\t原生目标序列 @return\t继承开始末帧修正及真实循环接缝核验 */"""
    if not data.get('phase_handoff_recipe') or data.get('phase_handoff'):
        return
    _, start_data = _source(data['phase_handoff_recipe'])
    if (data['action'], start_data['action']) not in (('reload_insert', 'reload_start'), ('reload_end', 'reload_insert')) or start_data['weapon_root'] != data['weapon_root']:
        raise RuntimeError('RELOAD_HANDOFF_SOURCE_SCOPE')
    from BBBControlRigAuthoringToolset import _pose
    start = _asset(start_data['sequence'], unreal.LevelSequence)
    def layer(target):
        sections = [s for b in target.get_bindings() for t in b.get_tracks()
                    if isinstance(t, unreal.MovieSceneControlRigParameterTrack) for s in t.get_sections()
                    if s.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
        if len(sections) != 1:
            raise RuntimeError('RELOAD_HANDOFF_SINGLE_OFFSET_REQUIRED')
        return sections[0]
    source_layer = layer(start)
    target_layer = layer(sequence)
    source_channels = {str(c.channel_name): c for c in source_layer.get_all_channels()}
    target_channels = {str(c.channel_name): c for c in target_layer.get_all_channels()}
    if set(source_channels) != set(target_channels):
        raise RuntimeError('RELOAD_HANDOFF_CHANNELS')
    rate = start.get_display_rate()
    duration = _asset(start_data['finger_animation'], unreal.AnimSequence).get_play_length()
    values = {}
    for name, channel in source_channels.items():
        value = 1.0 if name == 'Weight' else 0.0
        if channel.has_default():
            value = float(channel.get_default())
        if channel.get_keys():
            bounds = channel.compute_effective_range()
            bounds.set_start_seconds(duration)
            bounds.set_end_seconds(duration + rate.denominator / rate.numerator)
            samples = channel.evaluate_keys(bounds, rate)
            if not samples:
                raise RuntimeError('RELOAD_HANDOFF_CHANNEL_EVALUATION: ' + name)
            value = float(samples[0])
        if not math.isfinite(value):
            raise RuntimeError('RELOAD_HANDOFF_NONFINITE_OFFSET')
        values[name] = value
    for name, channel in target_channels.items():
        neutral = 1.0 if name == 'Weight' else 0.0
        numbers = [float(k.get_value()) for k in channel.get_keys()]
        if channel.has_default():
            numbers.append(float(channel.get_default()))
        if any(abs(v - neutral) > 0.00001 for v in numbers):
            raise RuntimeError('RELOAD_HANDOFF_TARGET_ALREADY_EDITED: ' + name)
    source_signature = _channel_digest(start)
    preserved = _channel_digest(sequence, [target_layer])
    changed = {n: v for n, v in values.items() if abs(v - (1.0 if n == 'Weight' else 0.0)) > 0.00001}
    last = sequence.get_playback_end() - 1
    release = data.get('handoff_release_frames')
    if data['action'] == 'reload_end':
        if not isinstance(release, list) or len(release) != 2 or not 0 < release[0] < release[1] < last:
            raise RuntimeError('RELOAD_HANDOFF_RELEASE_FRAMES')
    elif release is not None:
        raise RuntimeError('RELOAD_HANDOFF_UNEXPECTED_RELEASE')
    def write(target):
        target_layer = layer(target)
        target_layer.set_is_locked(False)
        channels = {str(c.channel_name): c for c in target_layer.get_all_channels()}
        for name, value in changed.items():
            channel = channels[name]
            for key in list(channel.get_keys()):
                channel.remove_key(key)
            channel.set_default(value)
            points = [(0, value), (last, value)]
            if release:
                points = [(0, value), (release[0], value), (release[1], 0.0), (last, 0.0)]
            for frame, keyed_value in points:
                channel.add_key(unreal.FrameNumber(value=frame), keyed_value, 0.0,
                                unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBReloadHandoff_' + uuid.uuid4().hex)
    try:
        expected_animation = _export(start, _asset(start_data['finger_animation'], unreal.AnimSequence), mesh, scope, 'Start')
        expected = _pose(expected_animation, mesh, expected_animation.get_play_length())
        copied = _copy_sequence(sequence, scope, 'InsertDraft')
        _export(copied, source, mesh, scope, 'Initialize', False)
        original_animation = _export(copied, source, mesh, scope, 'Neutral')
        final_expected = _pose(original_animation, mesh, original_animation.get_play_length())
        write(copied)
        actual_animation = _export(copied, source, mesh, scope, 'Insert')
        maximum = 0.0
        angle = 0.0
        names = ['clavicle_' + s for s in ('l', 'r')]
        names += [b + '_' + s for s in ('l', 'r') for b in ('upperarm', 'lowerarm', 'hand')]
        names += [f'{b}_{j:02}_{s}' for s in ('l', 'r') for b in ('thumb', 'index', 'middle', 'ring', 'pinky') for j in (1, 2, 3)]
        for time in (0.0, actual_animation.get_play_length()):
            actual = _pose(actual_animation, mesh, time)
            endpoint_expected = final_expected if release and time > 0 else expected
            for name in names:
                a = unreal.AnimPoseExtensions.get_bone_pose(endpoint_expected, name, unreal.AnimPoseSpaces.WORLD)
                b = unreal.AnimPoseExtensions.get_bone_pose(actual, name, unreal.AnimPoseSpaces.WORLD)
                error = (a.translation - b.translation).length()
                cosine = abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple())))
                degrees = math.degrees(2 * math.acos(min(1.0, cosine)))
                maximum = max(maximum, error)
                angle = max(angle, degrees)
                if error > 0.03 or degrees > 0.05:
                    raise RuntimeError('RELOAD_HANDOFF_ENDPOINT: %s time=%f cm=%f degrees=%f' % (name, time, error, degrees))
        require_asset_write([sequence])
        write(sequence)
        if _channel_digest(sequence, [target_layer]) != preserved or _channel_digest(start) != source_signature:
            raise RuntimeError('RELOAD_HANDOFF_UNRELATED_KEYS_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('RELOAD_HANDOFF_SAVE')
        data['phase_handoff'] = {'source_sequence': start_data['sequence'], 'source_channel_digest': source_signature,
                                        'inherited_offset_channels': changed, 'release_frames': release, 'endpoint_position_error_cm': maximum,
                                        'endpoint_rotation_error_degrees': angle, 'base_and_attachments_preserved': True,
                                        'source_keys_preserved': True, 'runtime_applied': False}
    finally:
        unreal.purge_object_references(scope, True)


def prepare_preview_mesh(data, sequence):
    """/** @param data\t正式制作源 @param sequence\t保留手调的序列 @return\t同骨架完整手臂预览更新证据 */"""
    destination = data.get('preview_mesh', '/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Arms/SK_arms')
    original = _asset(data['mesh'], unreal.SkeletalMesh)
    target = _asset(destination, unreal.SkeletalMesh)
    if original == target:
        return
    if original.get_editor_property('skeleton') != target.get_editor_property('skeleton'):
        raise RuntimeError('ACTION_PREVIEW_SKELETON_MISMATCH')
    require_asset_write([sequence])
    binding = _mesh_binding(sequence, original)
    component = binding.get_object_template().skeletal_mesh_component
    signature = _channel_digest(sequence)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBPreviewMesh_' + uuid.uuid4().hex)
    try:
        before = _export(sequence, source, original, scope, 'Before')
        sequence.modify()
        component.modify()
        component.set_skeletal_mesh_asset(target)
        after = _export(sequence, source, target, scope, 'After')
        error = _compare(before, after)
        if _channel_digest(sequence) != signature or _mesh_binding(sequence, target).get_id().export_text() != binding.get_id().export_text():
            raise RuntimeError('ACTION_PREVIEW_KEYS_OR_BINDING_CHANGED')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('ACTION_PREVIEW_MESH_SAVE')
        data['mesh'] = destination
        data['preview_mesh'] = destination
        data['preview_mesh_update'] = {'channel_digest': signature, 'keys_preserved': True,
                                       'binding_preserved': True, 'native_bone_track_error_cm': error}
        unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    except Exception:
        component.set_skeletal_mesh_asset(original)
        raise
    finally:
        unreal.purge_object_references(scope, True)


def _copy_sequence(sequence, scope, name):
    """/** @param sequence\t正式序列 @param scope\t瞬态容器 @param name\t副本名 @return\t携带运行预览语义的瞬态副本 */"""
    copied = unreal.SystemLibrary.duplicate_object(sequence, scope, name)
    tag = 'BBB_RuntimeRightWristPreview'
    encoded = unreal.EditorAssetLibrary.get_metadata_tag(sequence, tag)
    if encoded:
        unreal.EditorAssetLibrary.set_metadata_tag(copied, tag, encoded)
    return copied


def _export(sequence, source, mesh, scope, name, duplicate=True):
    """/** @param sequence\t制作序列 @param source\t源动画 @param mesh\t网格 @param scope\t瞬态作用域 @param name\t名称 @return\t官方直接导出结果 */"""
    copied = sequence
    if duplicate:
        copied = _copy_sequence(sequence, scope, name + 'Sequence')
    result = unreal.SystemLibrary.duplicate_object(source, scope, name + 'Animation')
    if duplicate:
        copied.set_display_rate(unreal.FrameRate(numerator=120, denominator=1))
        copied.set_playback_start(0)
        copied.set_playback_end(round(source.get_play_length() * 120))
    options = unreal.AnimSeqExportOption()
    options.export_transforms = True
    options.export_morph_targets = False
    options.export_attribute_curves = False
    options.export_material_curves = False
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    try:
        binding = _mesh_binding(copied, mesh)
    except RuntimeError as error:
        raise RuntimeError('NATIVE_ACTION_EXPORT_BINDING: ' + copied.get_path_name() + ' mesh=' + mesh.get_path_name()) from error
    if not unreal.SequencerTools.export_anim_sequence(world, copied, result, options, binding, False):
        raise RuntimeError('NATIVE_ACTION_EXPORT_FAILED')
    encoded = unreal.EditorAssetLibrary.get_metadata_tag(sequence, 'BBB_RuntimeRightWristPreview')
    if encoded:
        inverse = unreal.Quat(*json.loads(encoded)).inversed()
        values = list(unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(result, 'hand_r'))
        if not values:
            raise RuntimeError('WRIST_PREVIEW_EXPORT_TRACK')
        if not result.controller.set_bone_track_keys('hand_r', [v.translation for v in values],
                [(inverse * v.rotation).normalized() for v in values], [v.scale3d for v in values], False):
            raise RuntimeError('WRIST_PREVIEW_EXPORT_COMPENSATION')
    if duplicate and abs(result.get_play_length() - source.get_play_length()) > 0.0001:
        raise RuntimeError('NATIVE_ACTION_EXPORT_LENGTH: ' + str(result.get_play_length()))
    return result


def _compare(first, second):
    """/** @param first\t预期输出 @param second\t实际输出 @return\t全轨最大位置误差 */"""
    maximum = 0.0
    for name in first.data_model_interface.get_bone_track_names():
        a = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(first, name)
        b = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(second, name)
        if len(a) != len(b):
            raise RuntimeError('NATIVE_ACTION_KEYS: ' + str(name))
        for left, right in zip(a, b):
            error = (left.translation - right.translation).length()
            maximum = max(maximum, error)
            cosine = abs(sum(x * y for x, y in zip(left.rotation.to_tuple(), right.rotation.to_tuple())))
            if error > 0.02 or cosine < 0.99999 or (left.scale3d - right.scale3d).length() > 0.0001:
                raise RuntimeError('NATIVE_ACTION_POSE: ' + str(name) + ' cm=' + str(error))
    return maximum


def prepare_offset(data, sequence):
    """/** @param data\t制作源 @param sequence\t原序列 @return\t自动建立并选中原生叠加段 保留原键 */"""
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    tracks = _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1:
        raise RuntimeError('NATIVE_OFFSET_SINGLE_TRACK')
    track = tracks[0]
    sections = list(track.get_sections())
    layers = [section for section in sections if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(layers) > 1:
        raise RuntimeError('NATIVE_OFFSET_MULTIPLE_LAYERS')
    if not layers:
        if len(sections) != 1:
            raise RuntimeError('NATIVE_OFFSET_SINGLE_BASE')
        require_asset_write([sequence])
        unreal.LevelSequenceEditorBlueprintLibrary.empty_selection()
        scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeOffset_' + uuid.uuid4().hex)
        layer = None
        try:
            before = _export(sequence, source, mesh, scope, 'Before')
            layer = track.add_section()
            layer.set_blend_type(unreal.MovieSceneBlendType.ADDITIVE)
            layer.set_range(sections[0].get_start_frame(), sections[0].get_end_frame())
            layer.set_row_index(1)
            unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            _export(sequence, source, mesh, scope, 'Initialize', False)
            for channel in layer.get_all_channels():
                for key in list(channel.get_keys()):
                    channel.remove_key(key)
                value = 0.0
                if str(channel.channel_name) == 'Weight':
                    value = 1.0
                channel.set_default(value)
            unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            after = _export(sequence, source, mesh, scope, 'After')
            error = _compare(before, after)
            data['native_offset'] = {'mode': 'native_additive_section', 'neutral_export_error_cm': error,
                                     'base_keys_preserved': True, 'custom_interpolation': False}
        except Exception:
            if layer is not None:
                track.remove_section(layer)
                unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
            raise
        finally:
            unreal.purge_object_references(scope, True)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('NATIVE_OFFSET_SAVE')
        layers = [layer]
    unreal.LevelSequenceEditorBlueprintLibrary.empty_selection()
    unreal.LevelSequenceEditorBlueprintLibrary.select_sections(layers)
    for section in track.get_sections():
        section.set_is_locked(section not in layers)
    if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
        raise RuntimeError('NATIVE_OFFSET_LOCK_SAVE')
    if 'native_offset' not in data:
        data['native_offset'] = {'mode': 'native_additive_section', 'resumed_existing_layer': True,
                                 'custom_interpolation': False}
    if 'probe_left_delta_cm' not in data.get('native_offset', {}):
        scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeProbe_' + uuid.uuid4().hex)
        try:
            neutral = _export(sequence, source, mesh, scope, 'Neutral')
            probe = _copy_sequence(sequence, scope, 'Probe')
            _export(probe, source, mesh, scope, 'InitializeProbe', False)
            probe_track = _mesh_binding(probe, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)[0]
            probe_layer = [item for item in probe_track.get_sections() if item.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE][0]
            channels = {str(channel.channel_name): channel for channel in probe_layer.get_all_channels()}
            channels['hand_l_ik_ctrl.Location.X'].set_default(1.0)
            moved = _export(probe, source, mesh, scope, 'Moved')
            from BBBControlRigAuthoringToolset import _pose
            a = _pose(neutral, mesh, 0)
            b = _pose(moved, mesh, 0)
            errors = {}
            for bone in ('hand_l', 'hand_r'):
                errors[bone] = (unreal.AnimPoseExtensions.get_bone_pose(a, bone, unreal.AnimPoseSpaces.WORLD).translation - unreal.AnimPoseExtensions.get_bone_pose(b, bone, unreal.AnimPoseSpaces.WORLD).translation).length()
            if errors['hand_l'] < 0.1 or errors['hand_l'] > 2.0 or errors['hand_r'] > 0.02:
                raise RuntimeError('NATIVE_OFFSET_PROBE: ' + str(errors))
            data['native_offset']['probe_left_delta_cm'] = errors['hand_l']
            data['native_offset']['probe_right_delta_cm'] = errors['hand_r']
        finally:
            unreal.purge_object_references(scope, True)
    return {'mode': 'native_additive_section', 'sections': len(track.get_sections()), 'custom_interpolation': False}


def inspect_manual(recipe_path, write_paths):
    """/** @param recipe_path\t制作源 @param write_paths\t占用范围 @return\t实际段与通道状态 不解释人工修改意图 */"""
    path, data = _source(recipe_path)
    if set(write_paths) != {data['sequence'], data['rig']}:
        raise RuntimeError('NATIVE_ACTION_INSPECT_SCOPE')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    mesh = _asset(data['mesh'], unreal.SkeletalMesh)
    tracks = _mesh_binding(sequence, mesh).find_tracks_by_type(unreal.MovieSceneControlRigParameterTrack)
    if len(tracks) != 1:
        raise RuntimeError('NATIVE_ACTION_INSPECT_TRACK')
    rows = []
    for section in tracks[0].get_sections():
        rows.append({'blend': str(section.get_blend_type().blend_type), 'row': section.get_row_index(),
                     'channels': [{'name': str(channel.channel_name), 'keys': len(channel.get_keys())}
                                  for channel in section.get_all_channels() if len(channel.get_keys())]})
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    scope = unreal.new_object(unreal.LevelSequence, name='BBBCommonInspect_' + uuid.uuid4().hex)
    evidence = {}
    try:
        baked = _export(sequence, source, mesh, scope, 'Visible')
        evidence['native_sample_keys'] = baked.data_model_interface.get_number_of_keys()
        from BBBCommonActionSources import is_finger
        from BBBControlRigAuthoringToolset import _pose
        maximum = 0.0
        minimum_cosine = 1.0
        rate = sequence.get_display_rate()
        names = [n for n in source.data_model_interface.get_bone_track_names() if is_finger(n)]
        for frame in range(source.data_model_interface.get_number_of_keys()):
            time = frame * rate.denominator / rate.numerator
            expected = _pose(source, mesh, time)
            actual = _pose(baked, mesh, time)
            for name in names:
                a = unreal.AnimPoseExtensions.get_bone_pose(expected, name, unreal.AnimPoseSpaces.LOCAL)
                b = unreal.AnimPoseExtensions.get_bone_pose(actual, name, unreal.AnimPoseSpaces.LOCAL)
                maximum = max(maximum, (a.translation - b.translation).length())
                minimum_cosine = min(minimum_cosine, abs(sum(x * y for x, y in zip(a.rotation.to_tuple(), b.rotation.to_tuple()))))
        evidence['finger_nonzero_additive_defaults'] = []
        for section in tracks[0].get_sections():
            if section.get_blend_type().blend_type != unreal.MovieSceneBlendType.ADDITIVE:
                continue
            for channel in section.get_all_channels():
                if str(channel.channel_name).startswith('fk_') and channel.has_default():
                    value = channel.get_default()
                    if abs(float(value)) > 0.0001:
                        evidence['finger_nonzero_additive_defaults'].append({'channel': str(channel.channel_name), 'default': value, 'keys': len(channel.get_keys())})
        evidence['finger_track_ranges'] = []
        for name in names:
            source_keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(source, name)
            actual_keys = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(baked, name)
            evidence['finger_track_ranges'].append({'bone': str(name),
                'source_max_yaw': max(k.rotation.rotator().yaw for k in source_keys),
                'sequence_max_yaw': max(k.rotation.rotator().yaw for k in actual_keys)})
        evidence['finger_source_position_error_cm'] = maximum
        evidence['finger_source_rotation_cosine_min'] = minimum_cosine
        output = unreal.load_asset(data['output_animation'])
        if output is not None:
            try:
                evidence['existing_output_error_cm'] = _compare(baked, output)
                evidence['existing_output_matches_preview'] = True
            except RuntimeError as error:
                evidence['existing_output_matches_preview'] = False
                evidence['difference'] = str(error)
    finally:
        unreal.purge_object_references(scope, True)
    return {'sequence': data['sequence'], 'sections': rows, 'bake_mode': 'official_sequencer_direct',
            'source_matches_preparation': _digest(_asset(data['animation'], unreal.AnimSequence)) == data['source_track_digest'],
            'common_source': data['animation'], 'output_animation': data['output_animation'],
            'native_evidence': evidence, 'custom_interpolation': False, 'assetModified': False}


def bake_animation(recipe_path, write_paths):
    """/** @param recipe_path\t制作源 @param write_paths\t唯一成品 @return\t序列实际求值的直接烘焙及回读 */"""
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError('NATIVE_ACTION_PIE_FORBIDDEN')
    path, data = _source(recipe_path)
    destination = data['output_animation']
    if set(write_paths) != {destination} or destination.rsplit('/', 1)[0] != data['weapon_root'] + '/Animation/Sequence':
        raise RuntimeError('NATIVE_ACTION_WRITE_SCOPE')
    source = _asset(data['finger_animation'], unreal.AnimSequence)
    if _digest(_asset(data['animation'], unreal.AnimSequence)) != data['source_track_digest']:
        raise RuntimeError('NATIVE_ACTION_SOURCE_CHANGED')
    sequence = _asset(data['sequence'], unreal.LevelSequence)
    output = unreal.load_asset(destination)
    if output is None:
        require_asset_write([], destinations=[destination])
        output = unreal.EditorAssetLibrary.duplicate_asset(data['finger_animation'], destination)
    if not isinstance(output, unreal.AnimSequence):
        raise RuntimeError('NATIVE_ACTION_OUTPUT_TYPE')
    require_asset_write([output])
    scope = unreal.new_object(unreal.LevelSequence, name='BBBNativeBake_' + uuid.uuid4().hex)
    try:
        baked = _export(sequence, source, _asset(data['mesh'], unreal.SkeletalMesh), scope, 'Visible')
        controller = output.controller
        controller.open_bracket('直接烘焙序列可见结果', False)
        try:
            controller.remove_all_bone_tracks(False)
            controller.set_frame_rate(baked.data_model_interface.get_frame_rate(), False)
            controller.set_number_of_frames(unreal.FrameNumber(value=baked.data_model_interface.get_number_of_keys() - 1), False)
            for name in baked.data_model_interface.get_bone_track_names():
                values = unreal.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms(baked, name)
                if not controller.add_bone_track(name, False) or not controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                    raise RuntimeError('NATIVE_ACTION_WRITE_BONE: ' + str(name))
        finally:
            controller.close_bracket(False)
        if unreal.BBBBlueprintEditorLibrary.copy_animation_float_curves(_asset(data['finger_animation'], unreal.AnimSequence), output) < 0:
            raise RuntimeError('NATIVE_ACTION_CURVES')
        error = _compare(baked, output)
        if not unreal.EditorAssetLibrary.save_loaded_asset(output, False):
            raise RuntimeError('NATIVE_ACTION_SAVE')
        result = {'animation': destination, 'bake_mode': 'official_sequencer_direct', 'custom_interpolation': False,
                  'sample_keys': output.data_model_interface.get_number_of_keys(), 'seconds': output.get_play_length(),
                  'native_track_error_cm': error, 'visualAcceptance': 'pending', 'runtimeReferenceChanged': False}
        data['bake_result'] = result
        data['runtime_applied'] = False
        _save(path, data)
        return result
    finally:
        unreal.purge_object_references(scope, True)
