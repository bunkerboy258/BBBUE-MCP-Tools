import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "Scripts"), str(Path(__file__).parent)]
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import UnrealBackend
from MCP.mcp_service import ProjectRuntime
from test_mcp_task_gateway import fixtures, operation


class DeferredShutdownTests(unittest.TestCase):
    """/** 编辑器退出的时序 身份和交接保护 */"""

    def setUp(self):
        """/** @return 独立编辑器帧与实际源码函数 */"""
        self.now = 0
        self.dirty = []
        self.pie = []
        self.events = []
        self.callbacks = {}
        editors = SimpleNamespace(close_all_editors_for_asset=lambda asset: self.events.append("close_blueprint") or 1)
        level = SimpleNamespace(is_in_play_in_editor=lambda: bool(self.pie))
        unreal = SimpleNamespace(
            EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda paused: self.pie),
            LevelEditorSubsystem="level", AssetEditorSubsystem="assets", Blueprint="blueprint",
            get_editor_subsystem=lambda kind: level if kind == "level" else editors,
            EditorLoadingAndSavingUtils=SimpleNamespace(get_dirty_content_packages=lambda: self.dirty, get_dirty_map_packages=lambda: []),
            ObjectIterator=lambda kind: [SimpleNamespace(get_path_name=lambda: "/Game/ABP.ABP")],
            register_slate_post_tick_callback=lambda callback: self.callbacks.setdefault("tick", callback) and "tick",
            unregister_slate_post_tick_callback=lambda handle: self.callbacks.pop(handle),
            SystemLibrary=SimpleNamespace(quit_editor=lambda: self.events.append("quit")),
            log=lambda message: None, log_warning=lambda message: None, log_error=lambda message: None)
        self.runtime = {"unreal": unreal, "json": json, "os": SimpleNamespace(getpid=lambda: 42),
            "time": SimpleNamespace(monotonic=lambda: self.now), "active_activities": lambda: [],
            "_host_state": {"host_instance": "host-a"}}
        tree = ast.parse((ROOT / "Scripts/BBBMcpTaskToolset.py").read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_shutdown_tick", "_shutdown_blocked"}]
        definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BBBMcpTaskToolset")
        request = next(node for node in definition.body if isinstance(node, ast.FunctionDef) and node.name == "request_editor_shutdown")
        request.decorator_list = []
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes + [request], type_ignores=[])), "shutdown", "exec"), self.runtime)

    def request(self):
        """/** @return 正式入口的退出回执 */"""
        return json.loads(self.runtime["request_editor_shutdown"](42, "host-a"))

    def tick(self, now):
        """/** @param now 编辑器时间 @return 推进一步退出时序 */"""
        self.now = now
        self.callbacks["tick"](0.016)

    def test_response_precedes_blueprint_close_and_later_exit(self):
        """/** @return 回执 蓝图窗口关闭和退出分帧执行 */"""
        self.assertEqual(self.request()["status"], "shutdown_requested")
        self.assertEqual(self.events, [])
        self.tick(0.4)
        self.assertEqual(self.events, [])
        self.tick(0.6)
        self.assertEqual(self.events, ["close_blueprint"])
        self.tick(0.9)
        self.assertEqual(self.events, ["close_blueprint", "quit"])
        self.assertEqual(self.callbacks, {})

    def test_identity_and_busy_state_prevent_scheduling(self):
        """/** @return 身份变化 脏包与PIE保持原进程 */"""
        with self.assertRaisesRegex(RuntimeError, "HOST_IDENTITY_CHANGED"):
            self.runtime["request_editor_shutdown"](43, "host-a")
        for values in (self.dirty, self.pie):
            values.append("busy")
            with self.assertRaisesRegex(RuntimeError, "HOST_BUSY"):
                self.request()
            values.clear()
        self.assertEqual(self.callbacks, {})

    def test_new_dirty_package_cancels_exit_at_each_boundary(self):
        """/** @return 请求后及窗口关闭后出现修改时保留编辑器 */"""
        for after_close in (False, True):
            self.setUp()
            self.request()
            if after_close:
                self.tick(0.6)
            self.dirty.append("/Game/NewChange")
            self.tick(1)
            self.assertNotIn("quit", self.events)
            self.assertEqual(self.runtime["_host_state"]["shutdown"]["status"], "shutdown_blocked")
            self.assertEqual(self.callbacks, {})

    def test_repeated_request_keeps_single_callback(self):
        """/** @return 重复请求使用同一退出安排 */"""
        self.request()
        state = self.runtime["_host_state"]["shutdown"]
        self.request()
        self.assertIs(self.runtime["_host_state"]["shutdown"], state)
        self.assertEqual(len(self.callbacks), 1)

    def test_exit_error_is_observable(self):
        """/** @return 退出异常保留明确状态并回收帧回调 */"""
        def fail():
            """/** @return 模拟退出异常 */"""
            raise RuntimeError("exit failed")
        self.runtime["unreal"].SystemLibrary.quit_editor = fail
        self.request()
        self.tick(0.6)
        self.tick(0.9)
        self.assertEqual(self.runtime["_host_state"]["shutdown"]["code"], "EDITOR_SHUTDOWN_FAILED")
        self.assertEqual(self.callbacks, {})


