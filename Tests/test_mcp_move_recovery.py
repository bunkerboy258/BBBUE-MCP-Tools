import copy
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "Scripts"), str(Path(__file__).resolve().parent)]
from MCP.mcp_result import McpBusinessError, McpExecutionError
from MCP.mcp_response import response
from MCP.mcp_jobs import JobQueue
from MCP.mcp_task_gateway import TaskGateway
from test_mcp_task_gateway import fixtures, operation
import test_asset_move_persistence as persistence_tests


class MoveRecoveryTests(unittest.TestCase):
    """/** 已改名 保存故障与干员收尾组合的隔离检查 */"""

    def setUp(self):
        """/** @return 独立时钟与迁移故障后端 */"""
        self.now = 0
        self.backend, self.catalog, self.queue = fixtures(clock=lambda: self.now)
        self.addCleanup(self.queue.close)
        self.owner = self.queue.connect()
        self.other = self.queue.connect()
        self.queue.clients.operators.manage(self.owner, task="迁移资产", level=0)
        self.catalog.add({"id": "assets.move_assets_batch", "name": "move_assets_batch", "toolset": "test", "definition": "Test",
            "parameters": {"type": "object", "properties": {"moves": {"type": "array", "items": {"type": "object"}}}},
            "access": "write", "world": "editor", "summary": "迁移资产"})
        self.record = {"assets": [{"source": "/Game/Old/A", "destination": "/Game/New/A"}],
            "referencer_packages": ["/Game/Ref"], "object_results": [{"source": "/Game/Old/A", "renamed": True}]}
        self.backend.expand_scope = lambda operation: {"/Game/Ref"}
        self.invocation = self.backend.invoke
        self.recover_calls = []
        def invoke(contract, arguments):
            """/** @param contract 契约 @param arguments 参数 @return 已改名后故障 */"""
            if contract["id"] == "assets.move_assets_batch":
                self.backend.calls.append((contract["name"], copy.deepcopy(arguments)))
                self.backend.state["dirty_packages"] = ["/Game/Old/A", "/Game/Ref"]
                raise McpExecutionError("partial", "ASSET_MOVE_INCOMPLETE", "部分保存失败", {"recovery": self.record})
            return self.invocation(contract, arguments)
        self.backend.invoke = invoke
        self.backend.finalize = lambda packages: (_ for _ in ()).throw(AssertionError("普通保存接触迁空源包"))
        def recover(record):
            """/** @param record 原批次证据 @return 暂时保存失败 */"""
            self.recover_calls.append(copy.deepcopy(record))
            raise McpExecutionError("partial", "ASSET_MOVE_INCOMPLETE", "引用者仍被锁定", {"recovery": record})
        self.backend.recover_asset_moves = recover

    def submit_move(self):
        """/** @return 唯一迁移批次 */"""
        batch = self.queue.submit(self.owner, [{"tool": "assets.move_assets_batch",
            "arguments": {"moves": [{"source": "/Game/Old/A", "destination": "/Game/New/A"}]}}])["batch"]
        self.queue.run_once()
        return batch

    def test_finished_operator_can_only_recover_own_batch(self):
        """/** @return 收尾权限仅覆盖原批次并保持原失败证据 */"""
        batch = self.submit_move()
        self.queue.clients.operators.manage(self.owner, action="finish")
        with self.assertRaises(McpBusinessError) as caught:
            self.queue.clients.operators.manage(self.owner, task="继续迁移", level=0)
        self.assertEqual(caught.exception.value["next"], {"tool": "control_task", "arguments": {"action": "recover", "batch": batch}})
        self.assertEqual(self.queue.clients.operators.level(self.owner), 2)
        with self.assertRaises(McpBusinessError):
            self.queue.control(self.other, "recover", batch)
        with self.assertRaises(McpBusinessError):
            self.queue.submit(self.owner, [operation("write", asset="/Game/Other")])
        self.backend.recover_asset_moves = lambda report: self.backend.state.update(dirty_packages=[]) or {"success": True, "persistence": {"saved_packages": ["/Game/New/A", "/Game/Ref"]}}
        self.queue.control(self.owner, "recover", batch)
        self.queue.run_once()
        value = self.queue.inspect(self.owner, batch)
        self.assertEqual(value["status"], "failed")
        self.assertTrue(value["proof"]["move_recovery"]["success"])
        self.assertEqual(self.queue.assets.claims, {})
        self.assertEqual(sum(name == "move_assets_batch" for name, arguments in self.backend.calls), 1)
        renewed = self.queue.clients.operators.manage(self.owner, task="新任务")
        self.assertEqual(renewed["level"], 2)

    def test_zero_level_takes_over_fault_and_fences_original_client(self):
        """/** @return 零级接管持久化归属 原客户端失去控制权限并保留审计 */"""
        batch = self.submit_move()
        previous = self.queue.jobs[batch]["operator"]
        self.queue.clients.operators.manage(self.owner, action="finish")
        self.queue.clients.operators.manage(self.other, task="接管迁移收尾", level=0)
        self.queue.control(self.other, "recover", batch)
        self.assertEqual(self.queue.jobs[batch]["owner"], self.other)
        self.assertEqual(self.queue.jobs[batch]["operator"], self.queue.clients.operators.identity(self.other))
        audit = next(row for row in self.queue.clients.operators.audit if row["action"] == "takeover_recovery")
        self.assertEqual(audit["previous_operator"], previous)
        with self.assertRaises(McpBusinessError):
            self.queue.control(self.owner, "recover", batch)
        self.backend.recover_asset_moves = lambda report: self.backend.state.update(dirty_packages=[]) or {"success": True}
        self.queue.run_once()
        self.assertNotIn(batch, self.queue.assets.claims)
        self.assertTrue(self.queue.inspect(self.other, batch)["proof"]["move_recovery"]["success"])
        self.assertEqual(sum(name == "move_assets_batch" for name, arguments in self.backend.calls), 1)

    def test_takeover_requires_zero_level_and_terminal_fault(self):
        """/** @return 普通干员与正在执行批次维持归属 */"""
        batch = self.submit_move()
        self.queue.clients.operators.manage(self.other, task="接管迁移收尾")
        with self.assertRaises(McpBusinessError) as caught:
            self.queue.control(self.other, "recover", batch)
        self.assertEqual(caught.exception.value["code"], "OPERATOR_LEVEL_REQUIRED")
        self.queue.clients.operators.manage(self.other, level=0)
        for state in ("running", "queued"):
            self.queue.jobs[batch]["status"] = state
            with self.assertRaises(McpBusinessError) as caught:
                self.queue.control(self.other, "recover", batch)
            self.assertEqual(caught.exception.value["code"], "BATCH_ACTIVE")
            self.assertEqual(self.queue.jobs[batch]["owner"], self.owner)

    def test_takeover_is_persisted_across_service_restart(self):
        """/** @return 重启恢复接管身份并保留迁移证据 */"""
        stored = {}
        self.queue.clients.store_job = lambda row: stored.update({row["id"]: copy.deepcopy(row)})
        self.queue.clients.stored_jobs = lambda: list(copy.deepcopy(stored).values())
        batch = self.submit_move()
        self.queue.clients.operators.manage(self.other, task="接管迁移收尾", level=0)
        self.queue.control(self.other, "recover", batch)
        self.assertEqual(stored[batch]["owner"], self.queue.clients.digest(self.other))
        restored = JobQueue(self.backend, self.catalog, clock=lambda: self.now, start_worker=False, clients=self.queue.clients)
        self.addCleanup(restored.close)
        restored.connect(resume_key=self.other)
        self.assertEqual(restored.jobs[batch]["owner"], self.other)
        self.assertEqual(restored.jobs[batch]["move_recovery"], self.record)

    def test_automatic_recovery_stops_after_bounded_failures(self):
        """/** @return 确定失败返回明确恢复动作并保留证据 */"""
        batch = self.submit_move()
        for instant in (100, 200, 300):
            self.now = instant
            self.queue.run_once()
        value = self.queue.inspect(self.owner, batch)
        self.assertIsNone(value["assets"]["retry_at"])
        count = len(self.recover_calls)
        self.now = 400
        self.queue.run_once()
        self.assertEqual(len(self.recover_calls), count)
        self.assertEqual(value["next"]["arguments"], {"action": "recover", "batch": batch})
        self.assertIn("recovery_failure", value)

    def test_pie_defers_recovery_without_spending_retry_budget(self):
        """/** @return 其它会话的 PIE 等待期间保留恢复次数 */"""
        batch = self.submit_move()
        attempts = self.queue.assets.claims[batch]["attempts"]
        self.backend.state.update(pie_active=True, worlds=["PIE_0"])
        self.now = 10
        self.queue.run_once()
        self.assertEqual(self.queue.assets.claims[batch]["attempts"], attempts)

    def test_reconnecting_releasing_client_receives_recovery_without_registration(self):
        """/** @return 重连保留查询和恢复通道且等级保持释放 */"""
        batch = self.submit_move()
        self.queue.clients.operators.manage(self.owner, action="finish")
        gateway = TaskGateway(self.backend, self.catalog, start_worker=False, clients=self.queue.clients)
        self.addCleanup(gateway.jobs.close)
        status, headers, result = gateway.handle("POST", {}, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"_meta": {"bbb/client_key": self.owner, "bbb/operator": {"task": "继续迁移", "level": 0}}}})
        self.assertEqual(status, 200)
        metadata = result["result"]["_meta"]
        self.assertIsNone(metadata["bbb/operator"])
        self.assertEqual(metadata["bbb/operator_recovery"]["next"]["arguments"]["batch"], batch)
        self.assertEqual(self.queue.clients.operators.level(self.owner), 2)

    def test_recovery_evidence_and_retry_limit_survive_service_restart(self):
        """/** @return 重启保持迁移证据和已耗尽恢复次数 */"""
        stored = {}
        self.queue.clients.store_job = lambda row: stored.update({row["id"]: copy.deepcopy(row)})
        self.queue.clients.stored_jobs = lambda: list(copy.deepcopy(stored).values())
        batch = self.submit_move()
        for instant in (100, 200):
            self.now = instant
            self.queue.run_once()
        restored = JobQueue(self.backend, self.catalog, clock=lambda: self.now, start_worker=False, clients=self.queue.clients)
        self.addCleanup(restored.close)
        self.assertEqual(restored.jobs[batch]["move_recovery"], self.record)
        self.assertIn("recovery_failure", restored.jobs[batch])
        self.assertIsNone(restored.assets.claims[batch]["retry_at"])
        count = len(self.recover_calls)
        self.now = 1000
        restored.run_once()
        self.assertEqual(len(self.recover_calls), count)

    def test_new_host_keeps_move_evidence_for_explicit_recovery(self):
        """/** @return 宿主切换后保留迁移范围并等待实际身份核验 */"""
        stored = {}
        self.queue.clients.store_job = lambda row: stored.update({row["id"]: copy.deepcopy(row)})
        self.queue.clients.stored_jobs = lambda: list(copy.deepcopy(stored).values())
        batch = self.submit_move()
        self.backend.state.update(host_instance="new-host", dirty_packages=[])
        restored = JobQueue(self.backend, self.catalog, clock=lambda: self.now, start_worker=False, clients=self.queue.clients)
        self.addCleanup(restored.close)
        claim = restored.assets.claims[batch]
        self.assertEqual(claim["code"], "MOVE_HOST_CHANGED")
        self.assertIsNone(claim["retry_at"])
        self.assertEqual(restored.jobs[batch]["move_recovery"], self.record)
        count = len(self.recover_calls)
        restored.run_once()
        self.assertEqual(len(self.recover_calls), count)


