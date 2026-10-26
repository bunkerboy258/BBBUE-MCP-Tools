import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class MotionMatchingCleanupTests(unittest.TestCase):
    def test_implicit_cached_pose_dependency_survives_pruning(self):
        source = Path(__file__).resolve().parents[1] / 'Scripts' / 'BBBMotionMatchingCleanup.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_prune_graph')
        def row(guid, kind, incoming=()):
            return {'guid': guid, 'path': guid, 'nodeClass': '/Script/AnimGraph.' + kind,
                    'pins': [{'direction': 'input', 'links': [{'nodeGuid': node} for node in incoming]}]}
        snapshot = {'nodes': [row('output', 'AnimGraphNode_Root', ['use']),
                              row('use', 'AnimGraphNode_UseCachedPose'),
                              row('saved', 'AnimGraphNode_SaveCachedPose', ['mm']),
                              row('mm', 'AnimGraphNode_MotionMatching'),
                              row('implicit_pose', 'AnimGraphNode_RefPose'),
                              row('orphan_use', 'AnimGraphNode_UseCachedPose'),
                              row('unused', 'K2Node_VariableGet')]}
        objects = {item['guid']: SimpleNamespace(get_path_name=lambda guid=item['guid']: guid) for item in snapshot['nodes']}
        editor = Mock()
        editor.list_all_nodes.return_value = list(objects.values())
        engine = SimpleNamespace(
            BBBBlueprintEditorLibrary=SimpleNamespace(inspect_blueprint_graph_logical_snapshot=lambda graph: json.dumps(snapshot)),
            BlueprintGraphEditor=SimpleNamespace(get_graph_editor=lambda graph: editor))
        namespace = {'unreal': engine, 'json': json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        namespace['_prune_graph'](object())
        editor.remove_nodes.assert_called_once_with([objects['orphan_use'], objects['unused']])

    def test_dead_execution_path_does_not_survive_through_return_input(self):
        source = Path(__file__).resolve().parents[1] / 'Scripts' / 'BBBMotionMatchingCleanup.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_prune_graph')
        entry = {'guid': 'entry', 'path': 'entry', 'nodeClass': '/Script/BlueprintGraph.K2Node_FunctionEntry',
                 'pins': [{'direction': 'output', 'kind': 'exec', 'links': [{'nodeGuid': 'return'}]}]}
        result = {'guid': 'return', 'path': 'return', 'nodeClass': '/Script/BlueprintGraph.K2Node_FunctionResult',
                  'pins': [{'direction': 'input', 'kind': 'exec', 'links': [{'nodeGuid': 'entry'}, {'nodeGuid': 'dead'}]}]}
        dead = {'guid': 'dead', 'path': 'dead', 'nodeClass': '/Script/BlueprintGraph.K2Node_IfThenElse', 'pins': []}
        snapshot = {'nodes': [entry, result, dead]}
        objects = {item['guid']: SimpleNamespace(get_path_name=lambda guid=item['guid']: guid) for item in snapshot['nodes']}
        editor = Mock()
        editor.list_all_nodes.return_value = list(objects.values())
        engine = SimpleNamespace(
            BBBBlueprintEditorLibrary=SimpleNamespace(inspect_blueprint_graph_logical_snapshot=lambda graph: json.dumps(snapshot)),
            BlueprintGraphEditor=SimpleNamespace(get_graph_editor=lambda graph: editor))
        namespace = {'unreal': engine, 'json': json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        namespace['_prune_graph'](object())
        editor.remove_nodes.assert_called_once_with([objects['dead']])


if __name__ == '__main__':
    unittest.main()
