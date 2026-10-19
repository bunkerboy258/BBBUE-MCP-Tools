"""正式握姿原生采样的彩色三视图；只绘制实际保存结果，不拟合或覆盖姿势。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

from BBBGripPoseFitting import transform_matrix


COLORS = {
    'index': (100, 185, 255),
    'middle': (235, 200, 40),
    'ring': (240, 100, 120),
    'pinky': (170, 115, 240),
    'thumb': (80, 210, 140),
}
CHECKLIST = [
    '先核对枪口、枪身上方和右腕的相对方向，再判断握持结构',
    '掌内侧贴合实际握持部位，虎口卡住上缘；允许合理轻微重合',
    '下三指相似卷曲并排靠拢，指节弯曲平面连续，指端实际包住握持部位',
    'YZ视图中中指、无名指、小指的末端顺势排列，没有单指异常前突',
    '拇指在正确侧顺贴，沿原始姿态自然包握，没有上下大幅起伏',
    '食指沿枪身向前，位于扳机及护圈外侧；结合机匣参考检查穿入',
    '左掌、拇指和四指自然包住实际护木或把手，腕部无异常扭转',
    '三个投影逐一看图，说明是否符合真实握持、是否自然；图片生成不等于通过',
]


def read_json(path):
    """/** @param path 明确输入路径 @return 带原始字节摘要的对象 */"""
    path = Path(path).resolve()
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8-sig')), {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def asset_package(value):
    """/** @param value 原生资产路径 @return 用于比较的包路径 */"""
    if not isinstance(value, str) or not value.startswith('/Game/'):
        raise ValueError('输入缺少明确的 /Game/ 资产来源')
    return value.split('.', 1)[0]


def saved_curve_alpha(action_recipe, animation, name, time):
    """/** @param action_recipe 正式动作源 @param animation 明确动作 @param name 抑制曲线 @param time 秒数 @return 原生曲线证据对应的实际指层权重 */"""
    matches = [item for item in action_recipe.get('curves', []) if asset_package(item['asset']) == asset_package(animation)]
    if len(matches) != 1 or name not in matches[0].get('curves', {}):
        raise ValueError('真实动画层视觉需要已保存曲线的独立原生回读: ' + name)
    curve = matches[0]['curves'][name]
    if curve.get('exists') is False:
        return 1.
    keys = curve.get('keys')
    if not curve.get('exists') or not keys:
        raise ValueError('已存在的抑制曲线缺少完整原生关键帧')
    if any(second['time'] <= first['time'] for first, second in zip(keys, keys[1:])):
        raise ValueError('抑制曲线时间必须严格递增')
    value = keys[0]['value']
    if time >= keys[-1]['time']:
        value = keys[-1]['value']
    for first, second in zip(keys, keys[1:]):
        if not first['time'] <= time < second['time']:
            continue
        weight = (time - first['time']) / (second['time'] - first['time'])
        mode = first['interp_mode']
        if mode == 'RCIM_Cubic':
            if abs(first['leave_tangent']) > 1e-12 or abs(second['arrive_tangent']) > 1e-12:
                raise ValueError('动画层视觉目前只支持明确水平切线的三次曲线')
            weight = weight * weight * (3 - 2 * weight)
        if mode not in ('RCIM_Cubic', 'RCIM_Linear'):
            raise ValueError('动画层视觉不猜测未知曲线插值')
        value = first['value'] * (1 - weight) + second['value'] * weight
    if not np.isfinite(value):
        raise ValueError('原生抑制曲线值必须有限')
    return float(np.clip(1 - value, 0, 1))


def handling_surface(report, recipe, action_recipe, action_index):
    """/** @param report 真实原生节点求值报告 @param recipe 正式校准 @param action_recipe 正式动作源 @param action_index 动作序号 @return 仅整理原生字段的表面 不覆盖姿态 */"""
    if report.get('status') != 'ok' or report.get('readOnly') is not True or report.get('projectDirtyPackagesUnchanged') is not True:
        raise ValueError('需要未修改项目的正式原生动画节点报告')
    if report.get('evaluationRoute') != 'TransientAnimBlueprint->FormalHandPose->NativeModifyBoneFromFormalConfiguration':
        raise ValueError('不接受未知的动画层求值路径')
    if any(report.get(field) is not False for field in ('mainGameplayEvaluated', 'fullBodyLayerEvaluated', 'aimIKEnabled', 'leftHandIKEnabled')):
        raise ValueError('动画层报告必须明确限定实际求值范围')
    configuration = report.get('nativeNodeConfiguration', {})
    expected = {'bone': 'hand_r', 'rotationMode': 'AddToExisting', 'rotationSpace': 'ParentBoneSpace',
                'translationMode': 'Ignore', 'scaleMode': 'Ignore', 'alphaInputType': 'Bool',
                'blendInTime': 0, 'blendOutTime': 0, 'rotationGetter': 'GetRightHandGripRotationOffset',
                'gateGetter': 'HasRightHandGripRotationOffset'}
    if any(configuration.get(key) != value for key, value in expected.items()):
        raise ValueError('原生节点配置与正式右腕职责不同')
    snapshot = report['inputSnapshot']
    action = action_recipe['actions'][action_index]
    if asset_package(snapshot['animation']) != asset_package(action['asset']) or asset_package(snapshot['grip']) != asset_package(recipe['animation']):
        raise ValueError('原生动画层求值未使用本型号正式动作和握姿')
    if asset_package(snapshot['mesh']) != asset_package(recipe['character_mesh']) or snapshot.get('equipmentEnabled') is not True:
        raise ValueError('原生动画层求值的网格或装备事实不匹配')
    if asset_package(report['nativeNodeConfigurationSource']) != asset_package(snapshot['base']):
        raise ValueError('原生节点不是从指定正式基础层读取')
    time = snapshot['timeSeconds']
    if not np.isfinite(time) or time < 0 or abs(time - report['timeSeconds']) > 1e-7:
        raise ValueError('原生动画层求值时间不一致')
    delta = np.asarray(recipe['calibration']['right_wrist_delta'], dtype=float)
    actual = np.asarray(snapshot['rightHandOffsetQuaternion'], dtype=float)
    if delta.shape != (4,) or actual.shape != (4,) or not np.all(np.isfinite(delta)) or not np.all(np.isfinite(actual)) or abs(np.linalg.norm(actual) - 1) > .0001 or abs(np.linalg.norm(delta) - 1) > .0001:
        raise ValueError('原生右腕快照必须是单位四元数')
    delta = delta / np.linalg.norm(delta)
    actual = actual / np.linalg.norm(actual)
    if abs(float(delta @ actual)) < np.cos(np.radians(.02) / 2):
        raise ValueError('原生右腕快照与正式DA校准不同')
    for side, curve in [('left', 'DisableLeftHandPoseOverride'), ('right', 'DisableRightHandPoseOverride')]:
        alpha = saved_curve_alpha(action_recipe, action['asset'], curve, time)
        if not np.isfinite(snapshot[side + 'GripAlpha']) or abs(snapshot[side + 'GripAlpha'] - alpha) > .0001:
            raise ValueError('原生指层快照与正式抑制曲线不一致: ' + side)
    local = {name.casefold(): values for name, values in report['localBones'].items()}
    source = transform_matrix(report['sourceRightHandLocal'])
    expected_rotation = transform_matrix([0, 0, 0] + delta.tolist() + [1, 1, 1])[:3, :3] @ source[:3, :3]
    if np.max(np.abs(transform_matrix(local['hand_r'])[:3, :3] - expected_rotation)) > .001 or report['parentSpacePreMultiplyErrorDegrees'] > .02:
        raise ValueError('真实原生右腕不符合父骨空间增量')
    if np.linalg.norm(np.asarray(local['hand_r'][:3]) - source[:3, 3]) > .001:
        raise ValueError('原生右腕节点意外改变了腕部局部位置')
    surface = dict(report['surface'])
    surface['bones'] = [{**bone, 'local': local[bone['name'].casefold()]} for bone in surface['bones']]
    surface.update({'readOnly': True, 'localRotationOverrides': {}, 'animation': snapshot['animation'], 'timeSeconds': time})
    return surface


def check_native(sample, expected_mesh, expected_animation=None):
    """/** @param sample 原生采样 @param expected_mesh 正式网格 @param expected_animation 正式动画 @return 校验后的原生来源信息 */"""
    if sample.get('readOnly') is not True or sample.get('localRotationOverrides') != {}:
        raise ValueError('只接受 readOnly=true 且 localRotationOverrides={} 的原生采样，拒绝候选覆盖')
    if sample.get('space') != 'mesh_component_centimeters' or sample.get('lod') != 0:
        raise ValueError('需要原生 LOD0 网格组件空间厘米采样')
    if asset_package(sample.get('mesh')) != asset_package(expected_mesh):
        raise ValueError('采样网格与正式 recipe 不一致')
    if expected_animation is not None:
        if asset_package(sample.get('animation')) != asset_package(expected_animation):
            raise ValueError('手部采样动画与正式成品动画不一致')
    if not sample.get('vertices') or not sample.get('triangles') or not sample.get('bones'):
        raise ValueError('原生采样缺少网格或骨架')
    return {
        'mesh': sample['mesh'],
        'animation': sample.get('animation', ''),
        'time_seconds': sample.get('timeSeconds'),
        'lod': sample['lod'],
        'deformation': sample.get('deformation', 'unknown'),
        'morph_target_count': sample.get('morphTargetCount'),
        'cloth_section_count': sample.get('clothSectionCount'),
        'morph_supported': False,
        'cloth_supported': False,
        'mesh_deformer_supported': False,
        'limitation': '仅原生线性蒙皮几何，不包含 Morph、布料、网格变形器或实际材质外观',
    }


def output_directory(project_root, output_dir):
    """/** @param project_root 明确项目根 @param output_dir 明确任务临时目录 @return 通过边界检查的输出目录 */"""
    project = Path(project_root).resolve()
    destination = Path(output_dir).resolve()
    temporary_root = (project / 'Saved' / 'temp').resolve()
    if not list(project.glob('*.uproject')):
        raise ValueError('项目根必须存在 .uproject')
    if not destination.is_relative_to(temporary_root) or destination == temporary_root:
        raise ValueError('输出必须位于项目 Saved/temp 下的明确任务子目录')
    return destination


def select_regions(regions, sample, weapon_digest, side, references):
    """/** @param regions 本武器明确面片清单 @param sample 实际武器采样 @param weapon_digest 采样摘要 @param side 手侧 @param references 附加参考区域 @return 去重后的实际面片编号 */"""
    if regions.get('format') != 'BBBGripVisualRegions' or regions.get('schema') != 1:
        raise ValueError('区域清单格式必须是 BBBGripVisualRegions schema=1')
    if asset_package(regions.get('weapon_mesh')) != asset_package(sample['mesh']):
        raise ValueError('区域清单属于另一把武器')
    if regions.get('weapon_sample_sha256') != weapon_digest:
        raise ValueError('区域清单与本次武器采样字节摘要不一致，必须重新确认面片')
    known = {triangle['id'] for triangle in sample['triangles']}
    selected = set()
    for name in [side + '_grip'] + list(references):
        identifiers = regions.get('regions', {}).get(name)
        if not isinstance(identifiers, list) or not identifiers:
            raise ValueError('缺少本武器的明确非空区域: ' + name)
        if any(type(identifier) is not int for identifier in identifiers):
            raise ValueError('面片编号必须为整数: ' + name)
        if len(set(identifiers)) != len(identifiers) or not set(identifiers) <= known:
            raise ValueError('区域包含重复或不存在的面片: ' + name)
        selected.update(identifiers)
    return selected


def hand_triangles(sample, side, show_palm):
    """/** @param sample 正式原生网格 @param side 手侧 @param show_palm 是否显示掌部 @return 原生位置的彩色三角面及覆盖统计 */"""
    suffix = '_r' if side == 'right' else '_l'
    vertices = {vertex['id']: vertex for vertex in sample['vertices']}
    if len(vertices) != len(sample['vertices']):
        raise ValueError('原生采样包含重复顶点编号')
    triangles = []
    counts = {finger: 0 for finger in COLORS}
    counts['palm'] = 0
    for triangle in sample['triangles']:
        rows = [vertices[identifier] for identifier in triangle['vertices']]
        names = [sample['bones'][max(row['weights'], key=lambda weight: weight[1])[0]]['name'] for row in rows]
        allowed = [name.endswith(suffix) and (name.split('_')[0] in COLORS or show_palm and name == 'hand' + suffix) for name in names]
        if not all(allowed):
            continue
        kind = names[0].split('_')[0]
        if kind == 'hand':
            kind = 'palm'
        points = np.asarray([row['position'] for row in rows], dtype=float)
        if points.shape != (3, 3) or not np.all(np.isfinite(points)):
            raise ValueError('手部原生位置必须为有限三维坐标')
        triangles.append((points, COLORS.get(kind, (90, 130, 145))))
        counts[kind] += 1
    missing = [finger for finger, count in counts.items() if count == 0 and (finger != 'palm' or show_palm)]
    if missing:
        raise ValueError(side + ' 手实际采样覆盖不足，缺少: ' + ', '.join(missing))
    return triangles, counts


def weapon_matrix(character, recipe):
    """/** @param character 实际原生骨架 @param recipe 正式制作源及上下文 @return 实际挂接顺序的武器矩阵 */"""
    bones = {bone['name']: bone for bone in character['bones']}
    attachment = recipe['solution']['inputs']['context']['attachment_socket']
    if attachment['parent'] != 'hand_r' or 'hand_r' not in bones:
        raise ValueError('需要正式右手挂接上下文与实际 hand_r')
    for bone in character['bones']:
        expected = recipe['solution']['component_pose'].get(bone['name'])
        if expected is None:
            raise ValueError('正式制作源缺少采样骨骼: ' + bone['name'])
        if np.max(np.abs(transform_matrix(bone['component']) - transform_matrix(expected))) > 0.002:
            raise ValueError('原生采样姿势与正式制作源不一致: ' + bone['name'])
    calibration = recipe['calibration']['spawn_offset']
    if not np.allclose(calibration, recipe['solution']['calibration']['spawn_offset'], atol=1e-8, rtol=0):
        raise ValueError('挂接校准尚未写入正式解，拒绝绘制未保存候选')
    return transform_matrix(bones['hand_r']['component']) @ transform_matrix(attachment['local']) @ transform_matrix(calibration)


def action_context(character, weapon, recipe, action_recipe, action_index):
    """/** @param character 实际动作角色采样 @param weapon 实际武器采样 @param recipe 同型号正式握姿源 @param action_recipe 正式动作制作源 @param action_index 明确动作序号 @return 原生来源、动作挂接矩阵和原始姿势范围说明 */"""
    if action_recipe.get('schema') != 1:
        raise ValueError('动作制作源需要 schema=1')
    root = asset_package(recipe['weapon_root'])
    if asset_package(action_recipe.get('weapon')) != root:
        raise ValueError('动作制作源与握姿制作源不属于同一型号')
    fingerprint = recipe.get('validation', {}).get('fingerprint')
    if not fingerprint or action_recipe.get('grip_fingerprint') != fingerprint:
        raise ValueError('动作制作源未绑定当前正式握姿指纹')
    actions = action_recipe.get('actions')
    if not isinstance(actions, list) or type(action_index) is not int or action_index < 0 or action_index >= len(actions):
        raise ValueError('动作序号必须指向 actions 中实际存在的一项')
    action = actions[action_index]
    animation = asset_package(action.get('asset'))
    if not animation.startswith(root + '/'):
        raise ValueError('动作成品资产不在本型号目录中')
    character_info = check_native(character, recipe['character_mesh'], animation)
    time_seconds = character.get('timeSeconds')
    if type(time_seconds) not in (int, float) or not np.isfinite(time_seconds) or time_seconds < 0:
        raise ValueError('实际动作采样必须携带非负有限时间')
    weapon_animation = action.get('weapon_animation')
    weapon_info = check_native(weapon, recipe['weapon_mesh'], weapon_animation)
    if weapon_animation is None and weapon.get('animation'):
        raise ValueError('动作未指定 weapon_animation，需要无动画武器原生采样')
    if weapon_animation is not None and not asset_package(weapon_animation).startswith(root + '/'):
        raise ValueError('武器动画不在本型号目录中')
    if weapon_animation is not None:
        weapon_time = weapon.get('timeSeconds')
        play_rate = action.get('weapon_animation_play_rate', 1.)
        if type(play_rate) not in (int, float) or not np.isfinite(play_rate) or play_rate <= 0:
            raise ValueError('武器动画需要原生蒙太奇已核验的有限正播放倍率')
        if type(weapon_time) not in (int, float) or not np.isfinite(weapon_time) or abs(weapon_time - time_seconds * play_rate) > 0.0001:
            raise ValueError('角色和武器实际动画采样时间不一致')
    attachment = recipe['solution']['inputs']['context']['attachment_socket']
    bones = {bone['name']: bone for bone in character['bones']}
    if attachment['parent'] != 'hand_r' or 'hand_r' not in bones:
        raise ValueError('动作需要同型号正式右手挂接上下文和实际 hand_r')
    calibration = recipe['calibration']['spawn_offset']
    if not np.allclose(calibration, recipe['solution']['calibration']['spawn_offset'], atol=1e-8, rtol=0):
        raise ValueError('动作引用的挂接校准尚未写入正式握姿解')
    matrix = transform_matrix(bones['hand_r']['component']) @ transform_matrix(attachment['local']) @ transform_matrix(calibration)
    scope = {
        'mode': 'actual_action_as_original_finger_pose',
        'description': '实际动作AS原始手指姿势；没有模拟运行时握姿曲线混合，不能冒称最终runtime画面',
        'runtime_grip_curve_blending_simulated': False,
        'runtime_animation_graph_simulated': False,
        'runtime_visibility_notifies_simulated': False,
        'independent_hand_attachments_included': False,
        'action_index': action_index,
        'action_kind': action.get('kind'),
        'action_asset': animation,
        'character_time_seconds': time_seconds,
        'weapon_animation': weapon_animation,
        'weapon_time_seconds': weapon.get('timeSeconds'),
        'weapon_animation_play_rate': action.get('weapon_animation_play_rate', 1.),
        'weapon_pose_mode': 'specified_native_animation' if weapon_animation is not None else 'static_native_reference',
    }
    return character_info, weapon_info, matrix, scope


def read_action_recipe(project_root, action_recipe_path, action_index):
    """/** @param project_root 项目根 @param action_recipe_path 正式动作制作源路径 @param action_index 明确动作序号 @return 正式内容目录内的动作源与摘要 */"""
    path = Path(action_recipe_path).resolve()
    content_root = (Path(project_root).resolve() / 'Content').resolve()
    if not path.is_relative_to(content_root) or not path.name.endswith('.json.source') or path.parent.name != 'Animation' or path.parent.parent.name != 'Source':
        raise ValueError('action-recipe 必须是项目 Content 内正式 Source/Animation/*.json.source')
    if action_index is None:
        raise ValueError('action-recipe 必须同时明确 action-index')
    return read_json(path)


def time_window(entry, time_seconds):
    """/** @param entry 明确起止时间与原生来源说明 @param time_seconds 实际角色动作时间 @return 是否处于左闭右开窗口 */"""
    start = entry.get('start')
    end = entry.get('end')
    if type(start) not in (int, float) or type(end) not in (int, float):
        raise ValueError('动作附件及显隐窗口需要明确 start/end')
    if not np.isfinite(start) or not np.isfinite(end) or start < 0 or end <= start:
        raise ValueError('动作附件及显隐窗口必须非负且 end 大于 start')
    if not isinstance(entry.get('source_note'), str) or not entry['source_note'].strip():
        raise ValueError('动作附件及显隐窗口必须说明具体原生 Notify 来源')
    return start <= time_seconds < end


def attachment_geometry(character, action, sample_paths):
    """/** @param character 原生动作采样 @param action 明确附件声明的正式动作条目 @param sample_paths 原生静态附件采样路径 @return 骨骼实际挂接三角面及独立附件来源报告 */"""
    entries = action.get('attachments', [])
    if not isinstance(entries, list):
        raise ValueError('动作 attachments 必须为数组')
    declared = {}
    instance_ids = set()
    for entry in entries:
        mesh = asset_package(entry.get('mesh'))
        time_window(entry, character['timeSeconds'])
        instance_id = entry.get('instance_id')
        if 'instance_id' in entry:
            if not isinstance(instance_id, str) or not instance_id.strip() or instance_id in instance_ids:
                raise ValueError('附件 instance_id 必须为明确唯一的实际通知实例')
            instance_ids.add(instance_id)
        for previous in declared.get(mesh, []):
            if entry['start'] < previous['end'] and previous['start'] < entry['end']:
                if not instance_id or not previous.get('instance_id'):
                    raise ValueError('同一附件网格的声明时间窗口重叠时必须各有唯一 instance_id')
            if entry.get('sample_sha256') != previous.get('sample_sha256'):
                raise ValueError('同一附件网格必须使用相同原生采样 SHA256')
        declared.setdefault(mesh, []).append(entry)
    samples = {}
    for path in sample_paths:
        sample, source = read_json(path)
        mesh = asset_package(sample.get('mesh'))
        if mesh not in declared or mesh in samples:
            raise ValueError('附件采样未声明或同一网格重复提供')
        if sample.get('meshType') != 'StaticMesh' or sample.get('source') != 'RenderDataLOD0':
            raise ValueError('附件需要原生 StaticMesh RenderDataLOD0 采样')
        if sample.get('readOnly') is not True or sample.get('localRotationOverrides') != {}:
            raise ValueError('附件必须是无候选覆盖的只读原生采样')
        if sample.get('space') != 'mesh_component_centimeters' or sample.get('lod') != 0:
            raise ValueError('附件需要 LOD0 组件空间厘米采样')
        if source['sha256'] != declared[mesh][0].get('sample_sha256'):
            raise ValueError('附件原生采样与正式动作源 SHA256 不匹配')
        samples[mesh] = (sample, source)
    bones = {bone['name']: bone for bone in character['bones']}
    geometries = []
    report = []
    for entry in entries:
        mesh = asset_package(entry['mesh'])
        active = time_window(entry, character['timeSeconds'])
        bone = entry.get('bone')
        if bone not in bones:
            raise ValueError('附件声明的挂接骨不在实际角色采样中')
        local = transform_matrix(entry['local'])
        digest = entry.get('sample_sha256')
        if not isinstance(digest, str) or len(digest) != 64 or any(value not in '0123456789abcdef' for value in digest):
            raise ValueError('附件声明需要明确原生采样 SHA256')
        item = {'mesh': mesh, 'bone': bone, 'local': entry['local'], 'start': entry['start'], 'end': entry['end'],
                'instance_id': entry.get('instance_id'),
                'source_note': entry['source_note'], 'active': active, 'sample_sha256': digest, 'triangle_count': 0,
                'material_world_position_offset_simulated': False}
        if mesh in samples:
            item['source'] = samples[mesh][1]
            item['geometry_source'] = samples[mesh][0]['source']
            item['mesh_type'] = samples[mesh][0]['meshType']
        if active:
            if mesh not in samples:
                raise ValueError('实际动作时间处于附件窗口，缺少明确原生附件采样')
            sample, source = samples[mesh]
            vertices = {vertex['id']: np.asarray(vertex['position'], dtype=float) for vertex in sample.get('vertices', [])}
            if not vertices or len(vertices) != len(sample['vertices']) or any(point.shape != (3,) or not np.all(np.isfinite(point)) for point in vertices.values()):
                raise ValueError('附件缺少有效原生顶点')
            faces = np.asarray([[vertices[index] for index in triangle['vertices']] for triangle in sample.get('triangles', [])])
            if faces.ndim != 3 or faces.shape[1:] != (3, 3) or not len(faces):
                raise ValueError('附件缺少有效原生三角面')
            matrix = transform_matrix(bones[bone]['component']) @ local
            faces = faces @ matrix[:3, :3].T + matrix[:3, 3]
            item['attachment_to_character_matrix'] = matrix.tolist()
            item['triangle_count'] = len(faces)
            geometries.append(faces)
        report.append(item)
    return geometries, report


def hidden_weapon_triangle_ids(action, regions, weapon, time_seconds):
    """/** @param action 正式动作显隐声明 @param regions 本枪明确面片区域 @param weapon 实际武器采样 @param time_seconds 实际动作时间 @return 活动隐藏面片和原生窗口来源报告 */"""
    entries = action.get('hidden_weapon_regions', [])
    if not isinstance(entries, list):
        raise ValueError('hidden_weapon_regions 必须为数组')
    known = {triangle['id'] for triangle in weapon['triangles']}
    hidden = set()
    report = []
    for entry in entries:
        name = entry.get('region')
        identifiers = regions.get('regions', {}).get(name)
        if not isinstance(identifiers, list) or not identifiers or any(type(value) is not int for value in identifiers) or not set(identifiers) <= known:
            raise ValueError('武器显隐声明缺少有效的明确区域: ' + str(name))
        active = time_window(entry, time_seconds)
        if active:
            hidden.update(identifiers)
        report.append({'region': name, 'start': entry['start'], 'end': entry['end'], 'source_note': entry['source_note'],
                       'active': active, 'hidden_triangle_count': len(set(identifiers)) if active else 0})
    return hidden, report


def visible_triangle_count(faces, hand_faces):
    """/** @param faces 已挂接参考面片 @param hand_faces 实际手部面片 @return 与原绘图相同手部视域内面片数 */"""
    hand = np.concatenate([points for points, color in hand_faces])
    low = hand.min(axis=0) - 1
    high = hand.max(axis=0) + 1
    return sum(bool(np.all(face.max(axis=0) >= low) and np.all(face.min(axis=0) <= high)) for face in faces)


def render(triangles, weapon_triangles, destination, side, reverse_depth=False):
    """/** @param triangles 原生手部三角面 @param weapon_triangles 已挂接武器面 @param destination 图片目标 @param side 手侧 @param reverse_depth 是否反转观察深度 @return 三视图绘制统计 */"""
    hand = np.concatenate([points for points, color in triangles])
    low = hand.min(axis=0) - 1
    high = hand.max(axis=0) + 1
    visible = list(triangles)
    for triangle in weapon_triangles:
        if np.all(triangle.max(axis=0) >= low) and np.all(triangle.min(axis=0) <= high):
            visible.append((triangle, (100, 110, 115)))
    image = Image.new('RGB', (1500, 650), (24, 28, 33))
    draw = ImageDraw.Draw(image)
    for index, (a, b, depth) in enumerate([(0, 2, 1), (1, 2, 0), (0, 1, 2)]):
        scale = min(450 / (high[a] - low[a]), 570 / (high[b] - low[b]))
        center_x = index * 500 + 250
        center_y = 330
        center = (low + high) / 2
        for triangle, color in sorted(visible, key=lambda item: item[0][:, depth].mean(), reverse=reverse_depth):
            xy = [(center_x + (point[a] - center[a]) * scale, center_y - (point[b] - center[b]) * scale) for point in triangle]
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            normal /= max(np.linalg.norm(normal), 1e-12)
            shade = .5 + .5 * abs(normal[depth])
            draw.polygon(xy, fill=tuple(int(value * shade) for value in color))
        label = side + ' ' + ['XZ view', 'YZ view', 'XY view'][index]
        if reverse_depth:
            label += ' reverse depth'
        draw.text((index * 500 + 20, 15), label, fill='white')
    for index, (name, color) in enumerate(COLORS.items()):
        draw.text((20 + index * 200, 625), name, fill=color)
    image.save(destination)
    return {'hand_triangle_count': len(triangles), 'visible_weapon_triangle_count': len(visible) - len(triangles)}


def generate(project_root, character_path, weapon_path, recipe_path, regions_path, side, references, palm, output_dir, reverse_depth=False, action_recipe_path=None, action_index=None, attachment_sample_paths=()):
    """/** @param project_root 项目根 @param character_path 原生角色采样 @param weapon_path 原生武器采样 @param recipe_path 正式制作源 @param regions_path 独立面片清单 @param side 手侧或双手 @param references 参考区域 @param palm 显示掌部 @param output_dir 临时任务目录 @param reverse_depth 是否反转观察深度 @return 图片及待人工或代理看图复核的来源元数据 */"""
    destination = output_directory(project_root, output_dir)
    character, character_source = read_json(character_path)
    weapon, weapon_source = read_json(weapon_path)
    recipe, recipe_source = read_json(recipe_path)
    regions, regions_source = read_json(regions_path)
    if recipe.get('format') != 'BBBGripAuthoring':
        raise ValueError('需要正式 BBBGripAuthoring 制作源')
    action_source = None
    attachment_faces = []
    attachments = []
    hidden_ids = set()
    hidden_regions = []
    scope = {'mode': 'saved_static_grip', 'runtime_animation_graph_simulated': False}
    if action_recipe_path is None:
        if action_index is not None:
            raise ValueError('action-index 必须同时指定 action-recipe')
        if attachment_sample_paths:
            raise ValueError('独立附件输入必须绑定明确正式动作条目')
        character_info = check_native(character, recipe['character_mesh'], recipe['animation'])
        weapon_info = check_native(weapon, recipe['weapon_mesh'])
        if weapon.get('animation'):
            raise ValueError('握姿参考武器需要无动画原生采样')
        matrix = weapon_matrix(character, recipe)
    if action_recipe_path is not None:
        action_recipe, action_source = read_action_recipe(project_root, action_recipe_path, action_index)
        handling = character if 'surface' in character else None
        if handling is not None:
            character = handling_surface(handling, recipe, action_recipe, action_index)
        character_info, weapon_info, matrix, scope = action_context(character, weapon, recipe, action_recipe, action_index)
        if handling is not None:
            scope.update({'mode': 'native_formal_hand_pose_and_wrist',
                          'description': '真实UE正式手指层与正式右腕节点求值；未求值主玩法、Aim或左手IK',
                          'native_handling_evaluated': True, 'main_gameplay_evaluated': False,
                          'full_body_controls_evaluated': False, 'aim_and_left_ik_evaluated': False,
                          'native_node_configuration_source': handling['nativeNodeConfigurationSource'],
                          'input_snapshot': handling['inputSnapshot']})
        action = action_recipe['actions'][action_index]
        attachment_faces, attachments = attachment_geometry(character, action, attachment_sample_paths)
        hidden_ids, hidden_regions = hidden_weapon_triangle_ids(action, regions, weapon, character['timeSeconds'])
        scope['independent_hand_attachments_included'] = any(item['active'] for item in attachments)
        scope['explicit_weapon_region_visibility_applied'] = bool(hidden_ids)
    vertices = {vertex['id']: np.asarray(vertex['position'], dtype=float) for vertex in weapon['vertices']}
    if any(point.shape != (3,) or not np.all(np.isfinite(point)) for point in vertices.values()):
        raise ValueError('武器原生位置必须为有限三维坐标')
    sides = ['left', 'right'] if side == 'both' else [side]
    prepared = []
    for hand in sides:
        hand_faces, counts = hand_triangles(character, hand, palm)
        identifiers = select_regions(regions, weapon, weapon_source['sha256'], hand, references)
        identifiers -= hidden_ids
        faces = np.asarray([[vertices[identifier] for identifier in triangle['vertices']] for triangle in weapon['triangles'] if triangle['id'] in identifiers], dtype=float).reshape(-1, 3, 3)
        faces = faces @ matrix[:3, :3].T + matrix[:3, 3]
        weapon_count = visible_triangle_count(faces, hand_faces)
        attachment_count = sum(visible_triangle_count(group, hand_faces) for group in attachment_faces)
        groups = [faces] + attachment_faces
        faces = np.concatenate(groups, axis=0)
        prepared.append((hand, hand_faces, counts, faces, weapon_count, attachment_count))
    destination.mkdir(parents=True, exist_ok=True)
    report = {
        'format': 'BBBGripVisualReview',
        'schema': 1,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'pending_visual_inspection',
        'candidate_overrides_supported': False,
        'sources': {'character': character_source, 'weapon': weapon_source, 'recipe': recipe_source, 'regions': regions_source},
        'review_scope': scope,
        'character': character_info,
        'weapon': weapon_info,
        'recipe_validation_fingerprint': recipe.get('validation', {}).get('fingerprint'),
        'weapon_to_character_matrix': matrix.tolist(),
        'reference_regions': references,
        'region_selection_basis': regions.get('selection_basis', {}),
        'reference_limitations': regions.get('reference_limitations', []),
        'palm_visible': palm,
        'reverse_depth': reverse_depth,
        'render_method': '原工具 Pillow 三角面按平均深度排序；没有逐像素深度缓冲，遮挡不能单独证明无穿透',
        'checklist': CHECKLIST,
        'hands': {},
        'attachments': attachments,
        'hidden_weapon_regions': hidden_regions,
    }
    if action_source is not None:
        report['sources']['action_recipe'] = action_source
    for hand, hand_faces, counts, faces, weapon_count, attachment_count in prepared:
        suffix = '_reverse_three_views.png' if reverse_depth else '_three_views.png'
        image_path = destination / (hand + suffix)
        result = render(hand_faces, faces, image_path, hand, reverse_depth)
        result['visible_weapon_triangle_count'] = weapon_count
        result['visible_attachment_triangle_count'] = attachment_count
        result['image'] = str(image_path)
        result['coverage_by_dominant_bone'] = counts
        report['hands'][hand] = result
    report_path = destination / 'visual_review.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    """/** @return 严格参数 CLI 的进程返回码 */"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--character', required=True)
    parser.add_argument('--weapon', required=True)
    parser.add_argument('--recipe', required=True)
    parser.add_argument('--regions', required=True)
    parser.add_argument('--side', choices=['left', 'right', 'both'], required=True)
    parser.add_argument('--reference-region', action='append', default=[])
    parser.add_argument('--palm', action='store_true')
    parser.add_argument('--reverse-depth', action='store_true')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--action-recipe')
    parser.add_argument('--action-index', type=int)
    parser.add_argument('--attachment-sample', action='append', default=[])
    args = parser.parse_args()
    try:
        report = generate(args.project_root, args.character, args.weapon, args.recipe, args.regions, args.side, args.reference_region, args.palm, args.output_dir, args.reverse_depth, args.action_recipe, args.action_index, args.attachment_sample)
    except (ValueError, KeyError, IndexError, TypeError, OSError) as error:
        print('握姿视觉输入拒绝: ' + str(error), file=sys.stderr)
        return 2
    print(json.dumps({'status': report['status'], 'hands': report['hands']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
