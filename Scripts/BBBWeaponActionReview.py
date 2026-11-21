import hashlib
import json
import math
import uuid

import unreal

from BBBAssetWritePolicy import require_asset_write


def _grip_relative(animation, mesh):
    """/** @param animation 握姿动画 @param mesh 预览网格 @return 左腕相对右腕的基准变换 */"""
    from BBBControlRigAuthoringToolset import _pose

    if animation.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise RuntimeError('参考握姿与动作预览骨架不一致')
    pose = _pose(animation, mesh, 0.0)
    return _bone(pose, 'hand_l').make_relative(_bone(pose, 'hand_r'))


def _bone(pose, name):
    """/** @param pose 动画姿势 @param name 骨骼名称 @return 组件空间骨骼变换 */"""
    return unreal.AnimPoseExtensions.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)


def _action_weights(animation, times):
    """/** @param animation 正式角色动画 @param times 采样秒数 @return 禁用左手 IK 的原曲线权重 */"""
    library = unreal.AnimationLibrary
    names = library.get_animation_curve_names(animation, unreal.RawCurveTrackTypes.RCT_FLOAT)
    curve = next((name for name in names if str(name).casefold() == 'disablelefthandik'), None)
    if curve is None:
        raise RuntimeError('正式动作缺少 DisableLeftHandIK 曲线')
    weights = [float(library.get_float_value_at_time(animation, curve, time)) for time in times]
    if any(not math.isfinite(value) for value in weights):
        raise RuntimeError('正式动作的左手 IK 曲线包含非有限值')
    return [min(1.0, max(0.0, value)) for value in weights]


def _pose_error(actual, expected):
    """/** @param actual 实际左手变换 @param expected 目标左手变换 @return 位置厘米误差和旋转度数误差 */"""
    distance = (actual.translation - expected.translation).length()
    dot = abs(sum(a * b for a, b in zip(actual.rotation.to_tuple(), expected.rotation.to_tuple())))
    return distance, math.degrees(2 * math.acos(min(1.0, dot)))


def _transform_changes(binding, transform):
    """读取附件局部变换的差异。"""
    from BBBControlRigAuthoringToolset import _attachment_defaults

    section, defaults = _attachment_defaults(binding, transform)
    changes = []
    for channel, value in defaults:
        name = str(channel.channel_name)
        difference = float(channel.get_default()) - value if channel.has_default() else math.inf
        if name.startswith('Rotation.') and math.isfinite(difference):
            difference = math.remainder(difference, 360.0)
        if abs(difference) > 0.00001:
            changes.append((channel, value))
    return section, changes


def _attachment_changes(definition, weapon):
    """读取本型号配置和序列的武器挂接差异。"""
    return _transform_changes(weapon, definition.get_editor_property('spawn_offset'))


def _magazine_changes(montage, sequence):
    """按正式换弹通知核对预览弹匣的挂接骨和偏移。"""
    from BBBManualActionAuthoring import _notify_events

    labels = {'BBBCharacterOldMagazineDisplayAnimNotifyState': 'OldMagazine',
              'BBBCharacterNewMagazineDisplayAnimNotifyState': 'NewMagazine'}
    bindings = {label: [binding for binding in sequence.get_bindings() if binding.get_name() == label]
                for label in labels.values()}
    result = []
    for state, start, end in _notify_events(montage):
        if state is None or state.get_class().get_name() not in labels:
            continue
        label = labels[state.get_class().get_name()]
        matches = bindings[label]
        if len(matches) != 1:
            raise RuntimeError(f'{sequence.get_path_name()} 的 {label} 弹匣绑定不唯一')
        binding = matches[0]
        bone = str(state.get_editor_property('hand_bone_name'))
        tracks = binding.find_tracks_by_type(unreal.MovieScene3DAttachTrack)
        sections = [section for track in tracks for section in track.get_sections() if section.is_active()]
        if not sections or any(str(section.get_editor_property('attach_socket_name')) != bone for section in sections):
            raise RuntimeError(f'{sequence.get_path_name()} 的 {label} 弹匣应挂接到 {bone}')
        section, changes = _transform_changes(binding, state.get_editor_property('hand_magazine_transform'))
        result.append((section, changes, {'binding': label, 'bone': bone, 'start': start, 'end': end}))
    return result


