import ast
import json
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class PIEAudioRecordingTests(unittest.TestCase):
    """/** 游戏输出录音边界和异步结果语义回归 */"""

    def setUp(self):
        """/** @return 隔离引擎替身和工具函数作用域 */"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = Mock()
        self.engine.SystemLibrary.get_command_line.return_value = ""
        self.world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.Paths.project_saved_dir.return_value = str(self.root)
        self.engine.Paths.convert_relative_path_to_full.side_effect = lambda path: path
        self.namespace = {"unreal": self.engine, "json": json, "os": os, "re": re, "_pie_audio_capture": None}
        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name in {"start_pie_audio_recording", "finish_pie_audio_recording"}]
        for node in methods:
            node.decorator_list = []
        exec(compile(ast.Module(body=methods, type_ignores=[]), "audio_recording", "exec"), self.namespace)
        self.helper = types.SimpleNamespace(_directory=Path)

    def test_prefix_and_missing_pie_rejected_before_recording(self):
        """/** @return 空值 越界和无 PIE 不启动音频录制 */"""
        for prefix in ["", "../Escape", "A/B/C", "A/../B", "A\\B"]:
            with self.assertRaises(RuntimeError):
                with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
                    self.namespace["start_pie_audio_recording"](prefix)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
                self.namespace["start_pie_audio_recording"]("Task/Clip")
        self.engine.AudioMixerLibrary.start_recording_output.assert_not_called()

    def test_no_overwrite_and_only_one_active_recording(self):
        """/** @return 文件不覆盖且同时只接受一个录音 */"""
        directory = self.root / "temp/Task"
        directory.mkdir(parents=True)
        (directory / "Existing.wav").write_bytes(b"unchanged")
        with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
            with self.assertRaises(RuntimeError):
                self.namespace["start_pie_audio_recording"]("Task/Existing")
            self.namespace["start_pie_audio_recording"]("Task/New")
            with self.assertRaises(RuntimeError):
                self.namespace["start_pie_audio_recording"]("Task/Another")
        self.assertEqual((directory / "Existing.wav").read_bytes(), b"unchanged")
        self.engine.AudioMixerLibrary.start_recording_output.assert_called_once()

    def test_no_sound_host_is_rejected(self):
        """/** @return 禁用声音的宿主不进入录音状态 */"""
        self.engine.SystemLibrary.get_command_line.return_value = "-NoSound -NullRHI"
        with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
            with self.assertRaises(RuntimeError):
                self.namespace["start_pie_audio_recording"]("Task/Clip")
        self.assertIsNone(self.namespace["_pie_audio_capture"])
        self.engine.AudioMixerLibrary.start_recording_output.assert_not_called()

    def test_finish_only_requests_export_and_rejects_world_change(self):
        """/** @return 异步导出不冒充成功且世界改变不继续写入 */"""
        with self.assertRaises(RuntimeError):
            self.namespace["finish_pie_audio_recording"]()
        with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
            self.namespace["start_pie_audio_recording"]("Task/Clip")
        result = json.loads(self.namespace["finish_pie_audio_recording"]())
        self.assertTrue(result["export_requested"])
        self.assertNotIn("success", result)
        self.assertFalse(Path(result["file"]).exists())
        self.assertIsNone(self.namespace["_pie_audio_capture"])
        with patch.dict("sys.modules", {"BBBSoundAssetAudit": self.helper}):
            self.namespace["start_pie_audio_recording"]("Task/Other")
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.namespace["finish_pie_audio_recording"]()
        self.assertIsNone(self.namespace["_pie_audio_capture"])
        self.engine.AudioMixerLibrary.stop_recording_output.assert_called_once()


if __name__ == "__main__":
    unittest.main()
