import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


class PIEActionTargetTests(unittest.TestCase):
    """/** 验证增强输入仅注入明确的 PIE 本地控制器 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inject_pie_action")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.PlayerController = type("Controller", (), {})
        self.controller = self.engine.PlayerController()
        self.controller.get_world = Mock(return_value="PIE")
        self.controller.is_local_controller = Mock(return_value=True)
        self.controller.get_path_name = Mock(return_value="ClientController")
        self.engine.find_object.return_value = self.controller
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = ["PIE"]
        self.asset = Mock()
        namespace = {"unreal": self.engine, "json": json, "_asset": Mock(return_value=self.asset)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "pie_action_target", "exec"), namespace)
        self.inject = namespace["inject_pie_action"]

    def test_client_controller_is_used(self):
        result = json.loads(self.inject("Fire", 1.0, "ClientController"))
        self.assertEqual(result["controller"], "ClientController")
        library = self.engine.get_default_object.return_value
        self.assertIs(library.call_method.call_args_list[0].args[1][0], self.controller)

    def test_non_controller_is_rejected(self):
        self.engine.find_object.return_value = None
        with self.assertRaises(RuntimeError):
            self.inject("Fire", 1.0, "Missing")

    def test_non_pie_world_is_rejected(self):
        self.controller.get_world.return_value = "Editor"
        with self.assertRaises(RuntimeError):
            self.inject("Fire", 1.0, "EditorController")

    def test_remote_controller_is_rejected(self):
        self.controller.is_local_controller.return_value = False
        with self.assertRaises(RuntimeError):
            self.inject("Fire", 1.0, "MirrorController")


if __name__ == "__main__":
    unittest.main()
