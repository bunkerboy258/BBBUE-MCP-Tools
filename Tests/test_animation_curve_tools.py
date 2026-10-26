import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Curve:
    def __init__(self, name, keys='cubic user 0 0 weighted'):
        self.name = name
        self.keys = keys

    def export_text(self):
        return 'CurveName="' + self.name + '":' + self.keys

    def get_editor_property(self, name):
        return ''


class Sequence:
    def __init__(self, name, curves=None, length=2):
        self.name = name
        self.curves = curves or []
        self.length = length
        self.data_model_interface = self
        self.controller = self
        self.writes = 0

    def get_class(self):
        return types.SimpleNamespace(get_name=lambda: 'AnimDataModel')

    def get_bone_track_names(self):
        return []

    def get_editor_property(self, name):
        if name == 'CurveData':
            return self
        return self.curves

    def get_play_length(self):
        return self.length

    def get_path_name(self):
        return self.name

    def modify(self):
        self.writes += 1

    def set_curve_color(self, *args):
        return True

    def set_curve_comment(self, *args):
        return True

    def rename_curve(self, old, new, transact):
        for curve in self.curves:
            if curve.name.casefold() == old.name.casefold():
                curve.name = new.name
        return True


class Identifier:
    def set_curve_identifier(self, name, kind):
        self.name = name


class AnimationCurveTests(unittest.TestCase):
    def setUp(self):
        self.assets = {}
        self.saved = []
        self.api = types.SimpleNamespace(
            AnimSequence=Sequence, AnimBlueprint=type('Blueprint', (), {}),
            load_asset=lambda p: self.assets[p],
            AnimationCurveIdentifier=Identifier,
            RawCurveTrackTypes=types.SimpleNamespace(RCT_FLOAT=0),
            AnimationLibrary=types.SimpleNamespace(get_animation_curve_names=lambda a, k: [c.name for c in a.curves]),
            EditorAssetLibrary=types.SimpleNamespace(save_loaded_asset=lambda a, dirty: self.saved.append(a.name) or True),
            BBBBlueprintEditorLibrary=types.SimpleNamespace(copy_animation_float_curves=self.copy))
        self.modules = patch.dict(sys.modules, {'unreal': self.api,
            'BBBAssetWritePolicy': types.SimpleNamespace(require_write_access=lambda a: None)})
        self.modules.start()
        spec = importlib.util.spec_from_file_location('curve_tools_tested', Path(__file__).parents[1] / 'Scripts/BBBAnimationCurveTools.py')
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)

    def tearDown(self):
        self.modules.stop()

    def copy(self, source, target):
        for curve in source.curves:
            target.curves = [c for c in target.curves if c.name != curve.name]
            target.curves.append(Curve(curve.name, curve.keys))
        return len(source.curves)

    def add(self, name, curves=None, length=2):
        path = '/Game/_Project/' + name
        self.assets[path] = Sequence(path, curves, length)
        return path

    def test_rename_preserves_all_key_data(self):
        path = self.add('Source', [Curve('Old')])
        self.tools.rename([path], 'Old', 'New', False)
        self.assertEqual(self.assets[path].curves[0].export_text(), 'CurveName="New":cubic user 0 0 weighted')
        self.assertEqual(self.saved, [path])

    def test_dry_run_does_not_modify(self):
        path = self.add('Source', [Curve('Old')])
        self.tools.rename([path], 'Old', 'New', True)
        self.assertEqual(self.assets[path].writes, 0)
        self.assertFalse(self.saved)

    def test_case_insensitive_original_name(self):
        path = self.add('Source', [Curve('old')])
        self.tools.rename([path], 'Old', 'New', False)
        self.assertEqual(self.assets[path].curves[0].name, 'New')

    def test_duplicate_names_rejected_before_modify(self):
        path = self.add('Source', [Curve('Old'), Curve('New')])
        with self.assertRaises(RuntimeError):
            self.tools.rename([path], 'Old', 'New', False)
        self.assertFalse(self.saved)

    def test_third_party_target_rejected(self):
        with self.assertRaises(RuntimeError):
            self.tools.rename(['/Game/_ThirdParty/Source'], 'Old', 'New', False)

    def test_copy_keeps_unrelated_curves(self):
        source = self.add('Source', [Curve('Control')])
        target = self.add('Target', [Curve('Unrelated', 'unchanged')])
        self.tools.copy(source, [target], False)
        self.assertEqual([c.export_text() for c in self.assets[target].curves],
            ['CurveName="Unrelated":unchanged', 'CurveName="Control":cubic user 0 0 weighted'])

    def test_length_mismatch_rejected_before_copy(self):
        source = self.add('Source', [Curve('Control')])
        target = self.add('Target', length=1)
        with self.assertRaises(RuntimeError):
            self.tools.copy(source, [target], False)
        self.assertFalse(self.saved)
