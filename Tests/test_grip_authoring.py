import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))
from BBBGripAuthoring import arm_pose, bounded_search, canonical_digest, contact_pad_audit, matrix_quaternion, matrix_values, quaternion_angle_degrees, runtime_geometry
from BBBGripFingerConstraints import triangle_pair_metrics
from BBBGripPoseFitting import SurfacePose, TriangleQuery, rotation_matrix, transform_matrix
import BBBMcpCapabilities as capabilities


IDENTITY = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]


def module_functions():
    """/** @return 不依赖编辑器的真实协议函数 */"""
    source = ROOT / 'Scripts/BBBGripAuthoringToolset.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'_digest', '_safe_file', '_write_recipe', '_response', '_recipe'}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    import hashlib
    import math
    import os
    import re
    import uuid
    fingers = tuple(f'{finger}_{joint:02}_{side}' for side in ('l', 'r') for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3))
    namespace = {'Path': Path, 'hashlib': hashlib, 'json': json, 'math': math, 'os': os, 're': re, 'uuid': uuid, '_FORMAT': 'BBBGripAuthoring', '_FINGERS': fingers}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


def arm_sample():
    """/** @return 单位骨长的可解析弯曲左臂样本 */"""
    bones = []
    for name, parent, position in [('hand_r', -1, [0, 0, 0]), ('upperarm_l', 0, [0, 0, 0]),
                                   ('lowerarm_l', 1, [1, 0, 0]), ('hand_l', 2, [0, 1, 0])]:
        local = position + IDENTITY[3:]
        component = transform_matrix(local)
        if parent >= 0:
            component = transform_matrix(bones[parent]['component']) @ component
        bones.append({'name': name, 'parent': parent, 'local': local, 'referenceLocal': local,
                      'component': matrix_values(component), 'inverseBindMatrix': np.linalg.inv(component).T.flatten().tolist()})
    return {'bones': bones, 'vertices': [{'id': 10, 'bindPosition': [1, 1, 0], 'position': [1, 1, 0], 'weights': [[3, 1]], 'selected': True}],
            'triangles': []}


