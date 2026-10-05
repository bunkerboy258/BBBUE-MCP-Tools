import ast
import json
import os
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


class TextureReimportTests(unittest.TestCase):
    """/** 原位纹理导入的目标保护与失败边界 */"""

    def setUp(self):
        """/** @return 独立函数与引擎替身 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "reimport_texture")
        method.decorator_list = []
        self.texture = Mock()
        self.texture.get_outermost.return_value.get_path_name.return_value = "/Game/Test/Card"
        self.texture.get_path_name.return_value = "/Game/Test/Card.Card"
        self.texture.get_name.return_value = "Card"
        self.texture.blueprint_get_size_x.return_value = 512
        self.texture.blueprint_get_size_y.return_value = 512
        self.task = Mock()
        self.task.get_objects.return_value = [self.texture]
        self.engine = Mock()
        self.engine.Texture2D = Mock
        self.engine.load_asset.return_value = self.texture
        self.engine.AssetImportTask.return_value = self.task
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"os": os, "json": json, "unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        self.run_import = namespace["reimport_texture"]
        policy = types.SimpleNamespace(require_write_access=self.access)
        self.policy_patch = patch.dict("sys.modules", {"BBBAssetWritePolicy": policy})
        self.policy_patch.start()
        self.addCleanup(self.policy_patch.stop)
        self.file_patch = patch("os.path.isfile", return_value=True)
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.source = str(source.with_suffix(".png").resolve())

    def test_in_place_import_preserves_settings_and_saves_only_target(self):
        """/** @return 导入原路径和保留设置断言 */"""
        result = json.loads(self.run_import("/Game/Test/Card", self.source))
        self.access.assert_called_once_with(self.texture)
        self.assertEqual(result["asset"], "/Game/Test/Card.Card")
        self.assertEqual(self.task.destination_name, "Card")
        self.assertTrue(self.task.replace_existing)
        self.assertFalse(self.task.replace_existing_settings)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.texture, only_if_is_dirty=False)

    def test_dirty_target_is_rejected_before_import(self):
        """/** @return 未保存内容不得覆盖 */"""
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [self.texture.get_outermost()]
        with self.assertRaises(RuntimeError):
            self.run_import("/Game/Test/Card", self.source)
        self.engine.AssetImportTask.assert_not_called()

    def test_wrong_import_target_is_not_saved(self):
        """/** @return 不保存导入产生的意外对象 */"""
        self.task.get_objects.return_value = []
        with self.assertRaises(RuntimeError):
            self.run_import("/Game/Test/Card", self.source)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_access_failure_prevents_import(self):
        """/** @return 签出检查失败不得继续 */"""
        self.access.side_effect = RuntimeError("未签出")
        with self.assertRaises(RuntimeError):
            self.run_import("/Game/Test/Card", self.source)
        self.engine.AssetImportTask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
