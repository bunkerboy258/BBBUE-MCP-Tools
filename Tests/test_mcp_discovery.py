import ast
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBMcpCapabilities import ToolCatalog
from MCP.mcp_workflows import PURPOSES, ROUTES


DISCOVERY_CASES = [
    ("蓝图 注释 整理", "blueprint.add_blueprint_comment_node"),
    ("读取蓝图逻辑", "blueprint.inspect_blueprint_graph"),
    ("节点区块注释", "blueprint.add_blueprint_comment_node"),
    ("add_blueprint_comment_node", "blueprint.add_blueprint_comment_node"),
    ("inspect_blueprint_graph", "blueprint.inspect_blueprint_graph"),
    ("优化蓝图布局", "blueprint.format_blueprint_graph"),
    ("动画通知事件", "editor.inspect_animation_notifies"),
    ("保存资产", "assets.resave_assets"),
    ("动画蒙太奇片段", "editor.inspect_animation_montage_segments"),
    ("animation montage segments", "editor.inspect_animation_montage_segments"),
    ("LMG_01 换弹 验收", "animation.sample_weapon_handling_runtime"),
    ("run_pie_input_sequence", "animation.run_pie_input_sequence"),
    ("检查重定向器", "retarget.inspect_retargeter"),
    ("读取重定向动画骨骼姿态", "retarget.inspect_animation_poses"),
    ("render_asset_thumbnails", "editor.render_asset_thumbnails"),
]


def fixture_catalog():
    """/** @return 当前领域源码的契约与描述 */"""
    root = Path(__file__).resolve().parents[1]
    schemas = json.loads((root / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8-sig"))
    descriptions = {}
    for module in schemas:
        file = root / "Scripts" / (module + ".py")
        if not file.exists():
            continue
        descriptions[module] = {node.name: ast.get_docstring(node) or "" for node in ast.walk(ast.parse(file.read_text(encoding="utf-8-sig"))) if isinstance(node, ast.FunctionDef)}

    class Backend:
        """/** 只读源码目录 */"""

        def descriptors(self):
            """/** @return 已登记领域描述 */"""
            return [(module, [{"name": name, "inputSchema": schema["inputSchema"], "description": descriptions.get(module, {}).get(name, "")} for name, schema in methods.items()]) for module, methods in schemas.items()]

        def external_contracts(self):
            """/** @return 隔离领域目录 */"""
            return []

    return ToolCatalog(Backend())


class DiscoveryTests(unittest.TestCase):
    """/** 中英文发现与上下文预算验收 */"""

    def test_common_tasks_recall_and_first_contract(self):
        """/** @return 常见目标命中前三项 首项可直接构造调用 */"""
        catalog = fixture_catalog()
        for query, expected in DISCOVERY_CASES:
            with self.subTest(query=query):
                result = catalog.find(query)
                self.assertIn(expected, [item["id"] for item in result])
                self.assertLessEqual(len(result), 3)
                self.assertIn("parameters", result[0])
                self.assertLessEqual(len(json.dumps(result[0], ensure_ascii=False).encode()), 4096)

    def test_external_action_name_does_not_make_entire_domain_an_exact_match(self):
        """/** @return 外部动作按自身名称匹配 */"""
        catalog = fixture_catalog()
        contract = {"id": "external.data_table.get_column_names", "name": "data_table", "action": "get_column_names", "toolset": "test", "definition": "BBBExternalToolset", "parameters": {"type": "object", "properties": {}}, "summary": "List table columns", "access": "read", "world": "any"}
        catalog.add(contract)
        catalog.add({"id": "data_table.list_rows", "name": "list_rows", "toolset": "test", "definition": "DataTableTools", "parameters": {"type": "object", "properties": {}}, "summary": "List data table rows", "access": "read", "world": "any"})
        self.assertEqual(catalog.find("get_column_names")[0]["id"], "external.data_table.get_column_names")
        self.assertNotEqual(catalog.find("data_table")[0]["id"], "external.data_table.get_column_names")

    def test_blueprint_layout_prefers_graph_formatter(self):
        """/** @return 蓝图整理优先返回图表级工具 */"""
        catalog = fixture_catalog()
        for query in ("整理蓝图节点布局", "把蓝图节点摆整齐"):
            self.assertEqual(catalog.find(query)[0]["id"], "blueprint.format_blueprint_graph")

    def test_only_specific_use_guidance_is_returned(self):
        """/** @return 省略重复用途并保留专用路线与完成条件 */"""
        catalog = fixture_catalog()
        named = catalog.describe("blueprint.inspect_blueprint_graph")
        self.assertIn("use_when", named)
        other = next(item for item in catalog.tools.values() if item["id"] not in PURPOSES and item["id"] not in ROUTES)
        compact = catalog.describe(other["id"])
        self.assertNotIn("use_when", compact)
        self.assertIn("complete_when", compact)


if __name__ == "__main__":
    unittest.main()
