import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ControlRigBakeTests(unittest.TestCase):
    """/** 官方烘焙的目标权限与失败保存边界 */"""

    def setUp(self):
        """/** @return 提取工具函数并隔离引擎资产 */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in definition.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"bake_control_rig_animation", "create_control_rig_sequence"}]
        for method in methods:
            method.decorator_list = []
        self.engine = Mock()
        self.animation = Mock(sequence_length=2.0)
        self.animation.get_path_name.return_value = "/Game/Target.Target"
        self.sequence = Mock()
        self.mesh = Mock()
        self.binding = Mock()
        self.access = Mock()
        self.assets = Mock(side_effect=lambda path, kind: {
            "/Game/Sequence": self.sequence, "/Game/Mesh": self.mesh,
            "/Game/Target": self.animation}[path])
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.engine.SequencerTools.export_anim_sequence.return_value = True
        self.binding.find_tracks_by_type.return_value = [Mock()]
        self.namespace = {"json": json, "math": math, "unreal": self.engine,
                          "require_write_access": self.access, "_asset": self.assets,
                          "_mesh_binding": Mock(return_value=self.binding)}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "control_rig_bake", "exec"), self.namespace)
        self.bake = self.namespace["bake_control_rig_animation"]

    def test_explicit_target_is_checked_and_is_the_only_saved_asset(self):
        """/** @return 权限先于烘焙且只保存明确目标 */"""
        result = json.loads(self.bake("/Game/Sequence", "/Game/Target", "/Game/Mesh"))
        self.access.assert_called_once_with(self.animation)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.animation, False)
        self.animation.set_editor_property.assert_called_once_with("enable_root_motion", False)
        self.assertEqual(result["length"], 2.0)

    def test_checkout_failure_prevents_bake(self):
        """/** @return 未签出不能写入目标 */"""
        self.access.side_effect = RuntimeError("资产独占")
        with self.assertRaises(RuntimeError):
            self.bake("/Game/Sequence", "/Game/Target", "/Game/Mesh")
        self.engine.SequencerTools.export_anim_sequence.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_failed_or_empty_bake_is_never_saved(self):
        """/** @return 烘焙失败或空动作均拒绝保存 */"""
        self.engine.SequencerTools.export_anim_sequence.return_value = False
        with self.assertRaises(RuntimeError):
            self.bake("/Game/Sequence", "/Game/Target", "/Game/Mesh")
        self.engine.SequencerTools.export_anim_sequence.return_value = True
        self.animation.sequence_length = 0.0
        with self.assertRaises(RuntimeError):
            self.bake("/Game/Sequence", "/Game/Target", "/Game/Mesh")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_missing_rig_is_rejected_before_asset_creation(self):
        """/** @return 缺少控制绑定不能创建无效结果 */"""
        self.binding.find_tracks_by_type.return_value = []
        with self.assertRaises(RuntimeError):
            self.bake("/Game/Sequence", "/Game/Target", "/Game/Mesh")
        self.engine.EditorAssetLibrary.does_asset_exist.assert_not_called()

    def test_invalid_duration_is_rejected_before_loading(self):
        """/** @return 无效时间与帧率不产生序列 */"""
        create = self.namespace["create_control_rig_sequence"]
        for duration, rate in [(0, 30), (math.nan, 30), (2, 0), (2, 121)]:
            with self.assertRaises(RuntimeError):
                create("/Game/Sequence", "/Game/Mesh", duration, rate)
        self.assets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
