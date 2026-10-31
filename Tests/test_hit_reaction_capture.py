import ast
import json
import math
import inspect
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock


class HitReactionCaptureTests(unittest.TestCase):
    """/** 玩家验收与血效重建的失败边界 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        self.access = Mock()
        self.scope = {"unreal": self.engine, "json": json, "math": math, "re": re,
                      "require_write_access": self.access, "_captures": {}}
        for name in ("start_player_weapon_hit_capture", "rebuild_monster_blood_system", "normalize_hit_reaction_arm_bodies"):
            method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            method.decorator_list = []
            exec(compile(ast.Module(body=[method], type_ignores=[]), "hit_reaction_capture_test", "exec"), self.scope)

    def test_capture_rejects_unsafe_paths_and_invalid_timing_before_spawn(self):
        """/** @return 非法输出范围不创建相机或文件 */"""
        call = self.scope["start_player_weapon_hit_capture"]
        for path, duration in (("../OtherTask", 3), ("Task", math.nan), ("Task", 0.1), ("Task", 13)):
            with self.assertRaises(RuntimeError):
                call(path, duration)
        with self.assertRaises(RuntimeError):
            call("Task", width=4096)
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()

    def test_capture_requires_rendering_and_exclusive_capture(self):
        """/** @return 空世界 无渲染或已有采样时拒绝创建相机 */"""
        call = self.scope["start_player_weapon_hit_capture"]
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            call("Task")
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        self.engine.SystemLibrary.get_command_line.return_value = "-NullRHI"
        with self.assertRaises(RuntimeError):
            call("Task")
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.scope["_captures"]["existing"] = {"status": "pending"}
        with self.assertRaises(RuntimeError):
            call("Task")
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()

    def test_asset_rebuild_and_normalization_refuse_live_pie(self):
        """/** @return 运行中不修改物理与粒子资产 */"""
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = True
        with self.assertRaises(RuntimeError):
            self.scope["normalize_hit_reaction_arm_bodies"]("/Game/_Project/PA", "/Game/Mesh")
        with self.assertRaises(RuntimeError):
            self.scope["rebuild_monster_blood_system"](*["/Game/_Project/A"] * 5)
        self.engine.load_asset.assert_not_called()
        self.access.assert_not_called()

    def test_gib_sampling_is_opt_in_and_read_only(self):
        """/** @return 默认不采集碎肢 开启后只查询当帧真实物理 */"""
        call = self.scope["start_player_weapon_hit_capture"]
        self.assertIs(inspect.signature(call).parameters["capture_gibs"].default, False)
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_player_weapon_hit_capture")
        guard = next(node for node in ast.walk(method) if isinstance(node, ast.If)
                     and isinstance(node.test, ast.Name) and node.test.id == "capture_gibs")
        calls = [node.func.attr for node in ast.walk(guard) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertEqual(calls, ["loads", "inspect_gib_presentation"])

    def test_player_observation_does_not_wait_before_weapon_input(self):
        """/** @return 玩家采样不能阻挡正式输入序列 同帧记录实际开火 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_player_weapon_hit_capture")
        registration = next(node for node in ast.walk(method) if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name) and node.func.id == "register_activity")
        options = {item.arg: ast.literal_eval(item.value) for item in registration.keywords}
        self.assertEqual(options, {"blocking": False, "wait": False})

    def test_completion_releases_activity_after_pie_world_is_destroyed(self):
        """/** @return 世界退出后结束记录 不再访问已销毁相机 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_player_weapon_hit_capture")
        complete = next(node for node in ast.walk(method) if isinstance(node, ast.FunctionDef) and node.name == "complete")
        world = object()
        camera = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        record = {"status": "pending", "samples": []}
        with tempfile.TemporaryDirectory() as directory:
            scope = {"unreal": self.engine, "world": world, "camera": camera, "data": {"handle": 1},
                     "record": record, "directory": directory, "os": os, "json": json}
            exec(compile(ast.Module(body=[complete], type_ignores=[]), "hit_capture_completion_test", "exec"), scope)
            scope["complete"](RuntimeError("PIE ended"))
            self.assertEqual(record["status"], "failed")
            self.assertTrue(record["temporaryActorsDestroyed"])
            self.assertEqual(record["sampleFrames"], 0)
            camera.destroy_actor.assert_not_called()
            self.engine.unregister_slate_post_tick_callback.assert_called_once_with(1)
            self.assertTrue(Path(record["reportPath"]).is_file())
            scope["complete"]()
            self.engine.unregister_slate_post_tick_callback.assert_called_once()

    def test_cleanup_and_report_failures_cannot_leave_pending_activity(self):
        """/** @return 清理或报告失败也必须释放进行中状态 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_player_weapon_hit_capture")
        complete = next(node for node in ast.walk(method) if isinstance(node, ast.FunctionDef) and node.name == "complete")
        world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = world
        camera = Mock()
        camera.destroy_actor.side_effect = RuntimeError("Invalid actor")
        record = {"status": "pending", "samples": []}
        scope = {"unreal": self.engine, "world": world, "camera": camera, "data": {"handle": 2},
                 "record": record, "directory": "unused", "os": os, "json": json,
                 "open": Mock(side_effect=OSError("Report unavailable"))}
        exec(compile(ast.Module(body=[complete], type_ignores=[]), "hit_capture_completion_test", "exec"), scope)
        scope["complete"]()
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["temporaryActorsDestroyed"])
        self.assertIn("cleanupError", record)
        self.assertIn("reportError", record)
        self.assertNotIn("samples", record)


if __name__ == "__main__":
    unittest.main()
