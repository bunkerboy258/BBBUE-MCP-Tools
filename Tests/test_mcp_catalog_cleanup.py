import ast
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from MCP.mcp_contracts import backend_arguments, compile_contract
from MCP.mcp_task_gateway import UnrealBackend


class CatalogCleanupTests(unittest.TestCase):
    """/** 重复入口清理与现有对象路径转换 */"""

    def test_table_row_listing_has_one_registered_implementation(self):
        """/** @return 第三方重复入口移除且原生入口支持资产路径 */"""
        backend = object.__new__(UnrealBackend)
        backend.external_name = "test.BBBExternalToolset"
        external = {row["id"] for row in backend.external_contracts()}
        self.assertNotIn("external.data_table.get_row_names", external)
        source = Path(__file__).resolve().parents[1] / "Scripts/MCP/ThirdParty/GenOrca/data_table_actions.py"
        functions = {node.name for node in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("ue_get_row_names", functions)
        contract = compile_contract({"id": "data_table.list_rows", "name": "list_rows", "definition": "DataTableTools", "toolset": "test", "parameters": {"type": "object", "properties": {"data_table": {"type": "object", "properties": {"refPath": {"type": "string"}}}}, "required": ["data_table"]}, "access": "read", "world": "any"})
        self.assertEqual(backend_arguments(contract, {"data_table": "/Game/Tables/Items"}), {"data_table": {"refPath": "/Game/Tables/Items.Items"}})


if __name__ == "__main__":
    unittest.main()
