import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Scripts'))
from BBBGripGeometry import closest_point_triangle
from BBBGripPoseFitting import SurfacePose, TriangleQuery, contact_error, fit_pose, nearest_triangles, region_triangles, rotation_matrix
from BBBGripSolidAudit import WeldedSolidSurface


IDENTITY = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]


def hand_sample():
    """/** @return 已知精确蒙皮结果的两骨三角面样本 */"""
    finger = [1, 0, 0, 0, 0, 0, 1, 1, 1, 1]
    inverse = np.eye(4)
    inverse[0, 3] = -1
    return {'bones': [
        {'name': 'hand_r', 'parent': -1, 'referenceLocal': IDENTITY[:], 'local': IDENTITY[:], 'component': IDENTITY[:], 'inverseBindMatrix': np.eye(4).flatten().tolist()},
        {'name': 'finger', 'parent': 0, 'referenceLocal': finger[:], 'local': finger[:], 'component': finger[:], 'inverseBindMatrix': inverse.T.flatten().tolist()}],
        'vertices': [{'id': identifier, 'selected': True, 'position': point[:], 'bindPosition': point[:], 'weights': [[1, 1.0]]}
                     for identifier, point in [(10, [2, 0, 0]), (20, [2, .2, 0]), (30, [2, 0, .2])]],
        'triangles': [{'id': 9, 'vertices': [10, 20, 30]}]}


def weapon_sample():
    """/** @return 沿Y等于零点八的平面作为已知接触目标 */"""
    return {'vertices': [{'id': index, 'position': point} for index, point in enumerate([(0, .8, -1), (4, .8, -1), (0, .8, 2), (4, .8, 2)])],
            'triangles': [{'id': 101, 'vertices': [0, 1, 2]}, {'id': 102, 'vertices': [2, 1, 3]}]}


def fit_configuration():
    """/** @return 明确接触点和单轴有界拟合配置 */"""
    return {'attachment': IDENTITY[:], 'maximum_delta_degrees': 25, 'steps_degrees': [10, 3, 1],
            'contacts': [{'name': 'finger_pad', 'bones': ['finger'], 'axes': [2], 'vertex_ids': [10, 20, 30], 'selection_reviewed': True,
                          'weapon_triangle_ids': [101, 102], 'target_gap_cm': .05, 'surface_normal_sign': 1}]}


