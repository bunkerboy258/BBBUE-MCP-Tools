import importlib.util
import json
from pathlib import Path
import sys
import types
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class AnimationLibraryImportTests(unittest.TestCase):
    def load_module(self):
        calls = []
        system = types.SimpleNamespace(get_console_variable_bool_value=lambda name: True, execute_console_command=lambda world, command: calls.append(command))
        unreal = types.SimpleNamespace(SystemLibrary=system)
        policy = types.SimpleNamespace(require_asset_write=lambda *args: self.fail("preflight must not write"))
        specification = importlib.util.spec_from_file_location("library_import_test", ROOT / "Scripts/BBBAnimationLibraryImport.py")
        module = importlib.util.module_from_spec(specification)
        with patch.dict(sys.modules, {"unreal": unreal, "BBBAssetWritePolicy": policy}):
            specification.loader.exec_module(module)
        return module, calls

    def test_failed_import_restores_interchange_switch(self):
        module, calls = self.load_module()
        with self.assertRaisesRegex(RuntimeError, "factory failed"):
            with module.legacy_fbx_import():
                raise RuntimeError("factory failed")
        self.assertEqual(calls, ["Interchange.FeatureFlags.Import.FBX 0", "Interchange.FeatureFlags.Import.FBX 1"])

    def test_duplicate_destinations_rejected_before_write(self):
        module, calls = self.load_module()
        with self.assertRaises(RuntimeError):
            module.import_animation_library_batch(json.dumps([{"asset_path": "/Game/Clip"}, {"asset_path": "/Game/Clip"}]))
        self.assertEqual(calls, [])

    def test_roll_is_named_and_animation_uses_editor_skeleton_property(self):
        module, calls = self.load_module()
        skeleton = type("Skeleton", (), {})()
        mesh = type("SkeletalMesh", (), {"skeleton": skeleton})()
        sequence_type = type("AnimSequence", (), {
            "get_outermost": lambda self: types.SimpleNamespace(get_path_name=lambda: "/Game/NewClip"),
            "get_editor_property": lambda self, name: skeleton,
            "set_preview_skeletal_mesh": lambda self, value: None,
            "get_play_length": lambda self: 1.0,
            "data_model_interface": types.SimpleNamespace(get_number_of_keys=lambda: 31),
        })
        sequence = sequence_type()
        settings = {}
        data = types.SimpleNamespace(set_editor_property=lambda name, value: settings.update({name: value}))
        unreal = module.unreal
        unreal.Skeleton = type(skeleton)
        unreal.SkeletalMesh = type(mesh)
        unreal.AnimSequence = sequence_type
        unreal.load_asset = lambda path: skeleton if path == "/Game/Skeleton" else mesh
        unreal.EditorAssetLibrary = types.SimpleNamespace(does_asset_exist=lambda path: False, save_loaded_asset=lambda *args: True)
        unreal.FbxImportUI = lambda: types.SimpleNamespace(anim_sequence_import_data=data)
        unreal.FBXImportType = types.SimpleNamespace(FBXIT_ANIMATION=1)
        unreal.Rotator = lambda **values: values
        unreal.AssetImportTask = lambda: types.SimpleNamespace(get_objects=lambda: [sequence])
        unreal.FbxFactory = lambda: object()
        unreal.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=lambda tasks: None))
        module.require_asset_write = lambda *args: None
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.fbx"
            source.write_bytes(b"source")
            result = module.import_animation_library_batch(json.dumps([{"source_file": str(source), "asset_path": "/Game/NewClip", "skeleton_path": "/Game/Skeleton", "mesh_path": "/Game/Mesh", "import_roll": 90}]))
        self.assertEqual(settings["import_rotation"], {"pitch": 0.0, "yaw": 0.0, "roll": 90.0})
        self.assertEqual(json.loads(result)["saved"][0]["keys"], 31)
        self.assertEqual(calls[-1], "Interchange.FeatureFlags.Import.FBX 1")


if __name__ == "__main__":
    unittest.main()
