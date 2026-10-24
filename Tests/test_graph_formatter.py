from copy import deepcopy
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBGraphFormatter import verify_formatter_result


class GraphFormatterTests(unittest.TestCase):
    def setUp(self):
        self.before = {"logicSignature": "logic", "nodes": [{"guid": "a", "x": 0, "y": 0, "nodeComment": "手写说明", "pins": [{"links": ["b"]}]}]}

    def test_only_geometry_changes_are_allowed(self):
        after = deepcopy(self.before)
        after["nodes"][0]["x"] = 200
        self.assertEqual(verify_formatter_result(self.before, after)["moved"], 1)

    def test_logical_changes_are_rejected(self):
        after = deepcopy(self.before)
        after["logicSignature"] = "changed"
        with self.assertRaises(RuntimeError):
            verify_formatter_result(self.before, after)

    def test_handwritten_comments_and_connections_are_protected(self):
        for field, value in (("nodeComment", "替换"), ("pins", []), ("guid", "b")):
            after = deepcopy(self.before)
            after["nodes"][0][field] = value
            with self.assertRaises(RuntimeError):
                verify_formatter_result(self.before, after)

    def test_duplicate_identity_is_rejected(self):
        after = deepcopy(self.before)
        after["nodes"].append(deepcopy(after["nodes"][0]))
        with self.assertRaises(RuntimeError):
            verify_formatter_result(self.before, after)

    def test_native_array_is_forwarded_to_plugin_command(self):
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBBlueprintGraphToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "format_blueprint_graph")
        function.decorator_list = []
        calls = []
        native = SimpleNamespace(execute_graph_formatter=lambda graph, ids: calls.append(ids) or json.dumps({"executed": True}))
        fake = SimpleNamespace(BBBBlueprintEditorLibrary=native, load_object=lambda outer, path: object(), EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda value: []), log=lambda value: None)
        namespace = {"unreal": fake, "json": json, "require_write_access": lambda graph: None, "BBBBlueprintGraphToolset": SimpleNamespace(_graph_snapshot=lambda path: json.dumps(self.before))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        result = json.loads(namespace["format_blueprint_graph"]("/Game/Test.Test:Graph", ("a",)))
        self.assertEqual(calls, [["a"]])
        self.assertTrue(result["semanticConnectionsVerified"])


if __name__ == "__main__":
    unittest.main()
