"""特感动作的离线选片 重定向与正式表现装配。"""

import hashlib
import json
import math
import re
import statistics

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBGenericEditorToolset import _apply_editor_property
from BBBTraversalAnimationBaking import _slerp


def _asset(path, kind):
    """/** @param path 明确资源 @param kind 类型 @return 已核验对象 */"""
    value = unreal.load_asset(path)
    if not isinstance(value, kind):
        raise RuntimeError('资源类型不符 '+path)
    return value


def _options():
    """/** @return 不附加二次重定向的原始姿态设置 */"""
    value = unreal.AnimPoseEvaluationOptions()
    value.evaluation_type = unreal.AnimDataEvalType.RAW
    value.should_retarget = False
    return value


def _motion(sequence, count=21):
    """/** @param sequence 已保存序列 @param count 均匀采样数 @return 关键骨骼轨迹与循环接缝 */"""
    keys = sequence.data_model_interface.get_number_of_keys()
    frames = sorted({round(i*(keys-1)/(count-1)) for i in range(count)})
    names = ('pelvis', 'head', 'hand_l', 'hand_r', 'foot_l', 'foot_r')
    samples = []
    for frame in frames:
        pose = sequence.get_anim_pose_at_frame(frame, _options())
        row = {'frame': frame}
        for name in names:
            t = pose.get_bone_pose(name, unreal.AnimPoseSpaces.WORLD)
            row[name] = [t.translation.x, t.translation.y, t.translation.z,
                         t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w]
        samples.append(row)
    distance = max(math.dist(samples[0][n][:3], samples[-1][n][:3]) for n in names)
    angle = max(math.degrees(2*math.acos(min(1, abs(sum(a*b for a, b in zip(samples[0][n][3:], samples[-1][n][3:])))))) for n in names)
    return {'asset': sequence.get_path_name(), 'keys': keys, 'seconds': sequence.get_play_length(),
            'seamCm': distance, 'seamDegrees': angle, 'samples': samples}


def _retarget(root, role, source_path, signature):
    """/** @param root 自有变体目录 @param role 输出动作 @param source_path 原片 @param signature 制作指纹 @return 同骨架正式序列 */"""
    path = root+'/Animation/AS_'+role
    assets = unreal.EditorAssetLibrary
    old = unreal.load_asset(path) if assets.does_asset_exist(path) else None
    if old and str(assets.get_metadata_tag(old, 'BBB.SpecialPolish')) == signature:
        return old, False
    if old and not (assets.get_metadata_tag(old, 'BBB.SpecialSource') or assets.get_metadata_tag(old, 'BBB.SpecialPolish')):
        raise RuntimeError('拒绝覆盖非本工具动作 '+path)
    name = root.rsplit('/', 1)[1]
    source = _asset(source_path, unreal.AnimSequence)
    mesh = _asset(root+'/Mesh/SKM_'+name, unreal.SkeletalMesh)
    native_path = '/Game/_ThirdParty/Characters/Whisper/Base_Mesh/SK_Whisper' if name == 'Whisper' else '/Game/_ThirdParty/Characters/Urban_Zombie_Pack/'+name+'/Mesh/SK_'+name
    native = _asset(native_path, unreal.SkeletalMesh)
    kind = 'Native' if source.get_skeleton() == native.get_editor_property('skeleton') else 'Shared'
    retargeter = _asset(root+'/Animation/RTG_'+kind, unreal.IKRetargeter)
    controller = unreal.IKRetargeterController.get_controller(retargeter)
    source_mesh = controller.get_preview_mesh(unreal.RetargetSourceOrTarget.SOURCE)
    if source_mesh.get_editor_property('skeleton') != source.get_skeleton():
        raise RuntimeError('动作骨架与重定向来源不符 '+source_path)
    inputs = unreal.IKRetargetBatchOperationInputs()
    inputs.assets_to_retarget = [assets.find_asset_data(source.get_path_name())]
    inputs.source_mesh = source_mesh
    inputs.target_mesh = mesh
    inputs.ik_retarget_asset = retargeter
    inputs.target_path = root+'/Animation'
    inputs.search = source.get_name()
    inputs.replace = 'AS_'+role
    inputs.include_referenced_assets = False
    inputs.overwrite_existing_files = old is not None
    inputs.retain_additive_flags = False
    result = [str(x.package_name) for x in unreal.IKRetargetBatchOperation.run_batch_retarget(inputs)]
    if result != [path]:
        raise RuntimeError('正式动作输出不唯一 '+str(result))
    return _asset(path, unreal.AnimSequence), True


