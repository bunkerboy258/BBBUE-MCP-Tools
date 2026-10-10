import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ActionTimingTests(unittest.TestCase):
    """/** 验证机构重映射只改变时间并完整保留骨骼变换 */"""

    def setUp(self):
        """/** @return 不依赖编辑器的官方接口替身 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "remap_animation_bone_times")
        method.decorator_list = []
        self.engine = Mock()
        self.animation = Mock()
        self.animation.get_play_length.return_value = 1.0
        self.animation.data_model_interface.get_bone_track_names.return_value = ["root", "Magazine_joint"]
        self.engine.AnimationLibrary.get_animation_notify_events.return_value = []
        self.engine.AnimationLibrary.get_animation_curve_names.return_value = []
        self.source = Mock()
        self.source.get_play_length.return_value = 1.0
        self.source.data_model_interface.get_bone_track_names.return_value = ["root", "Magazine_joint"]
        self.engine.AnimPoseExtensions.get_bone_pose.side_effect = lambda pose, name, space: SimpleNamespace(translation=pose, rotation=name, scale3d=1)
        self.animation.controller.set_number_of_frames.side_effect = lambda value, transact: self.animation.get_play_length.configure_mock(return_value=2.0)
        self.pose = Mock(side_effect=lambda animation, mesh, time: time)
        self.access = Mock()
        namespace = {"json": json, "math": math, "unreal": self.engine,
                     "_asset": lambda path, kind: self.source if path == "Source" else self.animation, "_pose": self.pose,
                     "require_write_access": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "action_timing", "exec"), namespace)
        self.remap = namespace[method.name]

    def test_magazine_seats_at_handoff_and_other_tracks_stay_linear(self):
        """/** @return 弹匣装入后保持原最终姿势 其它机构仍完整播放 */"""
        self.remap("Animation", "Mesh", 2.0, 10,
                   json.dumps({"magazine_joint": [[0, 0], [0.5, 0.5], [1.2, 1], [2, 1]]}), "Source")
        writes = self.animation.controller.set_bone_track_keys.call_args_list
        self.assertEqual(writes[0].args[0], "root")
        self.assertAlmostEqual(writes[0].args[1][10], 0.5)
        self.assertEqual(writes[1].args[1][12:], [1.0] * 9)
        self.assertEqual(writes[1].args[2], ["Magazine_joint"] * 21)
        self.animation.controller.close_bracket.assert_called_once()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once()

    def test_incomplete_mapping_is_rejected_before_write(self):
        """/** @return 不完整范围不能破坏现有机构动画 */"""
        with self.assertRaises(RuntimeError):
            self.remap("Animation", "Mesh", 2.0, 10,
                       json.dumps({"magazine_joint": [[0.1, 0], [2, 1]]}), "Source")
        self.access.assert_not_called()
        self.pose.assert_not_called()

    def test_existing_notifies_are_rejected_before_write(self):
        """/** @return 有业务通知的源序列不能被默默重定时 */"""
        self.engine.AnimationLibrary.get_animation_notify_events.return_value = [object()]
        with self.assertRaises(RuntimeError):
            self.remap("Animation", "Mesh", 2.0, 10,
                       json.dumps({"magazine_joint": [[0, 0], [2, 1]]}), "Source")
        self.access.assert_not_called()

    def test_baked_transform_curve_removed_after_source_sampling(self):
        """/** @return 源运动写入骨骼后不再叠加目标旧变换曲线 */"""
        self.engine.AnimationLibrary.get_animation_curve_names.side_effect = [[], ["Magazine_joint"], []]
        self.remap("Animation", "Mesh", 2.0, 10,
                   json.dumps({"magazine_joint": [[0, 0], [2, 1]]}), "Source")
        self.animation.controller.remove_all_curves_of_type.assert_called_once()
        self.assertTrue(all(call.args[0] is self.source for call in self.pose.call_args_list))

    def test_same_source_target_rejected(self):
        """/** @return 禁止把上一轮结果再次当作源累计重映射 */"""
        with self.assertRaises(RuntimeError):
            self.remap("Animation", "Mesh", 2.0, 10,
                       json.dumps({"magazine_joint": [[0, 0], [2, 1]]}), "Animation")
        self.access.assert_not_called()


if __name__ == "__main__":
    unittest.main()
