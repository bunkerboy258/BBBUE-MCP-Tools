import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "Scripts/BBBMotionMatchingRuntimeProbe.py"


class MotionMatchingRuntimeProbeTests(unittest.TestCase):
    """/** 验证原生采集委托的入口拒绝和生命周期 */"""

    def setUp(self):
        self.engine = Mock()
        self.native = types.SimpleNamespace(
            start_motion_matching_runtime_probe=Mock(return_value='{"state":"running"}'),
            inspect_motion_matching_runtime_probe=Mock(return_value='{"state":"running"}'),
            stop_motion_matching_runtime_probe=Mock(return_value='{"state":"stopped"}'))
        self.engine.BBBMotionMatchingEditorLibrary = self.native
        self.activity = Mock()
        modules = {"unreal": self.engine,
            "BBBMcpCapabilities": types.SimpleNamespace(register_activity=self.activity)}
        self.patcher = patch.dict("sys.modules", modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.namespace = {}
        exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"), self.namespace)

    def test_invalid_bounds_and_paths_rejected_before_engine_access(self):
        for args in [(0, "probe"), (121, "probe"), (float("nan"), "probe"),
                     (20, "../probe"), (20, ""), (20, "a" * 101)]:
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                self.namespace["start"](*args)
        self.engine.get_editor_subsystem.assert_not_called()

    def test_missing_pie_does_not_start_native_capture(self):
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        with self.assertRaises(RuntimeError):
            self.namespace["start"](20, "probe")
        self.native.start_motion_matching_runtime_probe.assert_not_called()

    def test_native_rejection_does_not_register_activity(self):
        self.native.start_motion_matching_runtime_probe.return_value = '{"state":"rejected","error":"active"}'
        with self.assertRaisesRegex(RuntimeError, "active"):
            self.namespace["start"](20, "probe")
        self.activity.assert_not_called()

    def test_explicit_reference_actor_uses_same_native_capture(self):
        actor = object()
        self.engine.find_object.return_value = actor
        self.namespace["start"](15, "SourceGasp", "/Engine/Transient.World:PersistentLevel.Reference")
        self.native.start_motion_matching_runtime_probe.assert_called_once_with(actor, 15, "SourceGasp")
        self.activity.assert_called_once()
        callback = self.activity.call_args.args[1]
        self.assertTrue(callback())
        self.native.inspect_motion_matching_runtime_probe.return_value = '{"state":"completed"}'
        self.assertFalse(callback())

    def test_stop_delegates_cleanup_to_native_owner(self):
        self.assertEqual(json.loads(self.namespace["stop"]())["state"], "stopped")
        self.native.stop_motion_matching_runtime_probe.assert_called_once()
        self.engine.unregister_slate_post_tick_callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
