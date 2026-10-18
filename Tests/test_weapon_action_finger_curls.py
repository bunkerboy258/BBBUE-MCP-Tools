from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBWeaponActionAuthoring import apply_finger_curls, phase_weight


def axis_rotation(axis, degrees):
    """/** @param axis 明确坐标轴 @param degrees 角度 @return 解析坐标轴旋转矩阵 */"""
    angle = np.deg2rad(degrees)
    cosine = np.cos(angle)
    sine = np.sin(angle)
    if axis == 'x':
        return np.array([[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]])
    if axis == 'y':
        return np.array([[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]])
    if axis == 'z':
        return np.array([[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]])
    raise ValueError('测试夹具只接受坐标轴')


def finger_skeleton(plane_axis='z'):
    """/** @param plane_axis 掌空间平面法向轴 @return 父臂及手掌均非零旋转的简指骨链与局部姿态 */"""
    names = ['root', 'forearm_l', 'hand_l', 'middle_01_l', 'middle_02_l', 'middle_03_l',
             'finger_end_l', 'hand_r', 'middle_02_r']
    parents = [-1, 0, 1, 2, 3, 4, 5, 0, 7]
    local = np.repeat(np.eye(4)[None, :, :], len(names), axis=0)
    local[0, :3, :3] = axis_rotation('z', 23)
    local[1, :3, :3] = axis_rotation('x', 37)
    local[2, :3, :3] = axis_rotation('y', -28)
    local[1, :3, 3] = [2, 3, 1]
    local[2, :3, 3] = [5, 1, 2]
    local[3, :3, :3] = axis_rotation(plane_axis, 10)
    local[4, :3, :3] = axis_rotation(plane_axis, -12)
    local[5, :3, :3] = axis_rotation(plane_axis, 7)
    local[4, :3, 3] = [3, 0, 0]
    local[5, :3, 3] = [2, 0, 0]
    local[6, :3, 3] = [1, 0, 0]
    local[7, :3, 3] = [-5, 2, 0]
    local[8, :3, 3] = [3, 0, 0]

    def components(value):
        """/** @param value 局部姿态 @return 标准骨链正向组件姿态 */"""
        result = value.copy()
        for index, parent in enumerate(parents):
            if parent >= 0:
                result[index] = result[parent] @ value[index]
        return result

    surface = SimpleNamespace(names={name: index for index, name in enumerate(names)},
                              bones=[{'name': name, 'parent': parent} for name, parent in zip(names, parents)],
                              components=components)
    return surface, local


def correction(axis):
    """/** @param axis 明确掌空间平面法向 @return 只追加中指中末节角度的声明 */"""
    return [{'hand': 'hand_l', 'axis_in_hand': axis,
             'angles_degrees': {'middle_02_l': 30, 'middle_03_l': 20}}]


class WeaponActionFingerCurlTests(unittest.TestCase):
    def test_curled_tip_matches_planar_link_geometry_under_rotated_hand_and_arm(self):
        """/** @return 非零手掌及父臂旋转下指端仍匹配掌空间平面内解析连杆目标 */"""
        for axis_name, normal in [('z', [0, 0, 1]), ('y', [0, 1, 0])]:
            for weight in [.5, 1.0]:
                with self.subTest(axis=axis_name, weight=weight):
                    surface, local = finger_skeleton(axis_name)
                    output = apply_finger_curls(surface, local, correction(normal), weight)
                    actual = surface.components(output)
                    palm_inverse = np.linalg.inv(actual[surface.names['hand_l']])
                    points = np.asarray([(palm_inverse @ actual[index])[:3, 3] for index in [3, 4, 5, 6]])
                    np.testing.assert_allclose(points @ normal, 0, atol=1e-12)
                    angles = np.deg2rad([10, 10 - 12 + 30 * weight, 10 - 12 + 7 + 50 * weight])
                    expected = np.zeros(3)
                    expected[0] = np.dot([3, 2, 1], np.cos(angles))
                    if axis_name == 'z':
                        expected[1] = np.dot([3, 2, 1], np.sin(angles))
                    if axis_name == 'y':
                        expected[2] = -np.dot([3, 2, 1], np.sin(angles))
                    np.testing.assert_allclose(points[-1], expected, atol=1e-12)

    def test_bone_lengths_translations_input_and_unselected_locals_are_preserved(self):
        """/** @return 卷曲不伸缩骨长不改局部平移也不改未指定骨或原始输入 */"""
        surface, local = finger_skeleton()
        original = local.copy()
        before = surface.components(local)
        output = apply_finger_curls(surface, local, correction([0, 0, 1]), 1)
        after = surface.components(output)
        np.testing.assert_array_equal(local, original)
        np.testing.assert_array_equal(output[:, :3, 3], original[:, :3, 3])
        unchanged = [index for index in range(len(local)) if index not in [4, 5]]
        np.testing.assert_array_equal(output[unchanged], original[unchanged])
        for index, bone in enumerate(surface.bones):
            if bone['parent'] >= 0:
                parent = bone['parent']
                self.assertAlmostEqual(float(np.linalg.norm(before[index, :3, 3] - before[parent, :3, 3])),
                                       float(np.linalg.norm(after[index, :3, 3] - after[parent, :3, 3])), places=12)

    def test_zero_weight_returns_the_exact_original_pose(self):
        """/** @return 无修正权重的源姿势逐项保持原样而不经重复矩阵换算漂移 */"""
        surface, local = finger_skeleton()
        output = apply_finger_curls(surface, local, correction([0, 0, 1]), 0)
        np.testing.assert_array_equal(output, local)

    def test_phase_boundaries_are_bounded_with_flat_velocity_and_acceleration(self):
        """/** @return 四个阶段边界权重连续且一二阶变化趋零 */"""
        phases = [2, 12, 30, 42]
        self.assertEqual([phase_weight(frame, phases) for frame in [-1, 2, 12, 30, 42, 50]], [0, 0, 1, 1, 0, 0])
        values = [phase_weight(frame, phases) for frame in np.linspace(-5, 50, 501)]
        self.assertGreaterEqual(min(values), 0)
        self.assertLessEqual(max(values), 1)
        epsilon = .001
        for boundary in phases:
            first = phase_weight(boundary - epsilon, phases)
            center = phase_weight(boundary, phases)
            last = phase_weight(boundary + epsilon, phases)
            self.assertLess(abs((last - first) / (2 * epsilon)), 1e-5)
            self.assertLess(abs((last - 2 * center + first) / epsilon ** 2), 1e-3)
        with self.assertRaises(ValueError):
            phase_weight(5, [2, 2, 30, 42])

    def test_invalid_axis_cross_hand_and_nonfinger_bones_are_rejected(self):
        """/** @return 非法卷曲平面或越过指定手部指骨范围必须失败 */"""
        surface, local = finger_skeleton()
        for axis in [[0, 0, 0], [1, 0], [0, np.nan, 1], [np.inf, 0, 1]]:
            with self.subTest(axis=axis):
                with self.assertRaises(ValueError):
                    apply_finger_curls(surface, local, correction(axis), 1)
        for bone in ['middle_02_r', 'hand_l', 'forearm_l']:
            with self.subTest(bone=bone):
                with self.assertRaises(ValueError):
                    apply_finger_curls(surface, local, [{'hand': 'hand_l', 'axis_in_hand': [0, 0, 1], 'angles_degrees': {bone: 20}}], 1)


if __name__ == '__main__':
    unittest.main()
