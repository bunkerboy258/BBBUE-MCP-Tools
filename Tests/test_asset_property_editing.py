import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


class Value:
    def __init__(self, path='', outer=None, **fields):
        self.path = path
        self.outer = outer
        self.fields = fields

    def get_editor_property(self, name):
        return self.fields[name]

    def get_path_name(self):
        return self.path

    def get_outer(self):
        return self.outer

    def get_outermost(self):
        if self.outer is not None:
            return self.outer.get_outermost()
        return self

    def modify(self):
        pass


class Transaction:
    def __init__(self, name):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AssetPropertyEditingTests(unittest.TestCase):
    def setUp(self):
        self.owner = Value('/Game/_Project/Test.Test')
        self.node = Value(self.owner.path + ':Graph.Node', self.owner,
            node=Value(enabled=False, untouched=17))
        self.saved = []
        self.checked = []
        self.ue = types.SimpleNamespace(Object=Value, StructBase=type('Struct', (), {}),
            World=type('World', (), {}), Actor=type('Actor', (), {}), ActorComponent=type('Component', (), {}),
            load_asset=lambda path: self.owner, load_object=lambda outer, path: self.node,
            ScopedEditorTransaction=Transaction, log=lambda message: None,
            EditorAssetLibrary=types.SimpleNamespace(save_loaded_asset=lambda asset, force: self.saved.append(asset) or True))
        policy = types.SimpleNamespace(require_write_access=self.checked.append)
        source = pathlib.Path(__file__).parents[1] / 'Scripts/BBBAssetPropertyEditing.py'
        spec = importlib.util.spec_from_file_location('asset_property_editing_tested', source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'unreal': self.ue, 'BBBAssetWritePolicy': policy}):
            spec.loader.exec_module(self.module)

    def apply(self, target, name, value):
        if isinstance(value, dict):
            for key, child in value.items():
                self.apply(target.fields[name], key, child)
            return
        target.fields[name] = value

    def run_edit(self, apply=None):
        return self.module.configure(self.node.path, json.dumps({'node': {'enabled': True}}),
            apply or self.apply, lambda value: value, lambda value: value.fields)

    def test_partial_struct_preserves_sibling_and_saves_owner(self):
        self.run_edit()
        self.assertEqual(self.node.fields['node'].fields, {'enabled': True, 'untouched': 17})
        self.assertEqual(self.saved, [self.owner])
        self.assertEqual(self.checked, [self.owner])

    def test_wrong_owner_rejected_before_mutation(self):
        self.node.outer = Value('/Game/_Project/Other.Other')
        with self.assertRaisesRegex(RuntimeError, '不属于'):
            self.run_edit()
        self.assertFalse(self.saved)
        self.assertFalse(self.node.fields['node'].fields['enabled'])

    def test_readback_mismatch_prevents_save(self):
        with self.assertRaisesRegex(RuntimeError, '回读不符'):
            self.run_edit(lambda *args: None)
        self.assertFalse(self.saved)


if __name__ == '__main__':
    unittest.main()
