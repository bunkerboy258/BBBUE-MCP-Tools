import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
import BBBGripAuthoring as grip
import BBBWeaponActionAuthoring as action
from BBBGripPoseFitting import SurfacePose, rotation_matrix, transform_matrix


IDENTITY = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
NAMES = ['root', 'ik_hand_root', 'ik_hand_gun', 'ik_hand_l', 'ik_hand_r', 'hand_r', 'hand_l']
PARENTS = [-1, 0, 1, 2, 2, 0, 0]


def native_character(local):
    """/** @param local 嵌套辅助骨局部矩阵 @return 含独立原生组件变换的最小有效蒙皮采样 */"""
    components = local.copy()
    bones = []
    for index, name in enumerate(NAMES):
        if PARENTS[index] >= 0:
            components[index] = components[PARENTS[index]] @ local[index]
        values = grip.matrix_values(local[index])
        bones.append({'name': name, 'parent': PARENTS[index], 'local': values,
                      'referenceLocal': values, 'component': grip.matrix_values(components[index])})
    return {'bones': bones, 'vertices': [{'id': 0, 'bindPosition': [0, 0, 0], 'position': [0, 0, 0], 'weights': [[0, 1]]}], 'triangles': []}


def initial_local():
    """/** @return 枪辅助父骨与真实手骨不同方向的局部姿势 */"""
    local = np.repeat(np.eye(4)[None, :, :], len(NAMES), axis=0)
    local[1, :3, 3] = [.5, -.2, .1]
    local[2, :3, :3] = rotation_matrix([0, 0, np.sin(.2), np.cos(.2)])
    local[5, :3, 3] = [10, 2, 3]
    local[6, :3, 3] = [1, 15, 4]
    local[5, :3, :3] = rotation_matrix([0, 0, np.sin(.3), np.cos(.3)])
    local[6, :3, :3] = rotation_matrix([0, 0, -np.sin(.15), np.cos(.15)])
    return local


