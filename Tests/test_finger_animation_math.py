import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'Scripts'))
import BBBFingerAnimationMath as m


class FingerAnimationMathTests(unittest.TestCase):
    """/** 校准参照 左右符号 例外和离轴消除的离线边界 */"""

    def rule(self, **changes):
        """/** @param changes 明确规则变更 @return 测试校准 */"""
        return dict(dict(kind='hinge', neutral=[0, 0, 0, 1], axis=[0, 0, 1], limits_degrees=[0, 120], tolerance_degrees=0.1), **changes)

    def test_correct_samples_preserved(self):
        """/** @return 正常屈伸及等价四元数不被误改 */"""
        q = m.axis_angle([0, 0, 1], 70)
        source = [[0, 0, 0, 1], q, [-v for v in q]]
        result, errors = m.process(source, self.rule(), set())
        self.assertEqual(result, source)
        self.assertFalse(errors)

    def test_off_axis_removed_in_reference_frame(self):
        """/** @return 非零参考姿态下只消除离轴旋转 */"""
        neutral = m.axis_angle([0, 1, 0], 63)
        expected = m.multiply(neutral, m.axis_angle([0, 0, 1], 40))
        bad = m.multiply(neutral, m.multiply(m.axis_angle([1, 0, 0], 25), m.axis_angle([0, 0, 1], 40)))
        result, errors = m.process([bad], self.rule(neutral=neutral), set())
        self.assertEqual(len(errors), 1)
        self.assertLess(m.distance(result[0], expected), 0.001)
        self.assertFalse(m.process(result, self.rule(neutral=neutral), set())[1])

    def test_mirrored_axis(self):
        """/** @return 左右镜像轴通过自身校准确定符号 */"""
        axis = [0, 0, -1]
        correct = m.axis_angle(axis, 65)
        self.assertFalse(m.process([correct], self.rule(axis=axis), set())[1])
        output, errors = m.process([m.axis_angle(axis, -25)], self.rule(axis=axis), set())
        self.assertTrue(errors)
        self.assertLess(m.distance(output[0], [0, 0, 0, 1]), 0.001)

    def test_spread_preserves_flexion(self):
        """/** @return 限制展开时保留其他关节旋转 */"""
        flexion = m.axis_angle([1, 0, 0], 50)
        original = m.multiply(flexion, m.axis_angle([0, 0, 1], 35))
        output, unused = m.process([original], self.rule(kind='spread', limits_degrees=[-10, 10]), set())
        other, angle = m.split(output[0], [0, 0, 1])
        self.assertAlmostEqual(angle, 10)
        self.assertLess(m.distance(other, flexion), 0.001)

    def test_exception_singular_pose_preserved(self):
        """/** @return 特殊动作例外不会被修复或错误分解 */"""
        pose = m.axis_angle([1, 0, 0], 180)
        self.assertEqual(m.process([pose], self.rule(), {0}), ([pose], []))

    def test_long_interval_is_feasible_and_idempotent(self):
        """/** @return 连续异常修后满足允许域 重复修复不继续漂移 */"""
        poses = [m.multiply(m.axis_angle([1, 0, 0], 20), m.axis_angle([0, 0, 1], angle)) for angle in [-20, 30, 160, 60]]
        result, errors = m.process(poses, self.rule(), set())
        self.assertEqual(len(errors), 4)
        second, remaining = m.process(result, self.rule(), set())
        self.assertFalse(remaining)
        self.assertEqual(result, second)

    def test_invalid_axis_rejected(self):
        """/** @return 退化校准与非法数值不得生成候选 */"""
        for axis in ([0, 0, 0], [float('nan'), 0, 1]):
            with self.assertRaises(ValueError):
                m.process([[0, 0, 0, 1]], self.rule(axis=axis), set())


if __name__ == '__main__':
    unittest.main()
