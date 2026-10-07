import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class SoundAssetAuditTests(unittest.TestCase):
    """/** 声音只读审计和导出路径边界回归 */"""

    def setUp(self):
        """/** @return 隔离的引擎替身及自清理测试目录 */"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = Mock()
        self.engine.Paths.project_saved_dir.return_value = str(self.root / "Saved")
        self.engine.Paths.convert_relative_path_to_full.side_effect = lambda value: value
        self.engine.SoundWave = type("SoundWave", (), {})
        self.engine.SoundCue = type("SoundCue", (), {})
        self.engine.Array = list
        with patch.dict(sys.modules, {"unreal": self.engine}):
            spec = importlib.util.spec_from_file_location("sound_audit_test", ROOT / "Scripts/BBBSoundAssetAudit.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def test_invalid_and_duplicate_paths_are_rejected(self):
        """/** @return 空列表 重复包 越界和错误对象名均拒绝 */"""
        for paths in [[], ["/Engine/Sound/A"], ["/Game/Sound/../A"], ["/Game/A.B"], ["/Game/A", "/Game/A.A"], ["/Game/A"] * 257]:
            with self.assertRaises(RuntimeError):
                self.module._paths(paths)
        self.assertEqual(self.module._paths(["/Game/Audio/A.A"]), ["/Game/Audio/A"])

    def test_export_directory_rejects_escape_root_and_link(self):
        """/** @return 根目录 越界和链接阻断且不创建目录 */"""
        root = self.root / "Saved/temp"
        for path in ["relative", str(root), str(self.root / "outside"), str(root / "../Escape")]:
            with self.assertRaises(RuntimeError):
                self.module._directory(path)
        root.mkdir(parents=True)
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(RuntimeError):
                self.module._directory(str(root / "Audit"))
        self.assertFalse((root / "Audit").exists())

    def test_export_preflights_entire_batch_and_preserves_existing_file(self):
        """/** @return 后续错误不会产生首项输出且已有文件不覆盖 */"""
        directory = self.root / "Saved/temp/Audit"
        wave_asset = self.engine.SoundWave()
        wave_asset.get_name = lambda: "A"
        self.engine.EditorAssetLibrary.load_asset.side_effect = [wave_asset, object()]
        with self.assertRaises(RuntimeError):
            self.module.export_waves(["/Game/A", "/Game/B"], str(directory))
        self.assertFalse(directory.exists())
        directory.mkdir(parents=True)
        existing = directory / "A.wav"
        existing.write_bytes(b"unchanged")
        self.engine.EditorAssetLibrary.load_asset.side_effect = None
        self.engine.EditorAssetLibrary.load_asset.return_value = wave_asset
        with self.assertRaises(RuntimeError):
            self.module.export_waves(["/Game/A"], str(directory))
        self.assertEqual(existing.read_bytes(), b"unchanged")
        self.engine.Exporter.run_asset_export_task.assert_not_called()
        self.engine.EditorAssetLibrary.save_asset.assert_not_called()

    def test_same_filename_and_missing_asset_are_rejected(self):
        """/** @return 不同包同名输出及缺失声音拒绝 */"""
        asset = self.engine.SoundWave()
        asset.get_name = lambda: "Same"
        self.engine.EditorAssetLibrary.load_asset.return_value = asset
        directory = self.root / "Saved/temp/Audit"
        with self.assertRaises(RuntimeError):
            self.module.export_waves(["/Game/One/Same", "/Game/Two/Same"], str(directory))
        self.assertFalse(directory.exists())
        self.engine.EditorAssetLibrary.load_asset.return_value = None
        with self.assertRaises(RuntimeError):
            self.module.inspect_sounds(["/Game/Missing"])

    def test_unavailable_properties_are_not_reported_as_defaults(self):
        """/** @return 属性读取失败显式返回原因而不是假值 */"""
        target = types.SimpleNamespace(get_editor_property=Mock(side_effect=RuntimeError("unavailable")))
        result = self.module._properties(target, ["duration"])
        self.assertEqual(result["values"], {})
        self.assertEqual(result["unavailable"], {"duration": "unavailable"})


if __name__ == "__main__":
    unittest.main()
