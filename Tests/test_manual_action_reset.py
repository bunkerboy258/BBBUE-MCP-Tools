import ast
from pathlib import Path
import unittest


class ResetNeutralTests(unittest.TestCase):
    def test_native_additive_scale_is_zero_increment(self):
        path = Path(__file__).resolve().parents[1] / 'Scripts/BBBManualActionReset.py'
        node = next(node for node in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'neutral_value')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
        neutral = scope['neutral_value']
        for axis in ('X', 'Y', 'Z'):
            self.assertEqual(neutral('source_spine_01.Scale.' + axis, False), 0.0)
            self.assertEqual(neutral('source_spine_01.Scale.' + axis, True), 1.0)
        for kind in ('Location', 'Rotation'):
            self.assertEqual(neutral('hand_l_ik_ctrl.' + kind + '.X', False), 0.0)
            self.assertEqual(neutral('hand_l_ik_ctrl.' + kind + '.X', True), 0.0)


if __name__ == '__main__':
    unittest.main()
