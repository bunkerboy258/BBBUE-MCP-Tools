import hashlib
import json
import math
import os
import re

import unreal


def inspect_reference_events(content_directory, animation_paths):
    """/** @param content_directory 外部只读目录 @param animation_paths 目录内相对包名 @return 原生通知时刻与类 不执行蓝图 */"""
    if not content_directory or not 1 <= len(animation_paths) <= 128:
        raise RuntimeError('要求外部目录和一至一百二十八条动画')
    if os.path.normcase(os.path.realpath(content_directory)) == os.path.normcase(os.path.realpath(unreal.Paths.project_content_dir())):
        raise RuntimeError('来源必须是外部只读项目')
    if any(not re.fullmatch(r'[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*', path) for path in animation_paths):
        raise RuntimeError('参考动画使用外部 Content 内的相对包名')
    source_paths = ['/Game/' + path for path in animation_paths]
    animations = unreal.BBBMotionMatchingEditorLibrary.load_reference_animation_sequences(content_directory, source_paths)
    if len(animations) != len(animation_paths):
        raise RuntimeError('参考动画载入不完整')
    rows = []
    for path, animation in zip(animation_paths, animations):
        timing = json.loads(unreal.BBBHandPoseLayerEditorLibrary.inspect_animation_notify_timing(animation))
        events = list(unreal.AnimationLibrary.get_animation_notify_events(animation))
        if timing.get('error') or len(events) != len(timing.get('events', [])):
            raise RuntimeError('参考通知时间读取失败: ' + path)
        items = []
        for event, native in zip(events, timing['events']):
            instance = event.get_editor_property('notify') or event.get_editor_property('notify_state_class')
            properties = {}
            if instance and instance.get_class().get_name().startswith('BP_AnimNotify_FoleyEvent'):
                side = instance.get_editor_property('Side')
                properties = {'Event': {'structType': 'GameplayTag', 'structText': instance.get_editor_property('Event').export_text()},
                              'Side': {'enumType': type(side).__name__, 'value': side.name},
                              'VolumeMultiplier': float(instance.get_editor_property('VolumeMultiplier')),
                              'PitchMultiplier': float(instance.get_editor_property('PitchMultiplier'))}
            items.append({'class': instance.get_class().get_name() if instance else '',
                          'name': str(event.get_editor_property('notify_name')),
                          'time': native['nativeTriggerTime'] - native['triggerTimeOffset'],
                          'duration': native['nativeDuration'], 'properties': properties})
        rows.append({'animation': path, 'length': animation.get_play_length(), 'events': items})
    return json.dumps({'animations': rows}, ensure_ascii=False)


def _protected(animation):
    """/** @param animation 目标动画 @return 骨轨 曲线 标记与运动配置摘要 */"""
    values = [unreal.BBBBlueprintEditorLibrary.get_animation_protected_data_hash(animation, [])]
    if not values[0]:
        raise RuntimeError('动画保护摘要生成失败')
    model = animation.data_model_interface
    values.extend([model.get_frame_rate().export_text(), str(model.get_number_of_keys())])
    values.extend(marker.export_text() for marker in unreal.AnimationLibrary.get_animation_sync_markers(animation))
    for name in ('additive_anim_type', 'ref_pose_type', 'ref_pose_seq', 'ref_frame_index',
                 'enable_root_motion', 'force_root_lock', 'root_motion_root_lock', 'rate_scale', 'loop'):
        value = animation.get_editor_property(name)
        values.append(name + (value.get_path_name() if isinstance(value, unreal.Object) else str(value)))
    return hashlib.sha256('\n'.join(values).encode()).hexdigest()


