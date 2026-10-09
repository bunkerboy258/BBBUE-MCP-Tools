import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


class CombatTransitionBlendTests(unittest.TestCase):
    """/** 验证战斗转换参数 独占权限与编译保存边界 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_fact_combat_transition_blends")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = type("AnimBlueprint", (), {})
        self.blueprint = self.engine.AnimBlueprint()
        self.blueprint.get_editor_property = Mock(return_value=self.engine.BlueprintStatus.BS_UP_TO_DATE)
        self.engine.load_asset.return_value = self.blueprint
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions.return_value = 30
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        scope = {"unreal": self.engine, "math": math, "json": json, "require_write_access": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "combat_transition_test", "exec"), scope)
        self.configure = scope[method.name]

    def test_invalid_parameters_prevent_asset_load(self):
        """/** @return 非项目路径及无效时间不接触资产 */"""
        for value in (0.0, -0.1, 0.51, math.nan, math.inf):
            with self.assertRaises(RuntimeError):
                self.configure("/Game/_Project/ABP", movement_duration=value)
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_ThirdParty/ABP")
        self.engine.load_asset.assert_not_called()

    def test_pie_and_exclusive_access_precede_native_write(self):
        """/** @return 游戏运行和签出失败不修改蓝图 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/ABP")
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.access.side_effect = RuntimeError("未独占签出")
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/ABP")
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions.assert_not_called()

    def test_native_and_compile_failure_do_not_save(self):
        """/** @return 不完整状态机与编译失败不能保存 */"""
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions.return_value = -1
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/ABP")
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions.return_value = 30
        self.blueprint.get_editor_property.return_value = "Error"
        with self.assertRaises(RuntimeError):
            self.configure("/Game/_Project/ABP")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_success_forwards_all_durations_and_saves_only_target(self):
        """/** @return 分类时长前传且只保存目标 */"""
        result = json.loads(self.configure("/Game/_Project/ABP"))
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_combat_transitions.assert_called_once_with(
            self.blueprint, 0.22, 0.08, 0.16, 0.07, 0.18, 0.28, 0.04)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.blueprint, False)
        self.assertEqual(result["transitions"], 30)
        self.assertTrue(result["saved"])


if __name__ == "__main__":
    unittest.main()
