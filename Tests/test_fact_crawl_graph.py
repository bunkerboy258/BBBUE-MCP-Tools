import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


class FactCrawlGraphTests(unittest.TestCase):
    """/** 爬行构图的权限 参数与保存边界 */"""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_fact_crawl_states")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.AnimSequence = Mock
        self.blueprint = Mock()
        self.sequence = Mock()
        self.engine.load_asset.side_effect = lambda path: self.blueprint if path == "/Game/ABP" else self.sequence
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.blueprint.get_editor_property.return_value = self.engine.BlueprintStatus.BS_UP_TO_DATE
        self.access = Mock()
        scope = {"json": json, "math": math, "unreal": self.engine, "require_write_access": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "crawl_test", "exec"), scope)
        self.call = scope["configure_fact_crawl_states"]
        self.paths = ["/Game/Sequence"] * 6

    def test_explicit_six_sequences_and_exclusive_target(self):
        result = json.loads(self.call("/Game/ABP", self.paths))
        self.access.assert_called_once_with(self.blueprint)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states.assert_called_once_with(self.blueprint, [self.sequence] * 6, 0.18)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.blueprint, False)
        self.assertTrue(result["saved"])

    def test_invalid_parameters_do_not_load_assets(self):
        for paths, duration in [(self.paths[:5], 0.18), (self.paths, math.nan), (self.paths, 0.0), (self.paths, 0.6)]:
            with self.assertRaises(RuntimeError):
                self.call("/Game/ABP", paths, duration)
        self.engine.load_asset.assert_not_called()

    def test_pie_or_checkout_failure_prevents_graph_mutation(self):
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.call("/Game/ABP", self.paths)
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.access.side_effect = RuntimeError("未签出")
        with self.assertRaises(RuntimeError):
            self.call("/Game/ABP", self.paths)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states.assert_not_called()

    def test_native_or_compile_failure_never_saves(self):
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states.return_value = False
        with self.assertRaises(RuntimeError):
            self.call("/Game/ABP", self.paths)
        self.engine.BBBAnimationGraphEditorLibrary.configure_fact_crawl_states.return_value = True
        self.blueprint.get_editor_property.return_value = "Failed"
        with self.assertRaises(RuntimeError):
            self.call("/Game/ABP", self.paths)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_scene_inspection_requires_pie_and_never_writes(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAnimationGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_mass_scene_population")
        method.decorator_list = []
        scope = {"unreal": self.engine}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "scene_test", "exec"), scope)
        with self.assertRaises(RuntimeError):
            scope[method.name]()
        world = object()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = world
        scope[method.name]()
        self.engine.BBBMassValidationLibrary.inspect_population.assert_called_once_with(world, [])
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
