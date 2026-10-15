from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_result import McpBusinessError
from Tests.test_mcp_task_gateway import fixtures, operation


class CompletionTests(unittest.TestCase):
    """/** 资产收尾与批次独立等待的边界验收 */"""

    def setUp(self):
        """/** @return 建立两客户端调度 */"""
        self.backend, self.catalog, self.queue = fixtures()
        self.first = self.queue.connect()
        self.second = self.queue.connect()

    def tearDown(self):
        """/** @return 结束测试调度 */"""
        self.queue.close()

    def test_save_completes_only_owned_scope_and_releases_next_writer(self):
        """/** @return 外部脏包保持原状态 本批次完成保存 */"""
        self.backend.state["dirty_packages"] = ["/Game/Other"]
        saved = []

        def finalize(packages):
            """/** @param packages\t自有脏包 @return 保存证据 */"""
            saved.extend(packages)
            self.backend.state["dirty_packages"] = [value for value in self.backend.state["dirty_packages"] if value not in packages]
            return {"saved": packages, "readback": True}

        self.backend.finalize = finalize
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        view = self.queue.inspect(self.first, batch)
        self.assertEqual(view["status"], "completed")
        self.assertEqual(saved, ["/Game/A"])
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/Other"])
        self.assertEqual(view["next"], "submit_batch")

    def test_failed_save_keeps_review_evidence(self):
        """/** @return 保存失败保留资产和核实状态 */"""
        def finalize(packages):
            """/** @param packages\t自有脏包 @return 保存失败 */"""
            raise McpBusinessError({"execution": {"state": "partial"}, "code": "SAVE_FAILED"})

        self.backend.finalize = finalize
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.inspect(self.first, batch)["status"], "failed")
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/A"])

    def test_actual_new_dirty_dependencies_are_saved_with_owner(self):
        original = self.backend.invoke
        def invoke(contract, arguments):
            result = original(contract, arguments)
            self.backend.state["dirty_packages"].append("/Game/Unexpected")
            return result
        self.backend.invoke = invoke
        batch = self.queue.submit(self.first, [operation("write", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.assertEqual(self.queue.inspect(self.first, batch)["status"], "completed")
        self.assertEqual(self.queue.jobs[batch]["owned_dirty"], {"/Game/A", "/Game/Unexpected"})
        self.assertEqual(self.backend.state["dirty_packages"], [])

    def test_unrelated_batch_does_not_wake_selected_batch(self):
        """/** @return 等待按目标批次版本生效 */"""
        batch = self.queue.submit(self.first, [operation("read")])["batch"]
        self.queue.run_once()
        revision = self.queue.inspect(self.first, batch)["revision"]
        output = []
        started = time.monotonic()
        thread = threading.Thread(target=lambda: output.append(self.queue.inspect(self.first, batch, after_revision=revision, wait_seconds=0.15)))
        thread.start()
        self.queue.submit(self.second, [operation("read")])
        self.queue.run_once()
        thread.join(1)
        self.assertEqual(output[0]["revision"], revision)
        self.assertGreaterEqual(time.monotonic() - started, 0.13)


if __name__ == "__main__":
    unittest.main()
