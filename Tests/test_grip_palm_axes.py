import copy
from pathlib import Path
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBGripAuthoring import matrix_quaternion, palm_axis_audit
from BBBGripPoseFitting import rotation_matrix


class PalmAxesTests(unittest.TestCase):
    def test_quaternion_rejects_homogeneous_or_non_rotation_matrix(self):
        for matrix in (np.eye(4), np.diag([1., 1., -1.]), np.diag([2., 1., 1.]), np.full((3, 3), np.nan)):
            with self.subTest(matrix=matrix):
                with self.assertRaises(ValueError):
                    matrix_quaternion(matrix)
        rotation = rotation_matrix([0, .7071067811865476, 0, .7071067811865476])
        np.testing.assert_allclose(rotation_matrix(matrix_quaternion(rotation)), rotation, atol=1e-10)

    def setUp(self):
        self.locals = np.array([np.eye(4), np.eye(4), np.eye(4), np.eye(4)])
        self.surface = types.SimpleNamespace(
            locals=self.locals, names={'hand_r': 0, 'thumb_01_r': 1, 'thumb_03_r': 2, 'middle_03_r': 3},
            bones=[{'local': [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]} for _ in range(4)])

        def components(local):
            result = local.copy()
            result[1] = result[0] @ local[1]
            result[2] = result[1] @ local[2]
            result[3] = result[0] @ local[3]
            return result

        self.surface.components = components
        self.rule = {'name': 'thumb_forward', 'hand': 'hand_r', 'bone': 'thumb_03_r',
                     'axis': [1, 0, 0], 'reference_in_hand': [1, 0, 0], 'maximum_degrees': 15}

    def test_hand_rotation_does_not_change_palm_direction(self):
        self.locals[0, :3, :3] = rotation_matrix([0, 0, .7071067811865476, .7071067811865476])
        result = palm_axis_audit(self.surface, {}, [self.rule])[0]
        self.assertTrue(result['passed'])
        self.assertAlmostEqual(result['angleDegrees'], 0)

    def test_root_rotation_is_detected_despite_unchanged_distal_local(self):
        self.locals[1, :3, :3] = rotation_matrix([0, .7071067811865476, 0, .7071067811865476])
        result = palm_axis_audit(self.surface, {}, [self.rule])[0]
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['angleDegrees'], 90)

    def test_current_pair_rejects_opposite_terminal_direction(self):
        rule = dict(self.rule)
        del rule['reference_in_hand']
        rule.update(other_bone='middle_03_r', other_axis=[1, 0, 0])
        result = palm_axis_audit(self.surface, {'middle_03_r': [0, 1, 0, 0]}, [rule])[0]
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['angleDegrees'], 180)

    def test_invalid_or_ambiguous_axis_rules_fail(self):
        for changes in ({'axis': [0, 0, 0]}, {'maximum_degrees': float('nan')},
                        {'other_bone': 'middle_03_r', 'other_axis': [1, 0, 0]}):
            with self.subTest(changes=changes):
                rule = copy.deepcopy(self.rule)
                rule.update(changes)
                with self.assertRaises(ValueError):
                    palm_axis_audit(self.surface, {}, [rule])


if __name__ == '__main__':
    unittest.main()