def _check_wrist(definition, sequence):
    """核对关卡序列的右腕补偿与运行配置。"""
    encoded = unreal.EditorAssetLibrary.get_metadata_tag(sequence, 'BBB_RuntimeRightWristPreview')
    expected = definition.get_editor_property('right_hand_grip_rotation_offset').quaternion().normalized()
    actual = unreal.Quat(*json.loads(encoded)) if encoded else unreal.Quat(0.0, 0.0, 0.0, 1.0)
    cosine = abs(sum(a * b for a, b in zip(expected.to_tuple(), actual.to_tuple())))
    if not math.isfinite(cosine) or abs(1.0 - cosine) > 0.000001:
        raise RuntimeError(f'{sequence.get_path_name()} 的右腕预览已过期，须更新右腕预览后再烘焙')


def check_preview(definition, sequence, weapon):
    """校验预览枪挂接与右腕补偿，避免把错误预览烘焙进正式动作。"""
    _, changes = _attachment_changes(definition, weapon)
    if changes:
        names = ', '.join(str(channel.channel_name) for channel, _ in changes)
        raise RuntimeError(f'{sequence.get_path_name()} 的预览挂接与武器配置不一致：{names}')
    _check_wrist(definition, sequence)


def audit_recoil(definition, mesh):
    """检查正式角色后坐资源的所属型号、加法基底和实际骨轨。"""
    recoil = definition.get_editor_property('character_recoil_animation')
    root = definition.get_path_name().rsplit('/', 1)[0]
    if not isinstance(recoil, unreal.AnimSequence) or not recoil.get_path_name().startswith(root + '/Animation/'):
        raise RuntimeError(f'{definition.get_path_name()} 缺少本型号的角色后坐动画')
    if recoil.get_editor_property('skeleton') != mesh.get_editor_property('skeleton'):
        raise RuntimeError(f'{recoil.get_path_name()} 的角色骨架不一致')
    if recoil.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_LOCAL_SPACE_BASE:
        raise RuntimeError(f'{recoil.get_path_name()} 的后坐动画须为局部空间加法')
    base = recoil.get_editor_property('ref_pose_seq')
    if not isinstance(base, unreal.AnimSequence) or base.get_editor_property('skeleton') != recoil.get_editor_property('skeleton'):
        raise RuntimeError(f'{recoil.get_path_name()} 缺少有效的同骨架持枪加法基底')
    tracks = {str(name) for name in recoil.data_model_interface.get_bone_track_names()}
    missing = {'hand_r', 'lowerarm_r', 'upperarm_r'} - tracks
    if missing:
        raise RuntimeError(f'{recoil.get_path_name()} 缺少后坐骨轨：{", ".join(sorted(missing))}')
    return {'animation': recoil.get_path_name(), 'reference': base.get_path_name(), 'bone_tracks': len(tracks)}


