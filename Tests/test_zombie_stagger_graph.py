import ast
import json
import math
import os
import re
from pathlib import Path
import unittest
from unittest.mock import Mock


class ZombieStaggerGraphTests(unittest.TestCase):
    """/** 踉跄构图入口的参数 权限与保存边界 */"""

    def setUp(self):
        """/** @return 构造只提取本工具的隔离引擎替身 */"""
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_fact_stagger_state")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimSequence = Mock
        self.blueprint = Mock()
        self.sequence = Mock()
        self.engine.load_asset.side_effect = lambda path: self.blueprint if path == "/Game/_Project/Test/ABP" else self.sequence
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.blueprint.get_editor_property.return_value = self.engine.BlueprintStatus.BS_UP_TO_DATE
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "math": math, "require_write_access": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "stagger_boundary_test", "exec"), namespace)
        self.configure = namespace[method.name]
        self.arguments = ("/Game/_Project/Test/ABP", ["/Game/Head", "/Game/Left", "/Game/Right"])

    def test_explicit_sequences_and_only_target_saved(self):
        """/** @return 明确顺序和签出前传 只保存目标蓝图 */"""
        result = json.loads(self.configure(*self.arguments))
        self.access.assert_called_once_with(self.blueprint)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_stagger_state.assert_called_once_with(self.blueprint, [self.sequence] * 3, 0.12)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.blueprint, False)
        self.assertEqual(result["state"], "Stagger")

    def test_invalid_contract_rejected_before_loading(self):
        """/** @return 数量 重复路径 第三方蓝图和无效时间拒绝 */"""
        for path, sequences, duration in [(self.arguments[0], [], 0.12), (self.arguments[0], ["A"] * 3, 0.12),
                                          ("/Game/_ThirdParty/ABP", self.arguments[1], 0.12),
                                          (self.arguments[0], self.arguments[1], math.nan),
                                          (self.arguments[0], self.arguments[1], 0.0),
                                          (self.arguments[0], self.arguments[1], 0.31)]:
            with self.assertRaises(RuntimeError):
                self.configure(path, sequences, duration)
        self.engine.load_asset.assert_not_called()

    def test_pie_or_checkout_failure_cannot_edit(self):
        """/** @return PIE 和独占签出失败均阻止原生构图 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.access.side_effect = RuntimeError("未签出")
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_stagger_state.assert_not_called()

    def test_native_compile_or_save_failure_is_not_success(self):
        """/** @return 原生 编译 保存失败不得报告成功 */"""
        native = self.engine.BBBAnimationGraphEditorLibrary.configure_fact_stagger_state
        native.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        native.return_value = True
        self.blueprint.get_editor_property.return_value = "CompileError"
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()
        self.blueprint.get_editor_property.return_value = self.engine.BlueprintStatus.BS_UP_TO_DATE
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = False
        with self.assertRaises(RuntimeError):
            self.configure(*self.arguments)

    def capture_method(self):
        """/** @return 提取临时表现采样入口 不启动编辑器 */"""
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "capture_monster_stagger_samples")
        method.decorator_list = []
        namespace = {"unreal": self.engine, "json": json, "math": math, "os": os, "re": re}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "stagger_capture_test", "exec"), namespace)
        return namespace[method.name]

    def test_capture_requires_render_pie(self):
        """/** @return 无渲染或无 PIE 时不生成临时载体 */"""
        capture = self.capture_method()
        self.engine.SystemLibrary.get_command_line.return_value = "-NullRHI"
        with self.assertRaises(RuntimeError):
            capture(["/Game/_Project/BP"], 0, [0.25], "Test")
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        with self.assertRaises(RuntimeError):
            capture(["/Game/_Project/BP"], 0, [0.25], "Test")
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()

    def test_capture_invalid_parameters_cannot_spawn_or_save(self):
        """/** @return 无效路径 部位 进度和前缀拒绝 不写正式资产 */"""
        capture = self.capture_method()
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        for paths, region, progress, prefix in [([], 0, [0.25], "Test"), (["/Game/_ThirdParty/BP"], 0, [0.25], "Test"),
                                              (["/Game/_Project/BP"] * 2, 0, [0.25], "Test"),
                                              (["/Game/_Project/BP"], 6, [0.25], "Test"),
                                              (["/Game/_Project/BP"], 0, [math.nan], "Test"),
                                              (["/Game/_Project/BP"], 0, [0.5, 0.25], "Test"),
                                              (["/Game/_Project/BP"], 0, [0.25], "../Test")]:
            with self.assertRaises(RuntimeError):
                capture(paths, region, progress, prefix)
        self.engine.load_asset.assert_not_called()
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
