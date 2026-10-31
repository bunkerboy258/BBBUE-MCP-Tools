import ast
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


class MassBehaviorProbeTests(unittest.TestCase):
    """/** 行为探针的边界 与世界生命周期清理验证 */"""

    def setUp(self):
        """/** @return 使用真实文件输出和可推进世界时钟的探针 */"""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.world = object()
        self.now = 0.0
        self.callbacks = {}
        fake = types.SimpleNamespace(
            UnrealEditorSubsystem=object,
            get_editor_subsystem=lambda _: types.SimpleNamespace(get_game_world=lambda: self.world),
            Paths=types.SimpleNamespace(project_saved_dir=lambda: self.directory.name),
            GameplayStatics=types.SimpleNamespace(get_time_seconds=lambda _: self.now),
            SystemLibrary=types.SimpleNamespace(is_valid=lambda _: True),
            BBBMassValidationLibrary=types.SimpleNamespace(inspect_population=lambda *args: json.dumps({"worldSeconds": self.now})),
            register_slate_post_tick_callback=lambda callback: self.callbacks.setdefault(1, callback) and 1,
            unregister_slate_post_tick_callback=lambda handle: self.callbacks.pop(handle),
        )
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationPreviewToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "probe_mass_behavior")
        function.decorator_list = []
        namespace = dict(unreal=fake, json=json, math=math, os=os, re=re, time=time, _behavior_probe={})
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.probe = namespace["probe_mass_behavior"]
        module = types.ModuleType("BBBMcpCapabilities")
        module.register_activity = lambda *args, **kwargs: None
        self.modules = patch.dict(sys.modules, {"BBBMcpCapabilities": module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(lambda: self.probe("stop"))

    def test_invalid_input_creates_no_file(self):
        """/** @return 无效路径和时间不得产生文件或回调 */"""
        for prefix, duration, interval in [("../escape", 1, .2), ("Audit/test", math.nan, .2), ("Audit/test", 1, 0), ("Audit/test", 121, .2)]:
            with self.assertRaises(RuntimeError):
                self.probe("start", prefix, duration, interval)
        self.assertEqual(self.callbacks, {})
        self.assertEqual(list(Path(self.directory.name).rglob("*.jsonl")), [])

    def test_requires_pie(self):
        """/** @return 无 PIE 时不启动后台采样 */"""
        self.world = None
        with self.assertRaises(RuntimeError):
            self.probe("start", "Audit/test", 1, .2)

    def test_completion_closes_output_and_callback(self):
        """/** @return 游戏时间到达上限后数据完整且回调被撤销 */"""
        result = json.loads(self.probe("start", "Audit/test", 1, .2))
        self.callbacks[1](.1)
        self.now = 1.0
        self.callbacks[1](.1)
        report = json.loads(self.probe("status"))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["samples"], 2)
        self.assertEqual(self.callbacks, {})
        self.assertEqual(len(Path(result["path"]).read_text().splitlines()), 2)
        with self.assertRaises(FileExistsError):
            self.probe("start", "Audit/test", 1, .2)

    def test_world_replacement_ends_probe(self):
        """/** @return 世界替换立即结束 不读取另一轮 PIE */"""
        self.probe("start", "Audit/test", 1, .2)
        self.world = object()
        self.callbacks[1](.1)
        self.assertEqual(json.loads(self.probe("status"))["status"], "failed")
        self.assertEqual(self.callbacks, {})

    def test_overlap_rejected_and_stop_releases(self):
        """/** @return 同时只允许一个采样 停止后释放回调 */"""
        self.probe("start", "Audit/first", 1, .2)
        with self.assertRaises(RuntimeError):
            self.probe("start", "Audit/second", 1, .2)
        self.probe("stop")
        self.assertEqual(self.callbacks, {})
        self.assertEqual(json.loads(self.probe("status"))["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
