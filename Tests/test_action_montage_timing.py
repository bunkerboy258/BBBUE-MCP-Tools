import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ActionMontageTimingTests(unittest.TestCase):
    """/** 验证单段动作时长更新保留源动画与通知时刻 */"""

    def setUp(self):
        """/** @return 蒙太奇数据模型与编辑接口替身 */"""
        tree = ast.parse((ROOT / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "retime_single_action_montage")
        method.decorator_list = []
        method.body = [node for node in method.body if not isinstance(node, ast.ImportFrom)]
        self.engine = Mock()
        self.engine.AnimMontage = Mock
        self.montage = Mock()
        self.engine.EditorAssetLibrary.load_asset.return_value = self.montage
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.montage.get_play_length.return_value = 2.2
        self.segment_data = {
            "anim_reference": object(), "start_pos": 0.0, "looping_count": 1,
            "anim_play_rate": 1.0, "anim_start_time": 0.0, "anim_end_time": 1.0}
        self.segment = Mock()
        self.segment.get_editor_property.side_effect = self.segment_data.__getitem__
        self.animation_track = Mock()
        self.animation_track.get_editor_property.return_value = [self.segment]
        self.track = Mock()
        self.track.get_editor_property.return_value = self.animation_track
        self.montage.get_editor_property.return_value = [self.track]
        self.access = Mock()
        self.inspect = Mock(return_value="saved")
        namespace = {"math": math, "unreal": self.engine, "require_write_access": self.access,
                     "BBBGenericEditorToolset": SimpleNamespace(inspect_animation_montage_segments=self.inspect)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "montage_timing", "exec"), namespace)
        self.retime = namespace[method.name]

    def test_single_action_changes_only_rate_and_data_model_duration(self):
        """/** @return 只修改播放速率与数据模型时长 不改源动画和通知 */"""
        self.assertEqual(self.retime("Montage", 2.2, 30), "saved")
        self.segment.set_editor_property.assert_called_once_with("anim_play_rate", 1.0 / 2.2)
        self.engine.FrameNumber.assert_called_once_with(value=66)
        self.engine.FrameRate.assert_called_once_with(numerator=30, denominator=1)
        self.montage.set_editor_property.assert_called_once_with("slot_anim_tracks", [self.track])
        self.access.assert_called_once_with(self.montage)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.montage, False)

    def test_multiple_segments_are_rejected_before_mutation(self):
        """/** @return 多片段不能被默默合并为单个动作 */"""
        self.animation_track.get_editor_property.return_value = [self.segment, self.segment]
        with self.assertRaises(RuntimeError):
            self.retime("Montage", 2.2, 30)
        self.access.assert_not_called()
        self.montage.modify.assert_not_called()

    def test_fractional_frame_duration_is_rejected_before_mutation(self):
        """/** @return 非整数帧时长不能进入编辑阶段 */"""
        with self.assertRaises(RuntimeError):
            self.retime("Montage", 2.21, 30)
        self.access.assert_not_called()

    def test_native_duration_mismatch_is_not_saved(self):
        """/** @return 引擎长度未正确更新时禁止保存 */"""
        self.montage.get_play_length.return_value = 1.0
        with self.assertRaises(RuntimeError):
            self.retime("Montage", 2.2, 30)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
