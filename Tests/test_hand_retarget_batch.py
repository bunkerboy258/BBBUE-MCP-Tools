import ast
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HandRetargetBatchTests(unittest.TestCase):
    """/** 批量握持重定向输入与接触曲线 */"""

    def setUp(self):
        """/** @return 提取不依赖引擎的接触权重函数 */"""
        source = ROOT / "Scripts/BBBHandRetargetBatchToolset.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_contact_weight"
        )
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.contact_weight = namespace["_contact_weight"]

    def test_contact_fades_smoothly_and_returns_to_source(self):
        """/** @return 接触淡入淡出两端权重为零且中段完整生效 */"""
        contacts = [{
            "start_frame": 10,
            "end_frame": 20,
            "fade_in_frames": 4,
            "fade_out_frames": 4,
        }]
        self.assertEqual(self.contact_weight(9, contacts, 1.0), 0.0)
        self.assertEqual(self.contact_weight(10, contacts, 1.0), 0.0)
        self.assertAlmostEqual(self.contact_weight(12, contacts, 1.0), 0.5)
        self.assertEqual(self.contact_weight(14, contacts, 1.0), 1.0)
        self.assertEqual(self.contact_weight(20, contacts, 1.0), 0.0)
        self.assertEqual(self.contact_weight(21, contacts, 1.0), 0.0)

    def test_disjoint_contact_ranges_have_independent_fades(self):
        """/** @return 多个接触区间只采用较高修正权重 */"""
        contacts = [
            {"start_frame": 0, "end_frame": 6, "fade_in_frames": 0, "fade_out_frames": 0},
            {"start_frame": 7, "end_frame": 12, "fade_in_frames": 2, "fade_out_frames": 0},
        ]
        self.assertEqual(self.contact_weight(5, contacts, 0.75), 0.75)
        self.assertAlmostEqual(self.contact_weight(8, contacts, 0.75), 0.375)

    def test_batch_tools_have_explicit_write_scope(self):
        """/** @return 批量 API 的授权路径独立于动画清单 */"""
        capabilities = ast.parse(
            (ROOT / "Scripts/BBBMcpCapabilities.py").read_text(encoding="utf-8-sig")
        )
        contracts = ast.parse(
            (ROOT / "Scripts/MCP/mcp_contracts.py").read_text(encoding="utf-8-sig")
        )
        domains = next(
            node.value for node in capabilities.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "TOOL_DOMAINS"
                for target in node.targets
            )
        )
        policies = next(
            node.value for node in contracts.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "TOOL_POLICIES"
                for target in node.targets
            )
        )
        self.assertEqual(ast.literal_eval(domains)["BBBHandRetargetBatchToolset"], "control_rig")
        values = ast.literal_eval(policies)
        self.assertEqual(
            values["control_rig.build_hand_retarget_sequences"]["scope"]["fields"],
            ["write_paths"],
        )
        self.assertEqual(
            values["control_rig.bake_hand_retarget_sequences"]["scope"]["fields"],
            ["write_paths"],
        )


if __name__ == "__main__":
    unittest.main()
