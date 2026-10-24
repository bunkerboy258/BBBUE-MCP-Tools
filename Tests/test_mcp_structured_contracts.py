import ast
import json
from pathlib import Path
import sys
import unittest
import tempfile
import base64

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBMcpCapabilities import tool_contract, validate_arguments
from MCP.mcp_contracts import backend_arguments, default_arguments
from MCP.mcp_result import graph_view, result_artifacts, clean_result_artifacts


class StructuredContractTests(unittest.TestCase):
    """/** 全领域结构化输入与图表视图验收 */"""

    def test_every_registered_json_field_has_typed_public_input(self):
        """/** @return 所有领域输入保持显式类型与单一原生编码 */"""
        baseline = json.loads((Path(__file__).parent / "tool_schema_baseline.json").read_text(encoding="utf-8-sig"))
        tested = 0
        expected = 0
        for module, methods in baseline.items():
            for name, value in methods.items():
                contract = tool_contract(module, name, value["inputSchema"])
                if contract is None:
                    continue
                expected += sum(name.endswith("_json") for name in value["inputSchema"].get("properties", {}))
                properties = contract["parameters"].get("properties", {})
                self.assertFalse(any(field.endswith("_json") for field in properties), contract["id"])
                for name, codec in contract["codecs"].items():
                    if codec["encoding"] != "json":
                        continue
                    tested += 1
                    self.assertTrue("type" in properties[name] or "anyOf" in properties[name], contract["id"] + "/" + name)
                    value = [] if properties[name].get("type") == "array" else {}
                    encoded = backend_arguments(contract, {name: value})[codec["field"]]
                    if "empty" not in codec:
                        self.assertEqual(json.loads(encoded), value)
        self.assertEqual(tested, expected)
        self.assertGreater(tested, 0)

    def test_formatter_contract_validates_node_ids(self):
        """/** @return 插件整理节点范围保留结构化类型 */"""
        schema = {"type": "object", "properties": {"graph_path": {"type": "string"}, "node_guids": {"type": "array", "items": {"type": "string"}, "default": []}}, "required": ["graph_path"]}
        contract = tool_contract("BBBBlueprintGraphToolset", "format_blueprint_graph", schema)
        with self.assertRaisesRegex(ValueError, "/arguments/node_guids/0"):
            validate_arguments({"graph_path": "/Game/Test.Test:Graph", "node_guids": [1]}, contract["parameters"])
        validate_arguments({"graph_path": "/Game/Test.Test:Graph", "node_guids": ["guid"]}, contract["parameters"])

    def test_reference_and_property_inputs_use_public_native_boundaries(self):
        """/** @return 路径和属性字典在传输边界编码 */"""
        contract = tool_contract("ObjectTools", "set_properties", {"type": "object", "properties": {"instance": {"type": "object", "properties": {"refPath": {"type": "string"}}}, "values": {"type": "string"}}, "required": ["instance", "values"]})
        arguments = {"instance": "/Game/A.A", "values": {"TwoSided": True}}
        validate_arguments(arguments, contract["parameters"])
        encoded = backend_arguments(contract, arguments)
        self.assertEqual(encoded["instance"], {"refPath": "/Game/A.A"})
        self.assertEqual(json.loads(encoded["values"]), {"TwoSided": True})

    def test_graph_pages_preserve_single_directed_links_and_snapshot(self):
        """/** @return 节点引脚完整 连线按输出方向记录一次 分页绑定版本 */"""
        snapshot = {"snapshot": "one", "nodes": [{"guid": "A", "pins": [{"name": "out", "direction": "output", "links": [{"nodeGuid": "B", "pinName": "in"}]}]}, {"guid": "B", "pins": [{"name": "in", "direction": "input", "links": [{"nodeGuid": "A", "pinName": "out"}]}]}]}
        result = graph_view(snapshot, "logic", limit=1)
        self.assertEqual(len(result["links"]), 1)
        self.assertNotIn("links", result["nodes"][0]["pins"][0])
        self.assertEqual(result["next_page"], {"offset": 1, "expected_snapshot": "one"})
        self.assertEqual(graph_view(snapshot, "logic", offset=1, expected_snapshot="one")["nodes"][0]["guid"], "B")
        with self.assertRaisesRegex(ValueError, "GRAPH_SNAPSHOT_CHANGED"):
            graph_view(snapshot, "logic", offset=1, expected_snapshot="old")

    def test_package_reference_resolves_to_object_and_image_output_is_owned(self):
        """/** @return 包路径统一引用 图像作为所属文件返回并回收 */"""
        contract = {"codecs": {"instance": {"field": "instance", "encoding": "reference"}}}
        self.assertEqual(backend_arguments(contract, {"instance": "/Game/A"})["instance"], {"refPath": "/Game/A.A"})
        self.assertEqual(backend_arguments(contract, {"instance": "/Script/Engine.Actor"})["instance"], {"refPath": "/Script/Engine.Actor"})
        with tempfile.TemporaryDirectory() as task:
            output = Path(task) / "McpResults" / ("a" * 16)
            data = b"\x89PNG\r\n\x1a\n" + b"payload" * 1024
            result = result_artifacts({"success": True, "image_data": base64.b64encode(data).decode(), "width": 64}, output)
            self.assertNotIn("image_data", result)
            self.assertEqual(Path(result["artifact"]["path"]).read_bytes(), data)
            self.assertLess(len(json.dumps(result)), 512)
            clean_result_artifacts(output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
