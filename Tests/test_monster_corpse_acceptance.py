import ast
import json
import math
import io
import os
from pathlib import Path
import re
import types
import unittest
import uuid
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class CorpseAcceptanceTests(unittest.TestCase):
    """/** 尸体压力入口的关卡 句柄和参数边界 */"""

    def setUp(self):
        """/** @return 隔离引擎入口 不创建磁盘输出 */"""
        tree = ast.parse((ROOT / "Scripts/BBBAnimationPreviewToolset.py").read_text(encoding="utf-8-sig"))
        node = next(value for value in ast.walk(tree) if isinstance(value, ast.FunctionDef) and value.name == "start_mass_corpse_acceptance")
        node.decorator_list = []
        self.engine = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value.get_path_name.return_value = "/Game/Validation.Validation"
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.engine.MassEntityConfigAsset = Mock
        self.engine.load_asset.return_value = Mock()
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = []
        self.runs = {}
        self.output = io.StringIO()
        self.stream = Mock()
        self.stream.__enter__ = Mock(return_value=self.output)
        self.stream.__exit__ = Mock(return_value=False)
        self.files = types.SimpleNamespace(path=os.path, makedirs=Mock())
        namespace = {"unreal": self.engine, "math": math, "json": json, "re": re, "_population_runs": self.runs,
                     "uuid": uuid, "os": self.files, "open": Mock(return_value=self.stream)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "corpse", "exec"), namespace)
        self.call = namespace[node.name]
        self.arguments = (["/Game/Config"], 10, [0.0, 0.0, 90.0], 200.0, "/Game/Validation", "CorpseTest")

    def test_invalid_parameters_reject_before_engine_access(self):
        """/** @return 数量 非有限坐标 重复模板和路径拒绝 */"""
        for index, value in [(0, []), (0, ["A", "A"]), (1, 501), (1, 0), (2, [math.nan, 0, 0]), (3, math.inf), (4, "/Game/BBBTest"), (5, "../outside")]:
            arguments = list(self.arguments)
            arguments[index] = value
            with self.assertRaises(RuntimeError):
                self.call(*arguments)
        self.engine.get_editor_subsystem.assert_not_called()

    def test_wrong_world_nullrhi_or_busy_reject_before_spawn(self):
        """/** @return 关卡错误 无渲染或已有运行不会创建实体 */"""
        world = self.engine.get_editor_subsystem.return_value.get_game_world.return_value
        world.get_path_name.return_value = "/Game/BBBTest.BBBTest"
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        world.get_path_name.return_value = "/Game/Validation.Validation"
        self.engine.SystemLibrary.get_command_line.return_value = "-NullRHI"
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.runs["peer"] = {"status": "running"}
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.engine.BBBMassValidationLibrary.spawn_population.assert_not_called()

    def test_failed_spawn_cleans_only_returned_handles(self):
        """/** @return 创建不足只回收自身句柄 不写正式资产 */"""
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = ["own"]
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.engine.BBBMassValidationLibrary.destroy_population.assert_called_once()
        self.assertEqual(self.engine.BBBMassValidationLibrary.destroy_population.call_args.args[1], ["own"])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_game_time_damage_sampling_and_final_cleanup(self):
        """/** @return 正式伤害只投递一次 指标可序列化 验收结果不靠空样本成立 */"""
        time = [0.0]
        self.engine.GameplayStatics.get_time_seconds.side_effect = lambda world: time[0]
        self.engine.Paths.project_saved_dir.return_value = "E:/Virtual/Saved"
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = list(range(10))
        self.engine.BBBMassValidationLibrary.damage_population.return_value = 10
        self.engine.BBBAnimationGraphEditorLibrary.read_performance_frame_metrics.return_value = iter([1, 2, 3, 4, 5, 6])
        self.engine.BBBMassValidationLibrary.inspect_population.side_effect = lambda *args: json.dumps({
            "validEntities": 0 if time[0] >= 30 else 10,
            "presentationActors": 0 if time[0] >= 30 else 10,
            "locomotion": [] if time[0] >= 30 else [{"corpseSimulating": True, "corpseActive": True, "corpsePelvisZ": 90 if time[0] < 10 else 10}] * 10})
        started = json.loads(self.call(*self.arguments))
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        for seconds in [4, 5, 10, 14, 30]:
            time[0] = seconds
            callback(0.03)
        self.engine.BBBMassValidationLibrary.damage_population.assert_called_once()
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        self.engine.BBBMassValidationLibrary.destroy_population.assert_called_once()
        report = json.loads(self.output.getvalue())
        self.assertEqual(report["runId"], started["runId"])
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["retainedAt10s"] and report["physicsBudgetCorrect"] and report["recycled"] and report["ragdollsCollapsed"])
        self.assertTrue(report["allCorpsesCollapsed"])
        self.assertEqual(report["samples"][0]["frameMetrics"], [1., 2., 3., 4., 5., 6.])

    def test_incomplete_actor_population_does_not_receive_damage(self):
        """/** @return 分帧创建的演员未齐时不投递伤害 超时回收自身群体 */"""
        time = [0.0]
        self.engine.GameplayStatics.get_time_seconds.side_effect = lambda world: time[0]
        self.engine.Paths.project_saved_dir.return_value = "E:/Virtual/Saved"
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = list(range(10))
        self.engine.BBBMassValidationLibrary.inspect_population.return_value = json.dumps({"presentationActors": 9})
        self.call(*self.arguments)
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        time[0] = 4.0
        callback(0.03)
        self.engine.BBBMassValidationLibrary.damage_population.assert_not_called()
        time[0] = 60.0
        callback(0.03)
        self.assertEqual(json.loads(self.output.getvalue())["status"], "failed")
        self.engine.BBBMassValidationLibrary.destroy_population.assert_called_once()


if __name__ == "__main__":
    unittest.main()
