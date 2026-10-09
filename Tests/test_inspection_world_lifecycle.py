import ast
import json
import math
from pathlib import Path
import re
import unittest
from unittest.mock import Mock


class InspectionWorldLifecycleTests(unittest.TestCase):
    """/** 检查群体按真实世界生命周期隔离 不使用路径散列作为身份 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationPreviewToolset.py").read_text(encoding="utf-8-sig"))
        self.engine = Mock()
        self.world = Mock()
        self.world.get_path_name.return_value = "/Game/Test/UEDPIE_0_Validation.Validation"
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.SystemLibrary.get_command_line.return_value = ""
        self.engine.SystemLibrary.is_valid.side_effect = lambda world: world is self.world
        self.engine.MassEntityConfigAsset = type("Config", (), {})
        config = self.engine.MassEntityConfigAsset()
        self.engine.load_asset.return_value = config
        self.engine.BBBMassValidationLibrary.create_actor_stress_config.return_value = config
        self.engine.BBBMassValidationLibrary.spawn_population.return_value = [object()]
        self.engine.BBBMassValidationLibrary.inspect_population.return_value = '{}'
        self.scope = {"unreal": self.engine, "json": json, "re": re, "_inspection_population": {}, "_population_runs": {}}
        for name in ("spawn_mass_inspection_population", "inspect_mass_inspection_population"):
            method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            method.decorator_list = []
            exec(compile(ast.Module(body=[method], type_ignores=[]), "inspection_world_test", "exec"), self.scope)

    def spawn(self):
        """/** @return 在当前有效世界生成一个检查实体 */"""
        return self.scope["spawn_mass_inspection_population"](["/Game/Config"], [0.0, 0.0, 90.0], 250.0, "/Game/Test/Validation")

    def test_same_live_world_cannot_spawn_twice(self):
        """/** @return 同一轮 PIE 内重复生成仍被拒绝 */"""
        self.spawn()
        with self.assertRaisesRegex(RuntimeError, "重复"):
            self.spawn()
        self.engine.BBBMassValidationLibrary.spawn_population.assert_called_once()

    def test_restarted_pie_with_same_path_can_spawn(self):
        """/** @return 销毁后的同名世界不阻挡下一轮 PIE */"""
        self.spawn()
        previous = self.world
        self.world = Mock()
        self.world.get_path_name.return_value = previous.get_path_name.return_value
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.spawn()
        self.assertIs(self.scope["_inspection_population"]["worldObject"], self.world)
        self.assertEqual(self.engine.BBBMassValidationLibrary.spawn_population.call_count, 2)

    def test_old_entities_cannot_be_inspected_in_new_world(self):
        """/** @return 不把上一轮实体句柄读成当前世界数据 */"""
        self.spawn()
        self.world = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        with self.assertRaisesRegex(RuntimeError, "已结束"):
            self.scope["inspect_mass_inspection_population"]()

    def test_collected_world_wrapper_does_not_block_new_population(self):
        self.spawn()
        previous = self.world
        self.world = Mock()
        self.world.get_path_name.return_value = previous.get_path_name.return_value
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.SystemLibrary.is_valid.side_effect = TypeError("Cannot nativize collected World")
        self.spawn()
        self.assertIs(self.scope["_inspection_population"]["worldObject"], self.world)

    def test_collected_world_wrapper_is_rejected_by_inspection(self):
        self.spawn()
        self.engine.SystemLibrary.is_valid.side_effect = TypeError("Cannot nativize collected World")
        with self.assertRaisesRegex(RuntimeError, "已结束"):
            self.scope["inspect_mass_inspection_population"]()

    def test_formal_hit_population_uses_live_world_identity(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "spawn_mass_hit_acceptance_population")
        method.decorator_list = []
        self.scope.update({"math": math, "_acceptance_population": {}})
        exec(compile(ast.Module(body=[method], type_ignores=[]), "formal_hit_world_test", "exec"), self.scope)
        spawn = self.scope["spawn_mass_hit_acceptance_population"]
        spawn(["/Game/Config"], [0.0, 0.0, 90.0])
        with self.assertRaisesRegex(RuntimeError, "已创建"):
            spawn(["/Game/Config"], [0.0, 0.0, 90.0])
        self.world = Mock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = self.world
        self.engine.SystemLibrary.is_valid.side_effect = TypeError("Cannot nativize collected World")
        spawn(["/Game/Config"], [0.0, 0.0, 90.0])
        self.assertIs(self.scope["_acceptance_population"]["worldObject"], self.world)


if __name__ == "__main__":
    unittest.main()
