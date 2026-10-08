import ast
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class FontFaceImportTests(unittest.TestCase):
    """/** 永久字体导入的批次保护与内联资源回归 */"""

    def setUp(self):
        """/** @return 引擎替身与明确源路径 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBFontFaceImport.py"
        self.engine = Mock()
        self.face = Mock()
        self.face.get_path_name.return_value = "/Game/Fonts/Light.Light"
        self.engine.FontFace = Mock
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.EditorAssetLibrary.load_asset.return_value = self.face
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.engine.Paths.project_content_dir.return_value = str(source.parent / "Content")
        self.access = Mock()
        namespace = {}
        policy = types.SimpleNamespace(require_asset_write=self.access)
        with patch.dict(sys.modules, {"unreal": self.engine, "BBBAssetWritePolicy": policy}):
            exec(compile(ast.parse(source.read_text(encoding="utf-8")), str(source), "exec"), namespace)
        self.run_import = namespace["import_font_faces"]
        self.file_patch = patch("os.path.isfile", return_value=True)
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.request = {"source": str(source.parent / "Content/Fonts/Light.otf"),
                        "destination": "/Game/Fonts/Light"}

    def test_import_embeds_font_face_without_extra_font_asset(self):
        """/** @return 明确工厂 内联策略和逐项保存成立 */"""
        result = json.loads(self.run_import(json.dumps([self.request])))
        self.access.assert_called_once_with([], ["/Game/Fonts/Light"])
        self.engine.FontFileImportFactory.return_value.set_editor_property.assert_called_once_with(
            "batch_create_font_asset", self.engine.BatchCreateFontAsset.NO)
        self.face.set_editor_property.assert_called_once_with("loading_policy", self.engine.FontLoadingPolicy.INLINE)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.face, False)
        self.assertEqual(result[0]["asset"], "/Game/Fonts/Light.Light")

    def test_later_invalid_source_prevents_entire_batch(self):
        """/** @return 后续越界来源不留下前项资产 */"""
        outside = dict(self.request, source=str(Path(self.request["source"]).parents[2] / "Outside.ttf"),
                       destination="/Game/Fonts/Outside")
        with self.assertRaises(RuntimeError):
            self.run_import(json.dumps([self.request, outside]))
        self.engine.FontFileImportFactory.assert_not_called()
        self.access.assert_not_called()

    def test_existing_or_duplicate_target_never_imports(self):
        """/** @return 已有目标与重复目标均在写入前拒绝 */"""
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        with self.assertRaises(RuntimeError):
            self.run_import(json.dumps([self.request]))
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        with self.assertRaises(RuntimeError):
            self.run_import(json.dumps([self.request, self.request]))
        self.engine.FontFileImportFactory.assert_not_called()

    def test_write_denial_prevents_factory(self):
        """/** @return 版本占用保护拒绝时不创建资产 */"""
        self.access.side_effect = RuntimeError("目标被占用")
        with self.assertRaises(RuntimeError):
            self.run_import(json.dumps([self.request]))
        self.engine.FontFileImportFactory.assert_not_called()

    def test_failed_save_is_reported(self):
        """/** @return 保存失败不能伪装为已导入 */"""
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = False
        with self.assertRaises(RuntimeError):
            self.run_import(json.dumps([self.request]))


if __name__ == "__main__":
    unittest.main()
