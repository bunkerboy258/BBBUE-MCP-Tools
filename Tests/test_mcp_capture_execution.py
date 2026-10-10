import ast
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
import BBBMcpCapabilities as capabilities
from MCP.mcp_result import McpExecutionError, McpBusinessError, decode_tool_result
from MCP.mcp_task_gateway import write_execution_evidence


class CaptureExecutionTests(unittest.TestCase):
    """/** 截图业务错误通过真实函数和官方包装保留执行证据 */"""

    def setUp(self):
        """/** @return 准备临时截图目录与引擎替身 */"""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = MagicMock()
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        self.engine.SystemLibrary.get_command_line.return_value = "-RenderOffscreen"
        self.engine.Paths.project_saved_dir.return_value = self.directory.name
        self.actors = [MagicMock(), MagicMock()]
        for actor in self.actors:
            actor.destroy_actor.return_value = True
            actor.is_actor_being_destroyed.return_value = True
        self.engine.SystemLibrary.is_valid.return_value = True
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.side_effect = self.actors
        tree = ast.parse((ROOT / "Scripts" / "BBBAnimationPreviewToolset.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "capture_monster_hit_scene")
        function.decorator_list = []
        self.records = {}
        namespace = {"unreal": self.engine, "json": json, "math": math, "re": re, "os": os, "uuid": uuid,
            "McpExecutionError": McpExecutionError, "_transition_captures": self.records,
            "BBBAnimationPreviewToolset": types.SimpleNamespace(submit_monster_hit_ray=lambda *args: '{"hit":false}')}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "Scripts" / "BBBAnimationPreviewToolset.py"), "exec"), namespace)
        self.capture = namespace["capture_monster_hit_scene"]

    def invoke(self):
        """/** @return 调用实际截图函数 */"""
        return self.capture([0, 0, 0], [100, 0, 0], [0, 10, 100], [50, 0, 0], "Capture")

    def test_existing_image_rejected_before_any_mutation(self):
        """/** @return 重名截图保持登记和引擎状态 */"""
        path = Path(self.directory.name) / "temp" / "Capture" / "Capture.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing")
        with self.assertRaises(McpExecutionError) as error:
            self.invoke()
        self.assertEqual(error.exception.value["execution"]["state"], "rejected")
        self.assertEqual(error.exception.value["code"], "HIT_CAPTURE_EXISTS")
        self.engine.BBBBlueprintEditorLibrary.spawn_transient_pie_actor.assert_not_called()
        self.assertEqual(self.records, {})
        self.assertEqual(path.read_bytes(), b"existing")

    def test_ray_miss_cleans_actors_and_preserves_rejected_evidence(self):
        """/** @return 空射线清理两个临时演员 并明确拒绝状态 */"""
        with self.assertRaises(McpExecutionError) as error:
            self.invoke()
        self.assertEqual(error.exception.value["code"], "HIT_CAPTURE_RAY_MISSED")
        self.assertEqual(error.exception.value["execution"]["state"], "rejected")
        for actor in self.actors:
            actor.destroy_actor.assert_called_once()
        self.assertEqual(self.records, {})

    def test_cleanup_failure_requires_actual_result_review(self):
        """/** @return 清理失败保留部分执行状态 */"""
        self.actors[0].destroy_actor.return_value = False
        with self.assertRaises(McpExecutionError) as error:
            self.invoke()
        self.assertEqual(error.exception.value["execution"]["state"], "partial")
        self.assertEqual(error.exception.value["code"], "HIT_CAPTURE_CLEANUP_FAILED")
        self.assertEqual(self.records, {})

    def test_decorator_and_official_return_value_keep_evidence(self):
        """/** @return 官方字符串协议保留业务失败 同时供网关识别执行状态 */"""
        registry = types.SimpleNamespace(tool_call=lambda method: method.__func__)
        with patch.dict(sys.modules, {"unreal": self.engine, "toolset_registry": registry}), patch.object(capabilities, "native_requirements", return_value={}):
            tool = capabilities.mcp_tool(staticmethod(self.capture))
        result = tool([0, 0, 0], [100, 0, 0], [0, 10, 100], [50, 0, 0], "Capture")
        payload = {"result": {"content": [{"type": "text", "text": json.dumps({"returnValue": result})}]}}
        with self.assertRaises(McpBusinessError):
            decode_tool_result(payload)
        self.assertEqual(write_execution_evidence((200, {}, payload)), ("rejected", "tool_execution_evidence", "HIT_CAPTURE_RAY_MISSED"))

    def test_cleanup_request_requires_observed_destruction(self):
        """/** @return 演员仍有效且处于普通状态时保留核实要求 */"""
        self.actors[0].destroy_actor.return_value = None
        self.actors[0].is_actor_being_destroyed.return_value = False
        with self.assertRaises(McpExecutionError) as error:
            self.invoke()
        self.assertEqual(error.exception.value["execution"]["state"], "partial")
        self.assertIn("ACTOR_DESTROY_UNVERIFIED", error.exception.value["execution"]["details"]["cleanup_errors"])


if __name__ == "__main__":
    unittest.main()