def _finish(sequence, spec):
    """/** @param sequence 自有重定向结果 @param spec 裁剪与循环要求 @return 制作后的轨迹摘要 */"""
    model = sequence.data_model_interface
    total = model.get_number_of_frames()
    start, end = spec.get('frames', [0, total])
    if not 0 <= start < end <= total:
        raise RuntimeError('动作裁剪范围错误 '+sequence.get_path_name())
    poses = [sequence.get_anim_pose_at_frame(i, _options()) for i in range(start, end+1)]
    names = list(model.get_bone_track_names())
    controller = sequence.controller
    controller.open_bracket('打磨自有特感动作', False)
    try:
        if end < total:
            controller.resize_in_frames(unreal.FrameNumber(end), unreal.FrameNumber(end), unreal.FrameNumber(total), False)
        if start > 0:
            controller.resize_in_frames(unreal.FrameNumber(end-start), unreal.FrameNumber(0), unreal.FrameNumber(start), False)
        tail = min(8, max(2, (end-start)//8))
        for name in names:
            values = [pose.get_bone_pose(name, unreal.AnimPoseSpaces.LOCAL) for pose in poses]
            if str(name) == 'root':
                values = [values[0] for _ in values]
            if spec.get('loop'):
                for index in range(len(values)-tail, len(values)):
                    alpha = (index-(len(values)-tail))/(tail-1)
                    alpha = alpha*alpha*alpha*(alpha*(alpha*6-15)+10)
                    value = values[index]
                    target = values[0]
                    value.translation = value.translation*(1-alpha)+target.translation*alpha
                    value.rotation = _slerp(value.rotation, target.rotation, alpha)
                    value.scale3d = value.scale3d*(1-alpha)+target.scale3d*alpha
                    values[index] = value
            if not controller.set_bone_track_keys(name, [v.translation for v in values], [v.rotation for v in values], [v.scale3d for v in values], False):
                raise RuntimeError('骨轨写入失败 '+str(name))
    finally:
        controller.close_bracket(False)
    sequence.set_editor_property('enable_root_motion', False)
    sequence.set_editor_property('force_root_lock', True)
    return _motion(sequence, 9)


def _travel(sequence, scale):
    """/** @param sequence 完整移动循环 @param scale 身体比例 @return 接触期脚部后移累计对应的世界步幅 */"""
    rows = []
    for frame in range(sequence.data_model_interface.get_number_of_keys()):
        pose = sequence.get_anim_pose_at_frame(frame, _options())
        rows.append([pose.get_bone_pose(n, unreal.AnimPoseSpaces.WORLD).translation for n in ('foot_l', 'foot_r')])
    velocities = []
    step = sequence.get_play_length()/max(1, len(rows)-1)
    for side in range(2):
        low = min(row[side].z for row in rows)
        high = max(row[side].z for row in rows)
        for index, (a, b) in enumerate(zip(rows, rows[1:])):
            if .1*len(rows) <= index < .85*len(rows) and max(a[side].z, b[side].z) <= low+max(4.0, (high-low)*.3):
                speed = (a[side].y-b[side].y)/step
                if speed > 1.0:
                    velocities.append(speed)
    if not velocities:
        raise RuntimeError('移动动作没有可识别的支撑期 '+sequence.get_path_name())
    return max(30.0, statistics.median(velocities)*sequence.get_play_length()*scale)


def run(root, recipe):
    """/** @param root 明确的四类特感目录 @param recipe 当前阶段制作描述 @return 正式保存与轨迹回读 */"""
    if not re.fullmatch(r'/Game/_Project/Mass/Monster/SpecialInfected/(UrbanZombie[234]|Whisper)', root):
        raise RuntimeError('需要明确的正式特感目录')
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('PIE 期间等待特感制作')
    stage = recipe['stage']
    if stage == 'survey':
        sources = recipe['sources']
        if not 1 <= len(sources) <= 32:
            raise RuntimeError('单轮选片需要一至三十二项')
        return json.dumps({'readOnly': True, 'sources': [_motion(_asset(p, unreal.AnimSequence)) for p in sources]})
    name = root.rsplit('/', 1)[1]
    presentation = _asset(root+'/DA_'+name+'Presentation', unreal.BBBMonsterPresentationDefinition)
    require_asset_write([presentation], destinations=[root])
    if stage == 'polish_animations':
        rows = []
        for role, spec in recipe['animations'].items():
            if not re.fullmatch(r'[A-Za-z0-9_]+', role):
                raise RuntimeError('动作名称无效')
            signature = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            sequence, changed = _retarget(root, role, spec['source'], signature)
            report = _finish(sequence, spec) if changed else _motion(sequence, 9)
            sequence.set_preview_skeletal_mesh(presentation.get_editor_property('gore').get_editor_property('body'))
            unreal.EditorAssetLibrary.set_metadata_tag(sequence, 'BBB.SpecialPolish', signature)
            unreal.EditorAssetLibrary.set_metadata_tag(sequence, 'BBB.SpecialSource', spec['source'])
            if not unreal.EditorAssetLibrary.save_loaded_asset(sequence, False):
                raise RuntimeError('动作保存失败 '+role)
            rows.append({key: report[key] for key in ('asset', 'keys', 'seconds', 'seamCm', 'seamDegrees')})
        return json.dumps({'stage': stage, 'animations': rows})
    if stage == 'polish_physics':
        physics = presentation.get_editor_property('physics_asset')
        require_asset_write([physics])
        mesh = presentation.get_editor_property('gore').get_editor_property('body')
        tuning = recipe['physics']
        result = str(unreal.BBBHitReactionEditorLibrary.configure_physics_asset(physics, tuning['orientation'], tuning['driveDamping'], mesh, json.dumps(tuning)))
        if result.startswith('失败'):
            raise RuntimeError(result)
        for region, tune in recipe.get('profiles', {}).items():
            profile = presentation.get_editor_property('hit_reaction').get_editor_property(region+'_profile')
            result = str(unreal.BBBHitReactionEditorLibrary.configure_reaction_profile(profile, json.dumps(tune)))
            if result.startswith('失败'):
                raise RuntimeError(result)
        for field, value in recipe.get('hit_properties', {}).items():
            hit = presentation.get_editor_property('hit_reaction')
            _apply_editor_property(hit, field, value)
            presentation.set_editor_property('hit_reaction', hit)
        if not unreal.EditorAssetLibrary.save_loaded_asset(physics, False):
            raise RuntimeError('物理保存失败')
        result = str(unreal.BBBMonsterPresentationEditorLibrary.save_configuration(presentation))
        if result.startswith('失败'):
            raise RuntimeError(result)
        return json.dumps({'stage': stage, 'physics': physics.get_path_name(), 'presentation': presentation.get_path_name(), 'saved': True})
    if stage != 'polish_graph':
        raise RuntimeError('未知制作阶段')
    return _graph(root, presentation, recipe)


def _graph(root, presentation, recipe):
    """/** @param root 正式变体 @param presentation 唯一表现配置 @param recipe 动作选择与采样参数 @return 完整构图保存证据 */"""
    if len(recipe['idle']) != 3 or len(recipe['styles']) != 3 or any(len(x) != 4 for x in recipe['styles']) or len(recipe['special']) != 4:
        raise RuntimeError('需要三份待机 三种移动风格与四项技能动作')
    if not 1 <= len(recipe['attacks']) <= 4 or not 1 <= len(recipe['deaths']) <= 4 or len(recipe['attack_pivots']) != len(recipe['attacks']):
        raise RuntimeError('攻击 死亡与接触帧数量不符')
    roles = recipe['idle']+[recipe['alert']]+sum(recipe['styles'], [])+recipe['special']+recipe['attacks']+recipe['deaths']
    if any(not re.fullmatch(r'[A-Za-z0-9_]+', role) for role in roles) or any(not math.isfinite(x) or not 0 < x < 1 for x in recipe['attack_pivots']):
        raise RuntimeError('动作角色名或攻击接触进度无效')
    name = root.rsplit('/', 1)[1]
    logic = _asset(root+'/DA_'+name+'Logic', unreal.BBBMonsterDefinition)
    blueprint = _asset(root+'/ABP_'+name, unreal.AnimBlueprint)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    library = unreal.BBBAnimationGraphEditorLibrary
    def sequence(role):
        return _asset(root+'/Animation/AS_'+role, unreal.AnimSequence)
    idle = [sequence(x) for x in recipe['idle']]
    alert = [sequence(recipe['alert'])]
    styles = []
    cycles = []
    slow = []
    pursuit = []
    for index, roles in enumerate(recipe['styles']):
        clips = [sequence(x) for x in roles]
        path = root+'/BS_'+name+('Speed' if index == 0 else 'Style'+str(index))
        blend = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
        if blend is None:
            factory = unreal.BlendSpaceFactory1D()
            factory.set_editor_property('target_skeleton', clips[0].get_skeleton())
            blend = tools.create_asset(path.rsplit('/', 1)[1], root, unreal.BlendSpace1D, factory)
        walk_speed = float(logic.get_editor_property('walk_speed'))
        chase_speed = float(logic.get_editor_property('walker_chase_walk_speed'))
        slow_speed = float(presentation.get_editor_property('animation').get_editor_property('slow_walk_sample_speed'))
        speeds = [0, slow_speed, walk_speed, chase_speed, float(logic.get_editor_property('run_speed')), float(logic.get_editor_property('sprint_speed'))]
        if not library.configure_speed_blend_space(blend, [clips[0], clips[1], clips[1], clips[1], clips[2], clips[3]], speeds, .12):
            raise RuntimeError('移动采样构图失败')
        if not unreal.EditorAssetLibrary.save_loaded_asset(blend, False):
            raise RuntimeError('混合保存失败')
        styles.append(blend)
        scale = presentation.get_editor_property('mesh_transform').scale3d.x
        distances = [_travel(c, scale) for c in clips[1:]]
        cycles.append(unreal.Vector(*[d/s for d, s in zip(distances, (walk_speed, speeds[4], speeds[5]))]))
        slow.append(distances[0]/slow_speed)
        pursuit.append(distances[0]/chase_speed)
    attacks = [sequence(x) for x in recipe['attacks']]
    deaths = [sequence(x) for x in recipe['deaths']]
    if not library.build_fact_driven_state_machine_graph(blueprint, styles[0], [attacks[0], deaths[0]],
            [unreal.Name('BehaviorFact'), unreal.Name('MovementSpeedFact'), unreal.Name('ActionProgressFact')], [4, 5], .18):
        raise RuntimeError('完整事实图重建失败')
    if not library.configure_special_infected_actions(blueprint, [sequence(x) for x in recipe['special']]):
        raise RuntimeError('特殊动作构图失败')
    if not library.configure_fact_movement_styles(blueprint, styles, .18) or not library.configure_fact_locomotion_variants(blueprint, idle, alert, 3, .18):
        raise RuntimeError('移动或待机变体构图失败')
    death_duration = max(x.get_play_length() for x in deaths)
    ends = [x.get_play_length()/death_duration for x in deaths]
    pivots = recipe['attack_pivots']+[.45]*len(deaths)
    hit_fraction = presentation.get_editor_property('animation').get_editor_property('animation_hit_fraction')
    if not library.configure_fact_action_variants(blueprint, attacks+deaths, [len(attacks), len(deaths)],
            [hit_fraction]*len(attacks)+[end*.45 for end in ends], pivots, [1.0]*len(attacks)+ends, .15):
        raise RuntimeError('攻击与死亡变体构图失败')
    if not library.configure_fact_body_stagger_state(blueprint, [sequence('Stagger'+str(i)) for i in range(5)], .08):
        raise RuntimeError('部位踉跄构图失败')
    if not library.configure_fact_crawl_states(blueprint, [sequence('Crawl'+str(i)) for i in range(6)], .22):
        raise RuntimeError('爬行构图失败')
    traversal = json.loads(str(unreal.BBBMonsterTraversalEditorLibrary.configure_traversal_assets([logic], [presentation], sequence('Mantle'), sequence('Climb'))))
    if not traversal.get('success') or library.configure_fact_combat_transitions(blueprint, .18, .075, .19, .06, .2, .22, .045) < 0:
        raise RuntimeError('攀爬或动作衔接失败')
    special_rule = logic.get_editor_property('special')
    spit_origin = None
    if name == 'UrbanZombie4':
        spit = sequence('Spit')
        pose = spit.get_anim_pose_at_time(spit.get_play_length(), _options())
        point = pose.get_bone_pose('head', unreal.AnimPoseSpaces.WORLD).translation+unreal.Vector(0, 10, 0)
        origin = presentation.get_editor_property('mesh_transform').transform_location(point)
        special_rule.set_editor_property('spit_origin_offset', origin)
        spit_origin = [origin.x, origin.y, origin.z]
    animation = presentation.get_editor_property('animation')
    idle_seconds = [x.get_play_length() for x in idle]
    while len(idle_seconds) < 3:
        idle_seconds.append(idle_seconds[-1])
    animation.set_editor_property('idle_cycle_seconds', unreal.Vector(*idle_seconds))
    animation.set_editor_property('alert_cycle_seconds', alert[0].get_play_length())
    animation.set_editor_property('movement_cycle_seconds', cycles)
    animation.set_editor_property('slow_walk_cycle_seconds', unreal.Vector(*slow))
    animation.set_editor_property('pursuit_walk_cycle_seconds', unreal.Vector(*pursuit))
    animation.set_editor_property('animation_stride_scale', 1.0)
    animation.set_editor_property('death_animation_duration', death_duration)
    presentation.set_editor_property('animation', animation)
    special = dict(recipe['special_animation'])
    special['rush_stride'] = _travel(sequence(recipe['special'][1]), presentation.get_editor_property('mesh_transform').scale3d.x)
    if name == 'UrbanZombie2':
        special['rush_stride'] = max(special['rush_stride'], float(special_rule.get_editor_property('rush_speed'))*.4)
    _apply_editor_property(presentation, 'special_animation', special)
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError('特感完整图编译未通过')
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
        raise RuntimeError('动画蓝图保存失败')
    result = str(unreal.BBBMonsterPresentationEditorLibrary.save_configuration(presentation))
    if result.startswith('失败'):
        raise RuntimeError(result)
    if not unreal.EditorAssetLibrary.save_loaded_asset(logic, False):
        raise RuntimeError('逻辑挂点保存失败')
    return json.dumps({'stage': 'polish_graph', 'blueprint': blueprint.get_path_name(), 'styles': [x.get_path_name() for x in styles], 'spitOrigin': spit_origin,
                       'idleCount': len(idle), 'attackCount': len(attacks), 'deathCount': len(deaths), 'cycleSeconds': [[v.x, v.y, v.z] for v in cycles],
                       'rushStride': special['rush_stride'], 'presentationValidation': json.loads(result), 'saved': True})
