import sys
from pathlib import Path
import unittest

sys.dont_write_bytecode = True
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "Scripts"), str(Path(__file__).resolve().parent)]

from test_mcp_task_gateway import fixtures, operation
from MCP.mcp_decision import require_control
from MCP.mcp_result import McpBusinessError


class DecisionTests(unittest.TestCase):
    """/** 定向保存与管理权限的隔离检查 */"""

    def setUp(self):
        """/** @return 隔离队列与双客户端 */"""
        self.backend, self.catalog, self.queue = fixtures()
        self.first = self.queue.connect()
        self.second = self.queue.connect()
        self.addCleanup(self.queue.close)

    def test_baseline_saved_before_operation(self):
        """/** @return 前置保存完整范围 原操作读取干净目标 */"""
        packages = ["/Game/Pack/P" + str(index) for index in range(12)]
        self.backend.state["dirty_packages"] = packages + ["/Game/Other"]
        invoke = self.backend.invoke
        def checked(contract, arguments):
            self.assertEqual(self.backend.state["dirty_packages"], ["/Game/Other"])
            return invoke(contract, arguments)
        self.backend.invoke = checked
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/Pack")])["batch"]
        self.queue.run_once()
        view = self.queue.inspect(self.first, batch)
        self.assertEqual(view["status"], "completed")
        self.assertEqual(set(view["proof"]["prepared"]), set(packages))
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/Other"])

    def test_save_failure_preserves_original_operation(self):
        """/** @return 保存失败时原操作保持零派发 */"""
        self.backend.state["dirty_packages"] = ["/Game/A"]
        def fail(packages):
            raise McpBusinessError({"code": "READ_ONLY"})
        self.backend.finalize = fail
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.queue.jobs[batch]["completed"], 0)
        self.assertEqual(self.queue.assets.view(batch)["phase"], "fault")

    def test_foreign_claim_waits_with_complete_internal_scope(self):
        """/** @return 他人占用继续等待 摘要与内部范围独立 */"""
        packages = ["/Game/Pack/P" + str(index) for index in range(12)]
        first = self.queue.submit(self.first, [operation("write", asset="/Game/Pack")])["batch"]
        self.queue.queue.remove(first)
        self.queue.jobs[first]["status"] = "failed"
        self.queue.assets.hold(first, packages, "executing")
        self.backend.state["dirty_packages"] = packages
        second = self.queue.submit(self.second, [operation("write", asset="/Game/Pack")])["batch"]
        self.assertFalse(self.queue.run_once())
        self.assertEqual(self.queue.jobs[second]["code"], "ASSET_BUSY")
        self.assertEqual(len(self.queue.jobs[second]["blocked"]["packages"]), 12)
        self.assertEqual(len(self.queue.inspect(self.second, second)["blocked"]["packages"]), 8)
        self.assertEqual(len(self.queue.inspect(self.second, second, True)["blocked"]["packages"]), 12)
        self.assertEqual(self.backend.calls, [])

    def test_management_uses_registered_level(self):
        """/** @return 二级明确权限拒绝 零级直接通过 */"""
        pool = self.queue.clients.operators
        pool.manage(self.first, task="检查权限")
        with self.assertRaises(McpBusinessError) as error:
            require_control(pool, self.first, "terminate_host")
        self.assertEqual(error.exception.value["code"], "OPERATOR_LEVEL_REQUIRED")
        pool.manage(self.first, action="update", level=0)
        require_control(pool, self.first, "terminate_host")
        self.assertEqual(pool.level(self.first), 0)

    def test_failed_readback_blocks_original_operation(self):
        """/** @return 保存后回读失败保留核验占用 */"""
        self.backend.state["dirty_packages"] = ["/Game/A"]
        def unverifiable(packages):
            self.backend.state["dirty_packages"] = []
            return {"saved": packages, "readback": False}
        self.backend.finalize = unverifiable
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.queue.jobs[batch]["code"], "ASSET_READBACK_FAILED")
        self.assertEqual(self.queue.assets.view(batch)["packages"], ["/Game/A"])


if __name__ == "__main__":
    unittest.main()
