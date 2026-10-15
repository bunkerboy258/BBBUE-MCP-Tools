import ast
import json
from pathlib import Path
import math
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ScheduledActorCallTests(unittest.TestCase):
    """/** PIE 游戏时刻调用与世界退出边界 */"""

    def setUp(self):
        """/** @return 不加载编辑器的公开函数测试环境 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBGenericEditorToolset.py").read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BBBGenericEditorToolset")
        function = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "schedule_pie_actor_function")
        function.decorator_list = []
        self.world = object()
        self.current_world = self.world
        self.time = 10.0
        self.callback = None
        actor_type = type("Actor", (), {})
        self.actor = actor_type()
        self.actor.get_world = Mock(return_value=self.world)
        self.actor.is_actor_being_destroyed = Mock(return_value=False)
        self.actor.call_method = Mock(return_value=True)
        self.engine = Mock()
        self.engine.Actor = actor_type
        self.engine.get_editor_subsystem.return_value.get_game_world.side_effect = lambda: self.current_world
        self.engine.find_object.return_value = self.actor
        self.engine.GameplayStatics.get_time_seconds.side_effect = lambda world: self.time
        self.engine.register_slate_post_tick_callback.side_effect = self.register_callback
        self.namespace = {"unreal": self.engine, "json": json, "math": math, "re": re,
            "_pie_scheduled_actor_call": None, "_serialize_value": lambda value: value,
            "_function_argument": lambda value: value}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "scheduled_call_test", "exec"), self.namespace)
        self.activity = Mock()
        self.patch = patch.dict(sys.modules, {"BBBMcpCapabilities": SimpleNamespace(register_activity=self.activity)})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def register_callback(self, callback):
        """/** @param callback 游戏回调 @return 测试句柄 */"""
        self.callback = callback
        return 7

    def call(self, **kwargs):
        """/** @param kwargs 公开调用参数 @return 结构化实际状态 */"""
        return json.loads(self.namespace["schedule_pie_actor_function"](**kwargs))

    def start(self, delay=0.4):
        """/** @param delay 游戏秒 @return 已提交状态 */"""
        return self.call(action="start", actor_path="/PIE/Controller", function_name="SubmitItemSelect",
            arguments_json="[-1]", delay_seconds=delay)

    def test_game_time_not_callback_count_controls_execution(self):
        """/** @return 暂停与较早回调不推进调用时刻 */"""
        self.start()
        for _ in range(5):
            self.callback(1.0)
        self.actor.call_method.assert_not_called()
        self.time = 10.39
        self.callback(0.01)
        self.actor.call_method.assert_not_called()
        self.time = 10.4
        self.callback(0.01)
        self.actor.call_method.assert_called_once_with("SubmitItemSelect", (-1,))
        result = self.call(action="status")
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["executedTime"], 10.4)
        self.assertTrue(result["result"])
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(7)
        self.activity.assert_called_once()

    def test_world_end_cancels_without_calling_actor(self):
        """/** @return 世界退出时注销回调并报告失败 */"""
        self.start()
        self.current_world = None
        self.callback(0.01)
        self.assertEqual(self.call(action="status")["state"], "failed")
        self.actor.call_method.assert_not_called()
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(7)

    def test_actor_end_cancels_without_calling_actor(self):
        """/** @return 目标结束时不向旧对象执行函数 */"""
        self.start()
        self.actor.is_actor_being_destroyed.return_value = True
        self.callback(0.01)
        self.assertEqual(self.call(action="status")["state"], "failed")
        self.actor.call_method.assert_not_called()

    def test_overlap_rejected(self):
        """/** @return 不覆盖尚未完成的定时调用 */"""
        self.start()
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.call(action="status")["requestedTime"], 10.4)

    def test_repeat_calls_once_per_update_and_records_actual_times(self):
        """/** @return 延迟更新不会同帧补发多个调用 每次保留实际时刻 */"""
        self.call(action="start", actor_path="/PIE/Controller", function_name="SubmitPrimaryUse",
            repeat_count=3, interval_seconds=.1)
        self.callback(.01)
        self.time = 10.5
        self.callback(.5)
        self.assertEqual(self.actor.call_method.call_count, 2)
        self.assertEqual(self.call(action="status")["state"], "running")
        self.time = 10.6
        self.callback(.1)
        result = self.call(action="status")
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["executedCount"], 3)
        self.assertEqual([item["time"] for item in result["calls"]], [10, 10.5, 10.6])
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(7)

    def test_invalid_repeat_bounds_rejected(self):
        """/** @return 次数与总时长越界时不登记回调 */"""
        for count, interval in [(0, 0), (601, 0), (True, 0), (2, math.inf), (3, 31), (2, -1)]:
            with self.assertRaises(RuntimeError):
                self.call(action="start", actor_path="/PIE/Controller", function_name="SubmitPrimaryUse",
                    repeat_count=count, interval_seconds=interval)
        self.engine.register_slate_post_tick_callback.assert_not_called()

    def test_invalid_delay_rejected_before_registration(self):
        """/** @return 非有限值与超限游戏秒被拒绝 */"""
        for value in [math.nan, math.inf, -1.0, 61.0]:
            with self.assertRaises(RuntimeError):
                self.start(value)
        self.engine.register_slate_post_tick_callback.assert_not_called()

    def test_reflection_failure_is_reported_and_unregistered(self):
        """/** @return 反射失败不会遗留重复执行回调 */"""
        self.start(0)
        self.actor.call_method.side_effect = RuntimeError("函数参数无效")
        self.callback(0.01)
        result = self.call(action="status")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["errors"], ["函数参数无效"])
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