class GripAuthoringMathTests(unittest.TestCase):
    def test_contact_on_one_phalanx_does_not_approve_a_detached_distal_pad(self):
        surface = types.SimpleNamespace(ids={10: 0, 11: 1, 20: 2, 21: 3},
                                        names={'middle_02_r': 0, 'middle_03_r': 1},
                                        data={'vertices': [{'weights': [[0, 1]]}, {'weights': [[0, 1]]},
                                                           {'weights': [[1, 1]]}, {'weights': [[1, 1]]}]})
        points = np.asarray([[1, 1, .05], [2, 1, .08], [1, 2, .8], [2, 2, .9]])
        query = TriangleQuery(np.asarray([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]], dtype=float))
        request = {'bones': ['middle_02_r', 'middle_03_r'], 'minimum_pad_contact_vertices': 2,
                   'pad_contact_distance_cm': .2, 'pad_groups': {'middle_02_r': [10, 11], 'middle_03_r': [20, 21]}}
        reports = contact_pad_audit(surface, points, query, request)
        self.assertTrue(reports[0]['passed'])
        self.assertFalse(reports[1]['passed'])
        self.assertEqual(reports[1]['nearContactVertexCount'], 0)
        request['pad_groups']['middle_03_r'] = [10, 11]
        with self.assertRaisesRegex(ValueError, '权重'):
            contact_pad_audit(surface, points, query, request)

    def test_rotation_comparison_normalizes_float_storage_and_quaternion_sign(self):
        original = np.asarray([0, -.9357631206512451, 0, .3526292145252228])
        self.assertLess(quaternion_angle_degrees(original, original * (1 - 1e-7)), .00001)
        self.assertLess(quaternion_angle_degrees(original, -original), .00001)
        half_angle = np.deg2rad(1) / 2
        self.assertAlmostEqual(quaternion_angle_degrees([0, 0, 0, 1], [0, np.sin(half_angle), 0, np.cos(half_angle)]), 1, places=8)
        with self.assertRaises(ValueError):
            quaternion_angle_degrees([0, 0, 0, 0], original)

    def test_quaternion_round_trip_handles_half_turn_and_sign(self):
        for quaternion in ([1, 0, 0, 0], [0, -1, 0, 0], [.5, .5, .5, .5], [0, 0, 0, -1]):
            matrix = rotation_matrix(quaternion)
            np.testing.assert_allclose(rotation_matrix(matrix_quaternion(matrix)), matrix, atol=1e-12)

    def test_coplanar_separated_triangles_are_not_intersections(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]], dtype=float)
        second = np.array([[[1.5, 1.5, 0], [2, 1.5, 0], [1.5, 2, 0]]])
        result = triangle_pair_metrics(first, second)
        self.assertEqual(result['intersectionPairCount'], 0)
        self.assertAlmostEqual(result['minimumSurfaceGapCm'], np.sqrt(.5), places=10)

    def test_edge_only_crossing_is_detected_without_contained_vertices(self):
        first = np.array([[[-2, -.1, 0], [2, -.1, 0], [0, .1, 0]]])
        second = np.array([[[-.1, -2, 0], [.1, 2, 0], [.1, -2, 0]]])
        result = triangle_pair_metrics(first, second)
        self.assertEqual(result['intersectionPairCount'], 1)
        self.assertEqual(result['minimumSurfaceGapCm'], 0)

    def test_skew_edge_distance_is_not_vertex_distance(self):
        first = np.array([[[-2, 0, 0], [2, 0, 0], [2, -2, 0]]])
        second = np.array([[[0, -2, .3], [0, 2, .3], [-2, 2, .3]]])
        result = triangle_pair_metrics(first, second)
        self.assertEqual(result['intersectionPairCount'], 0)
        self.assertAlmostEqual(result['minimumSurfaceGapCm'], .3, places=10)

    def test_non_coplanar_crossing_and_degenerate_rejection(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]])
        second = np.array([[[.3, .3, -1], [.3, .3, 1], [1, 1, 0]]])
        self.assertEqual(triangle_pair_metrics(first, second)['intersectionPairCount'], 1)
        with self.assertRaisesRegex(ValueError, '退化'):
            triangle_pair_metrics(first, np.zeros((1, 3, 3)))

    def test_bounded_search_respects_asymmetric_limits(self):
        values, score = bounded_search([0, 0, 0], [[-1, 2], [-2, 1], [0, 0]], [1, .1],
                                       lambda value: float(np.sum((value - [4, -4, 3]) ** 2)))
        np.testing.assert_allclose(values, [2, -2, 0], atol=1e-12)
        self.assertAlmostEqual(score, 17)

    def test_analytic_arm_hits_target_without_changing_local_translation(self):
        surface = SurfacePose(arm_sample())
        target = np.eye(4)
        target[:3, 3] = [.8, .9, .4]
        local = arm_pose(surface, target, {})
        components = surface.components(local)
        np.testing.assert_allclose(components[3], target, atol=1e-12)
        np.testing.assert_allclose(local[:, :3, 3], surface.locals[:, :3, 3], atol=1e-12)
        with self.assertRaisesRegex(ValueError, '可达'):
            target[:3, 3] = [10, 0, 0]
            arm_pose(surface, target, {})

    def test_socket_parent_and_right_hand_offset_order_are_preserved(self):
        surface = SurfacePose(arm_sample())
        angle = np.sqrt(.5)
        context = {'attachment_socket': {'parent': 'hand_r', 'local': IDENTITY[:]},
                   'left_socket': {'parent': 'root_joint', 'local': [2, 0, 0] + IDENTITY[3:]}}
        weapon = {'bones': [{'name': 'root_joint', 'component': [0, 0, 0, 0, 0, angle, angle, 1, 1, 1]}]}
        calibration = {'spawn_offset': [3, 0, 0] + IDENTITY[3:], 'left_ik_offset': [1, 2, 3], 'left_ik_rotation': [0, 0, 0, 1]}
        matrix, target = runtime_geometry(surface, weapon, context, calibration)
        np.testing.assert_allclose(target[:3, 3], [4, 4, 3], atol=1e-12)
        np.testing.assert_allclose(target[:3, :3], rotation_matrix([0, 0, angle, angle]), atol=1e-12)

    def test_real_key_readback_includes_non_identity_control_offsets(self):
        from BBBGripAuthoring import audit

        character = arm_sample()
        local = {bone['name']: bone['local'] for bone in character['bones']}
        component = {bone['name']: bone['component'] for bone in character['bones']}
        offset = [10, -4, 2, 0, 0, np.sqrt(.5), np.sqrt(.5), 1, 1, 1]
        keys = []
        offsets = {}
        for name, desired in component.items():
            control = 'pose_' + name
            values = matrix_values(np.linalg.inv(transform_matrix(offset)) @ transform_matrix(desired))
            offsets[control] = {'position': offset[:3], 'rotation': offset[3:7], 'scale': offset[7:10]}
            for frame in (0, 1):
                keys.append({'control': control, 'frame': frame, 'value': {'position': values[:3], 'rotation': values[3:7], 'scale': values[7:10]}})
        calibration = {'spawn_offset': IDENTITY[:], 'left_ik_offset': [0, 0, 0], 'left_ik_rotation': [0, 0, 0, 1]}
        request = {'recipe': {'solution': {'calibration': calibration, 'local_pose': local, 'component_pose': component},
                              'checks': {'maximum_pose_position_error_cm': .001, 'maximum_pose_rotation_error_degrees': .02,
                                         'maximum_static_motion_cm': .001, 'maximum_wrist_error_cm': .001}},
                   'character': character, 'weapon': {}, 'context': {}, 'samples': [character] * 3,
                   'definition_calibration': calibration, 'control_keys': keys, 'control_offsets': offsets}
        with patch('BBBGripAuthoring.runtime_geometry', return_value=(np.eye(4), transform_matrix(component['hand_l']))), patch('BBBGripAuthoring.geometry_audit', return_value={'passed': True}):
            result = audit(request)
        self.assertTrue(result['passed'])
        self.assertLess(result['maximumControlPositionErrorCm'], 1e-10)
        self.assertLess(result['maximumControlRotationErrorDegrees'], 1e-5)

    def test_two_stage_palm_fit_reaches_known_plane_without_stretch(self):
        from BBBGripAuthoring import calibrate

        character = arm_sample()
        character['vertices'].append({'id': 20, 'bindPosition': [0, 0, 0], 'position': [0, 0, 0], 'weights': [[0, 1]], 'selected': True})
        weapon = {'bones': [{'name': 'root_joint', 'component': IDENTITY[:]}],
                  'vertices': [{'id': index, 'position': position} for index, position in enumerate([[-2, .2, -2], [2, .2, -2], [-2, .2, 2], [2, .2, 2]])],
                  'triangles': [{'id': 101, 'vertices': [0, 1, 2]}, {'id': 102, 'vertices': [2, 1, 3]}]}
        context = {'attachment_socket': {'parent': 'hand_r', 'local': IDENTITY[:]},
                   'left_socket': {'parent': 'root_joint', 'local': [1, 1, 0] + IDENTITY[3:]}}
        contact = {'weapon_triangle_ids': [101, 102], 'surface_normal_sign': 1, 'target_gap_cm': .05, 'clearance_cm': .02}
        recipe = {'pose': {'local_rotations': {}}, 'calibration': {'mode': 'fit', 'spawn_offset': IDENTITY[:],
                  'left_ik_offset': [0, 0, 0], 'left_ik_rotation': [0, 0, 0, 1], 'steps_cm': [.1, .02, .005],
                  'right_palm': {**contact, 'vertex_ids': [20], 'translation_limits_weapon_cm': [[0, 0], [-.3, .3], [0, 0]]},
                  'left_palm': {**contact, 'vertex_ids': [10], 'translation_limits_weapon_cm': [[0, 0], [-1.2, 0], [0, 0]]}}}
        calibration, local, matrix, target, error = calibrate(character, weapon, context, recipe)
        self.assertAlmostEqual(calibration['spawn_offset'][1], -.15, delta=.006)
        self.assertAlmostEqual(calibration['left_ik_offset'][1], -.85, delta=.006)
        np.testing.assert_allclose(local[:, :3, 3], SurfacePose(character).locals[:, :3, 3], atol=1e-12)

    def test_elbow_bend_does_not_flip_when_target_crosses_reference_upper_arm_axis(self):
        surface = SurfacePose(arm_sample())
        elbows = []
        for offset in (-.0001, 0, .0001):
            target = np.eye(4)
            target[:3, 3] = [1, offset, 0]
            local = arm_pose(surface, target, {})
            elbows.append(surface.components(local)[surface.names['lowerarm_l'], :3, 3])
        self.assertLess(float(np.linalg.norm(elbows[0] - elbows[-1])), .001)
        self.assertTrue(all(elbow[1] < -.8 for elbow in elbows))


