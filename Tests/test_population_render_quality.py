import ast
import itertools
import json
import math
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock, Mock


class PopulationRenderQualityTests(unittest.TestCase):
    """/** 验证群体测量不沿用隐藏宿主降画质且完整恢复配置 */"""

    def setUp(self):
        """/** @return 不访问编辑器和磁盘写入的隔离替身 */"""
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationPreviewToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_mass_population_benchmark")
        method.decorator_list = []
        self.engine = Mock()
        self.world = Mock()
        self.world.get_path_name.return_value = "/Game/ValidationWorld.ValidationWorld"
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen -PrivateHostSecret"
        self.engine.SystemLibrary.get_engine_version.return_value = "5.8-test"
        self.engine.MassEntityConfigAsset = type("MassEntityConfigAsset", (), {})
        self.engine.load_asset.return_value = self.engine.MassEntityConfigAsset()
        self.engine.GameplayStatics.get_all_actors_of_class.return_value = []
        self.engine.Vector = lambda *values: values
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = ["entity"]
        self.engine.BBBMassValidationLibrary.inspect_population.return_value = json.dumps({"validEntities": 1, "budgetMeshes": 1, "presentationActors": 1})
        self.engine.BBBMonsterDestructionValidationLibrary.inspect_population_destruction.return_value = json.dumps({"entities": [{"regions": [0] * 8, "dismemberment": [0] * 5}]})
        self.engine.BBBMonsterDestructionValidationLibrary.set_population_destruction.return_value = 1
        frames = itertools.count()
        self.engine.BBBAnimationGraphEditorLibrary.read_performance_frame_metrics.side_effect = lambda: [next(frames), 1.0, 2.0, 3.0, 16.7]
        self.values = {"t.MaxFPS": 30.0, "r.ScreenPercentage": 35.0, "r.Lumen.DiffuseIndirect.Allow": 0.0, "r.Lumen.Reflections.Allow": 0.0}
        self.engine.SystemLibrary.get_console_variable_float_value.side_effect = lambda name: self.values.setdefault(name, 0.0)
        self.engine.SystemLibrary.execute_console_command.side_effect = lambda world, command: self.values.__setitem__(command.split()[0], float(command.split()[1]))
        self.clock = [0.0]
        fake_os = Mock()
        fake_os.path.exists.return_value = False
        fake_os.path.join.side_effect = lambda *parts: "/".join(map(str, parts))
        fake_os.path.abspath.side_effect = lambda value: value
        self.runs = {}
        self.open = MagicMock()
        scope = {"unreal": self.engine, "os": fake_os, "re": re, "json": json, "csv": Mock(),
                 "uuid": Mock(), "time": Mock(perf_counter=lambda: self.clock[0]), "math": math, "open": self.open, "_population_runs": self.runs}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "population_render_quality", "exec"), scope)
        self.start = scope[method.name]

    def test_invalid_quality_never_reads_world_or_mutates(self):
        """/** @return 无效画质在世界查询和文件创建前拒绝 */"""
        for quality in (-1, 4, 1.5, True):
            with self.assertRaises(RuntimeError):
                self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe", quality_level=quality)
        self.engine.get_editor_subsystem.assert_not_called()
        self.engine.SystemLibrary.execute_console_command.assert_not_called()

    def test_full_resolution_settings_report_and_restore(self):
        """/** @return 完整分辨率测量并在正常结束恢复原始画质和三十帧 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe")
        report = next(iter(self.runs.values()))
        self.assertEqual(report["renderSettings"]["r.ScreenPercentage"], 100.0)
        self.assertEqual(report["renderSettings"]["sg.ShadowQuality"], 2.0)
        self.assertEqual(report["renderSettings"]["r.Lumen.DiffuseIndirect.Allow"], 1.0)
        self.assertNotIn("commandLine", report)
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        for second in range(60):
            self.clock[0] = float(second)
            callback(1.0 / 60.0)
            if report["status"] != "running":
                break
        self.assertEqual(report["status"], "completed")
        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.assertEqual(self.values["r.ScreenPercentage"], 35.0)
        self.assertEqual(self.values["sg.ShadowQuality"], 0.0)
        self.assertEqual(self.values["r.Lumen.DiffuseIndirect.Allow"], 0.0)
        self.engine.unregister_slate_post_tick_callback.assert_called_once()

    def test_pie_interruption_restores_quality_and_frame_limit(self):
        """/** @return 外部结束 PIE 也恢复实际画质和帧率 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe", quality_level=1)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        callback(1.0 / 60.0)
        report = next(iter(self.runs.values()))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.assertEqual(self.values["r.ScreenPercentage"], 35.0)
        self.assertEqual(self.values["r.Lumen.Reflections.Allow"], 0.0)

    def test_file_open_failure_cannot_change_frame_limit_or_quality(self):
        """/** @return 输出文件创建失败不能留下无限帧率或改变画质 */"""
        self.open.side_effect = OSError("输出目录不可写")
        with self.assertRaises(OSError):
            self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe")
        self.engine.SystemLibrary.execute_console_command.assert_not_called()
        self.assertEqual(self.values["t.MaxFPS"], 30.0)

    def test_collected_pie_world_is_never_used_for_console_restore(self):
        """/** @return 已销毁世界不再传入原生接口且终止回调只执行一次 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe")
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        original = self.engine.SystemLibrary.execute_console_command.side_effect
        def reject_collected_world(world, command):
            if world is self.world:
                raise TypeError("ObjectInstance is null")
            original(world, command)
        self.engine.SystemLibrary.execute_console_command.side_effect = reject_collected_world
        callback(1.0 / 60.0)
        callback(1.0 / 60.0)
        self.assertEqual(next(iter(self.runs.values()))["status"], "failed")
        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        self.open.return_value.close.assert_called_once()

    def test_console_restore_failure_still_closes_output_and_callback(self):
        """/** @return 恢复设置失败不能遗留帧回调与文件占用 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe")
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.SystemLibrary.execute_console_command.side_effect = RuntimeError("恢复失败")
        with self.assertRaisesRegex(RuntimeError, "恢复失败"):
            callback(1.0 / 60.0)
        callback(1.0 / 60.0)
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        self.open.return_value.close.assert_called_once()

    def test_callback_registration_failure_restores_quality(self):
        """/** @return 帧回调登记失败也关闭文件并恢复宿主设置 */"""
        self.engine.register_slate_post_tick_callback.side_effect = RuntimeError("回调不可用")
        with self.assertRaises(RuntimeError):
            self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "QualityProbe")

        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.assertEqual(self.values["r.ScreenPercentage"], 35.0)
        self.open.return_value.close.assert_called_once()

    def test_invalid_damage_never_reads_world_or_mutates(self):
        """/** @return 无效伤害在访问编辑器和输出文件前拒绝 */"""
        for damage in (-1, 10001, float("nan"), float("inf"), True, "20"):
            with self.assertRaises(RuntimeError):
                self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "WoundProbe", torso_damage=damage)
        self.engine.get_editor_subsystem.assert_not_called()

    def test_wound_measurement_uses_official_damage_input(self):
        """/** @return 每组只经正式入口投递一次且结果记录伤害值 */"""
        self.engine.BBBMassValidationLibrary.damage_population.return_value = 1
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "WoundProbe", torso_damage=20)
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        for second in range(60):
            self.clock[0] = float(second)
            callback(1.0 / 60.0)
        self.assertEqual(next(iter(self.runs.values()))["status"], "completed")
        self.assertEqual(next(iter(self.runs.values()))["torsoDamage"], 20.0)
        self.assertEqual(self.engine.BBBMassValidationLibrary.damage_population.call_count, 2)
        self.engine.BBBMassValidationLibrary.damage_population.assert_called_with(self.world, ["entity"], 20.0)

    def test_damage_failure_restores_frame_limit_and_cleans_entities(self):
        """/** @return 正式伤害投递不完整时明确失败并清理本轮实体 */"""
        self.engine.BBBMassValidationLibrary.damage_population.return_value = 0
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "WoundProbe", torso_damage=20)
        self.engine.register_slate_post_tick_callback.call_args.args[0](1.0 / 60.0)
        self.assertEqual(next(iter(self.runs.values()))["status"], "failed")
        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.engine.BBBMassValidationLibrary.destroy_population.assert_called_once_with(self.world, ["entity"])

    def test_level_name_substring_cannot_select_another_map(self):
        """/** @return 必须严格匹配 PIE 所属关卡的完整包路径 */"""
        with self.assertRaises(RuntimeError):
            self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "WoundProbe")
        self.open.assert_not_called()

    def test_destruction_and_severing_use_one_contribution_submission(self):
        """/** @return 毁伤与断臂共用一次正式输入并记录实际事实 */"""
        self.engine.BBBMonsterDestructionValidationLibrary.inspect_population_destruction.return_value = json.dumps({"entities": [{"regions": [255] * 4 + [0] * 4, "dismemberment": [0, 20, 0, 0, 0]}]})
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "DestructionProbe", destruction_regions=4, sever_left_arm=True)
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        for second in range(60):
            self.clock[0] = float(second)
            callback(1.0 / 60.0)
        report = next(iter(self.runs.values()))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["destructionRegions"], 4)
        self.assertTrue(report["severLeftArm"])
        self.engine.BBBMassValidationLibrary.damage_population.assert_not_called()
        self.assertEqual(self.engine.BBBMonsterDestructionValidationLibrary.set_population_destruction.call_count, 2)
        self.engine.BBBMonsterDestructionValidationLibrary.set_population_destruction.assert_called_with(self.world, ["entity"], 4, True, 0.0)

    def test_missing_destruction_fact_cannot_pass_measurement(self):
        """/** @return 投递成功但实际区域缺失时停止测量并清理群体 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "DestructionProbe", destruction_regions=8)
        callback = self.engine.register_slate_post_tick_callback.call_args.args[0]
        callback(1.0 / 60.0)
        self.clock[0] = 6.0
        callback(1.0 / 60.0)
        self.assertEqual(next(iter(self.runs.values()))["status"], "failed")
        self.engine.BBBMassValidationLibrary.destroy_population.assert_called_once_with(self.world, ["entity"])

    def test_invalid_destruction_never_enters_editor(self):
        """/** @return 错误毁伤参数在世界访问前被拒绝 */"""
        for regions in (-1, 9, True, 1.5):
            with self.assertRaises(RuntimeError):
                self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "/Game/ValidationWorld", "DestructionProbe", destruction_regions=regions)
        self.engine.get_editor_subsystem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