def replace_tracks(requests):
    """/** @param requests 明确的目标轨道与通知配置 每批八条 @return 保存后回读和保护摘要 */"""
    from BBBGenericEditorToolset import BBBGenericEditorToolset
    from BBBAssetWritePolicy import require_write_access
    if not 1 <= len(requests) <= 8 or len({item['asset_path'] for item in requests}) != len(requests):
        raise RuntimeError('每批要求一至八个唯一目标')
    rows = []
    for item in requests:
        path = item['asset_path']
        track = item['track_name']
        animation = unreal.load_asset(path)
        if not path.startswith('/Game/_Project/') or not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError('要求自有动画序列')
        require_write_access(animation)
        library = unreal.AnimationLibrary
        partitions = [[]]
        ends = [-1.0]
        for event in item['events']:
            index = next((i for i, end in enumerate(ends) if end <= event['time'] + .0000001), len(ends))
            if index == len(ends):
                partitions.append([])
                ends.append(-1.0)
            partitions[index].append(event)
            ends[index] = event['time'] + event.get('duration', 0.0)
        own_tracks = {track}
        own_tracks.update(track + '_' + str(i + 1) for i in range(1, len(partitions)))
        existing_own = {str(name) for name in library.get_animation_notify_track_names(animation)
                        if str(name) == track or re.fullmatch(re.escape(track) + r'_[2-9][0-9]*', str(name))}
        own_tracks.update(existing_own)
        untouched = [(str(name), [event.export_text() for event in library.get_animation_notify_events_for_track(animation, name)])
                     for name in library.get_animation_notify_track_names(animation) if str(name) not in own_tracks]
        before = _protected(animation)
        animation.modify()
        for name in existing_own:
            library.remove_animation_notify_events_by_track(animation, name)
        for index, events in enumerate(partitions):
            name = track if index == 0 else track + '_' + str(index + 1)
            result = json.loads(BBBGenericEditorToolset.replace_animation_notify_track(path, name, json.dumps(events)))
        after_untouched = [(str(name), [event.export_text() for event in library.get_animation_notify_events_for_track(animation, name)])
                           for name in library.get_animation_notify_track_names(animation) if str(name) not in own_tracks]
        after = _protected(animation)
        if before != after or untouched != after_untouched:
            raise RuntimeError('通知轨道更新改变了受保护数据: ' + json.dumps({
                'asset': path, 'beforeHash': before, 'afterHash': after,
                'beforeTracks': untouched, 'afterTracks': after_untouched}, ensure_ascii=False))
        expected = sorted(item['events'], key=lambda event: (event['time'], event['class_path']))
        actual = sorted([event for event in result['events'] if event['track'] in own_tracks], key=lambda event: (event['time'], event['classPath']))
        if len(actual) != len(expected) or any(abs(a['time'] - b['time']) > .0002 for a, b in zip(actual, expected)):
            raise RuntimeError('保存后的通知数量或时刻不符: ' + path)
        event_instances = [(event, event.get_editor_property('notify_state_class') or event.get_editor_property('notify'))
                           for name in own_tracks if library.is_valid_anim_notify_track_name(animation, name)
                           for event in library.get_animation_notify_events_for_track(animation, name)]
        event_instances.sort(key=lambda pair: (library.get_anim_notify_event_trigger_time(pair[0]), pair[1].get_class().get_path_name()))
        instances = [instance for _, instance in event_instances]
        for instance, requested in zip(instances, expected):
            if instance is None or instance.get_class().get_path_name() != requested['class_path']:
                raise RuntimeError('保存后的通知类型不符: ' + path)
            for name, value in requested.get('properties', {}).items():
                current = instance.get_editor_property(name)
                valid = current == value
                if isinstance(value, dict) and 'enumType' in value:
                    valid = type(current).__name__ == value['enumType'] and current.name == value['value']
                if isinstance(value, dict) and 'structType' in value:
                    desired = getattr(unreal, value['structType'])()
                    desired.import_text(value['structText'])
                    valid = current.export_text() == desired.export_text()
                if isinstance(current, float) and not isinstance(value, dict):
                    valid = math.isclose(current, float(value), rel_tol=1e-6, abs_tol=1e-6)
                if not valid:
                    raise RuntimeError('保存后的通知实例属性不符: ' + path + '.' + name)
        rows.append({'asset': path, 'count': len(actual), 'protectedHash': before, 'saved': True})
    return json.dumps({'animations': rows}, ensure_ascii=False)