class GripAuthoringProtocolTests(unittest.TestCase):
    def test_six_renamed_copies_of_one_neighbor_do_not_hide_missing_finger_pairs(self):
        functions = module_functions()
        root = '/Game/_Project/Items/Rifle01'
        recipe = {'format': 'BBBGripAuthoring', 'schema': 1, 'weapon_root': root, 'definition': root + '/DA_Rifle01',
                  'character_mesh': '/Game/Mesh', 'weapon_mesh': root + '/Mesh/Weapon', 'reference_animation': '/Game/Idle',
                  'rig': root + '/Animation/work/CR_Grip', 'sequence': root + '/Animation/work/LS_Grip', 'animation': root + '/Animation/Sequence/AS_Grip',
                  'attachment_socket': 'WeaponGrip_R', 'left_socket': 'LeftHand', 'calibration': {},
                  'pose': {'local_rotations': {name: [0, 0, 0, 1] for name in functions['_FINGERS']}},
                  'fitting': {'contacts': []}, 'checks': {},
                  'neighbors': [{'name': str(index), 'first_bones': ['ring_02_r'], 'second_bones': ['pinky_02_r']} for index in range(6)]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Grip.json.source'
            path.write_text(json.dumps(recipe), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'NEIGHBOR_COVERAGE_REQUIRED'):
                functions['_recipe'](path, root)

    def execute_save(self, solver_passed, bake_passed):
        """/** @param solver_passed 求解检查结果 @param bake_passed 真实烘焙回读结果 @return 正式公共保存函数的调用顺序及当前制作状态 */"""
        source = ROOT / 'Scripts/BBBGripAuthoringToolset.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'author_weapon')
        function.decorator_list = []
        recipe = {'solution': {'passed': solver_passed, 'input_digest': 'input'}}
        calls = []

        def worker(*args, **kwargs):
            calls.append('audit')
            return {'passed': bake_passed}

        fake_unreal = types.SimpleNamespace(UnrealEditorSubsystem=object,
                                           get_editor_subsystem=lambda kind: types.SimpleNamespace(get_game_world=lambda: None),
                                           Paths=types.SimpleNamespace(project_dir=lambda: '.'))
        namespace = {'unreal': fake_unreal, 'Path': Path, 'json': json,
                     '_safe_file': lambda *args: source,
                     '_recipe': lambda *args: recipe,
                     '_inputs': lambda *args: {'digest': 'input'},
                     '_response': lambda *args: {'status': 'needs_save'},
                     '_save_assets': lambda *args: calls.append('save') or ['/Game/Grip'],
                     '_run_worker': worker,
                     '_apply_definition': lambda *args: calls.append('apply_definition') or '/Game/Definition',
                     '_fingerprint': lambda *args: 'current',
                     '_write_recipe': lambda *args: calls.append('write_recipe')}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        return lambda: namespace['author_weapon']('/Game/_Project/Items/Rifle01', 'Grip.json.source', 'save'), calls, recipe

    def test_failed_solver_cannot_write_any_asset(self):
        execute, calls, recipe = self.execute_save(False, True)
        result = json.loads(execute())
        self.assertFalse(result['assetsModified'])
        self.assertEqual(result['gate'], 'geometry_not_passed')
        self.assertEqual(calls, [])

    def test_failed_bake_readback_cannot_connect_equipment_definition(self):
        execute, calls, recipe = self.execute_save(True, False)
        execute()
        self.assertEqual(calls, ['save', 'audit', 'write_recipe'])
        self.assertFalse(recipe['validation']['passed'])

    def test_equipment_is_connected_only_after_bake_readback_then_rechecked(self):
        execute, calls, recipe = self.execute_save(True, True)
        execute()
        self.assertEqual(calls, ['save', 'audit', 'apply_definition', 'audit', 'write_recipe'])
        self.assertTrue(recipe['validation']['passed'])

    def test_recipe_path_cannot_escape_model_source_or_trigger_json_import(self):
        functions = module_functions()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = '/Game/_Project/Characters/Soldier/Items/Equipment/Rifle/Rifle_01'
            relative = 'Content/_Project/Characters/Soldier/Items/Equipment/Rifle/Rifle_01/Source/Animation/Grip.json.source'
            self.assertEqual(functions['_safe_file'](project, root, relative), project / relative)
            for value in ('../Grip.json.source', relative.removesuffix('.source'), relative.replace('Source/Animation', 'Animation/work')):
                with self.assertRaises(RuntimeError):
                    functions['_safe_file'](project, root, value)

    def test_recipe_write_is_idempotent_and_contains_no_secondary_file(self):
        functions = module_functions()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Grip.json.source'
            functions['_write_recipe'](path, {'a': [1, 2]}, Path(directory))
            before = path.stat().st_mtime_ns
            functions['_write_recipe'](path, {'a': [1, 2]}, Path(directory))
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual([item.name for item in path.parent.iterdir() if item.is_file()], [path.name])
            self.assertFalse(list((Path(directory) / 'Saved' / 'temp').iterdir()))

    def test_failed_or_changed_solution_cannot_reuse_old_acceptance(self):
        functions = module_functions()
        functions['_fingerprint'] = lambda recipe, project: 'asset'
        recipe = {'fitting': {'contacts': [1]}, 'neighbors': [1] * 6, 'solution': {'input_digest': 'input', 'passed': True},
                  'validation': {'fingerprint': 'asset', 'passed': True},
                  'review': {'fingerprint': 'asset', 'decision': 'accepted'}}
        result = functions['_response'](recipe, {'digest': 'input'}, Path('.'))
        self.assertEqual(result['status'], 'ready_for_runtime_acceptance')
        self.assertIsNone(result['next'])
        recipe['solution']['passed'] = False
        self.assertEqual(functions['_response'](recipe, {'digest': 'input'}, Path('.'))['status'], 'geometry_failed')
        self.assertEqual(functions['_response'](recipe, {'digest': 'changed'}, Path('.'))['status'], 'needs_solve')

    def test_tool_contract_scopes_writes_and_keeps_observation_read_only(self):
        schema = {'type': 'object', 'properties': {name: {'type': 'string'} for name in ('weapon_root', 'recipe_path', 'action', 'python_executable', 'review_note', 'definition_path', 'character_mesh_path', 'reference_animation_path')}}
        contract = capabilities.tool_contract('BBBGripAuthoringToolset', 'author_weapon', schema)
        self.assertEqual(contract['id'], 'grip.author_weapon')
        self.assertEqual(set(contract['parameters']['properties']['action']['enum']), {'initialize', 'inspect', 'solve', 'save', 'audit', 'review', 'accept', 'adopt'})
        for action in ('inspect', 'audit', 'review'):
            self.assertEqual(capabilities.resolve_access(contract, {'action': action}), ('read', 'editor'))
        root = '/Game/_Project/Items/Rifle01'
        self.assertEqual(capabilities.write_scope(contract, {'weapon_root': root, 'action': 'save'}), ([root], True))
        self.assertEqual(capabilities.resolve_access(contract, {'action': 'save'}), ('write', 'editor'))

    def test_digest_is_stable_for_dictionary_order_and_rejects_nan(self):
        self.assertEqual(canonical_digest({'x': 1, 'y': 2}), canonical_digest({'y': 2, 'x': 1}))
        with self.assertRaises(ValueError):
            canonical_digest({'x': float('nan')})

    def test_hand_capture_rejects_invalid_exposure_before_touching_world(self):
        source = ROOT / 'Scripts/BBBGripCaptureTools.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'start_capture')
        function.decorator_list = []
        import math
        namespace = {'math': math, 'unreal': object()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        for bias in (float('nan'), float('inf'), -6.1, 6.1):
            with self.assertRaisesRegex(RuntimeError, '曝光'):
                namespace['start_capture']('/Game/Pose', '/Game/Hands', 0, '[]', [1, 2, 3], 'Task/Hands.png', bias, 'hand_r')

    def test_capture_receipt_serializes_unreal_array_arguments_before_async_work(self):
        source = ROOT / 'Scripts/BBBGripCaptureTools.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'start_capture')
        mesh_class = type('Mesh', (), {})
        animation_class = type('Animation', (), {'get_play_length': lambda self: 1})
        class ArrayLike:
            """/** 不被JSON原生支持的编辑器数组替身 */"""
            def __iter__(self):
                return iter([1, 2, 3])

        import math
        import os
        import re
        import uuid
        with tempfile.TemporaryDirectory() as directory:
            fake = types.SimpleNamespace(SystemLibrary=types.SimpleNamespace(get_command_line=lambda: ''),
                                         UnrealEditorSubsystem=object, SkeletalMesh=mesh_class, AnimSequence=animation_class,
                                         get_editor_subsystem=lambda kind: types.SimpleNamespace(get_game_world=lambda: object()),
                                         Paths=types.SimpleNamespace(project_saved_dir=lambda: directory),
                                         load_asset=lambda path: animation_class() if path == '/Game/Pose' else mesh_class(),
                                         register_slate_post_tick_callback=lambda callback: 'handle')
            namespace = {'json': json, 'math': math, 'os': os, 're': re, 'uuid': uuid, 'Path': Path, 'unreal': fake, '_CAPTURES': {}}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
            with patch.object(capabilities, 'register_activity'):
                result = json.loads(namespace['start_capture']('/Game/Pose', '/Game/Hands', 0, '[]', ArrayLike(), 'Task/Hands.png', 1, 'hand_r'))
            self.assertEqual(result['next']['arguments']['camera_offset'], [1, 2, 3])
            self.assertEqual(result['next']['arguments']['action'], 'status')
            self.assertEqual(result['status'], 'pending')
            self.assertEqual(result['linearExposureMultiplier'], 2)


if __name__ == '__main__':
    unittest.main()
