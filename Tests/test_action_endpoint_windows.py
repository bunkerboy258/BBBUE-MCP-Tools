import ast
from pathlib import Path
import unittest


class EndpointWindowTests(unittest.TestCase):
    """/** @return 单侧对齐窗口与受保护接口的边界验收 */"""

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'Scripts/BBBActionRetargetTools.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_endpoint_windows')
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), 'exec'), namespace)
        cls.windows = staticmethod(namespace['_endpoint_windows'])

    def test_start_keeps_insert_interface(self):
        entry, exit_window, preserved = self.windows({'entry_frames': [0, 6], 'exit_frames': None}, 26)
        self.assertEqual(entry, [0, 6])
        self.assertIsNone(exit_window)
        self.assertEqual(list(preserved), list(range(6, 26)))

    def test_end_keeps_insert_interface(self):
        entry, exit_window, preserved = self.windows({'entry_frames': None, 'exit_frames': [3, 13]}, 18)
        self.assertIsNone(entry)
        self.assertEqual(exit_window, [3, 13])
        self.assertEqual(list(preserved), [0, 1, 2, 3])

    def test_two_windows_keep_middle(self):
        _, _, preserved = self.windows({'entry_frames': [0, 6], 'exit_frames': [36, 46]}, 51)
        self.assertEqual(list(preserved), list(range(6, 37)))

    def test_missing_endpoint_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'ENDPOINT_REQUIRED'):
            self.windows({'entry_frames': None, 'exit_frames': None}, 18)

    def test_invalid_windows_are_rejected(self):
        cases = [([1, 6], None), ([0, 26], None), (None, [3, 26]), (None, [4, 4]), ([0, 6], [6, 13])]
        for entry, exit_window in cases:
            with self.subTest(entry=entry, exit_window=exit_window):
                with self.assertRaises(RuntimeError):
                    self.windows({'entry_frames': entry, 'exit_frames': exit_window}, 26)


if __name__ == '__main__':
    unittest.main()
