import ast
import unittest
from pathlib import Path
from unittest.mock import Mock


class AnimationViewCleanupTests(unittest.TestCase):
    """/** 验证结束世界时只报告一次失败并释放跨帧回调 */"""

    def setUp(self):
        """/** @return 隔离的跨帧观察回调 */"""
        self.tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationViewTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "advance_frame")
        self.engine = Mock()
        self.iterator = Mock()
        self.record = {"status": "pending"}
        self.scope = {"unreal": self.engine, "iterator": self.iterator, "record": self.record, "world": object(), "handle": 42}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "animation_view_callback", "exec"), self.scope)

    def test_cleanup_failure_still_unregisters_callback(self):
        """/** @return 清理异常不能触发无穷回调 */"""
        self.iterator.close.side_effect = RuntimeError("World destroyed")
        self.scope["advance_frame"](0.03)
        self.assertEqual(self.record["status"], "failed")
        self.assertEqual(self.record["cleanupError"], "World destroyed")
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(42)

    def test_ended_world_reports_failure_and_closes_iterator(self):
        """/** @return 世界结束后释放当前采样 */"""
        self.scope["advance_frame"](0.03)
        self.assertEqual(self.record["status"], "failed")
        self.iterator.close.assert_called_once_with()
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(42)

    def test_framing_includes_mesh_and_studio_light_is_local(self):
        """/** @return 取景包含真实网格 不修改关卡或源材质 */"""
        source = ast.unparse(self.tree)
        self.assertIn("get_component_bounds(component)", source)
        self.assertIn("ambient_cubemap_intensity", source)
        self.assertIn("is_valid(actor)", source)
        self.assertNotIn("save_loaded_asset", source)
        self.assertNotIn("save_current_level", source)


if __name__ == "__main__":
    unittest.main()