def copy_weapon_action(original, definition, montage_path, animation_path, grenades, write_paths, dry_run):
    """复制带原曲线和通知的动作 以写入范围内的配置接入正式引用。"""
    from BBBAnimationTrajectoryTools import replace_montage_references

    root = definition.get_path_name().rsplit('/', 1)[0]
    if not root.startswith('/Game/_Project/') or not isinstance(original, unreal.AnimMontage):
        raise RuntimeError('须提供目标武器配置和动作蒙太奇模板')
    if montage_path.rsplit('/', 1)[0] != root + '/Animation/Montage' or animation_path.rsplit('/', 1)[0] != root + '/Animation/Sequence':
        raise RuntimeError('请指定目标型号自己的 Montage 和 Sequence 路径')
    owners = grenades or [definition]
    owner_paths = {owner.get_path_name().split('.')[0] for owner in owners}
    if set(write_paths) != owner_paths | {montage_path, animation_path}:
        raise RuntimeError('写入范围须包含动作配置、蒙太奇及动画')

    tracks = original.get_editor_property('slot_anim_tracks')
    segments = [segment for track in tracks for segment in track.get_editor_property('anim_track').get_editor_property('anim_segments')]
    clips = {segment.get_editor_property('anim_reference') for segment in segments}
    if len(clips) != 1 or not isinstance(next(iter(clips)), unreal.AnimSequence):
        raise RuntimeError('参考蒙太奇须使用一份独立动画序列')
    clip = next(iter(clips))
    template = definition.get_editor_property('character_grip_pose')
    if not isinstance(template, unreal.AnimSequence) or template.get_editor_property('skeleton') != clip.get_editor_property('skeleton'):
        raise RuntimeError('目标握姿和参考动作须使用同一角色骨架')

    library = unreal.EditorAssetLibrary
    equipment_id = definition.get_editor_property('item_id')
    if grenades and str(equipment_id) in ('None', ''):
        raise RuntimeError('目标武器缺少物品标识')
    if grenades:
        mappings = [dict(owner.get_editor_property('equipment_throw_montages')) for owner in owners]
        current = [mapping.get(equipment_id) for mapping in mappings]
    else:
        current = [definition.get_editor_property('quick_melee_montage')]
    bound = all(asset and asset.get_path_name().split('.')[0] == montage_path for asset in current)
    existing = [library.does_asset_exist(path) for path in (montage_path, animation_path)]
    source_clip_path = clip.get_path_name().split('.')[0]
    rebind = not any(existing)
    if any(existing):
        if not all(existing):
            raise RuntimeError('动作目标路径只有一份资产，请核对归属后再配置')
        candidate = library.load_asset(montage_path)
        candidate_tracks = candidate.get_editor_property('slot_anim_tracks')
        candidate_clips = [segment.get_editor_property('anim_reference') for track in candidate_tracks
                           for segment in track.get_editor_property('anim_track').get_editor_property('anim_segments')]
        allowed = {source_clip_path, animation_path}
        actual = {item.get_path_name().split('.')[0] for item in candidate_clips if item}
        if len(candidate_clips) != len(segments) or any(item is None for item in candidate_clips) or not actual <= allowed:
            raise RuntimeError('已有蒙太奇含未经核对的动画引用')
        rebind = source_clip_path in actual
        if bound and not rebind:
            return {'status': 'bound', 'montage': montage_path}
    result = {'montage': montage_path, 'animation': animation_path, 'dry_run': dry_run}
    if dry_run:
        return result
    require_asset_write(owners, [montage_path, animation_path])
    if not any(existing):
        for asset, path in ((clip, animation_path), (original, montage_path)):
            if library.duplicate_asset(asset.get_path_name(), path) is None:
                raise RuntimeError('复制动作资产失败 ' + path)
    if rebind:
        replacement = replace_montage_references(montage_path, json.dumps({source_clip_path: animation_path}))
        if isinstance(replacement, str):
            replacement = json.loads(replacement)
        if replacement['replaced'] <= 0:
            raise RuntimeError('目标蒙太奇片段没有全部改用目标序列')
    montage = library.load_asset(montage_path)
    copied_tracks = montage.get_editor_property('slot_anim_tracks')
    copied_clips = [segment.get_editor_property('anim_reference') for track in copied_tracks
                    for segment in track.get_editor_property('anim_track').get_editor_property('anim_segments')]
    if len(copied_clips) != len(segments) or any(not item or item.get_path_name().split('.')[0] != animation_path for item in copied_clips):
        raise RuntimeError('动作蒙太奇未完全切换到本型号序列')
    if not library.save_asset(animation_path, False):
        raise RuntimeError('目标专用动作序列保存失败')
    for index, owner in enumerate(owners):
        owner.modify()
        if grenades:
            mapping = mappings[index]
            mapping[equipment_id] = montage
            owner.set_editor_property('equipment_throw_montages', mapping)
            actual = owner.get_editor_property('equipment_throw_montages').get(equipment_id)
        else:
            owner.set_editor_property('quick_melee_montage', montage)
            actual = owner.get_editor_property('quick_melee_montage')
        if actual != montage or not library.save_loaded_asset(owner, False):
            raise RuntimeError('动作配置保存或回读失败 ' + owner.get_path_name())
    return result


