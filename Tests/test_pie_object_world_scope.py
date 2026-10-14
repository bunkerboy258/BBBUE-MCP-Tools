import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class PIEObjectWorldTests(unittest.TestCase):
    """/** 对象世界检查不能把组件强制转换成 World */"""

    def test_animation_owner_chain_without_world_cast(self):
        """/** @return 动画实例沿组件所有者链调用 不对不同类型执行 World 相等比较 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BBBGenericEditorToolset")
        function = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "invoke_pie_object_function")
        function.decorator_list = []

        class World:
            """/** 模拟 UE World 的严格原生类型比较 */"""

            def __eq__(self, other):
                """/** @param other 被比较对象 @return 相同 World 否则明确类型错误 */"""
                if not isinstance(other, World):
                    raise TypeError("只允许 World")
                return self is other

            def get_path_name(self):
                """/** @return 测试 PIE 世界路径 */"""
                return "/PIE/World"

        world = World()
        component = SimpleNamespace(get_world=lambda: world)
        target = SimpleNamespace(get_outer=lambda: component, call_method=Mock(return_value="Montage"))
        engine = SimpleNamespace(World=World, find_object=lambda *args: target,
            EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda *args: [world]), log=Mock())
        namespace = {"unreal": engine, "json": json, "re": re,
            "_serialize_value": lambda value: value, "_function_argument": lambda value: value}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "pie_object_test", "exec"), namespace)
        result = json.loads(namespace["invoke_pie_object_function"]("/PIE/Actor.Mesh.Anim", "GetCurrentActiveMontage"))
        self.assertEqual(result["world"], "/PIE/World")
        self.assertEqual(result["result"], "Montage")
        target.call_method.assert_called_once_with("GetCurrentActiveMontage", ())


if __name__ == "__main__":
    unittest.main()
