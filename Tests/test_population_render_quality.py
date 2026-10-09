import ast
import itertools
import json
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
                 "uuid": Mock(), "time": Mock(perf_counter=lambda: self.clock[0]), "open": self.open, "_population_runs": self.runs}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "population_render_quality", "exec"), scope)
        self.start = scope[method.name]

    def test_invalid_quality_never_reads_world_or_mutates(self):
        """/** @return 无效画质在世界查询和文件创建前拒绝 */"""
        for quality in (-1, 4, 1.5, True):
            with self.assertRaises(RuntimeError):
                self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "QualityProbe", quality_level=quality)
        self.engine.get_editor_subsystem.assert_not_called()
        self.engine.SystemLibrary.execute_console_command.assert_not_called()

    def test_full_resolution_settings_report_and_restore(self):
        """/** @return 完整分辨率测量并在正常结束恢复原始画质和三十帧 */"""
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "QualityProbe")
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
        self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "QualityProbe", quality_level=1)
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
            self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "QualityProbe")
        self.engine.SystemLibrary.execute_console_command.assert_not_called()
        self.assertEqual(self.values["t.MaxFPS"], 30.0)

    def test_callback_registration_failure_restores_quality(self):
        """/** @return 帧回调登记失败也关闭文件并恢复宿主设置 */"""
        self.engine.register_slate_post_tick_callback.side_effect = RuntimeError("回调不可用")
        with self.assertRaises(RuntimeError):
            self.start(["/Game/Config"], [1], [0.0, 0.0, 90.0], 200.0, "ValidationWorld", "QualityProbe")
        self.assertEqual(self.values["t.MaxFPS"], 30.0)
        self.assertEqual(self.values["r.ScreenPercentage"], 35.0)
        self.open.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
