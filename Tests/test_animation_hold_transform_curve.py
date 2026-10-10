import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class HoldTransformCurveTests(unittest.TestCase):
    """/** 固定机构骨骼必须同步清除对应修正曲线 */"""

    def test_only_held_bone_curve_removed(self):
        """/** @return 枪管保持固定 其它机构曲线和通知不被清除 */"""
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAnimationTrajectoryTools.py").read_text(encoding="utf-8-sig"))
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "hold_tracks")
        engine = Mock()
        animation = Mock()
        engine.load_asset.return_value = animation
        animation.data_model_interface.get_number_of_keys.return_value = 3
        value = SimpleNamespace(translation=1, rotation=2, scale3d=3)
        engine.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms.return_value = [value] * 3
        engine.AnimationLibrary.get_animation_curve_names.side_effect = [["Rotator_joint", "Trigger_joint"], [], ["Trigger_joint"]]
        namespace = {"json": json, "unreal": engine}
        with patch.dict("sys.modules", {"BBBAssetWritePolicy": SimpleNamespace(require_write_access=Mock())}):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "hold_transform_curve", "exec"), namespace)
            namespace["hold_tracks"]("Animation", ["rotator_joint"], 0, False)
        engine.AnimationLibrary.remove_curve.assert_called_once_with(animation, "Rotator_joint", False)
        animation.controller.set_bone_track_keys.assert_called_once_with("rotator_joint", [1] * 3, [2] * 3, [3] * 3, False)
        engine.AnimationLibrary.remove_all_curve_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