def open_review(definition, sequence, action, reference):
    """核对本型号的动作和预览后打开审核序列。"""
    montage, animation, mesh, rig, weapon = action_inputs(definition, sequence, action)
    _check_wrist(definition, sequence)
    proof = fit(definition, sequence, animation, mesh, rig, weapon, reference, [], True, True)
    weapon_section, changes = _attachment_changes(definition, weapon)
    magazines = _magazine_changes(montage, sequence) if action.startswith('reload') else []
    handoff = proof['before_handoff_error_cm']
    if not handoff:
        raise RuntimeError(f'{animation.get_path_name()} 没有左手 IK 完全接管的帧')
    if max(handoff.values()) > 0.8 or max(proof['before_handoff_error_deg'].values()) > 5.0:
        proof = fit(definition, sequence, animation, mesh, rig, weapon, reference, [], False, False)
        changes = []
    if changes or any(rows for _, rows, _ in magazines):
        require_asset_write([sequence])
        with unreal.ScopedEditorTransaction('同步武器审核挂接'):
            sequence.modify()
            for section, rows, _ in [(weapon_section, changes, None)] + magazines:
                if rows:
                    section.modify()
                    for channel, value in rows:
                        channel.set_default(value)
        if _attachment_changes(definition, weapon)[1]:
            raise RuntimeError('预览挂接回读与武器配置不一致')
        if magazines and any(rows for _, rows, _ in _magazine_changes(montage, sequence)):
            raise RuntimeError('预览弹匣回读与正式换弹通知不一致')
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('同步预览挂接后保存失败')

    check_preview(definition, sequence, weapon)
    editor = unreal.LevelSequenceEditorBlueprintLibrary
    if not editor.open_level_sequence(sequence) or editor.get_current_level_sequence() != sequence:
        raise RuntimeError('审核序列打开失败 ' + sequence.get_path_name())
    editor.set_current_time(0)
    return {'next': sequence.get_path_name(), 'preview': proof, 'magazines': [details for _, _, details in magazines]}


def _verify_handoff(baked, animation, mesh, reference_grip):
    """/** @param baked 瞬态烘焙动画 @param animation 正式动作 @param mesh 角色网格 @param reference_grip 公共握姿 @return IK 完全接管帧的姿势误差 */"""
    from BBBControlRigAuthoringToolset import _pose

    data = animation.data_model_interface
    rate = data.get_frame_rate()
    times = [min(animation.get_play_length(), frame * rate.denominator / rate.numerator)
             for frame in range(data.get_number_of_keys())]
    handoffs = [frame for frame, weight in enumerate(_action_weights(animation, times)) if weight <= 0.0001]
    maximum = (0.0, 0.0)
    for frame in handoffs:
        pose = _pose(baked, mesh, min(baked.get_play_length(), times[frame]))
        error = _pose_error(_bone(pose, 'hand_l'), reference_grip * _bone(pose, 'hand_r'))
        if error[0] > 0.8 or error[1] > 5.0:
            raise RuntimeError(f'第 {frame} 帧尚未回到公共握姿 {error[0]:.3f} cm / {error[1]:.2f} deg')
        maximum = tuple(max(a, b) for a, b in zip(maximum, error))
    return {'frames': handoffs, 'maximum_error_cm': maximum[0], 'maximum_rotation_error_deg': maximum[1]}


