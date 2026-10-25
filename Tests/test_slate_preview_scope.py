import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_contracts import compile_contract


class SlatePreviewScopeTests(unittest.TestCase):
    def contract(self, name):
        return compile_contract({
            "id": "slate_inspector_toolset." + name,
            "definition": "SlateInspectorToolset",
            "name": name,
            "world": "editor",
            "access": "write",
            "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}},
        })

    def test_snapshot_reads_ui_without_asset_write_scope(self):
        contract = self.contract("Snapshot")
        self.assertEqual(contract["access"], "read")
        self.assertEqual(contract["scope"], {"kind": "session"})

    def test_preview_input_uses_ui_session_scope(self):
        for name in ("Click", "Type", "PressKey"):
            contract = self.contract(name)
            self.assertEqual(contract["access"], "write")
            self.assertEqual(contract["scope"], {"kind": "session"})


if __name__ == "__main__":
    unittest.main()
