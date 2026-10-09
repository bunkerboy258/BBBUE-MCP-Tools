import ast
import json
import math
import os
import re
import uuid
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock


class MonsterDamageCaptureTests(unittest.TestCase):
    """/** 验证真实部位损毁截图不绕过伤害入口 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationPreviewToolset.py").read_text(encoding="utf-8-sig"))
        self.method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "capture_monster_hit_scene")
        self.method.decorator_list = []
        self.engine = Mock()
        self.engine.SystemLibrary.get_command_line.return_value = ""
        self.files = Mock()
        scope = {"unreal": self.engine, "math": math, "json": json, "os": self.files, "re": re}
        exec(compile(ast.Module(body=[self.method], type_ignores=[]), "damage_capture_test", "exec"), scope)
        self.capture = scope[self.method.name]

    def test_invalid_damage_and_time_do_not_create_outputs(self):
        """/** @return 非有限伤害或超范围时间不创建文件与临时演员 */"""
        for key, values in (("damage", (math.nan, math.inf, -1.0, 10001.0)), ("sample_seconds", (math.nan, 0.0, 0.119, 3.001))):
            for value in values:
                with self.assertRaises(RuntimeError):
                    self.capture([0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], "BodyDamage", **{key: value})
        self.files.makedirs.assert_not_called()
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()

    def test_requested_damage_is_submitted_through_existing_public_ray(self):
        """/** @return 射线提交实际伤害而非写入生命 Fragment */"""
        calls = [node for node in ast.walk(self.method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "submit_monster_hit_ray"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0].args[2]), "damage")
        loops = [node for node in ast.walk(self.method) if isinstance(node, ast.While)]
        self.assertIn("elapsed < sample_seconds", [ast.unparse(node.test) for node in loops])

    def test_capture_uses_explicit_target_and_game_time(self):
        source = ast.unparse(self.method)
        self.assertIn("focus = unreal.Vector(*view_target)", source)
        self.assertIn("elapsed = unreal.GameplayStatics.get_time_seconds(world) - started_at", source)
        self.assertNotIn("elapsed += delta_seconds", source)

    def build_running_capture(self):
        """/** @return 独立帧回调替身 不创建真实文件或编辑器对象 */"""
        self.engine = MagicMock()
        self.world = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.SystemLibrary.get_command_line.return_value = ""
        self.clock = [10.0]
        self.engine.GameplayStatics.get_time_seconds.side_effect = lambda world: self.clock[0]
        self.actors = [MagicMock(), MagicMock()]
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.side_effect = self.actors
        self.files.path.exists.return_value = False
        self.files.path.join.side_effect = lambda *values: "/".join(map(str, values))
        self.files.path.abspath.side_effect = lambda value: value
        self.files.path.isfile.return_value = True
        self.files.path.getsize.return_value = 2048
        self.ray = Mock()
        self.ray.submit_monster_hit_ray.return_value = json.dumps({"hit": True, "damageSubmitted": True})
        self.captures = {}
        scope = {"unreal": self.engine, "math": math, "json": json, "os": self.files, "re": re,
                 "uuid": uuid, "_transition_captures": self.captures, "BBBAnimationPreviewToolset": self.ray}
        exec(compile(ast.Module(body=[self.method], type_ignores=[]), "running_damage_capture", "exec"), scope)
        scope[self.method.name]([0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], "BodyDamage", damage=60.0, sample_seconds=2.0)
        return self.engine.register_slate_post_tick_callback.call_args.args[0]

    def test_pause_does_not_consume_capture_window(self):
        """/** @return 暂停时保持待采样 恢复游戏时间后只导出一次 */"""
        callback = self.build_running_capture()
        for _ in range(4):
            callback(1.0)
        self.engine.RenderingLibrary.export_render_target.assert_not_called()
        self.clock[0] = 12.0
        callback(0.01)
        callback(0.01)
        self.assertEqual(next(iter(self.captures.values()))["status"], "completed")
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        self.ray.submit_monster_hit_ray.assert_called_once_with([0, 0, 0], [1, 0, 0], 60.0)
        for actor in self.actors:
            actor.destroy_actor.assert_called_once()

    def test_world_ends_before_capture_unregisters_and_cleans(self):
        """/** @return 外部结束 PIE 不遗留截图回调或临时演员 */"""
        callback = self.build_running_capture()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        callback(0.1)
        callback(0.1)
        self.assertEqual(next(iter(self.captures.values()))["status"], "failed")
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        self.engine.RenderingLibrary.export_render_target.assert_not_called()
        for actor in self.actors:
            actor.destroy_actor.assert_called_once()

    def test_one_actor_cleanup_failure_does_not_leak_callback(self):
        """/** @return 已销毁演员的清理异常不阻断其余清理或终止回调 */"""
        callback = self.build_running_capture()
        self.actors[1].destroy_actor.side_effect = RuntimeError("ObjectInstance is null")
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        callback(0.1)
        callback(0.1)
        self.assertEqual(next(iter(self.captures.values()))["status"], "failed")
        self.engine.unregister_slate_post_tick_callback.assert_called_once()
        for actor in self.actors:
            actor.destroy_actor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
