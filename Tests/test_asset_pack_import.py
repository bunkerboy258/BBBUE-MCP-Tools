import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class AssetPackImportTests(unittest.TestCase):
    """/** ZIP 导入越界和覆盖阻断回归 */"""

    def setUp(self):
        """/** @return 创建隔离引擎替身和自清理临时目录 */"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.content = self.root / "Content"
        self.content.mkdir()
        self.engine = Mock()
        self.engine.Paths.project_content_dir.return_value = str(self.content)
        self.engine.Paths.convert_relative_path_to_full.side_effect = lambda value: value
        self.engine.AssetRegistryHelpers.get_asset_registry.return_value.get_assets_by_path.return_value = []
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.engine.EditorLoadingAndSavingUtils.get_dirty_map_packages.return_value = []
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = False
        with patch.dict(sys.modules, {"unreal": self.engine}):
            spec = importlib.util.spec_from_file_location("pack_import_test", ROOT / "Scripts/BBBAssetPackImport.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.archive = self.root / "Pack.zip"

    def write_archive(self, names):
        """
        /**
         * @param names	测试 ZIP 项
         * @return 无返回值
         */
        """
        with zipfile.ZipFile(self.archive, "w") as output:
            for name in names:
                output.writestr(name, b"fixture")

    def invoke(self):
        """/** @return 只读导入预检 */"""
        return self.module.import_archive(str(self.archive), "Bundle/Pack", "/Game/Pack", "/Game/_ThirdParty/VFX/Pack", True)

    def test_valid_manifest_is_read_only_and_preserves_original(self):
        """/** @return 清单正确且未创建内容目录 */"""
        self.write_archive(["Bundle/Pack/Hit/NS_Hit.uasset", "Bundle/Pack/Maps/Demo.umap", "Bundle/Pack/readme.txt"])
        original = self.archive.read_bytes()
        result = json.loads(self.invoke())
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(list(self.content.iterdir()), [])
        self.assertEqual(self.archive.read_bytes(), original)
        self.engine.AssetToolsHelpers.get_asset_tools.assert_not_called()

    def test_traversal_collision_and_dirty_state_are_rejected_before_extraction(self):
        """/** @return 越界 重复项 已占用目录和脏包拒绝 */"""
        for names in [["Bundle/Pack/../Escape.uasset"], ["Bundle/Pack/A.uasset", "Bundle/Pack/a.uasset"]]:
            self.write_archive(names)
            with self.assertRaises(RuntimeError):
                self.invoke()
        self.write_archive(["Bundle/Pack/A.uasset"])
        (self.content / "Pack").mkdir()
        with self.assertRaises(RuntimeError):
            self.invoke()
        (self.content / "Pack").rmdir()
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [object()]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(list(self.content.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
