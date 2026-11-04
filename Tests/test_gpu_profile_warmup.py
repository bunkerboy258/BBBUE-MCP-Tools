import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class GpuProfileWarmupTests(unittest.TestCase):
    def test_prepare_warms_without_capture_and_repeated_captures_preserve_markers(self):
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBMcpRuntimeToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "profile_scene_gpu")
        method.decorator_list = []
        commands = []
        values = {"r.ProfileGPU.ShowUI": 1, "r.ShowMaterialDrawEvents": 0, "r.EmitMeshDrawEvents": 0}
        original = dict(values)
        frame = [100]

        def command(world, text):
            commands.append(text)
            if text != "ProfileGPU":
                name, value = text.split()
                values[name] = int(value)

        system = SimpleNamespace(execute_console_command=command,
                                 get_console_variable_int_value=lambda name: values.get(name, 0),
                                 get_frame_count=lambda: frame[0])
        unreal = SimpleNamespace(SystemLibrary=system, UnrealEditorSubsystem=object,
                                 get_editor_subsystem=lambda kind: SimpleNamespace(get_game_world=lambda: object()),
                                 Paths=SimpleNamespace(project_log_dir=lambda: "logs"),
                                 log=lambda text: None, log_error=lambda text: None)
        scope = {"unreal": unreal, "json": json, "_snapshot": lambda: {"null_rhi": False},
                 "_scene_gpu_profile_settings": None, "_scene_gpu_profile_ready_frame": None}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
        profile = scope["profile_scene_gpu"]
        with self.assertRaisesRegex(RuntimeError, "prepare"):
            profile("capture")
        self.assertEqual(json.loads(profile("prepare"))["status"], "prepared")
        self.assertEqual(json.loads(profile("capture"))["status"], "warming")
        self.assertNotIn("ProfileGPU", commands)
        marker_commands = list(commands)
        frame[0] += 60
        for _ in range(3):
            self.assertEqual(json.loads(profile("capture"))["status"], "requested")
        self.assertEqual(commands, marker_commands + ["ProfileGPU"] * 3)
        self.assertEqual(json.loads(profile("restore"))["status"], "restored")
        self.assertEqual(values, original)
        self.assertIsNone(scope["_scene_gpu_profile_ready_frame"])
        self.assertEqual(json.loads(profile("restore"))["status"], "idle")


if __name__ == "__main__":
    unittest.main()
