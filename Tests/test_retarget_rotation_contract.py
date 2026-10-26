import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBMcpCapabilities import ToolCatalog, validate_arguments
from MCP.mcp_contracts import backend_arguments


class RetargetRotationContractTests(unittest.TestCase):
    """/** 完整目录发现必须能登记骨骼四元数的结构化输入 */"""

    def test_rotation_contract_is_discoverable_and_encoded_once(self):
        class Backend:
            def descriptors(self):
                yield "PythonTypes.BBBRetargetAssetAuditToolset", [{"name": "set_retarget_pose_bone_rotations",
                    "inputSchema": {"type": "object", "properties": {
                        "asset_path": {"type": "string"}, "skeleton_side": {"type": "string"},
                        "rotations_json": {"type": "string"}},
                        "required": ["asset_path", "skeleton_side", "rotations_json"]}}]

            def external_contracts(self):
                return []

        catalog = ToolCatalog(Backend())
        contract = catalog.tools["retarget.set_retarget_pose_bone_rotations"]
        arguments = {"asset_path": "/Game/_Project/Retargeter", "skeleton_side": "target",
            "rotations": {"upperarm_l": [0, 0, 0, 1]}}
        validate_arguments(arguments, contract["parameters"])
        native = backend_arguments(contract, arguments)
        self.assertEqual(json.loads(native["rotations_json"]), arguments["rotations"])
        with self.assertRaises(Exception):
            validate_arguments({**arguments, "rotations": {"upperarm_l": [0, 1]}}, contract["parameters"])


if __name__ == "__main__":
    unittest.main()
