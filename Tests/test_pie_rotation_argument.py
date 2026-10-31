import ast
import math
from pathlib import Path
import types
import unittest


class PieRotationArgumentTests(unittest.TestCase):
    """/** 固定外部旋转参数的俯仰 偏航 滚转语义 */"""

    def test_named_rotation_axes(self):
        """/** @return 使用关键字绑定真实轴序 不依赖引擎结构体的位置参数次序 */"""
        source = Path(__file__).resolve().parents[1] / 'Scripts/BBBGenericEditorToolset.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_function_argument')
        namespace = {'math': math, 'unreal': types.SimpleNamespace(Rotator=lambda *, pitch, yaw, roll: (pitch, yaw, roll))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        self.assertEqual(namespace['_function_argument']({'$rotator': [-15, 30, 7]}), (-15, 30, 7))
        with self.assertRaises(RuntimeError):
            namespace['_function_argument']({'$rotator': [float('nan'), 0, 0]})


if __name__ == '__main__':
    unittest.main()
