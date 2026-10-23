import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class PreviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.skeleton = object()
        class Mesh:
            def __init__(inner, name):
                inner.name = name
            def get_path_name(inner):
                return inner.name + '.Mesh'
            def get_editor_property(inner, name):
                return self.skeleton
        class Actor:
            pass
        self.source = Mesh('/Game/Arms')
        self.display = Mesh('/Game/Full')
        actor = Actor()
        actor.skeletal_mesh_component = SimpleNamespace(get_skeletal_mesh_asset=lambda: self.display)
        self.binding = SimpleNamespace(get_id=lambda: SimpleNamespace(export_text=lambda: 'character-guid'),
                                       get_object_template=lambda: actor)
        self.mapping = {'source_mesh': '/Game/Arms', 'preview_mesh': '/Game/Full', 'binding': 'character-guid'}
        self.sequence = SimpleNamespace(get_bindings=lambda: [self.binding])
        self.unreal = SimpleNamespace(SkeletalMeshActor=Actor,
            EditorAssetLibrary=SimpleNamespace(get_metadata_tag=lambda *args: json.dumps(self.mapping)))
        specification = importlib.util.spec_from_file_location('preview_under_test',
            Path(__file__).resolve().parents[1] / 'Scripts/BBBWeaponSequencePreview.py')
        self.module = importlib.util.module_from_spec(specification)
        with patch.dict(sys.modules, {'unreal': self.unreal,
            'BBBAssetWritePolicy': SimpleNamespace(require_asset_write=lambda *args: None)}):
            specification.loader.exec_module(self.module)

    def test_explicit_preview_resolves_computation_mesh(self):
        self.assertIs(self.module.mesh_binding(self.sequence, self.source), self.binding)

    def test_display_mesh_resolves_directly(self):
        self.assertIs(self.module.mesh_binding(self.sequence, self.display), self.binding)

    def test_missing_mapping_never_guesses_by_skeleton(self):
        self.unreal.EditorAssetLibrary.get_metadata_tag = lambda *args: ''
        with self.assertRaisesRegex(RuntimeError, 'NOT_UNIQUE'):
            self.module.mesh_binding(self.sequence, self.source)

    def test_changed_binding_is_rejected(self):
        self.mapping['binding'] = 'different-guid'
        with self.assertRaisesRegex(RuntimeError, 'BINDING_CHANGED'):
            self.module.mesh_binding(self.sequence, self.source)

    def test_changed_display_mesh_is_rejected(self):
        self.mapping['preview_mesh'] = '/Game/Other'
        with self.assertRaisesRegex(RuntimeError, 'MESH_CHANGED'):
            self.module.mesh_binding(self.sequence, self.source)

    def test_duplicate_exact_binding_is_rejected(self):
        self.sequence.get_bindings = lambda: [self.binding, self.binding]
        with self.assertRaisesRegex(RuntimeError, 'NOT_UNIQUE'):
            self.module.mesh_binding(self.sequence, self.display)


if __name__ == '__main__':
    unittest.main()