class ShutdownGatewayTests(unittest.TestCase):
    """/** 网关退出回执和失败后的调度恢复 */"""

    def test_failed_request_releases_draining_state(self):
        """/** @return 调用失败恢复可用调度 */"""
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        client = queue.connect()
        def fail():
            """/** @return 模拟私有调用失败 */"""
            raise RuntimeError("request failed")
        backend.shutdown = fail
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            queue.control(client, "shutdown_host")
        self.assertFalse(queue.draining)
        self.assertFalse(queue.shutdown_requested)
        queue.submit(client, [operation("read")])
        self.assertTrue(queue.run_once())

    def test_delayed_busy_state_resumes_dispatch(self):
        """/** @return 延后检查遇到新活动时恢复调度 */"""
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        client = queue.connect()
        self.assertEqual(queue.control(client, "shutdown_host")["status"], "shutdown_requested")
        backend.state["shutdown"] = {"status": "shutdown_blocked", "code": "HOST_BUSY"}
        queue.observe(force=True)
        self.assertFalse(queue.draining)
        self.assertEqual(queue.inspect(client)["shutdown"]["code"], "HOST_BUSY")

    def test_backend_requires_matching_native_receipt(self):
        """/** @return 私有关闭使用确切宿主且核对响应身份 */"""
        backend = object.__new__(UnrealBackend)
        backend.task_name = "Task"
        backend.probe = lambda: {"process_id": 42, "host_instance": "host-a"}
        calls = []
        backend._call = lambda name, arguments: {"tools": [{"name": "request_editor_shutdown"}]} if name == "describe_toolset" else calls.append(arguments) or {"status": "shutdown_requested", "process_id": 42, "host_instance": "host-a"}
        self.assertEqual(backend.shutdown()["process_id"], 42)
        self.assertEqual(calls[0]["tool_name"], "request_editor_shutdown")
        backend._call = lambda name, arguments: {"tools": [{"name": "request_editor_shutdown"}]} if name == "describe_toolset" else {"status": "shutdown_requested", "process_id": 43}
        with self.assertRaises(McpBusinessError):
            backend.shutdown()

    def test_old_editor_requires_loading_updated_toolset(self):
        """/** @return 旧宿主明确报告工具集更新要求 */"""
        backend = object.__new__(UnrealBackend)
        backend.task_name = "Task"
        backend.probe = lambda: {"process_id": 42, "host_instance": "host-a"}
        backend._call = lambda name, arguments: {"tools": []}
        with self.assertRaises(McpBusinessError) as caught:
            backend.shutdown()
        self.assertEqual(caught.exception.value["code"], "EDITOR_TOOLSET_RELOAD_REQUIRED")

    def test_offline_connection_requires_process_exit_readback(self):
        """/** @return 断开连接与实际进程退出分别显示 */"""
        editor = SimpleNamespace(shutdown_requested=True, activity={"process_id": 42})
        runtime = object.__new__(ProjectRuntime)
        runtime.lock = threading.RLock()
        runtime.gateway = SimpleNamespace(jobs=SimpleNamespace(editor=editor, inspect=lambda *args: {"revision": 0, "host": {}}))
        runtime.state = "offline"
        runtime.identity = (42, "created")
        runtime.registry = SimpleNamespace(public=lambda: [], revision=0)
        runtime.clients = SimpleNamespace(operators=SimpleNamespace(revision=0))
        runtime.revision = 0
        runtime.view_signature = None
        runtime.view_revision = 0
        for current, expected in [(None, "exited"), ({"created": "created"}, "exit_pending"), ({"created": "reused"}, "exited")]:
            with patch("MCP.mcp_service.process_identity", return_value=current):
                self.assertEqual(runtime.inspect("client")["shutdown"]["status"], expected)

    def test_shutdown_discovery_returns_direct_public_call(self):
        """/** @return 关闭编辑器关键词直接给出正常退出调用 */"""
        from test_mcp_discovery import fixture_catalog
        catalog = fixture_catalog()
        for query in ("关闭编辑器", "shutdown_host", "quit editor"):
            self.assertEqual(catalog.find(query)[0]["call"], {"tool": "control_task", "arguments": {"action": "shutdown_host"}})


if __name__ == "__main__":
    unittest.main()