def action_inputs(definition, sequence, action):
    """/** @param definition 武器配置 @param sequence 审核序列 @param action 动作名称 @return 正式蒙太奇 骨轨目标和角色网格 */"""
    from BBBControlRigAuthoringToolset import _weapon_review_bindings

    fields = {'equip': 'character_equip_montage', 'reload': 'character_reload_montage',
              'reload_start': 'character_reload_start_montage', 'reload_end': 'character_reload_end_montage'}
    if action not in fields:
        raise RuntimeError('审核入口仅接收有正式角色蒙太奇的明确动作')
    montage = definition.get_editor_property(fields[action])
    if not isinstance(montage, unreal.AnimMontage):
        raise RuntimeError('武器未配置这个角色动作 ' + action)
    tracks = [slot.get_editor_property('anim_track') for slot in montage.get_editor_property('slot_anim_tracks')
              if str(slot.get_editor_property('slot_name')) == 'UpperBody']
    segments = tracks[0].get_editor_property('anim_segments') if len(tracks) == 1 else []
    animation = segments[0].get_editor_property('anim_reference') if len(segments) == 1 else None
    root = definition.get_path_name().rsplit('/', 1)[0]
    if not isinstance(animation, unreal.AnimSequence) or not animation.get_path_name().startswith(root + '/Animation/'):
        raise RuntimeError('角色动作须有唯一且属于本型号的 UpperBody 骨轨目标')
    proxies, weapon = _weapon_review_bindings(sequence, definition.get_editor_property('equipment_mesh'))
    if len(proxies) != 1:
        raise RuntimeError('动作校正须有唯一的角色 Rig 轨道')
    mesh = proxies[0].proxy.get_object_template().skeletal_mesh_component.get_skeletal_mesh_asset()
    return montage, animation, mesh, proxies[0], weapon


def _layers(rig_track):
    """/** @param rig_track 角色控制器轨道 @return 原始段与人工可编辑叠加段 */"""
    sections = [section for section in rig_track.get_sections() if section.is_active()]
    additive = [section for section in sections if section.get_blend_type().blend_type == unreal.MovieSceneBlendType.ADDITIVE]
    if len(sections) != 2 or len(additive) != 1:
        raise RuntimeError('校正需要一个原始段和一个可编辑叠加段')
    return next(section for section in sections if section != additive[0]), additive[0]


def _samples(section, names, rate, frames):
    """/** @param section 动画段 @param names 读取通道 @param rate 显示帧率 @param frames 显示帧 @return 连续逐帧通道值 */"""
    channels = {str(channel.channel_name): channel for channel in section.get_all_channels()}
    result = []
    for name in names:
        channel = channels[name]
        if not channel.get_keys() and channel.has_default():
            result.append([channel.get_default()] * len(frames))
            continue
        bounds = channel.compute_effective_range()
        bounds.set_start_seconds(frames[0] * rate.denominator / rate.numerator)
        bounds.set_end_seconds((frames[-1] + 1) * rate.denominator / rate.numerator)
        values = list(channel.evaluate_keys(bounds, rate))
        if len(values) < len(frames):
            raise RuntimeError('接触校正通道采样不足 ' + name)
        result.append(values[:len(frames)])
    return list(zip(*result))


