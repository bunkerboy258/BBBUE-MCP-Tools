import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

import unreal
from BBBAssetWritePolicy import require_asset_write
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


_FORMAT = 'BBBGripAuthoring'
_FINGERS = tuple(f'{finger}_{joint:02}_{side}' for side in ('l', 'r')
                 for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3))


def _digest(value):
    """/** @param value 明确制作输入 @return 稳定内容摘要 */"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _safe_file(project, weapon_root, recipe_path):
    """/** @param project 项目根 @param weapon_root 明确型号根 @param recipe_path 项目相对制作文件 @return 型号Source内无链接正式制作路径 */"""
    if re.fullmatch(r'/Game/_Project/(?:[A-Za-z0-9_]+/)+[A-Za-z0-9_]+', weapon_root) is None:
        raise RuntimeError('WEAPON_ROOT_REQUIRED: 必须明确自有武器型号根')
    expected = project / 'Content' / weapon_root.removeprefix('/Game/') / 'Source' / 'Animation'
    candidate = Path(recipe_path)
    if candidate.is_absolute() or '..' in candidate.parts or not recipe_path.endswith('.json.source'):
        raise RuntimeError('RECIPE_PATH_REQUIRED: 使用型号Source/Animation下项目相对.json.source路径')
    destination = project / candidate
    if destination.parent.resolve() != expected.resolve():
        raise RuntimeError('RECIPE_SCOPE_MISMATCH: 制作文件必须直接属于明确型号Source/Animation')
    current = destination
    while current != project.parent:
        if current.is_symlink() or (current.exists() and getattr(os.path, 'isjunction', lambda path: False)(current)):
            raise RuntimeError('RECIPE_LINK_REJECTED: 制作路径包含链接')
        if current == project:
            break
        current = current.parent
    return destination


def _asset(path, expected):
    """/** @param path 明确包路径 @param expected 正式资产类型 @return 类型正确的资产 */"""
    if not isinstance(path, str) or re.fullmatch(r'/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+', path) is None:
        raise RuntimeError('ASSET_PATH_REQUIRED: ' + str(path))
    asset = unreal.load_asset(path)
    if not isinstance(asset, expected):
        raise RuntimeError('ASSET_TYPE_MISMATCH: ' + path)
    return asset


def _values(transform):
    """/** @param transform 引擎变换 @return 平移四元数缩放十项 */"""
    return list(transform.translation.to_tuple()) + list(transform.rotation.to_tuple()) + list(transform.scale3d.to_tuple())


def _transform(values):
    """/** @param values 十项变换 @return 引擎变换 */"""
    value = unreal.Transform(location=unreal.Vector(*values[:3]), scale=unreal.Vector(*values[7:10]))
    value.rotation = unreal.Quat(*values[3:7])
    return value


def _socket(mesh, name):
    """/** @param mesh 明确网格 @param name 明确插槽 @return 实际父骨及相对变换 */"""
    socket = mesh.find_socket(name)
    if socket is None:
        raise RuntimeError('SOCKET_REQUIRED: ' + name)
    transform = unreal.Transform(location=socket.relative_location, rotation=socket.relative_rotation, scale=socket.relative_scale)
    return {'parent': str(socket.bone_name), 'local': _values(transform)}


def _write_recipe(path, recipe, project):
    """/** @param path 唯一制作源 @param recipe 当前有效数据 @return 保存后内容摘要 不建立副本 */"""
    text = json.dumps(recipe, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return _digest(recipe)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = project / 'Saved' / 'temp' / ('GripAuthoring_' + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    try:
        pending = temporary / 'Recipe.json.source'
        pending.write_text(text, encoding='utf-8')
        pending.replace(path)
    finally:
        for child in temporary.iterdir():
            child.unlink()
        temporary.rmdir()
    if json.loads(path.read_text(encoding='utf-8')) != recipe:
        raise RuntimeError('RECIPE_SAVE_MISMATCH: 制作源回读不一致')
    return _digest(recipe)


def _recipe(path, root):
    """/** @param path 唯一正式制作文件 @param root 任务型号根 @return 校验后的当前配置 */"""
    recipe = json.loads(path.read_text(encoding='utf-8'))
    if recipe.get('format') != _FORMAT or recipe.get('schema') != 1 or recipe.get('weapon_root') != root:
        raise RuntimeError('RECIPE_FORMAT_MISMATCH: 使用当前BBBGripAuthoring格式 禁止历史格式兼容执行')
    required = ('definition', 'character_mesh', 'weapon_mesh', 'reference_animation', 'rig', 'sequence', 'animation',
                'attachment_socket', 'left_socket', 'calibration', 'pose', 'fitting', 'neighbors', 'checks')
    if any(name not in recipe for name in required):
        raise RuntimeError('RECIPE_FIELDS_REQUIRED: ' + ','.join(name for name in required if name not in recipe))
    for field, folder in (('definition', ''), ('rig', '/Animation/work/'), ('sequence', '/Animation/work/'), ('animation', '/Animation/Sequence/')):
        expected = root + folder
        if field == 'definition':
            if recipe[field].rsplit('/', 1)[0] != root:
                raise RuntimeError('ASSET_SCOPE_MISMATCH: definition')
            continue
        if recipe[field].rsplit('/', 1)[0] + '/' != expected:
            raise RuntimeError('ASSET_SCOPE_MISMATCH: ' + field)
    rotations = recipe['pose'].get('local_rotations', {})
    if set(rotations) != set(_FINGERS):
        raise RuntimeError('FINGER_SEED_REQUIRED: 必须明确三十根手指骨局部四元数')
    for name, quaternion in rotations.items():
        if not isinstance(quaternion, list) or len(quaternion) != 4 or any(type(value) not in (int, float) or not math.isfinite(value) for value in quaternion):
            raise RuntimeError('FINGER_QUATERNION_INVALID: ' + name)
        if abs(sum(value * value for value in quaternion) - 1) > .0001:
            raise RuntimeError('FINGER_QUATERNION_NOT_NORMALIZED: ' + name)
    contacts = recipe['fitting'].get('contacts', [])
    if 'attachment' in recipe['fitting']:
        raise RuntimeError('ATTACHMENT_SINGLE_SOURCE_REQUIRED: 挂接只由calibration和实际插槽链维护')
    contact_bones = [name for contact in contacts for name in contact['bones']]
    if contacts and (len(contact_bones) != len(set(contact_bones)) or set(contact_bones) != set(_FINGERS)):
        raise RuntimeError('CONTACT_COVERAGE_REQUIRED: 十指各自的明确接触组必须覆盖三十根指骨且不能重复')
    if recipe['neighbors']:
        required_pairs = {frozenset((first + '_' + side, second + '_' + side)) for side in ('l', 'r')
                          for first, second in (('index', 'middle'), ('middle', 'ring'), ('ring', 'pinky'))}
        actual_pairs = set()
        for neighbor in recipe['neighbors']:
            groups = []
            for field in ('first_bones', 'second_bones'):
                names = neighbor[field]
                if not names or any(name not in _FINGERS for name in names):
                    raise RuntimeError('NEIGHBOR_BONES_REQUIRED: 邻指区域必须为明确指骨')
                tags = {name.split('_')[0] + '_' + name.split('_')[-1] for name in names}
                if len(tags) != 1:
                    raise RuntimeError('NEIGHBOR_REGION_MIXED: 同一指面不能混合不同手指')
                groups.append(next(iter(tags)))
            actual_pairs.add(frozenset(groups))
        if not required_pairs <= actual_pairs:
            raise RuntimeError('NEIGHBOR_COVERAGE_REQUIRED: 必须覆盖左右各自的食中 中环 环小指 六对实际邻指')
    for field in ('maximum_inside_depth_cm', 'contact_patch_distance_cm', 'minimum_contact_patch_vertices',
                  'maximum_pose_position_error_cm', 'maximum_pose_rotation_error_degrees', 'maximum_static_motion_cm', 'maximum_wrist_error_cm'):
        value = recipe['checks'].get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise RuntimeError('CHECK_THRESHOLD_REQUIRED: ' + field)
    return recipe


def _inputs(recipe, project):
    """/** @param recipe 制作配置 @param project 项目根 @return 当前依赖摘要和实际插槽链 */"""
    meshes = [_asset(recipe[field], unreal.SkeletalMesh) for field in ('character_mesh', 'weapon_mesh')]
    definition, current = _definition(recipe)
    if str(definition.get_editor_property('left_hand_socket_name')) != recipe['left_socket']:
        raise RuntimeError('LEFT_SOCKET_CONFIG_MISMATCH: 制作目标必须匹配武器正式左手插槽')
    hashes = {}
    for field in ('character_mesh', 'weapon_mesh', 'reference_animation'):
        path = project / 'Content' / (recipe[field].removeprefix('/Game/') + '.uasset')
        if not path.is_file():
            raise RuntimeError('DEPENDENCY_FILE_REQUIRED: ' + str(path))
        hashes[field] = hashlib.sha256(path.read_bytes()).hexdigest()
    context = {'attachment_socket': _socket(meshes[0], recipe['attachment_socket']),
               'left_socket': _socket(meshes[1], recipe['left_socket'])}
    config = {key: value for key, value in recipe.items() if key not in ('solution', 'validation', 'review')}
    code = {}
    for name in ('BBBGripAuthoring.py', 'BBBGripFingerConstraints.py', 'BBBGripPoseFitting.py', 'BBBGripSolidAudit.py'):
        code[name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    return {'digest': _digest({'configuration': config, 'files': hashes, 'sockets': context, 'solver': code}),
            'files': hashes, 'context': context, 'solver': code, 'configuration_digest': _digest(config)}


def _definition(recipe):
    """/** @param recipe 制作配置 @return 当前定义与实际偏移 */"""
    definition = unreal.load_asset(recipe['definition'])
    if definition is None:
        raise RuntimeError('DEFINITION_REQUIRED')
    mesh = definition.get_editor_property('equipment_mesh')
    if mesh is None or mesh.get_path_name().split('.')[0] != recipe['weapon_mesh']:
        raise RuntimeError('DEFINITION_MESH_MISMATCH')
    return definition, {'spawn_offset': _values(definition.get_editor_property('spawn_offset')),
                        'left_ik_offset': list(definition.get_editor_property('left_hand_ik_offset').to_tuple()),
                        'left_ik_rotation': list(definition.get_editor_property('left_hand_ik_rotation').quaternion().to_tuple())}


def _fingerprint(recipe, project):
    """/** @param recipe 制作配置 @param project 项目根 @return 运行输出和制作资产的当前摘要 */"""
    files = {}
    for field in ('rig', 'sequence', 'animation'):
        path = project / 'Content' / (recipe[field].removeprefix('/Game/') + '.uasset')
        if not path.is_file():
            return None
        files[field] = hashlib.sha256(path.read_bytes()).hexdigest()
    definition, values = _definition(recipe)
    grip = definition.get_editor_property('character_grip_pose')
    values['animation'] = grip.get_path_name().split('.')[0] if grip else None
    return _digest({'files': files, 'definition': values})


def _response(recipe, inputs, project, validation=None):
    """/** @param recipe 当前制作数据 @param inputs 当前依赖 @param project 项目根 @param validation 本次可选审计 @return 唯一后续动作及明确验收边界 */"""
    next_action = 'solve'
    status = 'needs_solve'
    solution = recipe.get('solution')
    if not recipe['fitting'].get('contacts') or len(recipe['neighbors']) < 6:
        return {'status': 'needs_contact_configuration', 'next': {'type': 'edit_recipe', 'fields': ['fitting.contacts', 'neighbors']}, 'runtimeAcceptance': 'pending'}
    fingerprint = _fingerprint(recipe, project)
    if solution and solution.get('input_digest') == inputs['digest']:
        status = 'needs_save'
        next_action = 'save'
        if not solution.get('passed'):
            status = 'geometry_failed'
            next_action = 'adjust_recipe'
        if solution.get('passed') and fingerprint and recipe.get('validation', {}).get('fingerprint') == fingerprint:
            current = validation or recipe['validation']
            status = 'needs_human_review'
            next_action = 'review'
            if not current.get('passed'):
                status = 'validation_failed'
                next_action = 'adjust_recipe'
            if current.get('passed') and recipe.get('review', {}).get('fingerprint') == fingerprint and recipe['review'].get('decision') == 'accepted':
                status = 'ready_for_runtime_acceptance'
                next_action = None
    if validation and not validation.get('passed'):
        status = 'validation_failed'
        next_action = 'adjust_recipe'
    next_step = {'action': next_action} if next_action else None
    if next_action == 'adjust_recipe':
        next_step = {'type': 'edit_recipe', 'fields': ['calibration', 'fitting.contacts', 'neighbors'],
                     'failures': solution.get('geometry', {}).get('failures', []) if solution else []}
    return {'status': status, 'next': next_step,
            'inputDigest': inputs['digest'], 'fingerprint': fingerprint,
            'visualAcceptance': recipe.get('review', {}).get('decision', 'pending'),
            'runtimeAcceptance': 'pending', 'wholeWeaponSolidPenetrationProven': False}


def _sample(recipe, name, animation, time, directory):
    """/** @param recipe 制作配置 @param name 本次报告名 @param animation 明确动画或参考姿势 @param time 秒数 @param directory 本次专属目录 @return 真实零级表面采样 */"""
    import BBBGripGeometryTools

    mesh = recipe['character_mesh']
    bones = ['hand_l', 'hand_r']
    if name == 'Weapon':
        mesh = recipe['weapon_mesh']
        bones = []
    result = json.loads(BBBGripGeometryTools.sample_surface(mesh, animation, time, bones, .35, [], directory.name + '/' + name))
    return json.loads(Path(result['report']).read_text(encoding='utf-8'))


def _run_worker(recipe, inputs, action, python_executable, project, require_definition_match=True):
    """/** @param recipe 制作配置 @param inputs 当前依赖 @param action solve或audit @param python_executable 已配置NumPy解释器 @param project 项目根 @return 正式离线工作器结果 自动清除本次文件 */"""
    interpreter = Path(python_executable)
    if not interpreter.is_absolute() or not interpreter.is_file() or interpreter.name.lower() != 'python.exe':
        raise RuntimeError('SOLVER_PYTHON_REQUIRED: 提供已安装NumPy的明确python.exe')
    directory = project / 'Saved' / 'temp' / ('GripAuthoring_' + uuid.uuid4().hex)
    if directory.parent.is_symlink() or getattr(os.path, 'isjunction', lambda path: False)(directory.parent):
        raise RuntimeError('TEMP_LINK_REJECTED')
    directory.mkdir(parents=True)
    try:
        animation = recipe['reference_animation']
        if action == 'audit':
            animation = recipe['animation']
        character = _sample(recipe, 'Character', animation, 0, directory)
        weapon = _sample(recipe, 'Weapon', '', 0, directory)
        request = {'action': action, 'recipe': recipe, 'context': inputs['context'], 'character': character, 'weapon': weapon}
        if action == 'audit':
            from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

            asset = _asset(animation, unreal.AnimSequence)
            if asset.get_editor_property('additive_anim_type') != unreal.AdditiveAnimationType.AAT_NONE or asset.get_editor_property('enable_root_motion'):
                raise RuntimeError('GRIP_SEQUENCE_FORMAT_INVALID: 静态握姿必须为无RootMotion的绝对动画')
            if abs(asset.sequence_length - 2 / 30) > .00001:
                raise RuntimeError('GRIP_SEQUENCE_LENGTH_INVALID: 静态握姿必须为三十帧率的三个相同采样')
            if unreal.AnimationLibrary.get_animation_curve_names(asset, unreal.RawCurveTrackTypes.RCT_FLOAT) or unreal.AnimationLibrary.get_animation_notify_events(asset):
                raise RuntimeError('GRIP_SEQUENCE_EVENTS_REJECTED: 静态握姿不得有曲线或通知')
            definition, current = _definition(recipe)
            request['definition_calibration'] = current
            request['require_definition_match'] = require_definition_match
            controls = ['pose_' + name for name in recipe['solution']['component_pose']]
            request['control_keys'] = json.loads(authoring.sample_sequence_controls(recipe['sequence'], [0, 1], controls))
            metadata = json.loads(authoring.inspect_control_rig_controls(recipe['rig']))
            request['control_offsets'] = {item['name']: item['offset'] for item in metadata['controls']}
            request['samples'] = [character]
            for index, time in enumerate((asset.sequence_length / 2, asset.sequence_length)):
                request['samples'].append(_sample(recipe, 'Static' + str(index), animation, time, directory))
        source = directory / 'Request.json'
        destination = directory / 'Result.json'
        source.write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        worker = Path(__file__).with_name('BBBGripAuthoring.py')
        completed = subprocess.run([str(interpreter), '-B', '-X', 'utf8', str(worker), str(source), str(destination)],
                                   capture_output=True, text=True, encoding='utf-8', timeout=480,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode or not destination.is_file():
            raise RuntimeError('GRIP_SOLVER_FAILED: ' + completed.stderr[-4000:])
        return json.loads(destination.read_text(encoding='utf-8'))
    finally:
        for child in directory.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        directory.rmdir()


def _rig_graph(names):
    """/** @param names 父骨在前的实际骨名 @return 明确组件姿势控制器和官方RigVM图 */"""
    controls = [{'name': 'pose_' + name, 'type': 'EULER_TRANSFORM'} for name in names]
    nodes = [{'name': 'Begin', 'struct': '/Script/ControlRig.RigUnit_BeginExecution'}]
    links = [['Begin.ExecutePin', 'ApplyPose.ExecutePin']]
    for index, name in enumerate(names):
        get_name = 'Read_' + name
        nodes.append({'name': get_name, 'struct': '/Script/ControlRig.RigUnit_GetTransform', 'position': [0, index * 120],
                      'defaults': {'Item': '(Type=Control,Name="pose_' + name + '")', 'Space': 'GlobalSpace', 'bInitial': 'False'}})
        links.append([get_name + '.Transform', 'ApplyPose.Transforms.' + str(index)])
    items = '(' + ','.join('(Type=Bone,Name="' + name + '")' for name in names) + ')'
    identity = '(Rotation=(X=0,Y=0,Z=0,W=1),Translation=(X=0,Y=0,Z=0),Scale3D=(X=1,Y=1,Z=1))'
    nodes.append({'name': 'ApplyPose', 'struct': '/Script/ControlRig.RigUnit_SetTransformItemArray', 'position': [400, 0],
                  'defaults': {'Items': items, 'Transforms': '(' + ','.join(identity for name in names) + ')',
                               'Space': 'GlobalSpace', 'bInitial': 'False', 'Weight': '1.0', 'bPropagateToChildren': 'False'}})
    return controls, {'nodes': nodes, 'links': links}


def _save_assets(recipe):
    """/** @param recipe 已通过数值检查的完整制作输入 @return 明确保存的制作和运行资产 */"""
    from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

    paths = [recipe[field] for field in ('rig', 'sequence', 'animation', 'definition')]
    dirty = {package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    if set(paths) & dirty:
        raise RuntimeError('TARGET_DIRTY: 目标有未交接修改 请先保存并回读')
    existing = [unreal.load_asset(path) for path in paths if unreal.EditorAssetLibrary.does_asset_exist(path)]
    destinations = [path for path in paths if not unreal.EditorAssetLibrary.does_asset_exist(path)]
    require_asset_write(existing, destinations)
    solution = recipe['solution']
    if not unreal.EditorAssetLibrary.does_asset_exist(recipe['rig']):
        controls, graph = _rig_graph(list(solution['component_pose']))
        authoring.create_control_rig(recipe['rig'], recipe['character_mesh'], json.dumps(controls), json.dumps(graph))
    if not unreal.EditorAssetLibrary.does_asset_exist(recipe['sequence']):
        authoring.prepare_animation_sequence(recipe['sequence'], recipe['reference_animation'], recipe['character_mesh'])
    sequence = _asset(recipe['sequence'], unreal.LevelSequence)
    character_mesh = _asset(recipe['character_mesh'], unreal.SkeletalMesh)
    characters = [binding for binding in sequence.get_bindings()
                  if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
                  and binding.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == character_mesh]
    if len(characters) != 1:
        raise RuntimeError('SEQUENCE_CHARACTER_BINDING_NOT_UNIQUE')
    sources = [section.get_editor_property('params').animation
               for track in characters[0].find_tracks_by_type(unreal.MovieSceneSkeletalAnimationTrack) for section in track.get_sections()]
    reference = _asset(recipe['reference_animation'], unreal.AnimSequence)
    if len(sources) != 1 or sources[0] != reference or recipe['reference_animation'] == recipe['animation']:
        raise RuntimeError('SEQUENCE_SOURCE_MISMATCH: 制作输入必须为明确且独立的公共参考动画')
    sequence.set_display_rate(unreal.FrameRate(numerator=30, denominator=1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(2)
    keys = []
    for name, values in solution['component_pose'].items():
        value = {'position': values[:3], 'rotation': values[3:7], 'scale': values[7:10]}
        for frame in (0, 1):
            keys.append({'control': 'pose_' + name, 'frame': frame, 'value': value})
    authoring.configure_sequence_rig(recipe['sequence'], recipe['rig'], json.dumps(keys), False, recipe['character_mesh'])
    label = 'GripWeapon'
    weapon_mesh = _asset(recipe['weapon_mesh'], unreal.SkeletalMesh)
    bindings = [binding for binding in sequence.get_bindings()
                if isinstance(binding.get_object_template(), unreal.SkeletalMeshActor)
                and binding.get_object_template().skeletal_mesh_component.skeletal_mesh_asset == weapon_mesh]
    if len(bindings) > 1:
        raise RuntimeError('SEQUENCE_WEAPON_BINDING_NOT_UNIQUE')
    if bindings:
        label = bindings[0].get_name()
    offset = solution['calibration']['spawn_offset']
    transform = {'position': offset[:3], 'rotation': offset[3:7], 'scale': offset[7:10]}
    if not bindings:
        authoring.create_sequence_attachment(recipe['sequence'], label, recipe['weapon_mesh'], recipe['attachment_socket'],
                                            json.dumps(transform), '[[0,3]]', '')
    if bindings:
        authoring.set_sequence_attachment_transform(recipe['sequence'], label, json.dumps(transform))
    authoring.bake_control_rig_animation(recipe['sequence'], recipe['animation'], recipe['character_mesh'])
    return paths[:3]


def _apply_definition(recipe):
    """/** @param recipe 烘焙后已通过真实回读的制作结果 @return 保存后的装备配置 */"""
    definition, current = _definition(recipe)
    require_asset_write([definition])
    calibration = recipe['solution']['calibration']
    definition.set_editor_property('spawn_offset', _transform(calibration['spawn_offset']))
    definition.set_editor_property('left_hand_ik_offset', unreal.Vector(*calibration['left_ik_offset']))
    definition.set_editor_property('left_hand_ik_rotation', unreal.Quat(*calibration['left_ik_rotation']).rotator())
    definition.set_editor_property('character_grip_pose', _asset(recipe['animation'], unreal.AnimSequence))
    if not unreal.EditorAssetLibrary.save_loaded_asset(definition, False):
        raise RuntimeError('DEFINITION_SAVE_FAILED')
    return definition.get_path_name()


def _initialize(path, root, project, definition_path, character_mesh_path, reference_animation_path):
    """/** @param path 新制作文件 @param root 型号根 @param project 项目根 @param definition_path 明确定义 @param character_mesh_path 实际角色网格 @param reference_animation_path 公共参考动作 @return 含当前偏移和真实手指种子的制作模板 */"""
    if path.exists():
        raise RuntimeError('RECIPE_ALREADY_EXISTS: initialize拒绝覆盖正式制作源')
    if not definition_path or not character_mesh_path or not reference_animation_path:
        return {'status': 'needs_initialize_inputs', 'next': {'action': 'initialize', 'required': ['definition_path', 'character_mesh_path', 'reference_animation_path']}}
    if definition_path.rsplit('/', 1)[0] != root:
        raise RuntimeError('DEFINITION_SCOPE_MISMATCH')
    definition = unreal.load_asset(definition_path)
    if definition is None:
        raise RuntimeError('DEFINITION_REQUIRED')
    mesh = definition.get_editor_property('equipment_mesh')
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError('WEAPON_SKELETAL_MESH_REQUIRED')
    _asset(character_mesh_path, unreal.SkeletalMesh)
    _asset(reference_animation_path, unreal.AnimSequence)
    model = root.rsplit('/', 1)[-1]
    recipe = {'format': _FORMAT, 'schema': 1, 'weapon_root': root, 'definition': definition_path,
              'character_mesh': character_mesh_path, 'weapon_mesh': mesh.get_path_name().split('.')[0],
              'reference_animation': reference_animation_path,
              'rig': root + '/Animation/work/CR_' + model + '_HandGrip',
              'sequence': root + '/Animation/work/LS_' + model + '_HandGrip',
              'animation': root + '/Animation/Sequence/AS_' + model + '_HandGrip',
              'attachment_socket': 'WeaponGrip_R', 'left_socket': 'LeftHand',
              'fitting': {'contacts': [], 'maximum_delta_degrees': 25, 'steps_degrees': [8, 3, 1], 'regularization': .00008},
              'pose': {'mode': 'fit', 'local_rotations': {}}, 'neighbors': [],
              'checks': {'maximum_inside_depth_cm': .03, 'contact_patch_distance_cm': .2, 'minimum_contact_patch_vertices': 3,
                         'maximum_pose_position_error_cm': .001, 'maximum_pose_rotation_error_degrees': .02,
                         'maximum_static_motion_cm': .001, 'maximum_wrist_error_cm': .001}}
    current_definition, calibration = _definition(recipe)
    recipe['calibration'] = {'mode': 'fixed', **calibration}
    directory = project / 'Saved' / 'temp' / ('GripAuthoring_' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    try:
        sample = _sample(recipe, 'Seed', reference_animation_path, 0, directory)
        recipe['pose']['local_rotations'] = {bone['name']: bone['local'][3:7] for bone in sample['bones'] if bone['name'] in _FINGERS}
    finally:
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
    _write_recipe(path, recipe, project)
    _recipe(path, root)
    return {'status': 'needs_contact_configuration', 'recipe': str(path),
            'next': {'type': 'edit_recipe', 'fields': ['fitting.contacts', 'neighbors']},
            'runtimeAcceptance': 'pending'}


@unreal.uclass()
class BBBGripAuthoringToolset(unreal.ToolsetDefinition):
    @mcp_tool
    @staticmethod
    def sample_static_attachment_surface(mesh_path: str, output_name: str) -> str:
        """
        /**
         * 只读提取独立静态附件的实际渲染三角面
         * @param mesh_path\t明确静态网格
         * @param output_name\t任务目录与文件名两段 不带扩展名
         * @return 原生LOD0网格组件空间报告
         */
        """
        if re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', output_name) is None:
            raise RuntimeError('ATTACHMENT_OUTPUT_TASK_REQUIRED')
        project = Path(unreal.Paths.project_dir()).resolve()
        destination = project / 'Saved' / 'temp' / (output_name + '.json')
        for candidate in [destination, *destination.parents]:
            if candidate == project:
                break
            if candidate.is_symlink() or getattr(os.path, 'isjunction', lambda path: False)(candidate):
                raise RuntimeError('ATTACHMENT_OUTPUT_LINK_REJECTED')
        mesh = _asset(mesh_path, unreal.StaticMesh)
        dynamic = unreal.DynamicMesh()
        options = unreal.GeometryScriptCopyMeshFromAssetOptions()
        lod = unreal.GeometryScriptMeshReadLOD(lod_type=unreal.GeometryScriptLODType.RENDER_DATA, lod_index=0)
        copied, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh_v2(mesh, dynamic, options, lod, True)
        if outcome != unreal.GeometryScriptOutcomePins.SUCCESS or copied != dynamic:
            raise RuntimeError('ATTACHMENT_RENDER_LOD0_COPY_FAILED')
        unused, positions, vertex_gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dynamic, False)
        unused, indices, triangle_gaps = unreal.GeometryScript_MeshQueries.get_all_triangle_indices(dynamic, False)
        if vertex_gaps or triangle_gaps:
            raise RuntimeError('ATTACHMENT_RENDER_TOPOLOGY_HAS_GAPS')
        positions = unreal.GeometryScript_List.convert_vector_list_to_array(positions)
        indices = unreal.GeometryScript_List.convert_triangle_list_to_array(indices)
        if not positions or not indices:
            raise RuntimeError('ATTACHMENT_RENDER_LOD0_EMPTY')
        report = {'mesh': mesh_path, 'meshType': 'StaticMesh', 'space': 'mesh_component_centimeters',
                  'lod': 0, 'source': 'RenderDataLOD0', 'readOnly': True, 'localRotationOverrides': {},
                  'vertices': [{'id': index, 'position': list(value.to_tuple())} for index, value in enumerate(positions)],
                  'triangles': [{'id': index, 'vertices': list(value.to_tuple())} for index, value in enumerate(indices)]}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return json.dumps({'report': str(destination), 'mesh': mesh_path, 'readOnly': True,
                           'vertices': len(positions), 'triangles': len(indices), 'source': 'RenderDataLOD0'})

    @mcp_tool
    @staticmethod
    def apply_action_recipe(weapon_root: str, recipe_path: str, action_index: int, dry_run: bool = True) -> str:
        """
        /**
         * 从型号唯一动作制作源写入绝对轨道并同步可编辑底稿
         * @param weapon_root\t明确武器型号根
         * @param recipe_path\t型号Source/Animation中的动作制作文件
         * @param action_index\t明确的一条动作索引
         * @param dry_run\t只检查范围和输入
         * @return 轨道及控制器保存回读结果
         */
        """
        from BBBAnimationMigrationToolset import BBBAnimationMigrationToolset as migration
        from BBBControlRigAuthoringToolset import BBBControlRigAuthoringToolset as authoring

        project = Path(unreal.Paths.project_dir()).resolve()
        path = _safe_file(project, weapon_root, recipe_path)
        recipe = json.loads(path.read_text(encoding='utf-8'))
        if recipe.get('schema') != 1 or recipe.get('weapon') != weapon_root:
            raise RuntimeError('ACTION_RECIPE_SCOPE_MISMATCH')
        actions = recipe.get('actions', [])
        if type(action_index) != int or action_index < 0 or action_index >= len(actions):
            raise RuntimeError('ACTION_INDEX_INVALID')
        request = actions[action_index]
        allowed = {'clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l', 'ik_hand_l', 'ik_hand_r', 'ik_hand_gun'} | set(_FINGERS)
        if not request.get('tracks') or not set(request['tracks']) <= allowed:
            raise RuntimeError('ACTION_BONE_SCOPE_INVALID')
        for field, folder in (('asset', '/Animation/Sequence/'), ('sequence', '/Animation/work/')):
            if request[field].rsplit('/', 1)[0] + '/' != weapon_root + folder:
                raise RuntimeError('ACTION_OUTPUT_SCOPE_MISMATCH: ' + field)
        if request['source'].rsplit('/', 1)[0] + '/' != weapon_root + '/Animation/Sequence/':
            raise RuntimeError('ACTION_SOURCE_SCOPE_MISMATCH')
        _asset(recipe['rig'], unreal.ControlRigBlueprint)
        grip_path = _safe_file(project, weapon_root, recipe['grip_recipe_path'])
        grip = _recipe(grip_path, weapon_root)
        if recipe['grip_fingerprint'] != _fingerprint(grip, project) or not grip.get('validation', {}).get('passed'):
            raise RuntimeError('ACTION_GRIP_BASELINE_STALE')
        source = _asset(request['source'], unreal.AnimSequence)
        count = source.data_model_interface.get_number_of_keys()
        if any(len(keys) != count for keys in request['tracks'].values()):
            raise RuntimeError('ACTION_FRAME_COUNT_MISMATCH')
        controls = json.loads(authoring.inspect_control_rig_controls(recipe['rig']))['controls']
        control_names = {control['name'].casefold(): control['name'] for control in controls}
        keys = []
        for key in request['keys']:
            name = control_names.get(key['control'].casefold())
            if name is None:
                raise RuntimeError('ACTION_CONTROL_MISSING: ' + key['control'])
            if type(key['frame']) != int or key['frame'] < 0 or key['frame'] >= count:
                raise RuntimeError('ACTION_CONTROL_FRAME_INVALID')
            keys.append({**key, 'control': name})
        response = {'asset': request['asset'], 'sequence': request['sequence'], 'frames': count,
                    'kind': request['kind'], 'dryRun': dry_run, 'assetsModified': False}
        if dry_run:
            return json.dumps(response)
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError('PIE_ACTIVE')
        outputs = [request['asset'], request['sequence']]
        existing = [value for value in outputs if unreal.EditorAssetLibrary.does_asset_exist(value)]
        destinations = [value for value in outputs if value not in existing]
        require_asset_write(existing, destinations)
        if not unreal.EditorAssetLibrary.does_asset_exist(request['asset']):
            if unreal.EditorAssetLibrary.duplicate_asset(request['source'], request['asset']) is None:
                raise RuntimeError('ACTION_DUPLICATE_FAILED')
        animation = _asset(request['asset'], unreal.AnimSequence)
        names = {str(name).casefold(): str(name) for name in animation.data_model_interface.get_bone_track_names()}
        tracks = {names[name]: keys for name, keys in request['tracks'].items()}
        response['tracks'] = json.loads(migration.replace_animation_bone_tracks(request['asset'], json.dumps(tracks)))
        if not unreal.EditorAssetLibrary.does_asset_exist(request['sequence']):
            authoring.prepare_animation_sequence(request['sequence'], request['source'], recipe['mesh'])
        response['draft'] = json.loads(authoring.configure_sequence_rig(request['sequence'], recipe['rig'], json.dumps(keys), False, recipe['mesh']))
        response['attachment'] = None
        if request.get('attachment_label'):
            response['attachment'] = json.loads(authoring.set_sequence_attachment_transform(
                request['sequence'], request['attachment_label'], json.dumps(recipe['attachment'])))
        response['assetsModified'] = True
        return json.dumps(response, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def author_weapon(weapon_root: str, recipe_path: str, action: str = 'inspect', python_executable: str = '', review_note: str = '',
                      definition_path: str = '', character_mesh_path: str = '', reference_animation_path: str = '') -> str:
        """
        /**
         * 按唯一制作源执行握姿求解 保存 数值检查和人工审核交接
         * @param weapon_root\t明确武器型号根
         * @param recipe_path\t项目相对Source/Animation制作文件.json.source
         * @param action\tinitialize inspect solve save audit review accept adopt
         * @param python_executable\t已安装NumPy的外部python.exe
         * @param review_note\t仅accept使用的人类明确审核意见
         * @param definition_path\t仅initialize使用的明确武器定义
         * @param character_mesh_path\t仅initialize使用的实际角色网格
         * @param reference_animation_path\t仅initialize使用的公共参考动画
         * @return 当前结果 唯一下一步及实际验收边界
         */
        """
        if action not in ('initialize', 'inspect', 'solve', 'save', 'audit', 'review', 'accept', 'adopt'):
            raise RuntimeError('GRIP_ACTION_INVALID')
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError('PIE_ACTIVE: 握姿制作须在PIE退出后执行')
        project = Path(unreal.Paths.project_dir()).resolve()
        path = _safe_file(project, weapon_root, recipe_path)
        if action == 'initialize':
            return json.dumps(_initialize(path, weapon_root, project, definition_path, character_mesh_path, reference_animation_path), ensure_ascii=False)
        if not path.is_file():
            return json.dumps({'status': 'needs_recipe', 'next': {'action': 'configure_recipe', 'documentation': 'Docs/BBBGripAuthoringMCP.md'}, 'recipe': str(path)})
        recipe = _recipe(path, weapon_root)
        inputs = _inputs(recipe, project)
        response = _response(recipe, inputs, project)
        if action == 'inspect':
            return json.dumps(response, ensure_ascii=False)
        if action == 'review':
            if re.search(r'(?i)(?:^|\s)-NullRHI(?:\s|$)', unreal.SystemLibrary.get_command_line()):
                response['next'] = {'type': 'visible_editor_handoff', 'asset': recipe['sequence']}
                return json.dumps(response, ensure_ascii=False)
            asset = _asset(recipe['sequence'], unreal.LevelSequence)
            if not unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(asset):
                raise RuntimeError('GRIP_REVIEW_OPEN_FAILED: 无法打开握姿制作序列')
            unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
            response['opened'] = recipe['sequence']
            if response['status'] in ('needs_human_review', 'ready_for_runtime_acceptance'):
                response['next'] = {'action': 'accept', 'requiresHumanReview': True}
            return json.dumps(response, ensure_ascii=False)
        if action == 'solve':
            if response['status'] == 'ready_for_runtime_acceptance':
                response['unchanged'] = True
                return json.dumps(response, ensure_ascii=False)
            if response['status'] == 'needs_contact_configuration':
                return json.dumps(response, ensure_ascii=False)
            solution = _run_worker(recipe, inputs, 'solve', python_executable, project)
            solution['input_digest'] = inputs['digest']
            solution['inputs'] = inputs
            recipe['solution'] = solution
            recipe.pop('validation', None)
            recipe.pop('review', None)
            _write_recipe(path, recipe, project)
            response = _response(recipe, inputs, project)
            response['geometry'] = solution['geometry']
            return json.dumps(response, ensure_ascii=False)
        if action == 'adopt':
            if recipe.get('solution', {}).get('input_digest') == inputs['digest'] and recipe.get('validation', {}).get('fingerprint') == _fingerprint(recipe, project):
                response['unchanged'] = True
                return json.dumps(response, ensure_ascii=False)
            directory = project / 'Saved' / 'temp' / ('GripAuthoring_' + uuid.uuid4().hex)
            directory.mkdir(parents=True)
            try:
                sample = _sample(recipe, 'Adopt', recipe['animation'], 0, directory)
            finally:
                for child in directory.iterdir():
                    child.unlink()
                directory.rmdir()
            definition, calibration = _definition(recipe)
            recipe['calibration'].update(calibration)
            recipe['pose']['local_rotations'] = {bone['name']: bone['local'][3:7] for bone in sample['bones'] if bone['name'] in _FINGERS}
            inputs = _inputs(recipe, project)
            recipe['solution'] = {'input_digest': inputs['digest'], 'calibration': calibration,
                                  'inputs': inputs,
                                  'local_pose': {bone['name']: bone['local'] for bone in sample['bones']},
                                  'component_pose': {bone['name']: bone['component'] for bone in sample['bones']},
                                  'finger_rotations': {bone['name']: bone['local'][3:7] for bone in sample['bones'] if bone['name'] in _FINGERS},
                                  'passed': True, 'origin': 'explicit_existing_asset_adoption', 'runtimeAcceptance': 'pending'}
            audit = _run_worker(recipe, inputs, 'audit', python_executable, project)
            recipe['solution']['passed'] = audit['passed']
            recipe['solution']['geometry'] = audit['geometry']
            recipe['validation'] = {**audit, 'fingerprint': _fingerprint(recipe, project)}
            recipe.pop('review', None)
            _write_recipe(path, recipe, project)
            response = _response(recipe, inputs, project)
            response['validation'] = audit
            return json.dumps(response, ensure_ascii=False)
        if not recipe.get('solution') or recipe['solution'].get('input_digest') != inputs['digest']:
            response['assetsModified'] = False
            return json.dumps(response, ensure_ascii=False)
        if action == 'save':
            if not recipe['solution']['passed']:
                response['assetsModified'] = False
                response['gate'] = 'geometry_not_passed'
                return json.dumps(response, ensure_ascii=False)
            if response['status'] in ('ready_for_runtime_acceptance', 'needs_human_review'):
                response['unchanged'] = True
                return json.dumps(response, ensure_ascii=False)
            response['saved'] = _save_assets(recipe)
            audit = _run_worker(recipe, inputs, 'audit', python_executable, project, require_definition_match=False)
            if audit['passed']:
                response['definitionSaved'] = _apply_definition(recipe)
                audit = _run_worker(recipe, inputs, 'audit', python_executable, project)
            recipe['validation'] = {**audit, 'fingerprint': _fingerprint(recipe, project)}
            recipe.pop('review', None)
            _write_recipe(path, recipe, project)
            response.update(_response(recipe, inputs, project))
            response['validation'] = audit
            return json.dumps(response, ensure_ascii=False)
        if action == 'audit':
            audit = _run_worker(recipe, inputs, 'audit', python_executable, project)
            response.update(_response(recipe, inputs, project, audit))
            response['validation'] = audit
            response['assetsModified'] = False
            return json.dumps(response, ensure_ascii=False)
        if action == 'accept':
            fingerprint = _fingerprint(recipe, project)
            validation = recipe.get('validation', {})
            if not review_note.strip() or not fingerprint or validation.get('fingerprint') != fingerprint or not validation.get('passed'):
                raise RuntimeError('HUMAN_REVIEW_REQUIRES_CURRENT_VALIDATION: 需要当前数值通过及人类明确复核意见')
            recipe['review'] = {'decision': 'accepted', 'note': review_note.strip(), 'fingerprint': fingerprint}
            _write_recipe(path, recipe, project)
            return json.dumps(_response(recipe, inputs, project), ensure_ascii=False)
        raise RuntimeError('GRIP_ACTION_UNHANDLED')


_registration = Registration([BBBGripAuthoringToolset])
