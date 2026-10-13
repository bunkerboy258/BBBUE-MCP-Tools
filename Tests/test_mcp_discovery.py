import ast
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBMcpCapabilities import ToolCatalog


DISCOVERY_CASES = [
    ("蓝图 注释 整理", "blueprint.annotate_blueprint_graph"),
    ("读取蓝图逻辑", "blueprint.inspect_blueprint_graph"),
    ("节点区块注释", "blueprint.annotate_blueprint_graph"),
    ("annotate_blueprint_graph", "blueprint.annotate_blueprint_graph"),
    ("inspect_blueprint_graph", "blueprint.inspect_blueprint_graph"),
    ("优化蓝图布局", "blueprint.optimize_blueprint_node_layout"),
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


if __name__ == "__main__":
    unittest.main()
