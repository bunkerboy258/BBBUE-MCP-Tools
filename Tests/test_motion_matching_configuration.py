import ast
import collections
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "Scripts/BBBMotionMatchingToolset.py"


class MotionMatchingConfigurationTests(unittest.TestCase):
    """/** 配置迁移的写入范围 预检和引擎数组序列化回归 */"""

    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        function = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "migrate_configuration")
        function.decorator_list = []
        self.engine = Mock()
        self.engine.Blueprint = type("Blueprint", (), {})
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.EditorAssetLibrary.load_asset.return_value = object()
        self.engine.load_asset.return_value = object()
        self.engine.BBBMotionMatchingEditorLibrary.migrate_configuration.return_value = '{"created": []}'
        self.policy = Mock()
        namespace = {"unreal": self.engine, "json": json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
        self.invoke = namespace["migrate_configuration"]

    def call(self, targets, request, dry_run=True):
        policy_module = types.SimpleNamespace(require_asset_write=self.policy)
        with patch.dict("sys.modules", {"BBBAssetWritePolicy": policy_module}):
            return self.invoke("reference/Content", targets, json.dumps(request), dry_run)

    def test_incomplete_scope_rejected_before_native_or_write(self):
        with self.assertRaises(RuntimeError):
            self.call([], {"assets": [{"source": "source", "target": "/Game/_Project/New"}]})
        self.engine.BBBMotionMatchingEditorLibrary.migrate_configuration.assert_not_called()
        self.policy.assert_not_called()

    def test_duplicate_scope_rejected(self):
        with self.assertRaises(RuntimeError):
            self.call(["/Game/_Project/New"] * 2, {"assets": [{"source": "source", "target": "/Game/_Project/New"}]})

    def test_linked_layer_requires_its_own_write_scope(self):
        request = {"assets": [], "blueprint": {"target": "/Game/_Project/Main"}, "integration": {"layer": "/Game/_Project/Layer"}}
        with self.assertRaises(RuntimeError):
            self.call(["/Game/_Project/Main"], request)
        self.engine.BBBMotionMatchingEditorLibrary.migrate_configuration.assert_not_called()

    def test_native_preflight_failure_does_not_save(self):
        self.engine.BBBMotionMatchingEditorLibrary.migrate_configuration.return_value = '{"error":"missing reference"}'
        with self.assertRaisesRegex(RuntimeError, "missing reference"):
            self.call(["/Game/_Project/New"], {"assets": [{"source": "source", "target": "/Game/_Project/New"}]})
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
        self.policy.assert_not_called()

    def test_new_destinations_are_checked_and_engine_array_is_serializable(self):
        targets = collections.UserList(["/Game/_Project/New"])
        result = json.loads(self.call(targets, {"assets": [{"source": "source", "target": targets[0]}]}, False))
        self.policy.assert_called_once_with([], [targets[0]])
        self.assertEqual(result["saved"], list(targets))
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
