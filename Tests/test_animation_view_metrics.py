import ast
import math
import types
import unittest
from pathlib import Path


class AnimationViewMetricsTests(unittest.TestCase):
    """/** 验证原生 GPU 计时不会把缺失或无效值当作有效成本 */"""

    def setUp(self):
        """/** @return 隔离的原生计时解析器 */"""
        source = (Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationViewTools.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_read_frame_metrics")
        self.engine = types.SimpleNamespace()
        scope = {"unreal": self.engine, "math": math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "metrics", "exec"), scope)
        self.read = scope["_read_frame_metrics"]

    def reader(self, values):
        """/** @param values 模拟原生数组 @return 设置测试接口 */"""
        self.engine.BBBAnimationGraphEditorLibrary = types.SimpleNamespace(read_performance_frame_metrics=lambda: values)

    def test_missing_native_library_is_unavailable(self):
        """/** @return 缺失接口不制造零耗时 */"""
        self.assertIsNone(self.read())

    def test_missing_native_function_is_unavailable(self):
        """/** @return 缺失方法明确返回空值 */"""
        self.engine.BBBAnimationGraphEditorLibrary = types.SimpleNamespace()
        self.assertIsNone(self.read())

    def test_native_array_preserves_metric_units(self):
        """/** @return 帧号和毫秒值保持原生语义 */"""
        self.reader(iter([101.0, 2.5, 3.0, 4.25, 16.6]))
        self.assertEqual(self.read(), {"frame": 101, "gameThreadMs": 2.5, "renderThreadMs": 3.0, "gpuMs": 4.25, "engineDeltaMs": 16.6})

    def test_zero_gpu_timer_is_unavailable(self):
        """/** @return 无 GPU 计时不能宣称零成本 */"""
        self.reader([101, 0, 0, 0, 16.6])
        result = self.read()
        self.assertIsNone(result["gpuMs"])
        self.assertEqual(result["gameThreadMs"], 0)

    def test_invalid_metrics_are_rejected(self):
        """/** @return 错误长度 非有限和负值必须拒绝 */"""
        for values in [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6], [1, 2, 3, -1, 5], [1, 2, 3, float("nan"), 5], [1, 2, 3, float("inf"), 5]]:
            with self.subTest(values=values):
                self.reader(values)
                with self.assertRaises(RuntimeError):
                    self.read()


if __name__ == "__main__":
    unittest.main()