class MovePersistenceRecoveryTests(unittest.TestCase):
    """/** 逐包保存阶段及源文件保护 */"""

    def setUp(self):
        """/** @return 实际迁移辅助函数的隔离环境 */"""
        self.fixture = persistence_tests.AssetMovePersistenceTests()
        self.fixture.setUp()

    def test_partial_save_keeps_successful_packages_and_empty_sources(self):
        """/** @return 单个引用者失败保留目标成功事实与空原包 */"""
        f = self.fixture
        state = f._empty_source_fixture()
        f.runtime["unreal"].EditorLoadingAndSavingUtils.save_packages = lambda packages, dirty: packages[0].get_path_name() != "/Game/Ref"
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            report = f.runtime["_persist_asset_moves"](f.report, [f.old], [f.asset], [f.ref])
        self.assertFalse(report["success"])
        self.assertEqual(report["saved_packages"], ["/Game/New/A"])
        self.assertEqual(report["failures"][0]["package"], "/Game/Ref")
        self.assertEqual(report["empty_sources"], ["/Game/Old/A"])
        self.assertFalse(any(call[0] in {"reload", "delete"} for call in f.calls))

    def test_recovery_checks_source_hash_before_writing(self):
        """/** @return 原源文件摘要变化时保持所有资产 */"""
        f = self.fixture
        state = f._empty_source_fixture()
        f.report["assets"][0].update(source_object="/Game/Old/A.A", destination_object="/Game/New/A.A", class_path="/Script/Engine.StaticMesh", source_sha256="changed")
        f.runtime["_move_path"] = lambda path: path
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            with self.assertRaises(McpExecutionError) as caught:
                f.runtime["_resume_asset_moves"](f.report)
        self.assertEqual(caught.exception.value["code"], "MOVE_SOURCE_CHANGED")
        self.assertEqual(f.calls, [])

    def test_temporary_save_lock_resumes_cleanup_without_renaming(self):
        """/** @return 临时锁释放后仅接续保存和原包清理 */"""
        f = self.fixture
        state = f._empty_source_fixture()
        f.report["referencer_packages"].append("/Game/Old/A")
        f.report["assets"][0]["destination_object"] = "/Game/New/A.A"
        native = f.runtime["unreal"]
        old_loader = native.load_object
        f.asset.get_path_name = lambda: "/Game/New/A.A"
        f.asset.get_class = lambda: SimpleNamespace(get_class_path_name=lambda: SimpleNamespace(package_name="/Script/Engine", asset_name="StaticMesh"))
        native.load_object = lambda outer, path, **options: f.asset if path == "/Game/New/A.A" else old_loader(outer, path, **options)
        native.find_object = lambda outer, path, **options: f.old
        def load_referencer(path):
            """/** @param path 实际外部引用者 @return 禁止再次加载已迁移原包 */"""
            self.assertNotEqual(path, "/Game/Old/A")
            return f.ref
        native.load_package = load_referencer
        f.runtime["_move_path"] = lambda path: path
        f.runtime["require_asset_write"] = lambda scope: None
        f.runtime["_verify_asset_moves_json"] = lambda rows: json.dumps({"success": "/Game/Old/A.uasset" not in state["files"]})
        native.EditorLoadingAndSavingUtils.save_packages = lambda packages, dirty: packages[0] != f.ref
        with patch("os.path.isfile", side_effect=lambda path: path in state["files"]):
            with self.assertRaises(McpExecutionError) as caught:
                f.runtime["_resume_asset_moves"](f.report)
            continuation = caught.exception.value["execution"]["details"]["recovery"]
            self.assertEqual(continuation["persistence"]["saved_packages"], ["/Game/New/A"])
            self.assertIn("/Game/Old/A.uasset", state["files"])
            native.EditorLoadingAndSavingUtils.save_packages = f.save
            result = f.runtime["_resume_asset_moves"](continuation)
        self.assertTrue(result["success"])
        self.assertEqual(result["persistence"]["empty_source_cleanup"]["deleted"], ["/Game/Old/A"])
        self.assertEqual(state["files"], {"/Game/New/A.uasset"})


if __name__ == "__main__":
    unittest.main()
