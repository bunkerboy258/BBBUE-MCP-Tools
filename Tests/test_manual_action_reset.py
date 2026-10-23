import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class ResetNeutralTests(unittest.TestCase):
    def test_position_edits_do_not_hide_finger_changes(self):
        path = Path(__file__).resolve().parents[1] / 'Scripts/BBBManualActionNative.py'
        node = next(node for node in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(node, ast.FunctionDef) and node.name == '_finger_channel_digest')
        values = {'hand_l_ik_ctrl.Location.X': 1.0, 'fk_thumb_01_l.Rotation.X': 2.0}
        channels = [SimpleNamespace(channel_name=name, get_keys=lambda: [], has_default=lambda: True,
                                   get_default=lambda name=name: values[name]) for name in values]
        sequence = SimpleNamespace(get_bindings=lambda: [SimpleNamespace(get_tracks=lambda: [
            SimpleNamespace(get_sections=lambda: [SimpleNamespace(get_all_channels=lambda: channels)])])])
        scope = {'hashlib': hashlib, 'json': json}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
        digest = scope['_finger_channel_digest']
        original = digest(sequence)
        values['hand_l_ik_ctrl.Location.X'] = 10.0
        self.assertEqual(original, digest(sequence))
        values['fk_thumb_01_l.Rotation.X'] = 20.0
        self.assertNotEqual(original, digest(sequence))

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
