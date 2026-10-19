import ast
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class SequenceReferenceTests(unittest.TestCase):
    """/** 检查引用替换不重建轨道或改写片段其他参数 */"""

    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "replace_sequence_animation_references")
        method.decorator_list = []

        class Asset:
            def __init__(self, path, length=1, skeleton="shared"):
                self.path = path
                self.length = length
                self.skeleton = skeleton

            def get_path_name(self):
                return self.path

            def get_play_length(self):
                return self.length

            def get_editor_property(self, key):
                return getattr(self, key)

        class Params:
            def __init__(self, animation):
                self.animation = animation
                self.other = {"playRate": 0.75, "offset": 4, "reverse": True, "weight": [0.2, 0.7]}

            def export_text(self):
                return json.dumps([self.animation.get_path_name(), self.other], sort_keys=True)

        class Section:
            def __init__(self, animation):
                self.params = Params(animation)
                self.range = (7, 29)
                self.active = False
                self.modified = 0

            def modify(self):
                self.modified += 1

            def get_editor_property(self, key):
                result = copy.copy(self.params)
                result.other = copy.deepcopy(self.params.other)
                return result

            def set_editor_property(self, key, value):
                self.params = copy.copy(value)

        class Track:
            def __init__(self, sections):
                self.sections = sections

            def get_sections(self):
                return self.sections

        self.source = Asset("/Game/Old.Old")
        self.destination = Asset("/Game/New.New")
        self.other = Asset("/Game/Other.Other")
        self.sections = [Section(self.source), Section(self.other)]
        self.track = Track(self.sections)
        self.sequence = SimpleNamespace(get_path_name=lambda: "/Game/LS.LS", get_tracks=lambda: [],
                                        get_bindings=lambda: [SimpleNamespace(get_tracks=lambda: [self.track])], modify=Mock())
        self.assets = {"/Game/Old": self.source, "/Game/New": self.destination, "/Game/Other": self.other, "/Game/LS": self.sequence}
        self.save = Mock(return_value=True)
        self.write = Mock()
        namespace = {"json": json, "math": math, "_asset": lambda path, kind: self.assets[path],
                     "require_write_access": self.write,
                     "unreal": SimpleNamespace(LevelSequence=object, AnimSequence=Asset, MovieSceneSkeletalAnimationTrack=Track,
                                               EditorAssetLibrary=SimpleNamespace(save_loaded_asset=self.save), log=Mock())}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "sequence_references", "exec"), namespace)
        self.run_tool = namespace[method.name]

    def test_dry_run_does_not_write(self):
        result = json.loads(self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New"}'))
        self.assertTrue(result["dryRun"])
        self.write.assert_not_called()
        self.save.assert_not_called()
        self.assertIs(self.sections[0].params.animation, self.source)

    def test_only_reference_changes_in_inactive_offset_section(self):
        before = self.sections[0].params.export_text()
        result = json.loads(self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New"}', False))
        self.assertTrue(result["parametersPreserved"])
        self.assertIs(self.sections[0].params.animation, self.destination)
        self.assertIs(self.sections[1].params.animation, self.other)
        self.assertEqual(self.sections[0].range, (7, 29))
        self.assertFalse(self.sections[0].active)
        restored = self.sections[0].get_editor_property("params")
        restored.animation = self.source
        self.assertEqual(restored.export_text(), before)
        self.save.assert_called_once_with(self.sequence, False)

    def test_missing_mapping_rejects_all_before_write(self):
        with self.assertRaisesRegex(RuntimeError, "没有匹配"):
            self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New","/Game/New":"/Game/Other"}', False)
        self.write.assert_not_called()
        self.assertIs(self.sections[0].params.animation, self.source)

    def test_shared_native_struct_view_not_restored_during_readback(self):
        self.sections[0].get_editor_property = lambda key: self.sections[0].params
        self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New"}', False)
        self.assertIs(self.sections[0].params.animation, self.destination)

    def test_skeleton_and_length_mismatch_rejected(self):
        for field, value in [("skeleton", "different"), ("length", 2)]:
            with self.subTest(field=field):
                previous = getattr(self.destination, field)
                setattr(self.destination, field, value)
                with self.assertRaises(RuntimeError):
                    self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New"}', False)
                setattr(self.destination, field, previous)
        self.write.assert_not_called()

    def test_save_failure_not_success(self):
        self.save.return_value = False
        with self.assertRaisesRegex(RuntimeError, "保存失败"):
            self.run_tool("/Game/LS", '{"/Game/Old":"/Game/New"}', False)


if __name__ == "__main__":
    unittest.main()
