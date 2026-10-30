import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class WeaponAimWriteBoundaryTests(unittest.TestCase):
    """/** 举枪工具的输入范围和失败保存边界 */"""

    def setUp(self):
        """/** @return 提取入口并注入受控引擎替身 */"""
        tree = ast.parse((ROOT / "Scripts/BBBWeaponAimTools.py").read_text(encoding="utf-8-sig"))
        methods = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"create_weapon_aim_additive", "configure_upper_body_pose"}]
        self.engine = Mock()
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = False
        self.engine.AnimSequence = Mock
        self.engine.AdditiveAnimationType.AAT_NONE = "absolute"
        self.neutral = Mock()
        self.target = Mock()
        self.output = Mock()
        self.reference = Mock()
        self.neutral.get_skeleton.return_value = "skeleton"
        self.target.get_skeleton.return_value = "skeleton"
        self.neutral.get_editor_property.return_value = "absolute"
        self.target.get_editor_property.return_value = "absolute"
        self.engine.load_asset.side_effect = [self.neutral, self.target]
        self.engine.EditorAssetLibrary.duplicate_asset.side_effect = [self.output, self.reference]
        self.engine.BBBWeaponAimEditorLibrary.build_aim_additive.return_value = True
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.output.get_editor_property.side_effect = lambda name: {"ref_pose_seq": self.reference,
            "ref_frame_index": 0, "additive_anim_type": "local"}[name]
        self.output.data_model_interface.get_number_of_keys.return_value = 2
        self.output.get_anim_pose_at_frame.return_value.get_curve_names.return_value = []
        self.output.get_path_name.return_value = "/Game/_Project/Aim.Aim"
        self.neutral.get_path_name.return_value = "/Game/Neutral.Neutral"
        self.target.get_path_name.return_value = "/Game/Target.Target"
        self.reference.get_path_name.return_value = "/Game/_Project/AimReference.AimReference"
        self.access = Mock()
        namespace = {"json": json, "unreal": self.engine, "require_asset_write": self.access}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "weapon_aim_test", "exec"), namespace)
        self.create = namespace["create_weapon_aim_additive"]
        self.configure = namespace["configure_upper_body_pose"]
        self.arguments = ("/Game/Neutral", "/Game/Target", "/Game/_Project/Aim", "/Game/_Project/AimReference")

    def test_creation_claims_only_destination_and_preserves_sources(self):
        """/** @return 只声明新目标写入并只保存新动画 */"""
        result = self.create(*self.arguments)
        self.access.assert_called_once_with([], destinations=list(self.arguments[2:]))
        self.assertEqual(self.engine.EditorAssetLibrary.save_loaded_asset.call_args_list[-1].args, (self.output, False))
        self.assertTrue(result["saved"])
        self.assertEqual(result["keys"], 2)

    def test_existing_or_third_party_destination_rejected_before_load(self):
        """/** @return 覆盖已有包或向第三方目录写入时拒绝 */"""
        self.engine.EditorAssetLibrary.does_asset_exist.return_value = True
        for path in ("/Game/_Project/Aim", "/Game/_ThirdParty/Aim"):
            with self.assertRaises(RuntimeError):
                self.create(self.arguments[0], self.arguments[1], path, self.arguments[3])
        self.engine.load_asset.assert_not_called()

    def test_native_failure_never_saves_partial_animation(self):
        """/** @return 原生制作失败不保存不完整动画 */"""
        self.engine.BBBWeaponAimEditorLibrary.build_aim_additive.return_value = False
        with self.assertRaises(RuntimeError):
            self.create(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_permission_failure_does_not_duplicate(self):
        """/** @return 未获得目标资产写入范围时不创建 */"""
        self.access.side_effect = RuntimeError("write denied")
        with self.assertRaises(RuntimeError):
            self.create(*self.arguments)
        self.engine.EditorAssetLibrary.duplicate_asset.assert_not_called()

    def test_nonzero_curve_delta_rejected_before_save(self):
        """/** @return 脚部接触曲线被基准相减时拒绝保存 */"""
        pose = self.output.get_anim_pose_at_frame.return_value
        pose.get_curve_names.return_value = ["contact_l"]
        pose.get_curve_weight.return_value = -1.0
        with self.assertRaises(RuntimeError):
            self.create(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_incomplete_or_duplicate_layer_mapping_rejected_before_load(self):
        """/** @return 映射长度和重复写入范围提前拒绝 */"""
        for interface, base, main, layers in [("I", "B", "M", []), ("I", "B", "M", ["B"]),
                ("I", "B", "I", ["R"]), ("I", "B", "M", ["R", "R"])]:
            with self.assertRaises(RuntimeError):
                self.configure(interface, base, main, layers)
        self.engine.load_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
