import unittest

from test_mcp_task_gateway import fixtures, operation
from MCP.mcp_jobs import JobConflict


class CancelFaultTests(unittest.TestCase):
    def setUp(self):
        self.backend, self.catalog, self.queue = fixtures()
        self.owner = self.queue.connect()
        self.other = self.queue.connect()

    def tearDown(self):
        self.queue.close()

    def fault(self):
        batch = self.queue.submit(self.owner, [operation("unknown", asset="/Game/A")])["batch"]
        self.queue.run_once()
        self.queue.assets.fault(batch, {"/Game/A"}, "MOVE_SOURCE_CHANGED", 0)
        self.queue.jobs[batch]["status"] = "failed"
        return batch

    def test_saved_fault_can_be_cancelled_without_replaying_or_deleting(self):
        batch = self.fault()
        before = list(self.backend.calls)
        result = self.queue.control(self.owner, "cancel", batch)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["execution"], "partial")
        self.assertEqual(self.backend.calls, before)
        self.assertNotIn(batch, self.queue.assets.claims)
        self.assertFalse(result["proof"]["cancelled_recovery"]["operation_replayed"])

    def test_dirty_fault_keeps_ownership(self):
        batch = self.fault()
        self.backend.state["dirty_packages"] = ["/Game/A"]
        with self.assertRaises(JobConflict) as caught:
            self.queue.control(self.owner, "cancel", batch)
        self.assertEqual(caught.exception.value["code"], "DIRTY_RECOVERY_PACKAGES")
        self.assertIn(batch, self.queue.assets.claims)

    def test_cancelled_move_releases_pending_recovery_after_host_change(self):
        batch = self.fault()
        job = self.queue.jobs[batch]
        job["move_recovery"] = {"assets": [{"source": "/Game/A", "destination": "/Game/B"}]}
        job["uncertain"].add("/Game/A")
        job["owned_dirty"].add("/Game/A")
        result = self.queue.control(self.owner, "cancel", batch)
        self.assertNotIn("move_recovery", job)
        self.assertFalse(job["uncertain"])
        self.assertFalse(job["owned_dirty"])
        self.assertIn("cancelled_move_recovery", result["proof"])
        self.queue._restore_jobs()
        self.assertNotIn(batch, self.queue.assets.claims)

    def test_foreign_client_cannot_cancel_fault(self):
        batch = self.fault()
        with self.assertRaises(JobConflict) as caught:
            self.queue.control(self.other, "cancel", batch)
        self.assertEqual(caught.exception.value["code"], "BATCH_OWNERSHIP")
        self.assertIn(batch, self.queue.assets.claims)

    def test_releasing_operator_can_complete_cancel_and_join_new_work(self):
        self.queue.clients.operators.manage(self.owner, task="迁移收尾")
        batch = self.fault()
        self.queue.clients.operators.manage(self.owner, action="finish")
        self.queue.control(self.owner, "cancel", batch)
        renewed = self.queue.clients.operators.manage(self.owner, task="新任务")
        self.assertEqual(renewed["task"], "新任务")


if __name__ == "__main__":
    unittest.main()
