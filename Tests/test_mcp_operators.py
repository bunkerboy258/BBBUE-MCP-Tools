import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_clients import ClientRegistry
from MCP.mcp_host_registry import process_identity, terminate_process
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import UnrealBackend
from test_mcp_task_gateway import fixtures, operation


class OperatorTests(unittest.TestCase):
    """/** 干员权限 持久归属与操作边界调度验收 */"""

    def setUp(self):
        """/** @return 双干员与隔离执行端 */"""
        self.backend, self.catalog, self.queue = fixtures()
        self.addCleanup(self.queue.close)
        self.pool = self.queue.clients.operators
        self.first = self.queue.connect()
        self.second = self.queue.connect()
        self.low = self.pool.manage(self.first, task="整理蓝图")
        self.high = self.pool.manage(self.second, task="验收换弹", level=0)

    def test_task_limit_default_grade_and_private_identity(self):
        """/** @return 任务长度 默认等级及私有凭证核验 */"""
        self.assertEqual(self.low["level"], 2)
        self.assertNotIn(self.first, json.dumps(self.pool.snapshot()))
        for task in ("", "字" * 21, "两行\n任务"):
            with self.assertRaises(McpBusinessError):
                self.pool.manage(self.first, task=task)

    def test_registration_grade_survives_live_reconnect_and_expires_when_idle(self):
        """/** @return 短连接与长期离线保留授权等级 */"""
        self.pool.manage(self.second, operator=self.low["id"], level=0)
        self.queue.connect(self.first)
        self.pool.manage(self.first, task="继续整理")
        self.assertEqual(self.pool.level(self.first), 0)
        self.pool.clock = lambda: 10 ** 12
        self.pool.collect()
        self.assertEqual(self.pool.level(self.first), 2)
        self.assertEqual(self.pool.snapshot()["items"], [])

    def test_low_grade_cannot_control_other_operator(self):
        """/** @return 普通干员的管理权限边界 */"""
        with self.assertRaises(McpBusinessError):
            self.pool.manage(self.first, operator=self.high["id"], level=2)
        with self.assertRaises(McpBusinessError):
            self.pool.pause(self.first, self.high["id"])
        with self.assertRaises(McpBusinessError):
            self.queue.control(self.first, "cancel_blocker", "unknown")

    def test_pause_lease_expires_and_grade_remains(self):
        """/** @return 暂停到期后恢复原等级调度 */"""
        now = [100.0]
        self.pool.clock = lambda: now[0]
        self.pool.pause(self.second, self.low["id"], 5)
        low = self.queue.submit(self.first, [operation("read")])["batch"]
        self.assertFalse(self.queue.run_once())
        self.assertEqual(self.queue.jobs[low]["code"], "OPERATOR_PAUSED")
        now[0] = 106
        self.assertTrue(self.queue.run_once())
        self.assertEqual(self.queue.jobs[low]["status"], "completed")
        self.assertEqual(self.pool.level(self.second), 0)

    def test_finish_clears_privilege_and_drains_queued_work(self):
        """/** @return 会话结束清理权限与排队任务 */"""
        batch = self.queue.submit(self.second, [operation("read")])["batch"]
        identity = self.high["id"]
        self.pool.manage(self.second, action="finish")
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[batch]["status"], "completed")
        self.pool.collect()
        self.assertEqual(self.pool.level(self.second), 2)
        row = self.pool.manage(self.second, task="新任务")
        self.assertNotEqual(identity, row["id"])

    def test_grade_precedes_fifo(self):
        """/** @return 等级优先于提交时间 */"""
        low = self.queue.submit(self.first, [operation("read", asset="/Game/A")])["batch"]
        high = self.queue.submit(self.second, [operation("read", asset="/Game/B")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[high]["status"], "completed")
        self.assertEqual(self.queue.jobs[low]["status"], "queued")

    def test_paused_high_task_allows_low_task(self):
        """/** @return 已暂停高级任务让出执行机会 */"""
        self.pool.pause(self.second, self.high["id"], 5)
        high = self.queue.submit(self.second, [operation("read")])["batch"]
        low = self.queue.submit(self.first, [operation("read")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[low]["status"], "completed")
        self.assertEqual(self.queue.jobs[high]["status"], "queued")

    def test_running_batch_yields_after_save_to_independent_high_task(self):
        """/** @return 保存后让行及续跑完整性 */"""
        finalized = []
        old = self.backend.finalize
        self.backend.finalize = lambda paths: (finalized.extend(paths), old(paths))[1]
        low = self.queue.submit(self.first, [operation("write", asset="/Game/A"), operation("long", asset="/Game/A"), operation("read", asset="/Game/A")])["batch"]
        thread = threading.Thread(target=self.queue.run_once)
        thread.start()
        self.assertTrue(self.backend.entered.wait(2))
        high = self.queue.submit(self.second, [operation("read", asset="/Game/B")])["batch"]
        self.backend.release.set()
        thread.join(3)
        self.assertEqual(self.queue.jobs[low]["status"], "queued")
        self.assertEqual(finalized, ["/Game/A"])
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[high]["status"], "completed")
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[low]["status"], "completed")
        self.assertEqual(len(self.backend.calls), 4)

    def test_same_asset_batch_remains_contiguous(self):
        """/** @return 同资产连续操作保持顺序 */"""
        low = self.queue.submit(self.first, [operation("long", asset="/Game/A"), operation("read", asset="/Game/A")])["batch"]
        thread = threading.Thread(target=self.queue.run_once)
        thread.start()
        self.assertTrue(self.backend.entered.wait(2))
        self.queue.submit(self.second, [operation("write", asset="/Game/A")])
        self.backend.release.set()
        thread.join(3)
        self.assertEqual(self.queue.jobs[low]["status"], "completed")

    def test_level_zero_cancels_running_at_boundary(self):
        """/** @return 定向取消在操作边界生效 */"""
        low = self.queue.submit(self.first, [operation("long", asset="/Game/A"), operation("write", asset="/Game/A")])["batch"]
        thread = threading.Thread(target=self.queue.run_once)
        thread.start()
        self.assertTrue(self.backend.entered.wait(2))
        value = self.queue.control(self.second, "cancel_blocker", low)
        self.assertEqual(value["status"], "cancelling")
        self.backend.release.set()
        thread.join(3)
        self.assertEqual(self.queue.jobs[low]["status"], "cancelled")
        self.assertEqual([name for name, args in self.backend.calls], ["long"])
        self.assertTrue(self.pool.audit)

    def test_pool_and_pause_persist_without_credentials(self):
        """/** @return 干员与暂停的持久归属 */"""
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.sqlite"
            first = ClientRegistry(state_path=path)
            key = first.connect()
            row = first.operators.manage(key, task="执行验收", level=0)
            first.operators.pause(key, row["id"], 30)
            first.database.close()
            second = ClientRegistry(state_path=path)
            try:
                second.connect(key)
                self.assertEqual(second.operators.level(key), 0)
                self.assertIsNotNone(second.operators.paused(key))
                second.operators.manage(key, action="finish")
                self.assertEqual(second.database.execute("SELECT COUNT(*) FROM operator_pauses").fetchone()[0], 0)
            finally:
                second.database.close()

    def test_level_zero_ends_target_pie_without_editor_termination(self):
        """/** @return 零级正常结束指定 PIE */"""
        batch = self.queue.submit(self.first, [operation("StartPIE")])["batch"]
        self.queue.run_once()
        self.assertTrue(self.backend.state["pie_active"])
        result = self.queue.control(self.second, "cancel_blocker", batch)
        self.assertEqual(result["status"], "cancelling")
        self.queue.run_once()
        self.assertFalse(self.backend.state["pie_active"])

    def test_finalization_compiles_only_stale_blueprints(self):
        """/** @return 实际编译状态控制编译次数 */"""
        for stale in (False, True):
            backend = object.__new__(UnrealBackend)
            backend.catalog = type("Catalog", (), {"tools": {key: {"id": key} for key in ("editor.inspect_asset_properties", "blueprint_base.compile_blueprint", "editor.resave_asset")}})()
            calls = []
            def invoke(contract, arguments):
                """/** @param contract	契约 @param arguments	参数 @return 模拟蓝图状态回读 */"""
                calls.append(contract["id"])
                status = "BS_DIRTY" if stale and "blueprint_base.compile_blueprint" not in calls else "BS_UP_TO_DATE"
                return {"assets": [{"classPath": "/Script/Engine.Blueprint", "assetPath": "/Game/A", "propertyErrors": [], "properties": {"status": status}}]}
            backend.invoke = invoke
            proof = backend.finalize(["/Game/A"])
            self.assertEqual(calls.count("blueprint_base.compile_blueprint"), int(stale))
            self.assertEqual(proof["saved"], ["/Game/A"])
            self.assertEqual(proof["failures"], [])

    @unittest.skipUnless(os.name == "nt", "Windows process handles")
    def test_native_termination_verifies_creation_before_targeted_exit(self):
        """/** @return 一次性辅助进程核验创建时间与精确终止 */"""
        process = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"], creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            identity = process_identity(process.pid)
            self.assertIsNotNone(identity)
            with self.assertRaises(RuntimeError):
                terminate_process({**identity, "created": "0"})
            self.assertIsNone(process.poll())
            result = terminate_process(identity)
            self.assertEqual(result["status"], "terminated")
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
