import json
import math
import os
import re
import time

import unreal

_record = {'status': 'idle'}
_handle = None
_bones = ('root', 'pelvis', 'spine_01', 'spine_02', 'spine_03', 'neck_01', 'head',
          'upperarm_l', 'lowerarm_l', 'hand_l', 'upperarm_r', 'lowerarm_r', 'hand_r',
          'thigh_l', 'calf_l', 'foot_l', 'ball_l', 'thigh_r', 'calf_r', 'foot_r', 'ball_r')


def _validate_segments(value):
    """/** @param value 明确的事实分段 @return 有界的骨骼采样计划 */"""
    segments = json.loads(value)
    fields = {'duration', 'behavior', 'speed', 'end_speed', 'cycle_seconds',
              'style', 'crawling', 'crawl_start', 'crawl_end', 'action_start', 'action_end',
              'yaw_rate', 'stagger_region'}
    if not isinstance(segments, list) or not 1 <= len(segments) <= 24:
        raise RuntimeError('采样需要一至二十四个明确分段')
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) - fields:
            raise RuntimeError('采样分段存在未知字段')
        if any(not isinstance(item, (int, float, bool)) or not math.isfinite(item) for item in segment.values()):
            raise RuntimeError('采样字段必须是有限数值或布尔值')
        if not 0 < segment.get('duration', 0) <= 10 or segment.get('behavior', 0) not in range(6):
            raise RuntimeError('采样持续时间或行为编号无效')
        if segment.get('style', segments[0].get('style', 0)) not in range(3) or segment.get('stagger_region', -1) not in range(-1, 6):
            raise RuntimeError('采样风格或踉跄部位无效')
        if segment.get('style', segments[0].get('style', 0)) != segments[0].get('style', 0):
            raise RuntimeError('同一个体不能在采样中更换出生风格')
        if any(not 0 <= segment.get(name, 0) <= 1 for name in ('crawl_start', 'crawl_end', 'action_start', 'action_end')):
            raise RuntimeError('姿态和动作进度必须归一化')
        if not 0.01 <= segment.get('cycle_seconds', 1) <= 20:
            raise RuntimeError('循环时长无效')
        if any(not 0 <= segment.get(name, 0) <= 650 for name in ('speed', 'end_speed')) or abs(segment.get('yaw_rate', 0)) > 360:
            raise RuntimeError('采样速度或实际转向速率无效')
    if sum(segment['duration'] for segment in segments) > 24:
        raise RuntimeError('单次采样最长二十四秒')
    return segments


def capture_status():
    """/** @return 当前数值采样状态 不返回逐帧大数组 */"""
    return json.dumps({key: value for key, value in _record.items() if key != 'frames'}, ensure_ascii=False)


def _transform_values(transform, z_origin=0.0):
    """/** @param transform 骨骼变换 @param z_origin 世界高度基准 @return 位置与四元数 */"""
    p, q = transform.translation, transform.rotation
    values = [p.x, p.y, p.z - z_origin, q.x, q.y, q.z, q.w]
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError('骨骼变换包含非有限数值')
    return values