def fit(definition, sequence, animation, mesh, rig_proxy, weapon, reference, contacts, inspect_only, dry_run):
    """/** @param definition 武器配置 @param sequence 审核序列 @param animation 正式动画 @param mesh 角色网格 @param rig_proxy 角色控制器 @param weapon 预览枪 @param reference 公共基准动画 @param contacts 接触窗口 @param inspect_only 仅测量原姿势 @param dry_run 仅验证候选 @return 校正证据 */"""
    from BBBControlRigAuthoringToolset import _attachment_defaults, _key, _pose
    from BBBHandRetargetBatchToolset import _contact_ranges, _contact_weight, _validate_contact_reach
    from BBBManualActionNative import _channel_digest, _copy_sequence, _export

    editor = unreal.LevelSequenceEditorBlueprintLibrary
    grip = definition.get_editor_property('character_grip_pose')
    if not isinstance(grip, unreal.AnimSequence):
        raise RuntimeError('先应用目标武器的未开火握姿')
    _, defaults = _attachment_defaults(weapon, definition.get_editor_property('spawn_offset'))
    rate = sequence.get_display_rate()
    if sequence.get_playback_start() != 0:
        raise RuntimeError('审核动作必须从零帧开始')
    count = min(sequence.get_playback_end(), math.floor(animation.get_play_length() * rate.numerator / rate.denominator + 0.0001) + 1)
    if contacts:
        _contact_ranges({'contacts': contacts}, count)
    names = ['hand_l_ik_ctrl.' + part + '.' + axis for part in ('Location', 'Rotation') for axis in 'XYZ']
    scope = unreal.new_object(unreal.LevelSequence, name='BBBActionReview_' + uuid.uuid4().hex)
    if not inspect_only and editor.get_current_level_sequence() == sequence:
        editor.force_update()
    signature = _channel_digest(sequence, relative_paths=True) if not inspect_only else None
    try:
        before = _export(sequence, animation, mesh, scope, 'Before', require_source_tracks=False)
        relative = _grip_relative(grip, mesh)
        common = _grip_relative(reference, mesh)
        frames = list(range(count))
        times = [min(before.get_play_length(), frame * rate.denominator / rate.numerator) for frame in frames]
        weights = _action_weights(animation, times)
        if not inspect_only:
            base, edit = _layers(rig_proxy.track)
            offset = rig_proxy.control_rig.get_hierarchy().get_global_control_offset_transform(_key('hand_l_ik_ctrl', 'CONTROL'), True)
            base_samples = _samples(base, names, rate, frames)
            edits = _samples(edit, names, rate, frames)
        plan = {}
        errors = []
        handoff_errors = {}
        handoff_angles = {}
        contact_weights = [_contact_weight(frame, contacts, 1.0) for frame in frames]
        changed = {frame for frame, (curve, contact) in enumerate(zip(weights, contact_weights))
                   if curve < 0.9999 or contact > 0.0001}
        anchors = {neighbor for frame in changed for neighbor in (frame - 1, frame + 1)
                   if 0 <= neighbor < count and neighbor not in changed}
        for frame, time in enumerate(times):
            pose = _pose(before, mesh, time)
            left = _bone(pose, 'hand_l')
            right = _bone(pose, 'hand_r')
            target = relative * right
            baseline = common * right
            errors.append(round((left.translation - target.translation).length(), 3))
            if weights[frame] <= 0.0001:
                distance, angle = _pose_error(left, baseline)
                handoff_errors[frame] = round(distance, 3)
                handoff_angles[frame] = round(angle, 3)
            if inspect_only or frame not in changed | anchors:
                continue
            if frame in anchors:
                plan[frame] = (edits[frame], left)
                continue
            authored = left.lerp(target, contact_weights[frame])
            desired = baseline.lerp(authored, weights[frame])
            arm = {name: _bone(pose, name) for name in ('upperarm_l', 'lowerarm_l', 'hand_l')}
            _validate_contact_reach(arm, desired)
            local = desired.make_relative(offset)
            angles = local.rotation.rotator()
            values = list(local.translation.to_tuple()) + [angles.roll, angles.pitch, angles.yaw]
            for index in range(3, 6):
                current = base_samples[frame][index] + edits[frame][index]
                values[index] += 360.0 * round((current - values[index]) / 360.0)
            plan[frame] = ([value - base_samples[frame][i] for i, value in enumerate(values)], desired)
        report = {'source_signature': signature, 'before_error_cm': errors, 'frames': count,
                  'reference': reference.get_path_name(), 'before_handoff_error_cm': handoff_errors,
                  'before_handoff_error_deg': handoff_angles,
                  'adjusted_frames': sorted(changed), 'dry_run': dry_run or inspect_only}
        if inspect_only:
            return report

        def write(target, edit_section, transform_defaults):
            target.modify()
            edit_section.modify()
            channels = {str(channel.channel_name): channel for channel in edit_section.get_all_channels()}
            for channel, value in transform_defaults:
                channel.set_default(value)
            for i, name in enumerate(names):
                for frame, (values, _) in plan.items():
                    channels[name].add_key(unreal.FrameNumber(value=frame), values[i], 0.0,
                                           unreal.MovieSceneTimeUnit.DISPLAY_RATE, unreal.MovieSceneKeyInterpolation.LINEAR)

        candidate = _copy_sequence(sequence, scope, 'Candidate')
        _export(candidate, animation, mesh, scope, 'Initialize', False, require_source_tracks=False)
        from BBBControlRigAuthoringToolset import _weapon_review_bindings
        tested_rig, tested_weapon = _weapon_review_bindings(candidate, definition.get_editor_property('equipment_mesh'))
        _, tested_edit = _layers(tested_rig[0].track)
        _, candidate_defaults = _attachment_defaults(tested_weapon, definition.get_editor_property('spawn_offset'))
        write(candidate, tested_edit, candidate_defaults)
        after = _export(candidate, animation, mesh, scope, 'After', require_source_tracks=False)
        maximum = 0.0
        max_rotation = 0.0
        for frame in frames:
            time = min(after.get_play_length(), frame * rate.denominator / rate.numerator)
            actual = _bone(_pose(after, mesh, time), 'hand_l')
            expected = plan[frame][1] if frame in plan else _bone(_pose(before, mesh, time), 'hand_l')
            error = _pose_error(actual, expected)
            maximum = max(maximum, error[0])
            max_rotation = max(max_rotation, error[1])
        if maximum > 0.8 or max_rotation > 5.0:
            raise RuntimeError(f'校正候选未通过 姿势误差 {maximum:.3f} cm / {max_rotation:.2f} deg')
        handoff = _verify_handoff(after, animation, mesh, common)
        report.update({'maximum_error_cm': maximum, 'maximum_rotation_error_deg': max_rotation, 'handoff': handoff})
        if dry_run:
            return report
        require_asset_write([sequence])
        if _channel_digest(sequence, relative_paths=True) != signature:
            raise RuntimeError('审核序列在采样期间发生修改')
        with unreal.ScopedEditorTransaction('校正武器动作目标握点'):
            write(sequence, edit, defaults)
        if editor.get_current_level_sequence() == sequence:
            editor.force_update()
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
            raise RuntimeError('校正序列保存失败')
        report['saved'] = True
        return report
    finally:
        unreal.purge_object_references(scope, True)