def audit_request(character):
    """/** @param character 实际姿势 @return 期望与实际完全相同的静态审计请求以独立检出辅助骨错误 */"""
    local = {bone['name']: bone['local'] for bone in character['bones']}
    components = {bone['name']: bone['component'] for bone in character['bones']}
    calibration = {'spawn_offset': list(IDENTITY), 'left_ik_offset': [0, 0, 0], 'left_ik_rotation': [0, 0, 0, 1]}
    keys = []
    offsets = {}
    for name, values in components.items():
        control = 'pose_' + name
        offsets[control] = {'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}
        for frame in [0, 1]:
            keys.append({'control': control, 'frame': frame,
                         'value': {'position': values[:3], 'rotation': values[3:7], 'scale': values[7:]}})
    return {'recipe': {'solution': {'calibration': calibration, 'local_pose': local, 'component_pose': components},
                       'checks': {'maximum_pose_position_error_cm': .001, 'maximum_pose_rotation_error_degrees': .02,
                                  'maximum_static_motion_cm': .001, 'maximum_wrist_error_cm': .001}},
            'character': character, 'weapon': {}, 'context': {}, 'samples': [character],
            'definition_calibration': calibration, 'control_keys': keys, 'control_offsets': offsets}


def run_audit(request):
    """/** @param request 独立辅助骨验证输入 @return 不依赖武器接触几何的真实静态审计结果 */"""
    wrist = next(bone['component'] for bone in request['character']['bones'] if bone['name'] == 'hand_l')
    with patch('BBBGripAuthoring.runtime_geometry', return_value=(np.eye(4), transform_matrix(wrist))), patch('BBBGripAuthoring.geometry_audit', return_value={'passed': True}):
        return grip.audit(request)


class GripHelperPairingTests(unittest.TestCase):
    def paired_local(self):
        """/** @return 按真实父子顺序同步后的局部矩阵 */"""
        local = initial_local()
        surface = SurfacePose(native_character(local))
        return grip.synchronize_hand_helpers(surface, local)[0]

    def test_action_import_is_the_same_shared_function(self):
        """/** @return 静态与动作没有复制辅助骨同步实现 */"""
        self.assertIs(action.synchronize_hand_helpers, grip.synchronize_hand_helpers)

    def test_static_solve_updates_nested_helper_parent_before_children(self):
        """/** @return 静态制作不会在更新枪辅助父骨后再次带偏左右手 */"""
        local = initial_local()
        character = native_character(local)
        calibration = {'spawn_offset': list(IDENTITY)}
        target = transform_matrix(character['bones'][-1]['component'])
        request = {'recipe': {'pose': {'mode': 'fixed', 'local_rotations': {}}},
                   'character': character, 'weapon': {}, 'context': {}}
        with patch('BBBGripAuthoring.calibrate', return_value=(calibration, local.copy(), np.eye(4), target, 0.0)), patch('BBBGripAuthoring.geometry_audit', return_value={'passed': True}):
            result = grip.solve(request)
        for helper, hand in [('ik_hand_gun', 'hand_r'), ('ik_hand_r', 'hand_r'), ('ik_hand_l', 'hand_l')]:
            np.testing.assert_allclose(transform_matrix(result['component_pose'][helper]), transform_matrix(result['component_pose'][hand]), atol=1e-10)

    def test_matching_reference_cannot_hide_actual_helper_position_drift(self):
        """/** @return 实际与错误期望完全一致时仍独立检出零点零零六九厘米偏差 */"""
        local = self.paired_local()
        local[2, 0, 3] += .0069
        result = run_audit(audit_request(native_character(local)))
        self.assertLess(result['maximumPosePositionErrorCm'], 1e-10)
        self.assertFalse(result['passed'])
        self.assertEqual(result['handHelperPairing']['pairCount'], 3)
        self.assertAlmostEqual(result['handHelperPairing']['maximumPositionErrorCm'], .0069, places=8)

    def test_matching_reference_cannot_hide_actual_helper_rotation_drift(self):
        """/** @return 辅助骨角度偏差独立使用既有零点零二度阈值拒绝 */"""
        local = self.paired_local()
        angle = np.deg2rad(.05)
        local[3, :3, :3] = local[3, :3, :3] @ rotation_matrix([0, 0, np.sin(angle / 2), np.cos(angle / 2)])
        result = run_audit(audit_request(native_character(local)))
        self.assertLess(result['maximumPoseRotationErrorDegrees'], 1e-5)
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['handHelperPairing']['maximumRotationErrorDegrees'], .05, places=6)

    def test_audit_checks_all_native_samples(self):
        """/** @return 后续帧原生组件偏差不会被首帧正确姿势掩盖 */"""
        character = native_character(self.paired_local())
        request = audit_request(character)
        changed = copy.deepcopy(character)
        changed['bones'][3]['component'][0] += .01
        request['samples'].append(changed)
        result = run_audit(request)
        self.assertFalse(result['passed'])
        self.assertEqual(result['handHelperPairing']['sampleCount'], 3)
        self.assertAlmostEqual(result['handHelperPairing']['maximumPositionErrorCm'], .01, places=8)

    def test_absent_helpers_are_explicitly_reported_without_fake_pairs(self):
        """/** @return 无辅助骨的通用骨架明确报告零对而不伪造缺骨 */"""
        character = {'bones': [{'name': 'hand_l', 'component': list(IDENTITY)}, {'name': 'hand_r', 'component': list(IDENTITY)}]}
        self.assertEqual(grip.hand_helper_pairing_audit(character)['pairCount'], 0)

    def test_present_helper_without_target_hand_is_rejected(self):
        """/** @return 存在辅助骨却缺少对应手骨必须明确失败 */"""
        character = native_character(initial_local())
        character['bones'][-1]['name'] = 'other_hand'
        with self.assertRaisesRegex(ValueError, '缺少对应手骨'):
            grip.hand_helper_pairing_audit(character)
        surface = SurfacePose(character)
        with self.assertRaisesRegex(ValueError, '缺少对应手骨'):
            grip.synchronize_hand_helpers(surface, surface.locals)


if __name__ == '__main__':
    unittest.main()
