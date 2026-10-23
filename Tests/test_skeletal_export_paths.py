import ast
import os
from pathlib import Path
import re
import unittest
from unittest.mock import Mock


class SkeletalExportPathTests(unittest.TestCase):
    """/** 参考网格中间文件必须支持明确任务目录 */"""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        function = next(item for item in ast.walk(tree)
                        if isinstance(item, ast.FunctionDef) and item.name == "export_skeletal_mesh_fbx")
        function.decorator_list = []
        self.engine = Mock()
        mesh_class = type("Mesh", (Mock,), {})
        self.engine.SkeletalMesh = mesh_class
        self.engine.load_asset.return_value = mesh_class()
        self.engine.load_asset.return_value.get_path_name.return_value = "/Game/_Project/Body.Body"
        skeleton = Mock()
        skeleton.get_path_name.return_value = "/Game/_Project/Skeleton.Skeleton"
        self.engine.load_asset.return_value.get_editor_property.return_value = skeleton
        self.engine.SystemLibrary.get_command_line.return_value = ""
        self.engine.EditorLevelLibrary.get_pie_worlds.return_value = []
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.Paths.project_saved_dir.return_value = "E:/BBB_Evac/Saved"
        self.engine.AnimPoseExtensions.get_reference_pose.side_effect = RuntimeError("STOP_AFTER_PATH_CHECK")
        self.files = Mock()
        self.files.path.join = os.path.join
        self.files.path.abspath = os.path.abspath
        self.files.path.exists.return_value = False
        scope = {"unreal": self.engine, "os": self.files, "re": re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "skeletal_export_test", "exec"), scope)
        self.export = scope["export_skeletal_mesh_fbx"]

    def test_task_output_is_inside_saved_temp(self):
        """/** @return 中间文件不会写进 Saved Exports */"""
        with self.assertRaisesRegex(RuntimeError, "STOP_AFTER_PATH_CHECK"):
            self.export("/Game/_Project/Body", "ConnorReference", "UnifiedZombieWounds20261023")
        expected = os.path.abspath(os.path.join("E:/BBB_Evac/Saved", "temp", "UnifiedZombieWounds20261023", "ConnorReference"))
        self.files.path.exists.assert_called_once_with(expected)
        self.files.makedirs.assert_not_called()

    def test_invalid_task_cannot_escape_workspace(self):
        """/** @return 不合法任务名不检查或创建输出 */"""
        with self.assertRaises(RuntimeError):
            self.export("/Game/_Project/Body", "ConnorReference", "../outside")
        self.files.path.exists.assert_not_called()
        self.files.makedirs.assert_not_called()
