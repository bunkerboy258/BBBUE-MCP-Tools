import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


class AnimationPoseRangeTests(unittest.TestCase):
    """/** 采样不能把越界参考姿势当成真实动作 */"""

    def setUp(self):
        """/** @return 可观察取样调用的引擎替身 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "sample_animation_poses")
        method.decorator_list = []
        self.engine = Mock()
        self.animation = Mock()
        self.animation.get_play_length.return_value = 0.06666667
        self.native = self.engine.BBBBlueprintEditorLibrary.sample_animation_component_poses
        self.native.side_effect = lambda animation, mesh, times, names: json.dumps([
            {"time": time, "bones": {name: {"position": [1, 2, 3], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]} for name in names or ["Hand_L"]}}
            for time in times])
        scope = {"unreal": self.engine, "json": json, "math": math,
                 "_asset": lambda path, kind: self.animation}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "animation_pose_range", "exec"), scope)
        self.sample = scope[method.name]

    def test_out_of_range_is_rejected_before_sampling(self):
        """/** @return 不让引擎悄悄返回参考姿势 */"""
        for times in ([0, 0.1], [-0.01], [float("nan")], []):
            with self.assertRaises(RuntimeError):
                self.sample("Animation", "Mesh", times, [])
        self.native.assert_not_called()

    def test_exact_end_is_a_valid_sample(self):
        """/** @return 合法末帧不丢失 */"""
        result = json.loads(self.sample("Animation", "Mesh", [0, 0.06666667], []))
        self.assertEqual([value["time"] for value in result], [0, 0.06666667])
        self.assertEqual(self.native.call_count, 1)

    def test_component_pose_preserves_requested_name(self):
        """/** @return 大小写不同的骨名读取同一真实组件姿势 */"""
        result = json.loads(self.sample("Animation", "Mesh", [0], ["hand_l"]))
        self.assertEqual(result[0]["bones"]["hand_l"]["position"], [1, 2, 3])
        self.assertEqual(self.native.call_args.args[3], ["hand_l"])

    def test_missing_bone_is_rejected_instead_of_identity_pose(self):
        """/** @return 拼错骨名不能得到假的单位变换 */"""
        self.native.side_effect = None
        self.native.return_value = ""
        with self.assertRaisesRegex(RuntimeError, "PoseSample"):
            self.sample("Animation", "Mesh", [0], ["Missing"])

    def test_wrong_count_is_rejected(self):
        """/** @return 批量结果不完整时明确报错 */"""
        self.native.side_effect = None
        self.native.return_value = "[]"
        with self.assertRaises(RuntimeError):
            self.sample("Animation", "Mesh", [0], [])


if __name__ == "__main__":
    unittest.main()
