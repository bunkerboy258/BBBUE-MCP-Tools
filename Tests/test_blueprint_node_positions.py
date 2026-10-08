import ast
from copy import deepcopy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class BlueprintNodePositionTests(unittest.TestCase):
    """/** 状态机排版仅能改变明确节点的坐标 */"""

    def setUp(self):
        tree = ast.parse((ROOT / "Scripts/BBBBlueprintGraphToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "set_blueprint_node_positions")
        method.decorator_list = []
        self.snapshot = {"snapshot": "current", "logicSignature": "logic",
                         "nodes": [{"guid": "A", "path": "node", "x": 0, "y": 0}]}
        self.engine = Mock()
        self.access = Mock()
        self.owner = types.SimpleNamespace(inspect_blueprint_graph_logic=lambda path: json.dumps(self.snapshot))
        self.engine.IntPoint.side_effect = lambda x, y: (x, y)

        def move(graph, nodes, positions):
            self.snapshot = deepcopy(self.snapshot)
            self.snapshot["nodes"][0].update(x=positions[0][0], y=positions[0][1])
            return True

        self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.side_effect = move
        namespace = {"unreal": self.engine, "json": json, "require_write_access": self.access,
                     "BBBBlueprintGraphToolset": self.owner}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "node_positions_test", "exec"), namespace)
        self.move = namespace[method.name]
        self.request = [{"nodeGuid": "A", "x": 208, "y": 1440}]

    def test_coordinates_read_back_without_saving(self):
        result = json.loads(self.move("/Game/Main:Graph", "current", json.dumps(self.request)))
        self.assertEqual(result["moved"], self.request)
        self.assertFalse(result["saved"])
        self.access.assert_called_once()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_stale_snapshot_and_invalid_requests_never_write(self):
        with self.assertRaises(RuntimeError):
            self.move("/Game/Main:Graph", "old", json.dumps(self.request))
        for items in [[], self.request * 2, [{"nodeGuid": "missing", "x": 0, "y": 0}],
                      [{"nodeGuid": "A", "x": True, "y": 0}],
                      [{"nodeGuid": "A", "x": 100001, "y": 0}],
                      [{"nodeGuid": "A", "x": 0, "y": 0, "unknown": 0}]]:
            with self.subTest(items=items), self.assertRaises(RuntimeError):
                self.move("/Game/Main:Graph", "current", json.dumps(items))
        self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.assert_not_called()

    def test_permission_and_native_failures_never_save(self):
        self.access.side_effect = RuntimeError("其它会话占用")
        with self.assertRaises(RuntimeError):
            self.move("/Game/Main:Graph", "current", json.dumps(self.request))
        self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.assert_not_called()
        self.access.side_effect = None
        self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.side_effect = None
        self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.return_value = False
        with self.assertRaises(RuntimeError):
            self.move("/Game/Main:Graph", "current", json.dumps(self.request))
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_logic_change_or_wrong_coordinates_rejected(self):
        for field, value in [("logicSignature", "changed"), ("nodes", self.snapshot["nodes"])]:
            self.setUp()
            original = self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.side_effect

            def incorrect(graph, nodes, positions):
                original(graph, nodes, positions)
                self.snapshot[field] = value
                return True

            self.engine.BBBBlueprintEditorLibrary.set_blueprint_graph_node_positions.side_effect = incorrect
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.move("/Game/Main:Graph", "current", json.dumps(self.request))
            self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
