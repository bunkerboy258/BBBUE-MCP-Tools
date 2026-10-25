import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "Scripts/BBBMotionMatchingRuntimeProbe.py"


class MotionMatchingRuntimeProbeTests(unittest.TestCase):
    """/** 验证采样上限 暂停 去重与失败清理边界 */"""

    def setUp(self):
        self.engine = Mock()
        self.namespace = {}
        with patch.dict("sys.modules", {"unreal": self.engine}):
            exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"), self.namespace)

    def test_invalid_bounds_and_paths_rejected_before_engine_access(self):
        for args in [(0, 0.1, "probe"), (121, 0.1, "probe"),
                     (20, 0.01, "probe"), (float("nan"), 0.1, "probe"),
                     (20, 0.1, "../probe"), (20, 0.1, "")]:
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                self.namespace["start"](*args)
        self.engine.get_editor_subsystem.assert_not_called()

    def test_running_probe_cannot_be_replaced(self):
        self.namespace["_handle"] = object()
        with self.assertRaises(RuntimeError):
            self.namespace["start"](20, 0.1, "probe")
        self.engine.unregister_slate_post_tick_callback.assert_not_called()

    def test_missing_pie_does_not_create_output(self):
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError), patch("builtins.open") as output:
            self.namespace["start"](20, 0.1, "probe")
        output.assert_not_called()

    def prepare_tick(self):
        world = object()
        pawn = object()
        counter = self.namespace["Counter"]()
        self.namespace["_capture"] = {"state": "recording", "world": world, "pawn": pawn,
            "deadline": float("inf"), "last_world_time": -1, "next_sample": 0,
            "sampleInterval": 0.1, "sampleCount": 0, "animations": counter, "errors": []}
        self.namespace["_output"] = io.StringIO()
        self.namespace["_handle"] = 42
        self.engine.SystemLibrary.is_valid.return_value = True
        self.engine.GameplayStatics.get_time_seconds.return_value = 1.0
        native = self.engine.BBBMotionMatchingEditorLibrary.probe_motion_matching_runtime
        native.return_value = json.dumps({"status": "ok", "matches": [
            {"animation": "active", "weight": 1, "directionErrorDegrees": 7},
            {"animation": "inactive", "weight": 0, "directionErrorDegrees": 170}]})
        return native

    def test_paused_world_does_not_duplicate_samples(self):
        native = self.prepare_tick()
        self.namespace["_tick"](0.016)
        self.namespace["_tick"](0.016)
        native.assert_called_once()
        summary = json.loads(self.namespace["inspect"]())
        self.assertEqual(summary["sampleCount"], 1)
        self.assertEqual(summary["directionErrorMean"], 7)
        self.assertEqual(summary["animations"], [["active", 1]])

    def test_native_failure_closes_output_and_unregisters(self):
        native = self.prepare_tick()
        native.return_value = '{"status":"error"}'
        output = self.namespace["_output"]
        self.namespace["_tick"](0.016)
        self.assertTrue(output.closed)
        self.engine.unregister_slate_post_tick_callback.assert_called_once_with(42)
        self.assertEqual(self.namespace["_capture"]["state"], "failed")

    def test_world_ends_before_any_native_sample(self):
        native = self.prepare_tick()
        self.engine.SystemLibrary.is_valid.return_value = False
        self.namespace["_tick"](0.016)
        native.assert_not_called()
        self.assertEqual(self.namespace["_capture"]["state"], "world_ended")

    def test_timeout_releases_callback(self):
        native = self.prepare_tick()
        self.namespace["_capture"]["deadline"] = 0
        self.namespace["_tick"](0.016)
        native.assert_not_called()
        self.assertIsNone(self.namespace["_handle"])
        self.assertEqual(self.namespace["_capture"]["state"], "completed")

    def test_destroyed_unreal_proxy_releases_without_sampling(self):
        native = self.prepare_tick()
        self.engine.SystemLibrary.is_valid.side_effect = TypeError("Deleted Unreal proxy")
        self.namespace["_tick"](0.016)
        native.assert_not_called()
        self.assertEqual(self.namespace["_capture"]["state"], "world_ended")
        self.assertIsNone(self.namespace["_handle"])


if __name__ == "__main__":
    unittest.main()
