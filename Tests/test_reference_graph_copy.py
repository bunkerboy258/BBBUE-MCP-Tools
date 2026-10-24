import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class ReferenceGraphCopyTests(unittest.TestCase):
    """/** 验证参考图复制的预检与保存边界 */"""

    def setUp(self):
        tree = ast.parse((ROOT / 'Scripts/BBBBlueprintGraphToolset.py').read_text(encoding='utf-8-sig'))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and node.name == 'copy_reference_graph_nodes')
        function.decorator_list = []
        self.source = object()
        self.graph = SimpleNamespace(get_name=lambda: 'UpdatePivotAnim')
        self.blueprint = SimpleNamespace(get_editor_property=lambda name: 'valid')
        self.copy = Mock(return_value=json.dumps({'created': []}))
        self.save = Mock(return_value=True)
        self.require = Mock()
        self.world = None
        library = SimpleNamespace(copy_blueprint_graph_nodes=self.copy)
        unreal = SimpleNamespace(
            BBBAnimationGraphEditorLibrary=SimpleNamespace(inspect_reference_animation_blueprint=lambda *args:
                json.dumps({'graphs': [{'name': 'UpdatePivotAnim', 'path': 'reference'}]})),
            BBBBlueprintEditorLibrary=library,
            load_object=lambda outer, path: self.source,
            load_asset=lambda path: self.blueprint,
            BlueprintGraphEditor=SimpleNamespace(get_graph_editor=lambda source:
                SimpleNamespace(list_all_nodes=lambda: [])),
            BlueprintEditorLibrary=SimpleNamespace(list_graphs=lambda blueprint: [self.graph],
                compile_blueprint=Mock()),
            get_editor_subsystem=lambda cls: SimpleNamespace(get_game_world=lambda: self.world),
            UnrealEditorSubsystem=object,
            BlueprintStatus=SimpleNamespace(BS_UP_TO_DATE='valid'),
            EditorAssetLibrary=SimpleNamespace(save_loaded_asset=self.save))
        namespace = {'os': os, 'json': json, 'unreal': unreal, 'require_write_access': self.require}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<reference-copy-test>', 'exec'), namespace)
        self.call = namespace['copy_reference_graph_nodes']
        self.args = dict(source_file=str(ROOT / 'Reference/Content/Source.uasset'),
            target_asset='/Game/_Project/Target', function_name='UpdatePivotAnim', node_guids=[],
            existing_nodes_json='{}', path_replacements_json='[]', replace_body=True)

    def invoke(self, **options):
        with patch('os.path.isfile', return_value=True):
            return self.call(**self.args, **options)

    def test_preview_never_copies_or_saves(self):
        result = json.loads(self.invoke())
        self.assertTrue(result['dryRun'])
        self.copy.assert_not_called()
        self.save.assert_not_called()
        self.require.assert_not_called()

    def test_pie_rejects_before_mutation(self):
        self.world = object()
        with self.assertRaisesRegex(RuntimeError, 'PIE'):
            self.invoke(dry_run=False)
        self.copy.assert_not_called()
        self.save.assert_not_called()

    def test_native_preflight_failure_never_saves(self):
        self.copy.return_value = '{"error":"UNMAPPED_BOUNDARY"}'
        with self.assertRaisesRegex(RuntimeError, 'UNMAPPED_BOUNDARY'):
            self.invoke(dry_run=False)
        self.save.assert_not_called()

    def test_compile_error_never_saves(self):
        self.blueprint.get_editor_property = lambda name: 'error'
        with self.assertRaisesRegex(RuntimeError, '编译'):
            self.invoke(dry_run=False)
        self.save.assert_not_called()

    def test_success_checks_write_access_then_saves(self):
        result = json.loads(self.invoke(dry_run=False))
        self.require.assert_called_once_with(self.blueprint)
        self.copy.assert_called_once()
        self.save.assert_called_once_with(self.blueprint, False)
        self.assertTrue(result['saved'])


if __name__ == '__main__':
    unittest.main()
