import json
import unittest
from unittest.mock import Mock

from Tests.test_consumable_authoring import load_method


class RootMotionMatrixTests(unittest.TestCase):
    """/** 检查矩阵写入权限和保存边界 */"""

    def setUp(self):
        self.engine = Mock()
        self.engine.AnimSequence = Mock
        self.asset = Mock()
        self.asset.get_path_name.return_value = "/Game/_Project/AS.AS"
        self.engine.load_asset.return_value = self.asset
        self.access = Mock()
        self.native = self.engine.BBBAssetRepairEditorLibrary.configure_animation_root_motion_matrix
        self.report = {"success": True, "animationDataUnchanged": True,
                       "assets": [{"asset": "/Game/_Project/AS.AS", "changed": True}]}
        self.native.return_value = json.dumps(self.report)
        self.configure = load_method("Scripts/BBBGenericEditorToolset.py", "configure_animation_root_motion_matrix",
                                     {"unreal": self.engine, "json": json, "require_asset_write": self.access})

    def test_invalid_scope_is_rejected_before_loading(self):
        """/** @return 空 重复 外部路径及超量目标在加载前拒绝 */"""
        for paths in [[], ["/Game/_Project/AS"] * 2, ["/Game/ThirdParty/AS"],
                      ["/Game/_Project/AS" + str(index) for index in range(513)]]:
            with self.subTest(paths=len(paths)), self.assertRaises(RuntimeError):
                self.configure(paths)
        self.engine.load_asset.assert_not_called()
        self.native.assert_not_called()

    def test_invalid_enum_is_rejected_before_loading(self):
        """/** @return 非法根锁定枚举不进入矩阵 */"""
        with self.assertRaises(RuntimeError):
            self.configure(["/Game/_Project/AS"], root_lock="invalid")
        self.engine.load_asset.assert_not_called()

    def test_wrong_asset_type_is_not_edited(self):
        """/** @return 非动画资产不取得写权限 */"""
        self.engine.load_asset.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure(["/Game/_Project/AS"], dry_run=False)
        self.access.assert_not_called()
        self.native.assert_not_called()

    def test_preview_never_acquires_write_or_saves(self):
        """/** @return 矩阵预检保持只读 */"""
        self.assertFalse(json.loads(self.configure(["/Game/_Project/AS"]))["saved"])
        self.access.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_write_permission_precedes_native_edit(self):
        """/** @return 未取得写权限时不执行原生矩阵 */"""
        self.access.side_effect = RuntimeError("denied")
        with self.assertRaisesRegex(RuntimeError, "denied"):
            self.configure(["/Game/_Project/AS"], dry_run=False)
        self.native.assert_not_called()

    def test_failed_or_incomplete_verification_never_saves(self):
        """/** @return 原生失败 数据变化及缺失行不能保存 */"""
        for report in [{"success": False}, {**self.report, "animationDataUnchanged": False},
                       {**self.report, "assets": []},
                       {**self.report, "assets": [{"asset": "/Game/_Project/Other", "changed": True}]}]:
            self.native.return_value = json.dumps(report)
            with self.assertRaises(RuntimeError):
                self.configure(["/Game/_Project/AS"], dry_run=False)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_changed_assets_save_after_verified_matrix_edit(self):
        """/** @return 核验后的修改目标完成保存 */"""
        result = json.loads(self.configure(["/Game/_Project/AS"], dry_run=False))
        self.assertTrue(result["saved"])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.asset, False)

    def test_unchanged_asset_is_not_reserialized(self):
        """/** @return 已符合设置的序列不重复写盘 */"""
        self.report["assets"][0]["changed"] = False
        self.native.return_value = json.dumps(self.report)
        self.configure(["/Game/_Project/AS"], dry_run=False)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_save_failure_is_reported(self):
        """/** @return 保存失败不返回成功 */"""
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = False
        with self.assertRaisesRegex(RuntimeError, "保存失败"):
            self.configure(["/Game/_Project/AS"], dry_run=False)


if __name__ == "__main__":
    unittest.main()
