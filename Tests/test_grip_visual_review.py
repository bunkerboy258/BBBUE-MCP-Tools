import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBGripVisualReview import action_context, attachment_geometry, check_native, hand_triangles, hidden_weapon_triangle_ids, output_directory, read_action_recipe, render, select_regions, weapon_matrix


IDENTITY = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]


def native_sample():
    """/** @return 只有右手真实来源字段的最小采样夹具 */"""
    return {
        'mesh': '/Game/Test/Character.Character',
        'animation': '/Game/Test/Grip',
        'readOnly': True,
        'localRotationOverrides': {},
        'space': 'mesh_component_centimeters',
        'lod': 0,
        'bones': [{'name': 'hand_r', 'component': IDENTITY}],
        'vertices': [
            {'id': 0, 'position': [0, 0, 0], 'weights': [[0, 1]]},
            {'id': 1, 'position': [1, 0, 0], 'weights': [[0, 1]]},
            {'id': 2, 'position': [0, 1, 0], 'weights': [[0, 1]]},
        ],
        'triangles': [{'id': 8, 'vertices': [0, 1, 2]}],
    }


class GripVisualReviewTests(unittest.TestCase):
    def test_native_source_rejects_candidate_overrides(self):
        """/** @return 候选旋转不能冒充正式动画回读 */"""
        sample = native_sample()
        sample['localRotationOverrides'] = {'thumb_01_r': [0, 0, 0, 1]}
        with self.assertRaisesRegex(ValueError, '拒绝候选覆盖'):
            check_native(sample, '/Game/Test/Character', '/Game/Test/Grip')

    def test_native_source_rejects_different_animation(self):
        """/** @return 另一条动画不能复用正式握姿来源 */"""
        with self.assertRaisesRegex(ValueError, '成品动画不一致'):
            check_native(native_sample(), '/Game/Test/Character', '/Game/Test/OtherGrip')

    def test_regions_require_exact_weapon_sample_and_mesh(self):
        """/** @return 不允许跨武器或跨网格采样复用面片编号 */"""
        regions = {'format': 'BBBGripVisualRegions', 'schema': 1, 'weapon_mesh': '/Game/Test/Character',
                   'weapon_sample_sha256': 'current', 'regions': {'right_grip': [8]}}
        self.assertEqual(select_regions(regions, native_sample(), 'current', 'right', []), {8})
        with self.assertRaisesRegex(ValueError, '字节摘要不一致'):
            select_regions(regions, native_sample(), 'new', 'right', [])
        regions['weapon_mesh'] = '/Game/Test/OtherWeapon'
        with self.assertRaisesRegex(ValueError, '另一把武器'):
            select_regions(regions, native_sample(), 'current', 'right', [])

    def test_missing_reference_or_hand_is_an_error(self):
        """/** @return 缺扳机区域或左手采样不能生成冒名视图 */"""
        regions = {'format': 'BBBGripVisualRegions', 'schema': 1, 'weapon_mesh': '/Game/Test/Character',
                   'weapon_sample_sha256': 'current', 'regions': {'right_grip': [8]}}
        with self.assertRaisesRegex(ValueError, 'trigger'):
            select_regions(regions, native_sample(), 'current', 'right', ['trigger'])
        with self.assertRaisesRegex(ValueError, 'left 手实际采样覆盖不足'):
            hand_triangles(native_sample(), 'left', True)

    def test_output_cannot_escape_task_temp(self):
        """/** @return 正式目录及临时根均不能写入图片 */"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Test.uproject').write_text('{}', encoding='utf-8')
            for forbidden in [root / 'Content', root / 'Saved/temp', root / 'Saved/temp/../Other']:
                with self.assertRaisesRegex(ValueError, '明确任务子目录'):
                    output_directory(root, forbidden)
            self.assertEqual(output_directory(root, root / 'Saved/temp/GripReview'), (root / 'Saved/temp/GripReview').resolve())

    def test_unsaved_calibration_and_stale_pose_are_rejected(self):
        """/** @return 采样与正式解不一致时不渲染候选成品 */"""
        recipe = {'calibration': {'spawn_offset': list(IDENTITY)}, 'solution': {
            'inputs': {'context': {'attachment_socket': {'parent': 'hand_r', 'local': list(IDENTITY)}}},
            'component_pose': {'hand_r': list(IDENTITY)}, 'calibration': {'spawn_offset': list(IDENTITY)}}}
        np.testing.assert_allclose(weapon_matrix(native_sample(), recipe), np.eye(4))
        changed = copy.deepcopy(recipe)
        changed['calibration']['spawn_offset'][0] = 1
        with self.assertRaisesRegex(ValueError, '未保存候选'):
            weapon_matrix(native_sample(), changed)
        sample = native_sample()
        sample['bones'][0]['component'] = list(IDENTITY)
        sample['bones'][0]['component'][0] = 1
        with self.assertRaisesRegex(ValueError, '姿势与正式制作源不一致'):
            weapon_matrix(sample, recipe)

    def test_reverse_depth_reveals_the_opposite_surface_without_changing_axes(self):
        """/** @return 相同投影坐标的前后表面随观察深度反转切换 */"""
        front = np.asarray([[-1, -1, 1], [1, -1, 1], [0, 1, 1]], dtype=float)
        back = front.copy()
        back[:, 2] = 0
        triangles = [(back, (240, 100, 120)), (front, (100, 185, 255))]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'views.png'
            render(triangles, [], path, 'right')
            with Image.open(path) as normal:
                self.assertEqual(normal.getpixel((1250, 330)), (100, 185, 255))
            render(triangles, [], path, 'right', reverse_depth=True)
            with Image.open(path) as reverse:
                self.assertEqual(reverse.getpixel((1250, 330)), (240, 100, 120))


class ActionVisualReviewTests(unittest.TestCase):
    def setUp(self):
        """/** @return 同型号正式动作及握姿源夹具 */"""
        self.root = '/Game/Test/Rifle'
        self.recipe = {
            'weapon_root': self.root,
            'character_mesh': '/Game/Test/Character',
            'weapon_mesh': self.root + '/Mesh/Weapon',
            'calibration': {'spawn_offset': list(IDENTITY)},
            'validation': {'fingerprint': 'accepted-grip'},
            'solution': {
                'inputs': {'context': {'attachment_socket': {'parent': 'hand_r', 'local': list(IDENTITY)}}},
                'component_pose': {'hand_r': list(IDENTITY)},
                'calibration': {'spawn_offset': list(IDENTITY)},
            },
        }
        self.action_recipe = {'schema': 1, 'weapon': self.root, 'grip_fingerprint': 'accepted-grip',
                              'actions': [{'kind': 'reload', 'asset': self.root + '/Animation/Reload'}]}
        self.character = native_sample()
        self.character['animation'] = self.root + '/Animation/Reload'
        self.character['timeSeconds'] = 0.5
        self.character['bones'][0]['component'] = list(IDENTITY)
        self.character['bones'][0]['component'][0] = 7
        self.weapon = native_sample()
        self.weapon['mesh'] = self.recipe['weapon_mesh']
        self.weapon['animation'] = ''
        self.weapon['timeSeconds'] = 0

    def context(self, index=0):
        """/** @param index 动作序号 @return 实际动作来源与挂接结果 */"""
        return action_context(self.character, self.weapon, self.recipe, self.action_recipe, index)

    def test_actual_action_pose_is_allowed_without_static_pose_equality(self):
        """/** @return 动作骨架采用实际采样姿势且明确不模拟运行时握姿层 */"""
        character, weapon, matrix, scope = self.context()
        self.assertEqual(matrix[0, 3], 7)
        self.assertEqual(scope['mode'], 'actual_action_as_original_finger_pose')
        self.assertFalse(scope['runtime_grip_curve_blending_simulated'])
        self.assertFalse(scope['runtime_animation_graph_simulated'])
        self.assertIn('实际动作AS原始手指姿势', scope['description'])
        with self.assertRaisesRegex(ValueError, '姿势与正式制作源不一致'):
            weapon_matrix(self.character, self.recipe)

    def test_wrong_character_action_and_candidate_override_are_rejected(self):
        """/** @return 静态握姿或另一动作不能冒充明确动作序号 */"""
        self.character['animation'] = '/Game/Test/Grip'
        with self.assertRaisesRegex(ValueError, '成品动画不一致'):
            self.context()
        self.character['animation'] = self.root + '/Animation/Reload'
        self.character['localRotationOverrides'] = {'hand_l': [0, 0, 0, 1]}
        with self.assertRaisesRegex(ValueError, '拒绝候选覆盖'):
            self.context()

    def test_other_weapon_or_stale_grip_fingerprint_is_rejected(self):
        """/** @return 动作源不能跨型号或使用旧握持基准 */"""
        self.action_recipe['weapon'] = '/Game/Test/OtherRifle'
        with self.assertRaisesRegex(ValueError, '同一型号'):
            self.context()
        self.action_recipe['weapon'] = self.root
        self.action_recipe['grip_fingerprint'] = 'old-grip'
        with self.assertRaisesRegex(ValueError, '当前正式握姿指纹'):
            self.context()

    def test_invalid_index_and_outside_asset_are_rejected(self):
        """/** @return 明确序号不能负向索引或越界且成品必须属于本型号 */"""
        for index in [-1, 1, None, True]:
            with self.assertRaisesRegex(ValueError, '动作序号'):
                self.context(index)
        self.action_recipe['actions'][0]['asset'] = '/Game/Test/OtherRifle/Reload'
        with self.assertRaisesRegex(ValueError, '本型号目录'):
            self.context()

    def test_weapon_animation_requires_explicit_exact_action_binding(self):
        """/** @return 武器动画只接受动作源明确指定资产 */"""
        self.weapon['animation'] = self.root + '/Animation/WeaponReload'
        with self.assertRaisesRegex(ValueError, '未指定 weapon_animation'):
            self.context()
        self.action_recipe['actions'][0]['weapon_animation'] = self.weapon['animation']
        self.weapon['timeSeconds'] = self.character['timeSeconds']
        result = self.context()
        self.assertEqual(result[3]['weapon_pose_mode'], 'specified_native_animation')
        self.weapon['animation'] = self.root + '/Animation/OtherWeaponReload'
        with self.assertRaisesRegex(ValueError, '成品动画不一致'):
            self.context()

    def test_dynamic_weapon_frame_must_match_character_time(self):
        """/** @return 同一动画的错误帧不能混入真实动作关键帧图 */"""
        self.action_recipe['actions'][0]['weapon_animation'] = self.root + '/Animation/WeaponReload'
        self.weapon['animation'] = self.root + '/Animation/WeaponReload'
        with self.assertRaisesRegex(ValueError, '采样时间不一致'):
            self.context()
        self.weapon['timeSeconds'] = self.character['timeSeconds']
        scope = self.context()[3]
        self.assertFalse(scope['runtime_visibility_notifies_simulated'])
        self.assertFalse(scope['independent_hand_attachments_included'])

    def test_action_recipe_must_be_formal_source_path(self):
        """/** @return 临时候选动作源和缺序号参数不能成为正式动作输入 */"""
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaisesRegex(ValueError, '正式 Source/Animation'):
                read_action_recipe(project, project / 'Saved/temp/Action.json.source', 0)
            path = project / 'Content/Weapon/Source/Animation/Action.json.source'
            path.parent.mkdir(parents=True)
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '同时明确 action-index'):
                read_action_recipe(project, path, None)
            data, source = read_action_recipe(project, path, 0)
            self.assertEqual(data, {})
            self.assertEqual(source['path'], str(path.resolve()))


class AttachmentVisualReviewTests(unittest.TestCase):
    def setUp(self):
        """/** @return 不含假骨架的原生静态附件样本和真实挂接声明夹具 */"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'Magazine.json'
        self.sample = {
            'mesh': '/Game/Test/Rifle/Magazine', 'meshType': 'StaticMesh', 'source': 'RenderDataLOD0',
            'readOnly': True, 'localRotationOverrides': {}, 'space': 'mesh_component_centimeters', 'lod': 0,
            'vertices': [{'id': 0, 'position': [0, 0, 0]}, {'id': 1, 'position': [1, 0, 0]}, {'id': 2, 'position': [0, 1, 0]}],
            'triangles': [{'id': 0, 'vertices': [0, 1, 2]}],
        }
        self.character = {'timeSeconds': .5, 'bones': [{'name': 'hand_l', 'component': [7, 0, 0] + IDENTITY[3:]}]}
        self.entry = {'mesh': self.sample['mesh'], 'bone': 'hand_l', 'local': [2, 3, 4] + IDENTITY[3:],
                      'start': .2, 'end': .8, 'sample_sha256': '', 'source_note': '正式换弹蒙太奇 Notify 实例的原生读取'}
        self.action = {'attachments': [self.entry]}
        self.write_sample()

    def write_sample(self):
        """/** @return 当前原生静态样本与声明摘要同步 */"""
        self.path.write_text(json.dumps(self.sample), encoding='utf-8')
        self.entry['sample_sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_native_static_attachment_uses_real_bone_and_local_transform(self):
        """/** @return 没有骨架的静态网格通过真实手骨变换独立挂接 */"""
        faces, report = attachment_geometry(self.character, self.action, [self.path])
        np.testing.assert_allclose(faces[0][0, 0], [9, 3, 4])
        self.assertTrue(report[0]['active'])
        self.assertEqual(report[0]['triangle_count'], 1)
        self.assertNotIn('bones', self.sample)
        self.assertEqual(report[0]['source']['sha256'], self.entry['sample_sha256'])

    def test_time_window_is_start_inclusive_and_end_exclusive(self):
        """/** @return 只有实际活动窗口需要附件样本并绘制 */"""
        self.character['timeSeconds'] = .2
        with self.assertRaisesRegex(ValueError, '缺少明确原生附件采样'):
            attachment_geometry(self.character, self.action, [])
        self.character['timeSeconds'] = .8
        faces, report = attachment_geometry(self.character, self.action, [])
        self.assertEqual(faces, [])
        self.assertFalse(report[0]['active'])

    def test_wrong_asset_stale_digest_and_candidate_overrides_are_rejected(self):
        """/** @return 错资产过期摘要与候选静态顶点输入不能冒充正式附件 */"""
        self.entry['sample_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA256 不匹配'):
            attachment_geometry(self.character, self.action, [self.path])
        self.write_sample()
        self.sample['localRotationOverrides'] = {'candidate': [0, 0, 0, 1]}
        self.write_sample()
        with self.assertRaisesRegex(ValueError, '无候选覆盖'):
            attachment_geometry(self.character, self.action, [self.path])
        self.sample['localRotationOverrides'] = {}
        self.sample['mesh'] = '/Game/Test/OtherRifle/Magazine'
        self.write_sample()
        with self.assertRaisesRegex(ValueError, '未声明'):
            attachment_geometry(self.character, self.action, [self.path])

    def test_static_native_source_and_declared_bone_are_required(self):
        """/** @return 非原生静态采样或未知挂接骨必须失败 */"""
        self.sample['source'] = 'candidate_positions'
        self.write_sample()
        with self.assertRaisesRegex(ValueError, 'RenderDataLOD0'):
            attachment_geometry(self.character, self.action, [self.path])
        self.sample['source'] = 'RenderDataLOD0'
        self.write_sample()
        self.entry['bone'] = 'fake_hand'
        with self.assertRaisesRegex(ValueError, '不在实际角色采样'):
            attachment_geometry(self.character, self.action, [self.path])

    def test_hidden_weapon_region_does_not_remove_independent_attachment(self):
        """/** @return 明确显示通知窗口只排除武器区域不删除独立新匣 */"""
        self.action['hidden_weapon_regions'] = [{'region': 'magazine', 'start': .2, 'end': .8,
                                                  'source_note': '正式蒙太奇显示通知实例原生字段'}]
        regions = {'regions': {'magazine': [8]}}
        hidden, report = hidden_weapon_triangle_ids(self.action, regions, native_sample(), .5)
        self.assertEqual(hidden, {8})
        self.assertTrue(report[0]['active'])
        self.assertEqual(len(attachment_geometry(self.character, self.action, [self.path])[0]), 1)
        self.assertEqual(hidden_weapon_triangle_ids(self.action, regions, native_sample(), .8)[0], set())
        with self.assertRaisesRegex(ValueError, '有效的明确区域'):
            hidden_weapon_triangle_ids(self.action, {'regions': {}}, native_sample(), .5)


if __name__ == '__main__':
    unittest.main()
