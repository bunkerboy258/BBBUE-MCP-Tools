import ast
import json
import math
import os
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class StaticMeshReimportTests(unittest.TestCase):
    """/** 静态网格原位导入的前置边界 不执行编辑器写入 */"""

    def setUp(self):
        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "reimport_static_mesh")
        function.decorator_list = []
        self.engine = Mock()
        self.access = Mock()
        policy = types.ModuleType("BBBAssetWritePolicy")
        policy.require_write_access = self.access
        self.modules = patch.dict(sys.modules, {"BBBAssetWritePolicy": policy})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.scope = {"unreal": self.engine, "json": json, "math": math, "os": os, "re": re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "static_reimport_test", "exec"), self.scope)
        self.call = self.scope["reimport_static_mesh"]

    def test_third_party_rejected_before_loading(self):
        with self.assertRaises(RuntimeError):
            self.call("/Game/_ThirdParty/Original", "Source.fbx")
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_relative_source_rejected_before_loading(self):
        with self.assertRaises(RuntimeError):
            self.call("/Game/_Project/Part", "Source.fbx")
        self.engine.load_asset.assert_not_called()

    def test_pie_rejected_before_loading(self):
        with patch("os.path.isabs", return_value=True), patch("os.path.isfile", return_value=True):
            self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
            with self.assertRaises(RuntimeError):
                self.call("/Game/_Project/Part", "Source.fbx")
        self.engine.load_asset.assert_not_called()

    def test_dirty_target_rejected_before_write(self):
        class Mesh:
            def get_outermost(self):
                return self

            def get_path_name(self):
                return "/Game/_Project/Part"

        mesh = Mesh()
        self.engine.StaticMesh = Mesh
        self.engine.load_asset.return_value = mesh
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [mesh]
        with patch("os.path.isabs", return_value=True), patch("os.path.isfile", return_value=True):
            with self.assertRaises(RuntimeError):
                self.call("/Game/_Project/Part", "Source.fbx")
        self.access.assert_not_called()


if __name__ == "__main__":
    unittest.main()
