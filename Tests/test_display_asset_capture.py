import ast
import json
import math
import os
import stat
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class DisplayAssetCaptureTests(unittest.TestCase):
    """/** 验证特效预览路径保护 参数与瞬态对象清理 */"""

    def setUp(self):
        """/** @return 隔离磁盘及引擎接口 */"""
        self.tree = ast.parse((ROOT / "Scripts/BBBDisplayAssetCaptureTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef))
        self.engine = Mock()
        self.engine.Paths.project_saved_dir.return_value = "E:/Virtual/Saved"
        namespace = {"unreal": self.engine, "json": json, "math": math, "os": os, "stat": stat, "_capture_handle": None}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "display_asset_capture", "exec"), namespace)
        self.capture = namespace["capture_niagara_asset"]

    def test_invalid_path_rejected_before_loading_asset(self):
        """/** @return 非任务路径不能触及资产或世界 */"""
        for path in ["image.png", "../image.png", "task/../image.png", "E:/image.png", "/image.png", "task/image.exr"]:
            with self.assertRaises(RuntimeError):
                self.capture("System", 0.1, [100, 0, 0], path)
        self.engine.load_asset.assert_not_called()

    def test_invalid_age_and_camera_rejected(self):
        """/** @return 无效模拟时间与观察点不进入引擎 */"""
        for age in [-1, float("nan"), float("inf"), 6]:
            with self.assertRaises(RuntimeError):
                self.capture("System", age, [100, 0, 0], "task/image.png")
        for camera in [[0, 0, 0], [10, 0], [float("nan"), 0, 0]]:
            with self.assertRaises(RuntimeError):
                self.capture("System", 0.1, camera, "task/image.png")
        self.engine.load_asset.assert_not_called()

    def test_junction_rejected(self):
        """/** @return 输出目录不能跳转到其它位置 */"""
        with patch.object(os.path, "lexists", return_value=True), patch.object(os.path, "islink", return_value=False), patch.object(os, "lstat", return_value=Mock(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            with self.assertRaises(RuntimeError):
                self.capture("System", 0.1, [100, 0, 0], "task/image.png")
        self.engine.load_asset.assert_not_called()

    def test_existing_file_rejected(self):
        """/** @return 既有图像不被覆盖 */"""
        with patch.object(os.path, "lexists", side_effect=[False, True]):
            with self.assertRaises(RuntimeError):
                self.capture("System", 0.1, [100, 0, 0], "task/image.png")
        self.engine.load_asset.assert_not_called()

    def test_preview_is_transient_and_cleaned_in_finally(self):
        """/** @return 预览不保存源资产或关卡 */"""
        text = ast.unparse(self.tree)
        self.assertIn("spawn_transient_pie_actor", text)
        self.assertIn("set_desired_age", text)
        self.assertIn("unregister_slate_post_tick_callback", text)
        self.assertIn("preview.destroy_actor()", text)
        self.assertIn("finally:", text)
        self.assertIn("actor.destroy_actor()", text)
        self.assertNotIn("save_loaded_asset", text)
        self.assertNotIn("save_current_level", text)


if __name__ == "__main__":
    unittest.main()
