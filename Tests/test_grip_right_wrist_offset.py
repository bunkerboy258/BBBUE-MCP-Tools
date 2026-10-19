import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBGripAuthoring import matrix_values, right_wrist_pose
from BBBGripPoseFitting import SurfacePose, rotation_matrix


def sample():
    local = np.tile(np.eye(4), (3, 1, 1))
    local[0, :3, :3] = rotation_matrix([.2588190451, 0, 0, .9659258263])
    local[1, :3, :3] = rotation_matrix([0, .3826834324, 0, .9238795325])
    local[1, :3, 3] = [3, 4, 5]
    local[2, :3, 3] = [2, 0, 0]
    components = [local[0], local[0] @ local[1], local[0] @ local[1] @ local[2]]
    bones = [{'name': name, 'parent': index - 1, 'local': matrix_values(local[index]),
              'component': matrix_values(components[index]), 'referenceLocal': matrix_values(local[index]),
              'inverseBindMatrix': np.linalg.inv(components[index]).T.flatten().tolist()}
             for index, name in enumerate(['lowerarm_r', 'hand_r', 'index_01_r'])]
    position = components[2][:3, 3].tolist()
    return {'bones': bones, 'vertices': [{'id': 1, 'bindPosition': position, 'position': position,
                                        'weights': [[2, 1]], 'selected': True}], 'triangles': []}


class RightWristOffsetTests(unittest.TestCase):
    def test_parent_space_left_multiply_with_noncommuting_rotations(self):
        surface = SurfacePose(sample())
        before = surface.locals.copy()
        delta = [0, 0, .5, np.sqrt(.75)]
        after = right_wrist_pose(surface, delta)
        expected = rotation_matrix(delta) @ before[1, :3, :3]
        np.testing.assert_allclose(after[1, :3, :3], expected, atol=1e-12)
        self.assertGreater(np.linalg.norm(expected - before[1, :3, :3] @ rotation_matrix(delta)), .1)
        np.testing.assert_array_equal(after[0], before[0])
        np.testing.assert_array_equal(after[2], before[2])
        np.testing.assert_array_equal(after[1, :3, 3], before[1, :3, 3])
        np.testing.assert_array_equal(surface.locals, before)

    def test_identity_keeps_reference_pose(self):
        surface = SurfacePose(sample())
        np.testing.assert_array_equal(right_wrist_pose(surface, [0, 0, 0, 1]), surface.locals)

    def test_inverse_mount_preserves_world_weapon_direction(self):
        surface = SurfacePose(sample())
        before = surface.components(surface.locals)[1]
        after_local = right_wrist_pose(surface, [.2588190451, 0, 0, .9659258263])
        after = surface.components(after_local)[1]
        old_mount = np.eye(4)
        old_mount[:3, 3] = [4, -3, 2]
        socket = np.eye(4)
        socket[:3, :3] = rotation_matrix([0, 0, .3826834324, .9238795325])
        new_mount = np.linalg.inv(socket) @ np.linalg.inv(after) @ before @ socket @ old_mount
        np.testing.assert_allclose(after @ socket @ new_mount, before @ socket @ old_mount, atol=1e-12)

    def test_invalid_quaternion_or_missing_hand_is_rejected(self):
        surface = SurfacePose(sample())
        for value in [[0, 0, 0, 0], [0, 0, 0, 2], [0, 0, 1], [np.nan, 0, 0, 1]]:
            with self.assertRaises(ValueError):
                right_wrist_pose(surface, value)
        data = copy.deepcopy(sample())
        data['bones'][1]['name'] = 'other'
        with self.assertRaises(ValueError):
            right_wrist_pose(SurfacePose(data), [0, 0, 0, 1])
