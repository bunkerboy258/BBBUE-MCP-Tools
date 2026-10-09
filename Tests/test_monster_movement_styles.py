import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class MonsterMovementStylesTests(unittest.TestCase):
    """/** 移动风格入口的参数 签出 编译 保存边界 */"""

    def setUp(self):
        """/** @return 隔离新入口及引擎替身 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_fact_movement_styles")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.BlendSpace1D = Mock
        self.blueprint = Mock()
        self.styles = [Mock(), Mock(), Mock()]
        self.engine.load_asset.side_effect = [self.blueprint] + self.styles
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.blueprint.get_editor_property.return_value = self.engine.BlueprintStatus.BS_UP_TO_DATE
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "math": math, "json": json, "require_write_access": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "movement_style_test", "exec"), namespace)
        self.call = namespace["configure_fact_movement_styles"]
        self.arguments = ("/Game/Test/ABP", ["/Game/A", "/Game/B", "/Game/C"])

    def test_valid_styles_compile_and_save_only_target(self):
        """/** @return 三个样式前传并只保存目标 */"""
        result = json.loads(self.call(*self.arguments))
        self.access.assert_called_once_with(self.blueprint)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_movement_styles.assert_called_once_with(self.blueprint, self.styles, 0.18)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.blueprint, False)
        self.assertTrue(result["continuousEntityPhase"])

    def test_invalid_parameters_stop_before_loading(self):
        """/** @return 空 重复 超限与非有限输入拒绝 */"""
        for styles, duration in [([], 0.18), (["A", "A", "B"], 0.18), (["A", "B", "C"], math.nan), (["A", "B", "C"], 0.31)]:
            with self.assertRaises(RuntimeError):
                self.call("/Game/Test/ABP", styles, duration)
        self.engine.load_asset.assert_not_called()

    def test_pie_access_dirty_and_compile_failure_never_save(self):
        """/** @return 非法编辑时机 权限与编译失败不保存 */"""
        for condition in ["pie", "access", "dirty", "compile", "native"]:
            self.setUp()
            if condition == "pie":
                self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
            if condition == "access":
                self.access.side_effect = RuntimeError("未签出")
            if condition == "dirty":
                package = Mock()
                package.get_path_name.return_value = self.blueprint.get_outermost().get_path_name()
                self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [package]
            if condition == "compile":
                self.blueprint.get_editor_property.return_value = "Failed"
            if condition == "native":
                self.engine.BBBAnimationGraphEditorLibrary.configure_fact_movement_styles.return_value = False
            with self.assertRaises(RuntimeError):
                self.call(*self.arguments)
            self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