class GripPoseFittingTests(unittest.TestCase):
    def test_skinning_uses_reference_bind_when_explicit_inverse_is_absent(self):
        data = hand_sample()
        for bone in data['bones']:
            del bone['inverseBindMatrix']
        quaternion = [0, 0, math.sqrt(.5), math.sqrt(.5)]
        data['bones'][1]['local'][3:7] = quaternion
        data['bones'][1]['component'][3:7] = quaternion
        for vertex in data['vertices']:
            offset = np.array(vertex['bindPosition']) - [1, 0, 0]
            vertex['position'] = (rotation_matrix(quaternion) @ offset + [1, 0, 0]).tolist()
        pose = SurfacePose(data)
        np.testing.assert_allclose(pose.skin(), pose.initial, atol=1e-12)
        np.testing.assert_allclose(pose.skin()[0], [1, 1, 0], atol=1e-12)

    def test_fit_improves_explicit_contact_and_preserves_joint_bounds(self):
        configuration = fit_configuration()
        configuration['steps_degrees'] = [10, 1, .5]
        configuration['contacts'][0]['joint_limits_degrees'] = {'finger': [[0, 0], [0, 0], [0, 12.5]]}
        configuration['contacts'][0]['exclude_vertex_ids'] = [20]
        result = fit_pose(hand_sample(), weapon_sample(), configuration)
        contact = result['contacts'][0]
        self.assertEqual(contact['sampleVertexIds'], [10, 30])
        self.assertLess(contact['afterMeanGapCm'], contact['beforeMeanGapCm'])
        self.assertTrue(contact['finalStateRecomputed'])
        self.assertEqual(contact['selectionMethod'], 'explicit_vertex_ids')
        self.assertFalse(contact['requiresContactSelectionReview'])
        np.testing.assert_allclose(contact['jointDeltaDegrees']['finger'], [0, 0, 12.5], atol=1e-10)
        self.assertAlmostEqual(contact['jointRotationDeltaDegrees']['finger'], 12.5, places=8)
        self.assertEqual(set(result['localRotations']), {'finger'})
        self.assertEqual(result['independentFullSurfaceAudit']['after']['sampleCount'], 3)
        self.assertFalse(result['independentFullSurfaceAudit']['after']['volumePenetrationEvaluated'])
        self.assertFalse(result['jointConstraintsAreAnatomicalProof'])

    def test_unreviewed_automatic_selection_is_not_a_formal_default(self):
        configuration = fit_configuration()
        del configuration['contacts'][0]['vertex_ids']
        with self.assertRaisesRegex(ValueError, 'vertex_ids'):
            fit_pose(hand_sample(), weapon_sample(), configuration)
        configuration['contacts'][0]['selection_mode'] = 'radial_candidate'
        result = fit_pose(hand_sample(), weapon_sample(), configuration)
        self.assertTrue(result['contacts'][0]['requiresContactSelectionReview'])

    def test_explicit_candidate_ids_do_not_claim_human_review(self):
        configuration = fit_configuration()
        del configuration['contacts'][0]['selection_reviewed']
        result = fit_pose(hand_sample(), weapon_sample(), configuration)
        self.assertFalse(result['contacts'][0]['selectionReviewed'])
        self.assertTrue(result['contacts'][0]['requiresContactSelectionReview'])

    def test_stale_vertex_ids_and_empty_exclusions_fail(self):
        for identifiers in ([99], [10, 10], []):
            configuration = fit_configuration()
            configuration['contacts'][0]['vertex_ids'] = identifiers
            with self.assertRaises(ValueError):
                fit_pose(hand_sample(), weapon_sample(), configuration)
        configuration = fit_configuration()
        configuration['contacts'][0]['exclude_vertex_ids'] = [10, 20, 30]
        with self.assertRaises(ValueError):
            fit_pose(hand_sample(), weapon_sample(), configuration)

    def test_target_region_ids_are_explicit_and_excludable(self):
        selected = region_triangles(weapon_sample(), None, np.eye(4), [101, 102], [102])
        self.assertEqual(selected.shape, (1, 3, 3))
        with self.assertRaises(ValueError):
            region_triangles(weapon_sample(), None, np.eye(4), [999])
        configuration = fit_configuration()
        del configuration['contacts'][0]['weapon_triangle_ids']
        with self.assertRaisesRegex(ValueError, '接触区域'):
            fit_pose(hand_sample(), weapon_sample(), configuration)

    def test_unrelated_vertices_are_included_in_independent_final_audit(self):
        data = hand_sample()
        data['vertices'].append({'id': 40, 'selected': True, 'position': [1, .79, 0], 'bindPosition': [1, .79, 0], 'weights': [[0, 1.0]]})
        result = fit_pose(data, weapon_sample(), fit_configuration())
        self.assertEqual(result['contacts'][0]['sampleCount'], 3)
        self.assertEqual(result['independentFullSurfaceAudit']['after']['sampleCount'], 4)
        self.assertIn(40, result['independentFullSurfaceAudit']['after']['closestVertexIds'])
        self.assertFalse(result['independentFullSurfaceAudit']['after']['normalSignIsVolumeClassification'])

    def test_bad_weights_hierarchy_and_baseline_fail_before_fitting(self):
        bad_weight = hand_sample()
        bad_weight['vertices'][0]['weights'][0][1] = .2
        with self.assertRaisesRegex(ValueError, '权重'):
            SurfacePose(bad_weight)
        bad_parent = hand_sample()
        bad_parent['bones'][1]['parent'] = 1
        with self.assertRaisesRegex(ValueError, '父子顺序'):
            SurfacePose(bad_parent)
        bad_baseline = hand_sample()
        bad_baseline['vertices'][0]['position'][0] += .01
        with self.assertRaisesRegex(ValueError, '离线蒙皮'):
            fit_pose(bad_baseline, weapon_sample(), fit_configuration())

    def test_vectorized_distance_matches_independent_triangle_implementation(self):
        generator = np.random.default_rng(1918)
        points = generator.normal(size=(75, 3)) * 3
        triangles = generator.normal(size=(45, 3, 3))
        nearest, distances, normal_gaps = nearest_triangles(points, triangles)
        expected = [min(np.linalg.norm(point-np.asarray(closest_point_triangle(point, *triangle))) for triangle in triangles) for point in points]
        np.testing.assert_allclose(distances, expected, atol=1e-10)
        np.testing.assert_allclose(np.linalg.norm(points-nearest, axis=1), distances, atol=1e-10)
        self.assertTrue(np.all(np.abs(normal_gaps) <= distances+1e-10))

    def test_overlapping_contact_joint_sets_do_not_silently_overwrite(self):
        configuration = fit_configuration()
        configuration['contacts'].append(copy.deepcopy(configuration['contacts'][0]))
        with self.assertRaisesRegex(ValueError, '重复拟合'):
            fit_pose(hand_sample(), weapon_sample(), configuration)

    def test_formal_contacts_require_an_explicit_surface_orientation(self):
        configuration = fit_configuration()
        del configuration['contacts'][0]['surface_normal_sign']
        with self.assertRaisesRegex(ValueError, 'surface_normal_sign'):
            fit_pose(hand_sample(), weapon_sample(), configuration)
        configuration['contacts'][0]['signed_normal_target'] = False
        result = fit_pose(hand_sample(), weapon_sample(), configuration)
        self.assertFalse(result['contacts'][0]['signedNormalTarget'])
        self.assertIsNone(result['contacts'][0]['meanOutwardNormalGapCm'])

    def test_signed_error_rejects_an_equally_close_back_side(self):
        error = contact_error(np.asarray([.1, .1]), np.asarray([.1, -.1]), .1, 1)
        self.assertAlmostEqual(error[0], 0)
        self.assertAlmostEqual(error[1], .04)
        reversed_error = contact_error(np.asarray([.1, .1]), np.asarray([.1, -.1]), .1, -1)
        self.assertAlmostEqual(reversed_error[0], .04)
        self.assertAlmostEqual(reversed_error[1], 0)

    def test_fitting_crosses_the_surface_to_the_requested_outward_side(self):
        data = hand_sample()
        for vertex in data['vertices']:
            vertex['position'][1] += 1
            vertex['bindPosition'][1] += 1
        configuration = fit_configuration()
        configuration['regularization'] = 0
        configuration['steps_degrees'] = [10, 3, 1, .2]
        configuration['contacts'][0]['vertex_ids'] = [10]
        configuration['contacts'][0]['target_gap_cm'] = .1
        positive = fit_pose(data, weapon_sample(), configuration)['contacts'][0]
        self.assertGreater(positive['meanNormalGapCm'], .07)
        self.assertEqual(positive['wrongSideContactPointCount'], 0)
        configuration['contacts'][0]['surface_normal_sign'] = -1
        negative = fit_pose(data, weapon_sample(), configuration)['contacts'][0]
        self.assertLess(negative['meanNormalGapCm'], -.07)
        self.assertGreater(negative['meanOutwardNormalGapCm'], .07)
        self.assertLess(negative['maximumDeltaDegrees'], positive['maximumDeltaDegrees'])

    def test_selected_row_skinning_is_cached_and_preserves_row_order(self):
        pose = SurfacePose(hand_sample())
        rotations = {'finger': [0, 0, math.sin(.2), math.cos(.2)]}
        expected = pose.skin(rotations)
        np.testing.assert_allclose(pose.skin(rotations, [2, 0, 2]), expected[[2, 0, 2]], atol=1e-12)
        np.testing.assert_allclose(pose.skin(rotations, [1]), expected[[1]], atol=1e-12)
        self.assertLess(len(pose.row_skin_cache[(1,)][0]), len(pose.weights))
        cached = pose.row_skin_cache[(1,)]
        pose.skin(rotations, [1])
        self.assertIs(pose.row_skin_cache[(1,)], cached)

    def test_cached_triangle_query_matches_public_query(self):
        triangles = np.asarray([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=float)
        query = TriangleQuery(triangles)
        points = np.asarray([[.2, .2, .5], [1, 1, -.3]])
        expected = nearest_triangles(points, triangles)
        for actual, target in zip(query.nearest(points), expected):
            np.testing.assert_allclose(actual, target, atol=1e-12)

    def test_clearance_protects_an_unselected_surface_vertex(self):
        data = hand_sample()
        data['vertices'].append({'id': 40, 'selected': True, 'position': [2, .5, 0], 'bindPosition': [2, .5, 0], 'weights': [[1, 1.0]]})
        weapon = weapon_sample()
        cube = GripSolidAuditTests().cube()*[.3, .25, .3]+[1.5, 1.05, 0]
        for index, point in enumerate(cube.reshape(-1, 3)):
            weapon['vertices'].append({'id': 1000+index, 'position': point.tolist()})
        for index in range(len(cube)):
            weapon['triangles'].append({'id': 200+index, 'vertices': [1000+index*3, 1001+index*3, 1002+index*3]})
        configuration = fit_configuration()
        configuration['regularization'] = 0
        configuration['maximum_delta_degrees'] = 45
        configuration['steps_degrees'] = [10, 3, 1, .2]
        configuration['contacts'][0]['vertex_ids'] = [10]
        unconstrained = fit_pose(data, weapon, configuration)
        request = configuration['contacts'][0]
        request['clearance_vertex_ids'] = [40]
        request['clearance_weapon_triangle_ids'] = list(range(200, 212))
        request['clearance_weight'] = 30
        protected = fit_pose(data, weapon, configuration)
        self.assertGreater(unconstrained['independentClosedComponentAudit']['after']['insideClosedComponentPointCount'],
                           protected['independentClosedComponentAudit']['after']['insideClosedComponentPointCount'])
        self.assertEqual(protected['contacts'][0]['clearanceAudit']['after']['sampleCount'], 1)
        self.assertTrue(protected['contacts'][0]['clearanceAudit']['finalStateRecomputed'])

    def test_clearance_configuration_requires_both_explicit_regions(self):
        configuration = fit_configuration()
        configuration['contacts'][0]['clearance_vertex_ids'] = [10]
        with self.assertRaisesRegex(ValueError, '清除约束'):
            fit_pose(hand_sample(), weapon_sample(), configuration)
        configuration['contacts'][0]['clearance_weapon_triangle_ids'] = [101, 102]
        with self.assertRaisesRegex(ValueError, '完整闭合'):
            fit_pose(hand_sample(), weapon_sample(), configuration)


class GripSolidAuditTests(unittest.TestCase):
    def cube(self):
        vertices = np.asarray([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                               [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=float)
        faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                 [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]]
        return vertices[np.asarray(faces)]

    def test_welded_closed_shell_classifies_inside_outside_and_boundary(self):
        audit = WeldedSolidSurface(self.cube()).audit(np.asarray([[0, 0, 0], [2, 0, 0], [1, 0, 0]]), [10, 20, 30])
        self.assertEqual(audit['closedComponentCount'], 1)
        self.assertEqual(audit['insideClosedComponentVertexIds'], [10])
        self.assertEqual(audit['surfaceBoundaryPointCount'], 1)
        self.assertEqual(audit['wholeSurfaceCoverage'], 'closed_components_only')
        self.assertFalse(audit['wholeWeaponSolidPenetrationProven'])

    def test_open_and_non_manifold_components_are_inconclusive(self):
        for triangles in (self.cube()[:-1], np.concatenate([self.cube(), self.cube()[:1]])):
            audit = WeldedSolidSurface(triangles).audit(np.asarray([[0, 0, 0]]))
            self.assertEqual(audit['closedComponentCount'], 0)
            self.assertEqual(audit['openOrNonManifoldComponentCount'], 1)
            self.assertIn('inconclusive', audit['wholeSurfaceCoverage'])

    def test_containment_is_independent_of_triangle_winding(self):
        for triangles in (self.cube(), self.cube()[:, ::-1]):
            audit = WeldedSolidSurface(triangles).audit(np.asarray([[0, 0, 0]]))
            self.assertEqual(audit['insideClosedComponentPointCount'], 1)
            self.assertEqual(audit['rayInconclusivePointCount'], 0)

    def test_inside_depth_is_distance_to_the_closed_component_surface(self):
        result = WeldedSolidSurface(self.cube()).audit(np.asarray([[0, 0, 0], [.6, 0, 0], [2, 0, 0]]), [10, 20, 30])
        self.assertAlmostEqual(result['insideDepthMaximumCm'], 1)
        self.assertAlmostEqual(result['insideDepthP95Cm'], .97)
        self.assertAlmostEqual(result['components'][0]['insideDepthMaximumCm'], 1)
        self.assertEqual(result['deepestPoints'][0]['id'], 10)


if __name__ == '__main__':
    unittest.main()