def apply(sequence, animation, mesh, reference):
    """/** @param sequence 已审核序列 @param animation 正式动作 @param mesh 角色网格 @param reference 公共基准动画 @param next_sequence 已准备的下一份 @return 保存和交接结果 */"""
    from BBBControlRigAuthoringToolset import _bake_existing_animation
    from BBBManualActionAuthoring import _digest
    from BBBManualActionNative import _channel_digest
    from BBBHandRetargetBatchToolset import _float_curve_signature

    library = unreal.EditorAssetLibrary
    editor = unreal.LevelSequenceEditorBlueprintLibrary
    editor.force_update()
    tag = 'BBBWeaponActionApplied'
    signature = _channel_digest(sequence, relative_paths=True) + _digest(reference) + repr(_float_curve_signature(animation))
    fingerprint = hashlib.sha256((signature + _digest(animation)).encode()).hexdigest()
    result = {'already_applied': library.get_metadata_tag(sequence, tag) == fingerprint}
    if not result['already_applied']:
        if editor.get_current_level_sequence() != sequence:
            raise RuntimeError('当前打开的序列与待应用序列不一致')
        require_asset_write([sequence, animation])
        common = _grip_relative(reference, mesh)

        def validate(baked):
            result['handoff'] = _verify_handoff(baked, animation, mesh, common)

        result['bake'] = json.loads(_bake_existing_animation(sequence, animation, mesh, validate_bake=validate))
        library.set_metadata_tag(sequence, tag, hashlib.sha256((signature + _digest(animation)).encode()).hexdigest())
        if not library.save_loaded_asset(sequence, False):
            raise RuntimeError('正式动画已保存 审核交接状态保存失败')
    return result
