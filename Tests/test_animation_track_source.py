import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class SourceTrackTests(unittest.TestCase):
    """/** 验证原位应用烘焙轨道的拒绝条件和高采样率数据保留 */"""

    def setUp(self):
        """/** @return 仅装载源轨道准备函数与只读引擎替身 */"""
        path = Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationTrajectoryTools.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_source_track_request")
        self.target = SimpleNamespace(data_model_interface=SimpleNamespace(get_bone_track_names=lambda: ["hand_l"]))
        self.source = SimpleNamespace(data_model_interface=SimpleNamespace(get_bone_track_names=lambda: ["hand_l"]))
        self.transform = SimpleNamespace(translation=SimpleNamespace(x=1, y=2, z=3), rotation=SimpleNamespace(x=0, y=0, z=0, w=1), scale3d=SimpleNamespace(x=1, y=1, z=1))
        self.unreal = SimpleNamespace(load_asset=lambda path: self.source, AnimSequence=SimpleNamespace, BBBBlueprintEditorLibrary=SimpleNamespace(get_animation_bone_track_transforms=lambda source, name: [self.transform] * 1046))
        self.namespace = {"unreal": self.unreal, "_track_metadata": lambda asset: {"frames": 1046}}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), self.namespace)

    def test_high_rate_source_keeps_every_frame_and_rotation(self):
        """/** @return 1046 帧位置旋转缩放全部保留 */"""
        tracks, metadata = self.namespace["_source_track_request"](self.target, "/Source")
        self.assertEqual(len(tracks["hand_l"]), 1046)
        self.assertEqual(tracks["hand_l"][-1], {"position": [1, 2, 3], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]})
        self.assertEqual(metadata, {"frames": 1046})

    def test_metadata_difference_rejected_before_track_read(self):
        """/** @return 骨架帧率或事件差异提前拒绝 */"""
        self.namespace["_track_metadata"] = lambda asset: {"frames": 1046 if asset is self.target else 30}
        with self.assertRaisesRegex(RuntimeError, "源与目标"):
            self.namespace["_source_track_request"](self.target, "/Source")

    def test_track_set_difference_rejected(self):
        """/** @return 缺失骨骼不能部分覆盖目标 */"""
        self.source.data_model_interface.get_bone_track_names = lambda: ["hand_r"]
        with self.assertRaisesRegex(RuntimeError, "轨道集合"):
            self.namespace["_source_track_request"](self.target, "/Source")

    def test_same_asset_rejected(self):
        """/** @return 自身作为源被拒绝 */"""
        self.unreal.load_asset = lambda path: self.target
        with self.assertRaisesRegex(RuntimeError, "源动画无效"):
            self.namespace["_source_track_request"](self.target, "/Source")


if __name__ == "__main__":
    unittest.main()
