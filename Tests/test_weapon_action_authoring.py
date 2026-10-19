from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBWeaponActionAuthoring import blend_rotation, contact_target, runtime_right_hand, smooth, synchronize_hand_helpers


def yaw(angle):
    """/** @param angle 角度 @return 绕竖轴纯旋转矩阵 */"""
    value = np.radians(angle)
    return np.array([[np.cos(value), -np.sin(value), 0], [np.sin(value), np.cos(value), 0], [0, 0, 1]])


class WeaponActionAuthoringTests(unittest.TestCase):
    def test_native_hold_audit_includes_declared_weapon_space_contact_and_rejects_wrong_target(self):
        """/** @return 满回握叠加接槽仍按显式目标验收 不把正确接槽当成静态握姿误差 错误轨道仍拒绝 */"""
        import copy
        from types import SimpleNamespace
        from unittest.mock import patch
        from BBBWeaponActionAuthoring import verify
        from BBBGripAuthoring import matrix_quaternion

        names = ['hand_l', 'hand_r', 'ik_hand_l', 'ik_hand_r', 'ik_hand_gun']
        reference = np.tile(np.eye(4), (5, 1, 1))
        reference[[1, 3, 4], :3, :3] = yaw(90)
        surface = SimpleNamespace(names={name: i for i, name in enumerate(names)}, bones=[{'name': name, 'parent': -1} for name in names], locals=reference, components=lambda local: local.copy())
        identity = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
        def native(matrix):
            return {'translation': dict(zip('xyz', matrix[:3, 3])), 'quaternion': list(matrix_quaternion(matrix[:3, :3])), 'scale': dict(zip('xyz', [1., 1., 1.]))}
        original = [{'frame': f, 'bones': {n: native(reference[i]) for i, n in enumerate(names)}} for f in range(3)]
        actual = copy.deepcopy(original)
        # A 90 degree gun rotates the explicitly declared weapon-space (4,-5,6) into (5,4,6).
        for n in ('hand_l', 'ik_hand_l'):
            actual[1]['bones'][n]['translation'] = dict(zip('xyz', [5., 4., 6.]))
        tracks = {n: [{'position': [5., 4., 6.] if f == 1 else [0., 0., 0.], 'rotation': [0., 0., 0., 1.], 'scale': [1., 1., 1.]} for f in range(3)] for n in ('hand_l', 'ik_hand_l')}
        action = {'source': 'original', 'asset': 'saved', 'kind': 'reload', 'tracks': tracks, 'metrics': [{'frame': f, 'holdWeight': 1.} for f in range(3)], 'contact_translation': {'delta_weapon_cm': [4., -5., 6.], 'phase_frames': [0, 1, 1, 2]}}
        request = {'character': {}, 'weapon': {}, 'recipe': {'calibration': {'spawn_offset': identity}, 'solution': {'inputs': {'context': {'attachment_socket': {'local': identity}}}}}, 'source_poses': {'assets': [{'asset': 'original', 'keys': 3, 'samples': original}]}}
        saved = {'assets': [{'asset': 'saved', 'keys': 3, 'samples': actual}]}
        with patch('BBBWeaponActionAuthoring.SurfacePose', return_value=surface), patch('BBBWeaponActionAuthoring.runtime_geometry', return_value=(None, np.eye(4))):
            correct = verify(request, {'actions': [action]}, saved)
            self.assertTrue(correct['passed'])
            self.assertEqual(correct['actions'][0]['fullhold_with_declared_contact_frames'], [1])
            self.assertEqual(correct['actions'][0]['fullhold_pure_static_frames'], [0, 2])
            wrong = copy.deepcopy(saved)
            wrong_action = copy.deepcopy(action)
            for n in ('hand_l', 'ik_hand_l'):
                wrong['assets'][0]['samples'][1]['bones'][n]['translation']['x'] += 1.
                wrong_action['tracks'][n][1]['position'][0] += 1.
            checked = verify(request, {'actions': [wrong_action]}, wrong)
            self.assertFalse(checked['passed'])
            self.assertAlmostEqual(checked['actions'][0]['errors']['track_position_cm'], 0.)
            self.assertAlmostEqual(checked['actions'][0]['errors']['hold_position_cm'], 1.)

    def test_finger_pose_policy_imports_without_site_packages_in_editor_python(self):
        import subprocess

        scripts = str(Path(__file__).resolve().parents[1] / 'Scripts')
        code = f"import sys;sys.path.insert(0,{scripts!r});from BBBWeaponActionPolicy import validate_finger_pose_windows;assert 'numpy' not in sys.modules"
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_segment_boundary_hold_preserves_attachment_and_fingers_across_three_clips(self):
        """/** @return 起段末帧 循环首尾与结束首帧保持同一腕反补与十五指姿 结束按阶段淡出 */"""
        from types import SimpleNamespace
        from BBBWeaponActionAuthoring import compensate_hand_attachment_grip, validate_finger_pose_windows, apply_finger_pose_windows

        target = np.eye(4)
        target[:3, :3] = yaw(27)
        target[:3, 3] = [4, 6, 8]
        old = [2, -3, 4, 0, 0, 0, 1, 1, 1, 1]
        new = [2, 4, 4, 0, 0, 0, 1, 1, 1, 1]
        phases = [(26, [0, 4, 25, 26], [25]), (12, [-1, 0, 11, 12], [0, 11]), (18, [-1, 0, 0, 16], [0])]
        names = ['hand_l'] + [f'{finger}_{joint:02d}_l' for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)]
        surface = SimpleNamespace(names={name: index for index, name in enumerate(names)})
        local = np.tile(np.eye(4), (len(names), 1, 1))
        rotations = {name: [0, 0, np.sin(.2), np.cos(.2)] for name in names[1:]}
        expected_wrist = None
        expected_fingers = None
        for count, stage, frames in phases:
            change = {'bone': 'hand_l', 'reference_attachment_local': old, 'attachment_local': new,
                      'phase_frames': stage, 'boundary_hold': True}
            window = {'hand': 'hand_l', 'phase_frames': stage, 'local_rotations': rotations, 'boundary_hold': True}
            validate_finger_pose_windows([window], surface.names, count)
            for frame in frames:
                wrist = compensate_hand_attachment_grip(target, frame, [change], count)
                fingers = apply_finger_pose_windows(surface, local, frame, [window])
                if expected_wrist is not None:
                    np.testing.assert_allclose(wrist, expected_wrist, atol=1e-12)
                    np.testing.assert_allclose(fingers, expected_fingers, atol=1e-12)
                expected_wrist = wrist
                expected_fingers = fingers
            if count == 18:
                np.testing.assert_array_equal(compensate_hand_attachment_grip(target, 16, [change], count), target)
                np.testing.assert_array_equal(apply_finger_pose_windows(surface, local, 16, [window]), local)

    def test_boundary_hold_rejects_unbounded_outside_or_implicit_windows(self):
        """/** @return 只有显式边界保持能跨一帧 且满权点 有限值与真实帧数全部受限 */"""
        from BBBWeaponActionAuthoring import bounded_action_phase_weight

        for phases in ([-2, 0, 11, 12], [-1, 0, 11, 13], [-1, -.1, 11, 12], [-1, 0, 12, 13], [-1, 0, 11, float('inf')]):
            with self.subTest(phases=phases), self.assertRaises(ValueError):
                bounded_action_phase_weight(0, {'phase_frames': phases, 'boundary_hold': True}, 12)
        for window, count in [({'phase_frames': [-1, 0, 11, 12]}, 12),
                              ({'phase_frames': [0, 1, 11, 12]}, 12),
                              ({'phase_frames': [-1, 0, 11, 12], 'boundary_hold': 'true'}, 12),
                              ({'phase_frames': [-1, 0, 11, 12], 'boundary_hold': True}, None)]:
            with self.subTest(window=window), self.assertRaises(ValueError):
                bounded_action_phase_weight(0, window, count)

    def test_explicit_finger_pose_holds_shape_without_moving_wrist_or_bone_lengths(self):
        from types import SimpleNamespace
        from BBBWeaponActionAuthoring import apply_finger_pose_windows, validate_finger_pose_windows

        names = ['hand_l'] + [f'{finger}_{joint:02d}_l' for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)]
        surface = SimpleNamespace(names={name: index for index, name in enumerate(names)})
        local = np.tile(np.eye(4), (len(names), 1, 1))
        for index in range(len(names)):
            local[index, :3, 3] = [index, index * .3, -index * .1]
            local[index, :3, :3] = yaw(index * 3) @ np.diag([1.01, .99, 1.02])
        rotations = {name: [0, 0, np.sin(.2), np.cos(.2)] for name in names[1:]}
        windows = [{'hand': 'hand_l', 'phase_frames': [1, 4, 8, 11], 'local_rotations': rotations}]
        self.assertEqual(validate_finger_pose_windows(windows, surface.names, 12), set(names[1:]))
        first = apply_finger_pose_windows(surface, local, 4, windows)
        other = local.copy()
        other[1:, :3, :3] = np.array([yaw(80 + i) @ np.diag([1.01, .99, 1.02]) for i in range(15)])
        second = apply_finger_pose_windows(surface, other, 8, windows)
        np.testing.assert_allclose(first, second, atol=1e-12)
        np.testing.assert_array_equal(first[0], local[0])
        np.testing.assert_array_equal(first[:, :3, 3], local[:, :3, 3])
        np.testing.assert_allclose(np.linalg.norm(first[:, :3, :3], axis=1), np.linalg.norm(local[:, :3, :3], axis=1), atol=1e-12)
        np.testing.assert_array_equal(apply_finger_pose_windows(surface, local, 1, windows), local)
        np.testing.assert_array_equal(apply_finger_pose_windows(surface, local, 11, windows), local)

    def test_explicit_finger_pose_rejects_incomplete_nonunit_and_overlapping_sources(self):
        import copy
        from BBBWeaponActionAuthoring import validate_finger_pose_windows

        names = [f'{finger}_{joint:02d}_l' for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)]
        window = {'hand': 'hand_l', 'phase_frames': [1, 4, 8, 11], 'local_rotations': {name: [0, 0, 0, 1] for name in names}}
        variants = []
        partial = copy.deepcopy(window)
        partial['local_rotations'].pop(names[0])
        variants.append([partial])
        nonunit = copy.deepcopy(window)
        nonunit['local_rotations'][names[0]] = [0, 0, 0, 2]
        variants.extend([[nonunit], [window, window], [{**window, 'phase_frames': [1, 4, 8, 12]}]])
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                validate_finger_pose_windows(variant, names, 12)

    def test_runtime_wrist_uses_parent_delta_without_baking_action_track(self):
        from types import SimpleNamespace

        surface = SimpleNamespace(names={'hand_r': 1}, bones=[{'parent': -1}, {'parent': 0}])
        local = np.tile(np.eye(4), (2, 1, 1))
        local[0, :3, :3] = yaw(25)
        local[1, :3, :3] = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        local[1, :3, 3] = [2, 3, 4]
        components = np.array([local[0], local[0] @ local[1]])
        before = local.copy()
        delta = [0, np.sqrt(.5), 0, np.sqrt(.5)]
        actual = runtime_right_hand(surface, components, local, delta)
        expected_local = local[1].copy()
        expected_local[:3, :3] = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]]) @ local[1, :3, :3]
        np.testing.assert_allclose(actual, local[0] @ expected_local, atol=1e-12)
        np.testing.assert_array_equal(local, before)
        np.testing.assert_allclose(runtime_right_hand(surface, components, local, [0, 0, 0, 1]), components[1], atol=1e-12)

    def test_nested_helper_parent_is_updated_before_children(self):
        """/** @return 枪辅助骨变化不会再次带偏左右手辅助骨 */"""
        from types import SimpleNamespace

        names = ['root', 'ik_hand_root', 'ik_hand_gun', 'ik_hand_l', 'ik_hand_r', 'hand_r', 'hand_l']
        parents = [-1, 0, 1, 2, 2, 0, 0]
        local = np.repeat(np.eye(4)[None, :, :], len(names), axis=0)
        local[5, :3, 3] = [10, 0, 2]
        local[6, :3, 3] = [0, 15, 3]
        local[5, :3, :3] = yaw(30)
        local[6, :3, :3] = yaw(-20)

        def components(value):
            result = value.copy()
            for index, parent in enumerate(parents):
                if parent >= 0:
                    result[index] = result[parent] @ value[index]
            return result

        surface = SimpleNamespace(names={name: index for index, name in enumerate(names)},
                                  bones=[{'parent': parent} for parent in parents], components=components)
        output, actual = synchronize_hand_helpers(surface, local)
        np.testing.assert_allclose(actual[2], actual[5], atol=1e-10)
        np.testing.assert_allclose(actual[3], actual[6], atol=1e-10)
        np.testing.assert_allclose(actual[4], actual[5], atol=1e-10)

    def test_contact_follows_translated_rotated_weapon_instead_of_translation_only(self):
        """/** @return 更改挂接方向后腕部仍位于同一武器局部接触点 */"""
        original = np.eye(4)
        original[:3, 3] = [3, 2, 0]
        current = np.eye(4)
        current[:3, :3] = yaw(90)
        current[:3, 3] = [10, 20, 0]
        wrist = np.eye(4)
        wrist[:3, 3] = [5, 2, 0]
        target = contact_target(original, current, wrist)
        np.testing.assert_allclose(target[:3, 3], [10, 22, 0], atol=1e-10)
        np.testing.assert_allclose(target[:3, :3], yaw(90), atol=1e-10)

    def test_rotation_blend_takes_short_arc_across_signed_yaw_boundary(self):
        """/** @return 正负一百七十九度之间不会绕回零度产生腕部翻转 */"""
        actual = blend_rotation(yaw(179), yaw(-179), .5)
        np.testing.assert_allclose(actual, yaw(180), atol=1e-8)

    def test_wrist_path_preserves_compensated_segment_boundaries_and_overrides_middle(self):
        """/** @return 持物反补后再精修腕姿 保留已反补边界且拒绝未反补的旧边界 */"""
        from BBBWeaponActionAuthoring import compensate_hand_attachment_grip, explicit_wrist_component_path
        from BBBGripAuthoring import matrix_values

        change = {
            'bone': 'hand_l',
            'reference_attachment_local': [2, 3, 4, 0, 0, 0, 1, 1, 1, 1],
            'attachment_local': [2, 10, 4, 0, 0, 0, 1, 1, 1, 1],
            'phase_frames': [-1, 0, 4, 5],
            'boundary_hold': True,
        }
        original = np.eye(4)
        original[:3, :3] = yaw(47)
        original[:3, 3] = [5, 7, 11]
        compensated = [compensate_hand_attachment_grip(original, frame, [change], 5) for frame in range(5)]
        middle = compensated[2].copy()
        middle[:3, :3] = yaw(17)
        keys = [{'frame': frame, 'transform': matrix_values(matrix)}
                for frame, matrix in [(0, compensated[0]), (2, middle), (4, compensated[4])]]
        actual = explicit_wrist_component_path(compensated, keys)
        np.testing.assert_allclose(actual[0], compensated[0], atol=1e-12)
        np.testing.assert_allclose(actual[2], middle, atol=1e-12)
        np.testing.assert_allclose(actual[4], compensated[4], atol=1e-12)
        self.assertGreater(np.linalg.norm(actual[0][:3, 3] - original[:3, 3]), 6.9)
        keys[0]['transform'] = matrix_values(original)
        with self.assertRaises(ValueError):
            explicit_wrist_component_path(compensated, keys)

    def test_return_envelope_has_flat_endpoints_and_stays_bounded(self):
        """/** @return 回握权重不超调且两端速度趋近零 */"""
        values = smooth(np.linspace(-.2, 1.2, 1001))
        self.assertGreaterEqual(values.min(), 0)
        self.assertLessEqual(values.max(), 1)
        self.assertAlmostEqual(float(smooth(0)), 0)
        self.assertAlmostEqual(float(smooth(1)), 1)
        self.assertLess(float(smooth(.0001) / .0001), .00001)
        self.assertLess(float((1 - smooth(.9999)) / .0001), .00001)


if __name__ == '__main__':
    unittest.main()
