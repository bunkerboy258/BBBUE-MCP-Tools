import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class PIEAudioDeviceInspectionTests(unittest.TestCase):
    """/** 音频设备诊断只读当前 PIE 不修改用户设置 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_pie_audio_device")
        method.decorator_list = []
        self.engine = Mock()
        self.scope = {"unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "audio_device_test", "exec"), self.scope)

    def test_missing_pie_never_calls_native(self):
        """/** @return 不从其它世界猜测音频状态 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaisesRegex(RuntimeError, "PIE"):
            self.scope["inspect_pie_audio_device"]()
        self.engine.BBBHitReactionEditorLibrary.inspect_audio_device.assert_not_called()

    def test_current_world_readback_without_mutation(self):
        """/** @return 设备结果原样返回 不修改音频或编辑器设置 */"""
        world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = world
        self.engine.BBBHitReactionEditorLibrary.inspect_audio_device.return_value = '{"deviceMuted":true}'
        self.assertEqual(self.scope["inspect_pie_audio_device"](), '{"deviceMuted":true}')
        self.engine.BBBHitReactionEditorLibrary.inspect_audio_device.assert_called_once_with(world)
        self.engine.SystemLibrary.execute_console_command.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