def start_capture(actor_blueprint_path, segments_json, file_prefix, fps, variation_seed):
    """
    /**
     * @param actor_blueprint_path 临时非 Mass 表现演员蓝图
     * @param segments_json 固定出生风格的事实分段
     * @param file_prefix 不存在的本任务临时目录
     * @param fps 动画求值频率 不代表游戏实测帧率
     * @param variation_seed 明确的出生种子
     * @return 骨骼数据采样活动 不创建图像或渲染对象
     */
    """
    global _record, _handle
    segments = _validate_segments(segments_json)
    if _handle is not None or not re.fullmatch(r'[A-Za-z0-9_-]+', file_prefix):
        raise RuntimeError('采样正在运行或输出前缀无效')
    if fps not in (30, 60) or not 1 <= variation_seed <= 4294967295:
        raise RuntimeError('采样频率或出生种子无效')
    directory = os.path.abspath(os.path.join(unreal.Paths.project_saved_dir(), 'temp', file_prefix))
    if os.path.lexists(directory):
        raise RuntimeError('采样输出目录必须不存在')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    blueprint = unreal.load_asset(actor_blueprint_path)
    if world is None or not isinstance(blueprint, unreal.Blueprint):
        raise RuntimeError('采样需要 PIE 与有效表现蓝图')
    os.makedirs(directory)
    actors = []
    spawn = unreal.BBBBlueprintEditorLibrary.spawn_transient_pie_actor
    library = unreal.BBBAnimationGraphEditorLibrary
    states = [unreal.BBBMonsterBehavior.IDLE, unreal.BBBMonsterBehavior.ALERT, unreal.BBBMonsterBehavior.PATROL,
              unreal.BBBMonsterBehavior.CHASE, unreal.BBBMonsterBehavior.ATTACK, unreal.BBBMonsterBehavior.DEAD]
    regions = [unreal.BBBMonsterHitRegion.TORSO, unreal.BBBMonsterHitRegion.HEAD, unreal.BBBMonsterHitRegion.LEFT_ARM,
               unreal.BBBMonsterHitRegion.RIGHT_ARM, unreal.BBBMonsterHitRegion.LEFT_LEG, unreal.BBBMonsterHitRegion.RIGHT_LEG]
    _record = {'status': 'running', 'directory': directory, 'fps': fps, 'frameCount': 0, 'frames': [],
               'scope': 'fixed_step_animation_blueprint_kinematics', 'segments': segments,
               'actorBlueprint': actor_blueprint_path, 'variationSeed': variation_seed,
               'imagesGenerated': False, 'started': time.monotonic()}

    def frames():
        try:
            origin = unreal.Vector(0, 0, 20000)
            actor = spawn(world, blueprint.generated_class(), unreal.Transform(location=origin + unreal.Vector(0, 0, 90)))
            if actor is None:
                raise RuntimeError('临时表现演员创建失败')
            actors.append(actor)
            actor.set_actor_hidden_in_game(True)
            mesh = actor.get_monster_mesh()
            presentation = actor.get_monster_presentation()
            mesh.set_component_tick_enabled(False)
            mesh.set_editor_property('enable_update_rate_optimizations', False)
            mesh.set_editor_property('visibility_based_anim_tick_option', unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
            style = segments[0].get('style', 0)
            presentation.call_method('ApplyPresentationState', (states[0], 0.0, 0.0, 1, 0.0))
            library.set_preview_locomotion_facts(mesh, style, 0.0, False, 0.0, variation_seed)
            for index in range(12):
                yield
                if not library.evaluate_animation_blueprint_frame(mesh, 1 / fps):
                    raise RuntimeError('动画图预热失败')
            phase, yaw, elapsed = 0.0, 0.0, 0.0
            position = unreal.Vector(0, 0, 90)
            previous_action = 1
            previous_segment = None
            entered_time = 0.0
            for segment_index, segment in enumerate(segments):
                count = max(1, round(segment['duration'] * fps))
                behavior = segment.get('behavior', 0)
                new_action = previous_segment is None or behavior != previous_segment.get('behavior', 0)
                if previous_segment and behavior == 4 and segment.get('action_start', 0) < previous_segment.get('action_end', 0):
                    new_action = True
                action_id = previous_action + int(new_action)
                if new_action:
                    entered_time = elapsed + 1.0
                    previous_action = action_id
                for index in range(count):
                    fraction = index / max(count - 1, 1)
                    speed = segment.get('speed', 0) + (segment.get('end_speed', segment.get('speed', 0)) - segment.get('speed', 0)) * fraction
                    progress = segment.get('action_start', 0) + (segment.get('action_end', 0) - segment.get('action_start', 0)) * fraction
                    crawl = segment.get('crawl_start', 1) + (segment.get('crawl_end', 1) - segment.get('crawl_start', 1)) * fraction
                    cycle = segment.get('cycle_seconds', 1)
                    phase = (phase + 1 / fps / cycle) % 1
                    yaw += segment.get('yaw_rate', 0) / fps
                    position += unreal.Vector(math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0) * (speed / fps)
                    position.z = 90 - 45 * crawl if segment.get('crawling', False) else 90
                    actor.set_actor_location_and_rotation(origin + position, unreal.Rotator(yaw=yaw), False, True)
                    presentation.call_method('ApplyPresentationState', (states[segment.get('behavior', 0)], speed, entered_time, action_id, progress))
                    if not library.set_preview_locomotion_facts(mesh, style, phase, segment.get('crawling', False), crawl, variation_seed):
                        raise RuntimeError('姿态事实写入失败')
                    region = segment.get('stagger_region', -1)
                    presentation.call_method('ApplyStaggerState', (region >= 0, progress, regions[max(0, region)]))
                    if not library.evaluate_animation_blueprint_frame(mesh, 1 / fps):
                        raise RuntimeError('逐帧动画图求值失败')
                    bones, component_bones = {}, {}
                    for name in _bones:
                        if not mesh.does_socket_exist(name):
                            raise RuntimeError('正式网格缺少采样骨骼: ' + name)
                        bones[name] = _transform_values(mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_WORLD), origin.z)
                        component_bones[name] = _transform_values(mesh.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT))
                    frame = {'index': _record['frameCount'], 'time': elapsed, 'segment': segment_index, 'speed': speed,
                             'yaw': yaw, 'bones': bones, 'componentBones': component_bones, 'actor': [position.x, position.y, position.z],
                             'phase': phase, 'actionId': action_id, 'actionProgress': progress, 'crawlProgress': crawl,
                             'crawling': segment.get('crawling', False)}
                    instance = mesh.get_anim_instance()
                    frame['selection'] = {name: instance.get_editor_property(name) for name in
                                          ('ActionEpoch', 'AttackPoseIndex', 'DeadPoseIndex', 'AttackSampleTime', 'DeadSampleTime')}
                    if index in (0, count - 1) or abs(progress - 0.4) < 1 / fps:
                        graph = json.loads(unreal.BBBBlueprintEditorLibrary.probe_animation_instance_runtime(mesh.get_anim_instance()))
                        frame['graph'] = {key: graph[key] for key in ('states', 'players') if key in graph}
                    _record['frames'].append(frame)
                    _record['frameCount'] += 1
                    elapsed += 1 / fps
                    yield
                previous_segment = segment
            _record['simulatedSeconds'] = elapsed
        finally:
            for actor in reversed(actors):
                if unreal.SystemLibrary.is_valid(actor):
                    actor.destroy_actor()
            _record['temporaryActorsDestroyed'] = all(not unreal.SystemLibrary.is_valid(actor) for actor in actors)

    iterator = frames()

    def finish(status, error=None):
        global _handle
        _record['status'] = status
        _record['error'] = error
        _record['wallSeconds'] = time.monotonic() - _record['started']
        unreal.unregister_slate_post_tick_callback(_handle)
        _handle = None
        with open(os.path.join(directory, 'motion.json'), 'w', encoding='utf-8') as stream:
            json.dump(_record, stream, ensure_ascii=False, separators=(',', ':'))

    def tick(delta_seconds):
        try:
            if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() != world:
                raise RuntimeError('采样世界已结束')
            if time.monotonic() - _record['started'] > 300:
                raise RuntimeError('骨骼采样等待超时')
            next(iterator)
        except StopIteration:
            finish('completed')
        except Exception as error:
            iterator.close()
            finish('failed', str(error))
            unreal.log_error('[BBBFactKinematics] ' + str(error))

    _handle = unreal.register_slate_post_tick_callback(tick)
    from BBBMcpCapabilities import register_activity
    register_activity('animation_finish:motion', lambda: _record)
    return capture_status()
