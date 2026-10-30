import ast
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))


class Properties:
    def __init__(self, **values):
        self.values = values

    def get_editor_property(self, name):
        return self.values[name]

    def set_editor_property(self, name, value):
        self.values[name] = value


class Presentation(Properties):
    def __init__(self, outer=None, **values):
        super().__init__(**values)
        self.outer = outer

    def get_outer(self):
        return self.outer

    def get_path_name(self):
        return "/Transient/HitTuning"


class Target(Properties):
    def __init__(self, world):
        super().__init__(presentation_override=None, override_presentation=False)
        self.world = world
        self.status = "idle"
        self.fail_application = False
        self.applications = 0

    def get_world(self):
        return self.world

    def call_method(self, name, arguments):
        if name == "GetHitTrajectoryStatus":
            return json.dumps({"status": self.status})
        if name == "ApplyConfiguration":
            self.applications += 1
            if self.fail_application and self.applications == 1:
                return False
            return True
        raise AssertionError(name)


class ZombieHitTuningTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / "Scripts/BBBHitReactionToolset.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "configure_pie_hit_tuning")
        method.decorator_list = []
        part = Properties(linear_impulse=100.0, angular_impulse=200.0)
        self.source = Presentation(hit_reaction=Properties(torso=part))
        self.world = object()
        self.actor = Target(self.world)

        def duplicate(source, outer, name):
            result = copy.deepcopy(source)
            result.outer = outer
            return result

        unreal = SimpleNamespace(
            BBBZombieHitReactionTarget=Target,
            BBBMonsterPresentationDefinition=Presentation,
            UnrealEditorSubsystem=object,
            get_editor_subsystem=lambda _: SimpleNamespace(get_game_world=lambda: self.world),
            find_object=lambda outer, path: self.actor,
            load_asset=lambda path: self.source,
            SystemLibrary=SimpleNamespace(duplicate_object=duplicate),
        )
        namespace = {"unreal": unreal, "json": json, "math": math, "uuid": uuid}
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        exec(compile(module, str(ROOT), "exec"), namespace)
        self.configure = namespace["configure_pie_hit_tuning"]

    def test_scales_only_the_actor_owned_copy(self):
        result = json.loads(self.configure("actor", "/Game/_Project/Presentation", 0, 0.5, 1.5))
        original = self.source.get_editor_property("hit_reaction").get_editor_property("torso")
        tuned = self.actor.get_editor_property("presentation_override").get_editor_property("hit_reaction").get_editor_property("torso")
        self.assertEqual((original.get_editor_property("linear_impulse"), original.get_editor_property("angular_impulse")), (100.0, 200.0))
        self.assertEqual((tuned.get_editor_property("linear_impulse"), tuned.get_editor_property("angular_impulse")), (50.0, 300.0))
        self.assertEqual(result["saved"], False)
        self.assertIs(self.actor.get_editor_property("presentation_override").get_outer(), self.actor)

    def test_failed_configuration_restores_the_previous_selection(self):
        previous = Presentation()
        self.actor.set_editor_property("presentation_override", previous)
        self.actor.set_editor_property("override_presentation", True)
        self.actor.fail_application = True
        with self.assertRaisesRegex(RuntimeError, "不匹配"):
            self.configure("actor", "/Game/_Project/Presentation", 0)
        self.assertIs(self.actor.get_editor_property("presentation_override"), previous)
        self.assertTrue(self.actor.get_editor_property("override_presentation"))
        self.assertEqual(self.actor.applications, 2)

    def test_rejects_invalid_scale_and_active_capture(self):
        with self.assertRaisesRegex(RuntimeError, "倍率"):
            self.configure("actor", "/Game/_Project/Presentation", 0, float("nan"), 1)
        self.actor.status = "running"
        with self.assertRaisesRegex(RuntimeError, "轨迹采样期间"):
            self.configure("actor", "/Game/_Project/Presentation", 0)
        self.assertFalse(self.actor.get_editor_property("override_presentation"))

    def test_tool_is_scoped_to_pie(self):
        from BBBMcpCapabilities import tool_contract
        contract = tool_contract("BBBHitReactionToolset", "configure_pie_hit_tuning", {"type": "object", "properties": {}})
        self.assertEqual(contract["id"], "hit.configure_pie_hit_tuning")
        self.assertEqual(contract["world"], "pie")


if __name__ == "__main__":
    unittest.main()
