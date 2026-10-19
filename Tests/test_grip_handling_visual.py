import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBGripVisualReview import handling_surface, saved_curve_alpha


def fixture():
    root = '/Game/Project/Weapon'
    identity = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
    recipe = {'animation': root + '/Grip', 'character_mesh': '/Game/Project/Character',
              'calibration': {'right_wrist_delta': [0, 0, 0, 1]}}
    curves = {'DisableLeftHandPoseOverride': {'exists': True, 'keys': [
        {'time': 0, 'value': 1, 'interp_mode': 'RCIM_Cubic', 'leave_tangent': 0, 'arrive_tangent': 0},
        {'time': 1, 'value': 0, 'interp_mode': 'RCIM_Cubic', 'leave_tangent': 0, 'arrive_tangent': 0}]},
        'DisableRightHandPoseOverride': {'exists': False}}
    actions = {'actions': [{'asset': root + '/Reload'}], 'curves': [{'asset': root + '/Reload', 'curves': curves}]}
    report = {'status': 'ok', 'readOnly': True, 'projectDirtyPackagesUnchanged': True,
              'evaluationRoute': 'TransientAnimBlueprint->FormalHandPose',
              'mainGameplayEvaluated': False, 'fullBodyLayerEvaluated': False, 'aimIKEnabled': False, 'leftHandIKEnabled': False,
              'inputSnapshot': {'animation': root + '/Reload', 'grip': root + '/Grip', 'mesh': '/Game/Project/Character',
                  'equipmentEnabled': True, 'base': '/Game/Project/Base', 'timeSeconds': .25,
                  'leftGripAlpha': .15625, 'rightGripAlpha': 1},
              'timeSeconds': .25, 'sourceRightHandLocal': identity,
              'localBones': {'Hand_R': identity},
              'surface': {'bones': [{'name': 'hand_r', 'component': identity}], 'vertices': [{'position': [1, 2, 3]}]}}
    return report, recipe, actions


class HandlingVisualTests(unittest.TestCase):
    def test_native_surface_is_only_rearranged_and_scope_remains_explicit(self):
        report, recipe, actions = fixture()
        before = copy.deepcopy(report)
        surface = handling_surface(report, recipe, actions, 0)
        self.assertEqual(surface['vertices'], before['surface']['vertices'])
        self.assertEqual(surface['bones'][0]['component'], before['surface']['bones'][0]['component'])
        self.assertEqual(surface['bones'][0]['local'], report['localBones']['Hand_R'])
        self.assertEqual(report, before)

    def test_saved_cubic_flat_curve_has_actual_mid_weight_and_missing_curve_is_zero_disable(self):
        report, recipe, actions = fixture()
        self.assertAlmostEqual(saved_curve_alpha(actions, actions['actions'][0]['asset'], 'DisableLeftHandPoseOverride', .25), .15625)
        self.assertEqual(saved_curve_alpha(actions, actions['actions'][0]['asset'], 'DisableRightHandPoseOverride', .25), 1)

    def test_unproven_curve_or_wrong_snapshot_alpha_is_rejected(self):
        for mode in ['missing', 'wrong_alpha', 'nan_alpha', 'nonflat']:
            report, recipe, actions = fixture()
            if mode == 'missing':
                actions['curves'] = []
            if mode == 'wrong_alpha':
                report['inputSnapshot']['leftGripAlpha'] = 1
            if mode == 'nan_alpha':
                report['inputSnapshot']['leftGripAlpha'] = np.nan
            if mode == 'nonflat':
                actions['curves'][0]['curves']['DisableLeftHandPoseOverride']['keys'][0]['leave_tangent'] = 2
            with self.assertRaises(ValueError):
                handling_surface(report, recipe, actions, 0)

    def test_wrong_delta_source_scope_and_wrist_translation_are_rejected(self):
        for mode in ['source', 'scope', 'translation']:
            report, recipe, actions = fixture()
            if mode == 'source':
                report['inputSnapshot']['grip'] = '/Game/Another/Grip'
            if mode == 'scope':
                report['mainGameplayEvaluated'] = True
            if mode == 'translation':
                report['localBones']['Hand_R'] = [2] + report['localBones']['Hand_R'][1:]
            with self.assertRaises(ValueError):
                handling_surface(report, recipe, actions, 0)
