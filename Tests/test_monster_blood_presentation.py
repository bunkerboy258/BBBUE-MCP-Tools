import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


class MonsterBloodPresentationTests(unittest.TestCase):
    """/** 定义血效绑定的类型 权限与保存边界 */"""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "Scripts/BBBAssetMaintenanceToolset.py").read_text(encoding="utf-8-sig"))
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertNotIn("configure_monster_blood_impact_system", [node.name for node in functions])
        self.assertNotIn("configure_monster_blood_presentation", [node.name for node in functions])
        method = next(node for node in functions if node.name == "configure_monster_blood_residue")
        method.decorator_list = []
        self.engine = Mock()
        self.engine.BBBMonsterDefinition = Mock
        self.engine.MaterialInterface = Mock
        self.engine.NiagaraDataChannelAsset = Mock
        self.engine.BBBMonsterBloodPresentationDefinition = Mock
        self.definition = Mock()
        self.settings = Mock()
        self.channel = Mock()
        self.material = Mock()
        self.assets = {"/Game/Definition": self.definition, "/Game/Settings": self.settings,
                       "/Game/Channel": self.channel, "/Game/Material": self.material}
        self.engine.load_asset.side_effect = self.assets.get
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = False
        self.definition.get_editor_property.return_value = self.settings
        self.definition.get_path_name.return_value = "/Game/Definition.Definition"
        self.settings.get_path_name.return_value = "/Game/Settings.Settings"
        self.values = {}
        self.settings.set_editor_property.side_effect = self.values.__setitem__
        self.settings.get_editor_property.side_effect = self.values.get
        self.access = Mock()
        scope = {"unreal": self.engine, "json": json, "_move_dirty_packages": lambda: [],
                 "_move_path": lambda value: value, "require_asset_write": self.access}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "blood_presentation_test", "exec"), scope)
        self.call = scope[method.name]
        self.arguments = ("/Game/Settings", "/Game/Channel", ["/Game/Material"], ["/Game/Material"], ["/Game/Material"])

    def test_bind_definition_without_blueprint_or_particle_rebuild(self):
        result = json.loads(self.call(*self.arguments))
        self.access.assert_called_once_with(["/Game/Settings"], [])
        self.definition.modify.assert_not_called()
        self.engine.BlueprintEditorLibrary.compile_blueprint.assert_not_called()
        self.engine.BBBNiagaraEditorLibrary.configure_monster_blood_impact_system.assert_not_called()
        self.assertFalse(result["particleSystemRebuilt"])
        self.assertTrue(result["success"])
        self.assertEqual(self.values["maximum_decals"], 192)
        self.assertEqual(self.values["maximum_flights"], 64)
        self.assertEqual(self.values["maximum_traces_per_frame"], 96)
        self.assertEqual(self.values["decal_lifetime"], 120.0)
        self.assertEqual(self.values["droplet_lifetime"], 50.0)

    def test_old_keyword_and_duplicate_definitions_are_rejected(self):
        with self.assertRaises(TypeError):
            self.call(settings_path="/Game/Settings", channel_path="/Game/Channel",
                      ground_material_paths=["/Game/Material"], actor_blueprint_paths=["/Game/Definition"])
        for definitions in ([], ["/Game/Definition", "/Game/Definition"]):
            with self.assertRaises(RuntimeError):
                self.call(*self.arguments[:3], definitions, self.arguments[4])
        self.engine.load_asset.assert_not_called()

    def test_invalid_asset_types_prevent_write(self):
        self.assets["/Game/Material"] = object()
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.access.assert_not_called()
        self.settings.modify.assert_not_called()

    def test_pie_and_checkout_failure_prevent_mutation(self):
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = True
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.engine.get_editor_subsystem.return_value.is_in_play_in_editor.return_value = False
        self.access.side_effect = RuntimeError("未独占持有")
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.settings.modify.assert_not_called()

    def test_failed_save_or_readback_is_not_success(self):
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = False
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)
        self.definition.modify.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.settings.get_editor_property.side_effect = lambda name: None
        with self.assertRaises(RuntimeError):
            self.call(*self.arguments)


if __name__ == "__main__":
    unittest.main()
