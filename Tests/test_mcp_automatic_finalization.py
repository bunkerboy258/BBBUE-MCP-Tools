import unittest

from test_mcp_task_gateway import fixtures, operation
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import public_tools


class AutomaticFinalizationTests(unittest.TestCase):
    """/** 自动收尾与遗忘会话的简短验收 */"""

    def setUp(self):
        """/** @return 可推进时钟的双客户端 */"""
        self.now = 0
        self.backend, self.catalog, self.queue = fixtures(clock=lambda: self.now)
        self.first = self.queue.connect()
        self.second = self.queue.connect()
        self.addCleanup(self.queue.close)

    def test_saved_result_releases_without_close(self):
        """/** @return 保留结果记录时后续同包写入继续 */"""
        one = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        two = self.queue.submit(self.second, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[one]["status"], "completed")
        self.assertEqual(self.queue.jobs[two]["status"], "completed")
        self.assertEqual(self.queue.assets.claims, {})

    def test_unknown_result_is_observed_and_released_automatically(self):
        """/** @return 自动核实保留原错误与执行边界 */"""
        failed = self.queue.submit(self.first, [operation("unknown", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[failed]["status"], "failed")
        self.assertEqual(self.queue.jobs[failed]["execution"], "unknown")
        self.assertIn("reconciled", self.queue.jobs[failed]["proof"])
        self.assertEqual(self.queue.assets.claims, {})
        self.assertEqual(len(self.backend.calls), 1)

    def test_abandoned_save_fault_recovers_without_client_action(self):
        """/** @return 客户端离开后网关继续保存并释放 */"""
        finalize = self.backend.finalize
        def fail(packages):
            raise McpBusinessError({"code": "SAVE_FAILED"})
        self.backend.finalize = fail
        failed = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        blocked = self.queue.submit(self.second, [operation("write", asset="/Game/A")])["batch"]
        independent = self.queue.submit(self.second, [operation("write", asset="/Game/B"), operation("save_assets", asset_paths=["/Game/B"])])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[independent]["status"], "completed")
        self.backend.finalize = finalize
        self.now = 301
        self.queue.touch(self.second)
        self.queue.run_once()
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[failed]["status"], "completed")
        self.assertEqual(self.queue.jobs[blocked]["status"], "completed")
        self.assertEqual(self.backend.state["dirty_packages"], [])

    def test_result_delivery_preserves_automatic_asset_recovery(self):
        """/** @return 交付结果后资产恢复继续由网关完成 */"""
        finalize = self.backend.finalize
        self.backend.finalize = lambda packages: (_ for _ in ()).throw(RuntimeError("read only"))
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.control(self.first, "close", batch)["asset_recovery"], "automatic")
        self.backend.finalize = finalize
        self.now = 3
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[batch]["status"], "completed")
        self.assertEqual(self.queue.assets.claims, {})

    def test_unrelated_existing_dirty_packages_stay_unchanged(self):
        """/** @return 自动核实仅处理本批次范围 */"""
        dirty = ["/Game/Other/P" + str(index) for index in range(191)]
        self.backend.state["dirty_packages"] = list(dirty)
        self.queue.observe(force=True)
        self.queue.submit(self.first, [operation("unknown", asset="/Game/A")])
        self.queue.run_once()
        self.assertEqual(self.backend.state["dirty_packages"], dirty)

    def test_public_control_has_single_lifecycle(self):
        """/** @return 公开协议保留提交 等待与交付 */"""
        tools = {item["name"]: item for item in public_tools()}
        self.assertNotIn("completion", tools["submit_batch"]["inputSchema"]["properties"])
        self.assertEqual(tools["control_task"]["inputSchema"]["properties"]["action"]["enum"], ["cancel", "close", "shutdown_host"])

    def test_expired_pie_owner_is_cleaned_up_automatically(self):
        """/** @return 客户端离线后其 PIE 自动结束 */"""
        self.queue.submit(self.first, [operation("StartPIE")])
        self.queue.run_once()
        self.now = 301
        self.assertTrue(self.queue.run_once())
        self.assertFalse(self.backend.state["pie_active"])
        self.assertIsNone(self.queue.pie_owner)


if __name__ == "__main__":
    unittest.main()
