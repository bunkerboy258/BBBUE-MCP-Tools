import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "Scripts/BBBRecoilAnimationTools.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
FUNCTION = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "recoil_envelope")
NAMESPACE = {}
exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), str(SOURCE), "exec"), NAMESPACE)
envelope = NAMESPACE["recoil_envelope"]


class RecoilEnvelopeTests(unittest.TestCase):
    """/** 验证实际动作包络的最大力度与连射边界 */"""

    def test_peak_and_neutral_tail(self):
        """/** @return 标准动作峰值为一 下一枪前严格归零 */"""
        peak = 0.020833333333333332
        settle = 0.0923076942563057 * 0.9
        self.assertEqual(envelope(peak, peak, settle), 1.0)
        self.assertEqual(envelope(0, peak, settle), 0.0)
        for time in (settle, 0.0923076942563057, 0.2, 100):
            self.assertEqual(envelope(time, peak, settle), 0.0)

    def test_bounded_and_smooth_joins(self):
        """/** @return 不超最大力度 受力峰值与恢复边界速度连续 */"""
        peak = 0.020833333333333332
        settle = 0.08307692483067512
        values = [envelope(index / 100000, peak, settle) for index in range(20001)]
        self.assertGreaterEqual(min(values), 0)
        self.assertLessEqual(max(values), 1)
        epsilon = 0.000001
        for boundary in (0, peak, settle):
            slope = (envelope(boundary + epsilon, peak, settle) - envelope(boundary - epsilon, peak, settle)) / (2 * epsilon)
            self.assertLess(abs(slope), 0.01)


if __name__ == "__main__":
    unittest.main()
