import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from MCP.mcp_call import McpSession
from MCP.mcp_host_registry import HostRegistry, RegistryGuard, atomic_json, process_identity, project_key
from MCP.mcp_project_host import project_identity
from MCP.mcp_result import McpBusinessError
from MCP.mcp_service import McpService, ProjectRuntime, ensure_service, make_service_server, service_health
from test_mcp_task_gateway import FakeBackend, fixtures, operation


class ConnectedBackend(FakeBackend):
    """/** 常驻服务隔离验收使用的可重连执行端 */"""

    instances = []

    def __init__(self, url, project, pid):
        self.__class__.instances.append(self)
        super().__init__()
        self.url = url
        self.project = project
        self.process_id = pid
        self.state.update(process_id=pid, host_instance=str(pid))
        self.guard = None

    def close(self):
        return


class ServiceTests(unittest.TestCase):
    """/** 真实 HTTP 入口与独立执行端的生命周期验收 */"""

    def setUp(self):
        environment = patch.dict(os.environ, {"CODEX_THREAD_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "Game.uproject"
        self.project.write_text("{}")
        self.registry = HostRegistry([self.project], inventory=lambda: [], identify=lambda pid: None)
        self.service = McpService([self.project], registry=self.registry)
        self.runtime = self.service.projects[self.service.default]
        self.server = make_service_server(self.service, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.port) + "/mcp"
        self.addCleanup(self.close_service)
        self.catalog = fixtures()[1]
        self.patches = [patch("MCP.mcp_service.UnrealBackend", ConnectedBackend),
                        patch("MCP.mcp_service.ToolCatalog", return_value=self.catalog)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def close_service(self):
        self.service.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.runtime.clients.database.close()

    def attach(self, pid):
        row = {"process_id": pid, "created": str(pid), "editor_path": "UnrealEditor.exe", "project": self.runtime.project,
               "project_file": str(self.project), "role": "editor", "backend_url": "http://127.0.0.1:1/bbb-mcp-" + "a" * 32}
        self.registry.hosts[pid] = row
        self.registry.discovered = [{"kind": "editor", "process_id": pid, "project_root": self.runtime.project}]
        self.registry.selected[self.runtime.project] = pid
        self.runtime.retry_at = 0
        self.runtime.reconcile()
        self.assertEqual(self.runtime.state, "ready", self.runtime.error)

    def test_mcp_initializes_and_reports_offline_without_editor(self):
        with McpSession(self.url, 5) as client:
            state = client.inspect_tasks()
            self.assertEqual(state["connection"], "offline")
            self.assertEqual(state["service"], "ready")
            self.assertIsNone(state["host"]["process_id"])
            self.assertEqual(len(client._post("tools/list", {})["result"]["tools"]), 6)
        self.assertEqual(service_health(self.url)["protocol"], 6)

    def test_operator_registration_and_panel_grant_survive_transport_close(self):
        """/** @return 初始化登记与面板授予在短连接之间保持 */"""
        with McpSession(self.url, 5, task="蓝图整理") as first:
            key = first.client_key
            identity = first.operator["id"]
            self.assertEqual(first.operator["level"], 2)
            with McpSession(self.url, 5, task="面板管理", level=0) as admin:
                admin.manage_operator(action="update", operator=identity, level=0)
                rows = admin.inspect_tasks(operators=True)["operators"]["items"]
                self.assertEqual(len(rows), 2)
                self.assertNotIn(key, json.dumps(rows))
        with McpSession(self.url, 5, client_key=key) as resumed:
            self.assertIsNone(resumed.operator)
            self.assertEqual(resumed.inspect_tasks(operators=True)["operators"]["count"], 0)
        with McpSession(self.url, 5, client_key=key, task="新任务") as fresh:
            self.assertEqual(fresh.operator["level"], 2)
            self.assertNotEqual(fresh.operator["id"], identity)

    def test_privileged_host_control_requires_grade_and_exact_project_identity(self):
        """/** @return 宿主无响应时管理动作仍由独立服务核验 */"""
        self.attach(101)
        host_id = self.registry.public()[0]["id"]
        with McpSession(self.url, 5, task="普通任务") as first:
            with self.assertRaises(McpBusinessError) as error:
                first.control_task("terminate_host", host=host_id)
            self.assertEqual(error.exception.value["code"], "OPERATOR_LEVEL_REQUIRED")
        with McpSession(self.url, 5, task="管理宿主", level=0) as admin:
            self.runtime.state = "unresponsive"
            with patch("MCP.mcp_host_registry.terminate_process", return_value={"status": "terminated"}) as terminate:
                result = admin.control_task("terminate_host", host=host_id)
                self.assertEqual(result["process_id"], 101)
                self.assertEqual(terminate.call_count, 1)
                self.assertEqual(terminate.call_args.args[0]["created"], "101")
            with patch("MCP.mcp_host_registry.terminate_process") as terminate:
                with self.assertRaises(McpBusinessError):
                    admin.control_task("terminate_host", host="101:old")
                terminate.assert_not_called()

    def test_sdk_conversation_restores_private_key_and_grade(self):
        """/** @return 同一聊天重建 SDK 时恢复干员 */"""
        with patch("MCP.mcp_service.service_directory", return_value=Path(self.temp.name) / "service"):
            with McpSession(self.url, 5, task="测试归属", level=0, conversation_id="chat-1") as first:
                key = first.client_key
                identity = first.operator["id"]
            with McpSession(self.url, 5, conversation_id="chat-1") as second:
                self.assertEqual(second.client_key, key)
                self.assertIsNone(second.operator)
                renewed = second.manage_operator(task="测试归属")
                self.assertNotEqual(renewed["id"], identity)
                self.assertEqual(renewed["level"], 2)
            with McpSession(self.url, 5, task="另一个聊天", conversation_id="chat-2") as third:
                self.assertNotEqual(third.client_key, key)

    def test_same_client_survives_attach_detach_and_new_editor(self):
        with McpSession(self.url, 5) as client:
            key = client.client_key
            self.attach(101)
            result = client.submit_batch([operation("read", asset="/Game/A")])
            self.assertEqual(result["status"], "completed")
            self.registry.hosts.clear()
            self.registry.selected.clear()
            self.runtime.reconcile()
            self.assertEqual(client.inspect_tasks()["connection"], "offline")
            self.attach(202)
            self.assertEqual(client.client_key, key)
            self.assertEqual(client.inspect_tasks()["host"]["process_id"], 202)
            self.assertEqual(client.submit_batch([operation("read", asset="/Game/B")])["status"], "completed")

    def test_two_clients_keep_private_results_after_host_reconnect(self):
        self.attach(101)
        with McpSession(self.url, 5) as first, McpSession(self.url, 5) as second:
            result = first.submit_batch([operation("read", asset="/Game/A")])
            self.attach(202)
            self.assertEqual(first.inspect_tasks(result["batch"])["status"], "completed")
            with self.assertRaises(McpBusinessError):
                second.inspect_tasks(result["batch"])

    def test_offline_submission_has_one_recovery_action(self):
        with McpSession(self.url, 5) as client:
            with self.assertRaises(McpBusinessError) as raised:
                client.submit_batch([operation("read", asset="/Game/A")])
            self.assertEqual(raised.exception.value["code"], "EDITOR_OFFLINE")
            self.assertEqual(raised.exception.value["next"]["tool"], "inspect_tasks")
            self.assertEqual(raised.exception.value["retry_after_seconds"], 2)

    def test_origin_requests_are_rejected(self):
        from urllib.error import HTTPError
        request = Request(self.url, data=b"{}", headers={"Origin": "https://example.invalid"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(raised.exception.code, 403)
        raised.exception.close()

    def test_cached_catalog_available_after_service_restart(self):
        self.attach(101)
        second = ProjectRuntime(self.project, self.registry)
        try:
            self.assertEqual(second.catalog.version(), self.runtime.catalog.version())
            self.assertEqual(second.catalog.describe("test.read")["id"], "test.read")
        finally:
            second.clients.database.close()

    def test_explicit_project_route_and_default_share_context(self):
        route = self.url.replace("/mcp", "/projects/" + project_key(self.project) + "/mcp")
        with McpSession(route, 5) as client:
            self.assertEqual(client.inspect_tasks()["service"], "ready")

    def test_active_pie_is_adopted_after_service_restart_without_replay(self):
        self.attach(101)
        backend = FakeBackend()
        backend.process_id = 201
        backend.state["process_id"] = 201
        host = types.SimpleNamespace(backend=backend, close=lambda: backend.state.update(pie_active=False, worlds=[]))
        jobs = self.runtime.gateway.jobs
        jobs.factory = lambda batch, options: host
        jobs.version = lambda record: {"digest": "same"}
        owner = jobs.connect()
        result = jobs.submit(owner, [operation("StartPIE")], environment="test", test_options={"map": "/Game/Test"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = jobs.inspect(owner, result["batch"])
            if result["status"] == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(result["status"], "completed")
        jobs.detach()
        for context in jobs.contexts.values():
            context["thread"].join(3)
        second = ProjectRuntime(self.project, self.registry)
        second._restore_test = lambda batch, options, pid: host
        second._version = lambda record: {"digest": "same"}
        try:
            second.reconcile()
            self.assertEqual(second.state, "ready", second.error)
            second.connect(owner)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and second.gateway.jobs.contexts[result["test_host"]]["state"] != "running":
                time.sleep(0.02)
            end = second.submit(owner, [operation("StopPIE")], environment="test", test_host=result["test_host"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                end = second.inspect(owner, end["batch"])
                if end["status"] == "completed":
                    break
                time.sleep(0.02)
            self.assertEqual(end["status"], "completed")
            self.assertEqual(sum(name == "StartPIE" for name, arguments in backend.calls), 1)
        finally:
            if second.gateway:
                second.gateway.jobs.close()
            second.clients.close()


class RegistryTests(unittest.TestCase):
    """/** PID 重用 连接凭据隐藏和资产宿主稳定归属 */"""

    def test_identity_of_running_python_is_exact(self):
        value = process_identity(os.getpid())
        self.assertEqual(value["process_id"], os.getpid())
        self.assertTrue(int(value["created"]) > 0)

    def test_pid_reuse_discards_stale_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Game.uproject"
            project.write_text("{}")
            directory = project.parent / "Saved/McpState/hosts"
            directory.mkdir(parents=True)
            record = {"process_id": 101, "created": "1", "editor_path": "UnrealEditor.exe"}
            atomic_json(directory / "101.json", record)
            registry = HostRegistry([project], inventory=lambda: [], identify=lambda pid: {**record, "created": "2"})
            registry.refresh()
            self.assertEqual(registry.public(), [])
            self.assertFalse((directory / "101.json").exists())

    def test_extra_editor_waits_while_selected_editor_keeps_ownership(self):
        registry = HostRegistry([], inventory=lambda: [])
        project = project_identity("project")
        registry.discovered = [{"process_id": 1, "project_root": project}, {"process_id": 2, "project_root": project}]
        registry.hosts = {pid: {"process_id": pid, "project": project, "role": "editor", "created": str(pid),
                                   "backend_url": "private-secret"} for pid in (1, 2)}
        registry.selected[project] = 1
        guard = RegistryGuard(registry, project, 1)
        self.assertTrue(guard.inspect()["exclusive"])
        self.assertEqual(registry.public()[1]["state"], "waiting_assignment")
        self.assertNotIn("private-secret", json.dumps(registry.public()))

    def test_occupied_nonservice_port_preserves_listener(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as temp:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with patch("MCP.mcp_service.service_health", side_effect=RuntimeError()):
                with self.assertRaisesRegex(RuntimeError, "SERVICE_HANDOVER_REQUIRED"):
                    ensure_service(port=listener.getsockname()[1], directory=temp)
            self.assertGreater(listener.fileno(), 0)


class ServiceProcessTests(unittest.TestCase):
    """/** 在独立端口验证真实服务进程和自动启动 */"""

    def test_two_clients_start_one_service_and_recover_after_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        from MCP.mcp_service import configuration
        with tempfile.TemporaryDirectory() as temp, socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
            reserve.close()
            project = Path(temp) / "Game.uproject"
            project.write_text("{}")
            directory = Path(temp) / "service"
            configuration(project, port, directory)
            url = "http://127.0.0.1:" + str(port) + "/mcp"
            pid = None
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: ensure_service(project, port, directory=directory), range(2)))
                self.assertEqual(results[0]["process_id"], results[1]["process_id"])
                pid = results[0]["process_id"]
                with McpSession(url, 5) as client:
                    state = client.inspect_tasks()
                    self.assertEqual(state["connection"], "offline")
                    key = client.client_key
                os.kill(pid, 15)
                deadline = time.monotonic() + 5
                while process_identity(pid) is not None and time.monotonic() < deadline:
                    time.sleep(0.1)
                with patch.dict(os.environ, {"BBB_MCP_SERVICE_DIRECTORY": str(directory)}):
                    with McpSession(url, 5, client_key=key) as client:
                        self.assertTrue(client._identity_recovered)
                        self.assertEqual(client.inspect_tasks()["service"], "ready")
                pid = service_health(url)["process_id"]
            finally:
                if pid and process_identity(pid):
                    os.kill(pid, 15)
                    deadline = time.monotonic() + 5
                    while process_identity(pid) is not None and time.monotonic() < deadline:
                        time.sleep(0.1)

    def test_restricted_test_process_survives_controller_exit_and_is_reclaimed(self):
        from MCP.mcp_test_process import TestProcess
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "abcdef1234567890"
            directory.mkdir()
            script = "\n".join([
                "import os,sys,json", "sys.path.insert(0,sys.argv[1])",
                "from MCP.mcp_test_process import TestProcess", "from MCP.mcp_host_registry import process_identity",
                "p=TestProcess([sys.executable,'-B','-c','import time;time.sleep(30)'],sys.argv[2],os.environ)",
                "print(json.dumps(process_identity(p.pid)),flush=True)"])
            result = subprocess.run([sys.executable, "-B", "-c", script, str(Path(__file__).resolve().parents[1] / "Scripts"), str(directory)],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout)
            handle = TestProcess.adopt(identity["process_id"], identity["created"], directory.name)
            try:
                self.assertIsNone(handle.poll())
            finally:
                handle.close()
            self.assertIsNone(process_identity(identity["process_id"]))


if __name__ == "__main__":
    unittest.main()
