from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBWeaponActionAuthoring import blend_rotation, contact_target, smooth, synchronize_hand_helpers


def yaw(angle):
    """/** @param angle 角度 @return 绕竖轴纯旋转矩阵 */"""
    value = np.radians(angle)
    return np.array([[np.cos(value), -np.sin(value), 0], [np.sin(value), np.cos(value), 0], [0, 0, 1]])


class WeaponActionAuthoringTests(unittest.TestCase):
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
