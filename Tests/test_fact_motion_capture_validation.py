import ast
import json
import math
from pathlib import Path
import unittest


class FactMotionCaptureValidationTests(unittest.TestCase):
    """/** 验证跨帧采样输入边界 避免无效时长和非有限数据进入引擎 */"""

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'Scripts' / 'BBBFactAnimationCaptureTools.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_validate_segments')
        namespace = {'json': json, 'math': math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        cls.validate = staticmethod(namespace['_validate_segments'])

    def test_accepts_real_motion_and_death_schedule(self):
        schedule = [{'duration': 1, 'behavior': 3, 'speed': 180, 'cycle_seconds': 0.766667, 'style': 2},
                    {'duration': 1.7, 'behavior': 5, 'crawling': True, 'action_start': 0, 'action_end': 1}]
        self.assertEqual(self.validate(json.dumps(schedule)), schedule)

    def test_rejects_unbounded_or_nonfinite_capture(self):
        for schedule in ([{'duration': 0}], [{'duration': float('nan')}], [{'duration': 11}],
                         [{'duration': 9}] * 3, [{'duration': 1, 'speed': float('inf')}],
                         [{'duration': 1, 'style': 3}], [{'duration': 1, 'behavior': 6}],
                         [{'duration': 1, 'action_end': 1.1}], [{'duration': 1, 'cycle_seconds': 0}],
                         [{'duration': 1, 'end_cycle_seconds': 0}], [{'duration': 1, 'action_id': 0}],
                         [{'duration': 1, 'style': 0}, {'duration': 1, 'style': 1}],
                         [{'duration': 1, 'unknown': 1}], []):
            with self.subTest(schedule=schedule), self.assertRaises(RuntimeError):
                self.validate(json.dumps(schedule))


if __name__ == '__main__':
    unittest.main()
