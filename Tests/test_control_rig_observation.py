import ast
import json
import os
import stat
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class ControlRigObservationTests(unittest.TestCase):
    """/** 验证 IK 通道读取与任务截图路径保护 */"""

    def setUp(self):
        """/** @return 隔离引擎和磁盘接口 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name in {"sample_sequence_controls", "capture_attachment_pose"}]
        for method in methods:
            method.decorator_list = []

        self.engine = Mock()
        self.sequence = Mock()
        self.sequence.get_playback_start.return_value = 0
        self.sequence.get_playback_end.return_value = 66
        self.rig = Mock()
        hierarchy = self.rig.get_hierarchy.return_value
        hierarchy.contains.return_value = True
        hierarchy.get_control_settings.return_value.control_type = self.engine.RigControlType.EULER_TRANSFORM
        self.engine.ControlRigSequencerLibrary.get_control_rigs.return_value = [Mock(control_rig=self.rig)]
        self.assets = Mock(return_value=self.sequence)
        self.engine.Paths.project_saved_dir.return_value = "E:/Virtual/Saved"
        self.namespace = {"json": json, "os": os, "stat": stat, "unreal": self.engine,
                          "_asset": self.assets, "_key": lambda name, kind: (name, kind),
                          "_read_transform": lambda value: {"position": [0, 0, 0]}}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "control_rig_observation", "exec"), self.namespace)

    def test_ik_controller_can_be_read_without_source_prefix(self):
        """/** @return 左手 IK 控制器读取不产生关键帧 */"""
        result = json.loads(self.namespace["sample_sequence_controls"]("Sequence", [0, 33], ["hand_l_ik_ctrl"]))
        self.assertEqual(len(result), 2)
        self.engine.ControlRigSequencerLibrary.set_local_control_rig_euler_transform.assert_not_called()

    def test_unknown_controller_is_rejected(self):
        """/** @return 缺失控制器不得返回伪造轨迹 */"""
        self.rig.get_hierarchy.return_value.contains.return_value = False
        with self.assertRaises(RuntimeError):
            self.namespace["sample_sequence_controls"]("Sequence", [0], ["Missing"])

    def test_invalid_output_is_rejected_before_world_access(self):
        """/** @return 截图只能写入明确任务目录 */"""
        capture = self.namespace["capture_attachment_pose"]
        for name in ["pose.png", "../pose.png", "task/../pose.png", "E:/pose.png", "/pose.png"]:
            with self.assertRaises(RuntimeError):
                capture("Animation", "Mesh", 0, "[]", [100, 0, 0], name)

        self.engine.get_editor_subsystem.assert_not_called()

    def test_junction_is_rejected_before_world_access(self):
        """/** @return Windows 目录联接不能成为截图目标目录 */"""
        with patch.object(os.path, "lexists", return_value=True), patch.object(os.path, "islink", return_value=False), patch.object(os, "lstat", return_value=Mock(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            with self.assertRaises(RuntimeError):
                self.namespace["capture_attachment_pose"]("Animation", "Mesh", 0, "[]", [100, 0, 0], "task/pose.png")
        self.engine.get_editor_subsystem.assert_not_called()

    def test_hand_closeup_light_preserves_contact_detail(self):
        """/** @return 近景补光强度不得让皮肤与手持物过曝 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        capture = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                       and node.name == "capture_attachment_pose")
        intensities = [node.args[0].value for node in ast.walk(capture)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr == "set_intensity" and isinstance(node.args[0], ast.Constant)]
        self.assertEqual(intensities, [2000.0])


if __name__ == "__main__":
    unittest.main()
