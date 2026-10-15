from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_clients import ClientRegistry
from MCP.mcp_result import McpBusinessError
from MCP.mcp_call import McpSession
from MCP.mcp_task_gateway import TaskGateway
from MCP.mcp_service import make_service_server
from types import SimpleNamespace
from MCP.mcp_jobs import JobQueue
from Tests.test_mcp_task_gateway import fixtures, operation


class ClientTests(unittest.TestCase):
    """/** 身份寿命与传输重放的隔离验收 */"""

    def test_open_session_survives_other_clients_after_long_idle(self):
        """/** @return HTTP 引用保持身份 心跳恢复任务租期 */"""
        now = [0]
        registry = ClientRegistry(lambda: now[0])
        key = registry.connect()
        session = registry.bind(key)
        for elapsed in (301, 1800, 90000):
            now[0] = elapsed
            registry.connect()
            self.assertEqual(registry.resolve(session), key)
            registry.touch(key)
            self.assertEqual(registry.connect(key), key)

    def test_disconnected_business_owner_can_resume(self):
        """/** @return 业务引用保留原归属 */"""
        now = [0]
        registry = ClientRegistry(lambda: now[0])
        key = registry.connect()
        session = registry.bind(key)
        registry.unbind(session)
        now[0] = 90000
        registry.connect(owners=[key])
        self.assertEqual(registry.connect(key), key)

    def test_replay_preserves_result_and_rejects_changed_payload(self):
        """/** @return 相同请求派发一次 变更请求产生明确拒绝 */"""
        registry = ClientRegistry()
        calls = []
        invoke = lambda: calls.append(1) or {"batch": "one"}
        self.assertEqual(registry.replay("owner", "request", {"a": 1}, invoke), {"batch": "one"})
        self.assertEqual(registry.replay("owner", "request", {"a": 1}, invoke), {"batch": "one"})
        self.assertEqual(calls, [1])
        with self.assertRaises(McpBusinessError) as raised:
            registry.replay("owner", "request", {"a": 2}, invoke)
        self.assertEqual(raised.exception.value["code"], "REQUEST_ID_REUSED")

    def test_http_response_loss_reconnects_and_replays_one_submission(self):
        """/** @return 已执行且响应丢失时返回原批次 */"""
        backend, catalog, unused = fixtures()
        unused.close()
        gateway = TaskGateway(backend, catalog)
        server = make_service_server(SimpleNamespace(projects={"default": SimpleNamespace(protocol=gateway)}, default="default"), 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with McpSession("http://127.0.0.1:" + str(server.server_port) + "/mcp", 5) as session:
                original = session._http.post
                lost = [False]

                def post(*args, **kwargs):
                    """/** @param args\t请求地址 @param kwargs\t请求内容 @return 丢失一次真实响应 */"""
                    response = original(*args, **kwargs)
                    body = kwargs.get("json", {})
                    if body.get("params", {}).get("name") == "submit_batch" and not lost[0]:
                        response.content
                        response.close()
                        lost[0] = True
                        raise requests.ConnectionError("response lost")
                    return response

                with patch.object(session._http, "post", side_effect=post):
                    value = session.submit_batch([operation("read")])
                self.assertEqual(value["status"], "completed")
                self.assertEqual(backend.calls, [("read", {})])
                self.assertEqual(len(gateway.jobs.editor.jobs), 1)
        finally:
            gateway.jobs.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_gateway_restart_restores_owner_and_replay_without_storing_keys(self):
        """/** @return 重启保留归属与唯一结果 磁盘仅保存单向凭证 */"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.sqlite"
            first = ClientRegistry(state_path=path)
            key = first.connect()
            calls = []
            value = first.replay(key, "once", {"operation": 1}, lambda: calls.append(1) or {"batch": "original"})
            first.close()
            second = ClientRegistry(state_path=path)
            self.assertEqual(second.connect(key), key)
            self.assertEqual(second.replay(key, "once", {"operation": 1}, lambda: calls.append(2)), value)
            self.assertEqual(calls, [1])
            second.close()
            self.assertNotIn(key.encode(), path.read_bytes())

    def test_restarted_queue_recovers_scoped_fault_for_original_owner(self):
        """/** @return 恢复后的核实范围允许独立任务继续 */"""
        backend, catalog, unused = fixtures()
        unused.close()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.sqlite"
            backend.reconcile = lambda packages: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
            first = JobQueue(backend, catalog, start_worker=False, state_path=path)
            key = first.connect()
            batch = first.submit(key, [operation("unknown", asset="/Game/A")])["batch"]
            first.run_once()
            first.close()
            first.clients.close()
            second = JobQueue(backend, catalog, start_worker=False, state_path=path)
            try:
                self.assertEqual(second.connect(key), key)
                self.assertEqual(second.inspect(key, batch)["code"], "EXECUTION_UNVERIFIED")
                other = second.connect()
                independent = second.submit(other, [operation("write", asset="/Game/B")])["batch"]
                self.assertTrue(second.run_once())
                self.assertEqual(second.inspect(other, independent)["status"], "completed")
                same = second.submit(other, [operation("write", asset="/Game/A")])["batch"]
                calls_before = list(backend.calls)
                second.run_once()
                self.assertEqual(backend.calls, calls_before)
                self.assertEqual(second.inspect(other, same)["code"], "ASSET_BUSY")
            finally:
                second.close()
                second.clients.close()


if __name__ == "__main__":
    unittest.main()
