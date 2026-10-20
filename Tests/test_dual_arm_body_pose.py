import ast
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))
from BBBMcpCapabilities import tool_contract, validate_arguments


def helpers():
    """/** @return 不加载编辑器的纯边界函数 */"""
    tree = ast.parse((ROOT / 'Scripts/BBBDualArmBodyPoseTools.py').read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('_scope', '_smooth', '_weight')]
    namespace = {'json': json}
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<dual_arm_boundaries>', 'exec'), namespace)
    return namespace


class DualArmBodyPoseTests(unittest.TestCase):
    """/** 双臂制作的写入边界与离手时段约束 */"""

    def test_exact_asset_scope_rejects_extra_target(self):
        functions = helpers()
        with self.assertRaisesRegex(RuntimeError, 'BODY_POSE_WRITE_SCOPE'):
            functions['_scope'](['/Game/A', '/Game/B'], ['/Game/A'])
        with self.assertRaisesRegex(RuntimeError, 'BODY_POSE_WRITE_SCOPE'):
            functions['_scope']([], ['/Game/A'])

    def test_reload_middle_is_not_replaced_by_hold(self):
        weight = helpers()['_weight']
        job = {'role': 'action'}
        self.assertEqual(weight(job, 0, 2), 1)
        for time in (0.2, 0.5, 1.0, 1.5):
            self.assertEqual(weight(job, time, 2), 0)
        self.assertEqual(weight(job, 2, 2), 1)

    def test_equip_start_retains_source_and_exit_is_smooth(self):
        weight = helpers()['_weight']
        job = {'role': 'action', 'equip': True}
        self.assertEqual(weight(job, 0, 1.4), 0)
        self.assertAlmostEqual(weight(job, 1, 1.4), 0)
        self.assertAlmostEqual(weight(job, 1.2, 1.4), 0.5)
        self.assertEqual(weight(job, 1.4, 1.4), 1)
        self.assertLess(weight(job, 1.00001, 1.4), 0.000001)
        self.assertLess(1 - weight(job, 1.39999, 1.4), 0.000001)

    def test_public_contract_requires_explicit_targets(self):
        baseline = json.loads((ROOT / 'Tests/tool_schema_baseline.json').read_text(encoding='utf-8-sig'))
        schema = baseline['BBBControlRigAuthoringToolset']['process_dual_arm_body_pose']['inputSchema']
        contract = tool_contract('BBBControlRigAuthoringToolset', 'process_dual_arm_body_pose', schema)
        self.assertEqual(contract['scope']['fields'], ['write_paths'])
        self.assertEqual(contract['world'], 'editor')
        self.assertEqual(contract['completion'], 'verified_save')
        validate_arguments({'recipe_path': 'source', 'action': 'finalize', 'write_paths': ['/Game/A']}, contract['parameters'])
        with self.assertRaises(Exception):
            validate_arguments({'recipe_path': 'source', 'action': 'finalize'}, contract['parameters'])


if __name__ == '__main__':
    unittest.main()
