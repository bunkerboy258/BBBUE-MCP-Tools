import ast
import json
import math
from pathlib import Path
import re
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


if __name__ == "__main__":
    unittest.main()
