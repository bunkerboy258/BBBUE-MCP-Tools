import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class CharacterBasePoseTests(unittest.TestCase):
    """/** 基础姿态构图的显式资产范围与编译保存边界 */"""

    def setUp(self):
        """/** @return 隔离实际工具方法与编辑器依赖 */"""
        tree = ast.parse((ROOT / "Scripts/BBBMotionMatchingToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "consolidate_character_base_pose")
        method.decorator_list = []
        method.body = [node for node in method.body if not isinstance(node, ast.ImportFrom)]
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimSequence = Mock
        self.engine.ChooserTable = Mock
        self.engine.BlueprintStatus.BS_UP_TO_DATE = "Ready"
        self.paths = ["/Game/Main", "/Game/Base", "/Game/Ground", "/Game/Stand", "/Game/Crouch", "/Game/HelpingChooser"]
        self.assets = [Mock() for _ in self.paths]
        for path, asset in zip(self.paths, self.assets):
            asset.get_path_name.return_value = path
            asset.get_outermost.return_value.get_path_name.return_value = path
            asset.get_editor_property.return_value = "Ready"
        self.engine.load_asset.side_effect = dict(zip(self.paths, self.assets)).get
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.native = self.engine.BBBAnimationGraphEditorLibrary.consolidate_character_base_pose
        self.native.return_value = '{"configured": true}'
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "require_asset_write": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "base_pose_test", "exec"), namespace)
        self.configure = namespace[method.name]

    def test_dry_run_does_not_mutate_compile_or_save(self):
        """/** @return 原生预检不能申请写入或保存蓝图 */"""
        self.configure(*self.paths)
        self.native.assert_called_once_with(*self.assets, 0.0, False)
        self.access.assert_not_called()
        self.engine.BlueprintEditorLibrary.compile_blueprint.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_only_two_blueprints_saved_after_both_compile(self):
        """/** @return 只保存明确的主图与基础层 不写源动画或其他脏包 */"""
        result = json.loads(self.configure(*self.paths, ground_pose_time=0.1, dry_run=False))
        self.access.assert_called_once_with(self.assets[:2])
        self.native.assert_called_once_with(*self.assets, 0.1, True)
        expected = [self.assets[1], self.assets[0]]
        self.assertEqual([call.args[0] for call in self.engine.BlueprintEditorLibrary.compile_blueprint.call_args_list], expected)
        self.assertEqual([call.args for call in self.engine.EditorAssetLibrary.save_loaded_asset.call_args_list],
                         [(asset, False) for asset in expected])
        self.assertEqual(result["saved"], self.paths[1::-1])

    def test_permission_or_dirty_target_prevents_native_mutation(self):
        """/** @return 拒绝占用和未保存目标 不将其他会话改动混入构图 */"""
        self.access.side_effect = RuntimeError("占用")
        with self.assertRaises(RuntimeError):
            self.configure(*self.paths, dry_run=False)
        self.access.side_effect = None
        dirty = Mock()
        dirty.get_path_name.return_value = self.paths[1]
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [dirty]
        with self.assertRaises(RuntimeError):
            self.configure(*self.paths, dry_run=False)
        self.native.assert_not_called()

    def test_missing_source_or_native_failure_does_not_save(self):
        """/** @return 无效素材和原生构图错误不能持久化 */"""
        with self.assertRaises(RuntimeError):
            self.configure(*self.paths[:5], "/Game/Missing", dry_run=False)
        self.native.return_value = '{"error": "构图失败"}'
        with self.assertRaises(RuntimeError):
            self.configure(*self.paths, dry_run=False)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_compile_warning_blocks_every_save(self):
        """/** @return 任一目标存在警告时两者都不能保存 */"""
        self.assets[0].get_editor_property.return_value = "Warning"
        with self.assertRaises(RuntimeError):
            self.configure(*self.paths, dry_run=False)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_retired_character_authoring_is_absent(self):
        """/** @return 旧状态机与攀爬运行时工具不保留兼容入口 */"""
        baseline = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(set(baseline["BBBTraversalToolset"]), {
            "inspect_pie_traversal_contact_points", "configure_traversal_contact_points",
            "inspect_traversal_montage_windows", "configure_traversal_montages"})
        self.assertNotIn("configure_character_downed_state", baseline["BBBAnimationGraphToolset"])
        self.assertNotIn("configure_character_rescue_state", baseline["BBBAnimationGraphToolset"])


if __name__ == "__main__":
    unittest.main()
