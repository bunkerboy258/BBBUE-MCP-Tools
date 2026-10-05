import ast
import json
import math
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class FactAnimationGraphTests(unittest.TestCase):
    """/** 事实构图入口参数 权限与保存边界回归 */"""

    def setUp(self):
        """/** @return 隔离提取工具函数并构造引擎替身 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name in
                   {"configure_fact_action_variants", "configure_fact_locomotion_variants"}]
        for method in methods:
            method.decorator_list = []
        self.blueprint = Mock()
        self.sequence = Mock()
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimSequence = Mock
        self.engine.load_asset.side_effect = lambda path: self.blueprint if path == "/Game/Test/ABP" else self.sequence
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.blueprint.get_editor_property.return_value = self.engine.BlueprintStatus.BS_UP_TO_DATE
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {"json": json, "math": math, "unreal": self.engine, "require_write_access": self.access}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "fact_graph_test", "exec"), namespace)
        self.actions = namespace["configure_fact_action_variants"]
        self.locomotion = namespace["configure_fact_locomotion_variants"]
        self.arguments = ("/Game/Test/ABP", ["/Game/A", "/Game/H", "/Game/D"], [1, 1, 1], [0.4, 0.5, 0.2], [0.65, 0.5, 0.5], [1.0, 1.0, 0.4])

    def test_explicit_mapping_forwarded_and_only_target_saved(self):
        """/** @return 完整时间锚点前传且不保存其它资产 */"""
        result = json.loads(self.actions(*self.arguments))
        self.access.assert_called_once_with(self.blueprint)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_action_variants.assert_called_once_with(
            self.blueprint, [self.sequence] * 3, [1, 1, 1], [0.4, 0.5, 0.2], [0.65, 0.5, 0.5], [1.0, 1.0, 0.4], 0.16)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.blueprint, False)
        self.assertTrue(result["saved"])

    def test_invalid_mapping_rejected_before_loading(self):
        """/** @return 数量 非有限值 与无效进度边界拒绝 */"""
        for pivots, samples, ends in [([], [0.5] * 3, [1.0] * 3), ([0.4] * 3, [math.nan] * 3, [1.0] * 3),
                                      ([0.4] * 3, [0.5] * 3, [0.4] * 3), ([0.4] * 3, [1.0] * 3, [1.0] * 3)]:
            with self.assertRaises(RuntimeError):
                self.actions(*self.arguments[:3], pivots, samples, ends)
        self.engine.load_asset.assert_not_called()

    def test_pie_and_access_failure_prevent_native_changes(self):
        """/** @return PIE 或签出失败不构图 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.actions(*self.arguments)
        with self.assertRaises(RuntimeError):
            self.locomotion("/Game/Test/ABP", ["/Game/I"], ["/Game/S"])
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.access.side_effect = RuntimeError("未签出")
        with self.assertRaises(RuntimeError):
            self.locomotion("/Game/Test/ABP", ["/Game/I"], ["/Game/S"])
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_locomotion_variants.assert_not_called()
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_action_variants.assert_not_called()

    def test_native_or_compile_failure_does_not_save(self):
        """/** @return 构图或编译失败保留内存诊断 不保存 */"""
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_locomotion_variants.return_value = False
        with self.assertRaises(RuntimeError):
            self.locomotion("/Game/Test/ABP", ["/Game/I"], ["/Game/S"])
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_action_variants.return_value = True
        self.blueprint.get_editor_property.return_value = "CompileFailed"
        with self.assertRaises(RuntimeError):
            self.actions(*self.arguments)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


class FactAnimationSamplingTests(unittest.TestCase):
    """/** 显式速度采样与单位根轨道回归 */"""

    def test_preview_requires_explicit_speeds_and_rejects_invalid_values(self):
        """/** @return 静止不被固定移动速度替代 无效值拒绝 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationPreviewToolset.py").read_text(encoding="utf-8-sig"))
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "capture_monster_animation_transition")
        method.decorator_list = []
        engine = Mock()
        engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        namespace = {"unreal": engine, "re": __import__("re")}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "preview_test", "exec"), namespace)
        capture = namespace[method.name]
        arguments = ("/Game/Actor", 0, 1, 0.0, 0.0)
        with self.assertRaises(TypeError):
            capture(*arguments, sample_seconds=[0.0], bone_names=[], file_prefix="Test")
        for speed in (-1.0, math.nan, math.inf, 10001.0):
            with self.assertRaises(RuntimeError):
                capture(*arguments, speed, 0.0, [0.0], [], "Test")
            with self.assertRaises(RuntimeError):
                capture(*arguments, 0.0, speed, [0.0], [], "Test")
        engine.load_asset.assert_not_called()
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "call_method"]
        state_calls = [node for node in calls if node.args[0].value == "ApplyPresentationState"]
        self.assertEqual([node.args[1].elts[1].id for node in state_calls], ["initial_speed", "target_speed"])

    def test_identity_root_is_not_first_frame_and_other_tracks_untouched(self):
        """/** @return 单位变换覆盖明确根轨道 保持其它轨道及权限边界 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationTrajectoryTools.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "hold_tracks")
        engine = Mock()
        animation = engine.load_asset.return_value
        animation.data_model_interface.get_number_of_keys.return_value = 3
        animation.controller.set_bone_track_keys.return_value = True
        original = Mock()
        engine.BBBBlueprintEditorLibrary.get_animation_bone_track_transforms.return_value = [original] * 3
        access = Mock()
        namespace = {"unreal": engine, "json": json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "trajectory_test", "exec"), namespace)
        with patch.dict("sys.modules", {"BBBAssetWritePolicy": types.SimpleNamespace(require_write_access=access)}):
            namespace["hold_tracks"]("/Game/Animation", ["root"], 0, True)
        value = engine.Transform.return_value
        access.assert_called_once_with(animation)
        animation.controller.set_bone_track_keys.assert_called_once_with("root", [value.translation] * 3, [value.rotation] * 3, [value.scale3d] * 3, False)
        engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(animation, False)


if __name__ == "__main__":
    unittest.main()
