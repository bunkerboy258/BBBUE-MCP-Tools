import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_contracts import compile_contract


class RetargetAuthoringScopeTests(unittest.TestCase):
    def test_retarget_writes_declare_the_actual_asset(self):
        for name, field in (("add_retarget_chain", "ik_rig_path"), ("auto_map_chains", "retargeter_path")):
            contract = compile_contract({"id": "external.retarget." + name, "definition": "RetargetTools", "name": name, "world": "editor", "parameters": {"type": "object", "properties": {field: {"type": "string"}}}, "access": "write"})
            self.assertEqual(contract["scope"], {"fields": [field]})


if __name__ == "__main__":
    unittest.main()
