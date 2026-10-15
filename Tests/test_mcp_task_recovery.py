import unittest

from test_mcp_task_gateway import fixtures, operation
from MCP.mcp_jobs import JobConflict


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.backend, self.catalog, self.manager = fixtures(clock=lambda: self.now)
        self.owner = self.manager.connect()
        self.claimant = self.manager.connect()

    def tearDown(self):
        self.manager.close()


    def test_queued_expired_job_cancels_before_dispatch(self):
        identity = self.manager.submit(self.owner, [operation("write", asset="/Game/A")])["batch"]
        self.now = 301
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[identity]["status"], "cancelled")
        self.assertEqual(self.backend.calls, [])

    def test_original_client_resumes_credentials_without_duplicate_dispatch(self):
        identity = self.manager.submit(self.owner, [operation("read")])["batch"]
        self.manager.run_once()
        self.now = 301
        self.assertEqual(self.manager.connect(self.owner), self.owner)
        self.assertEqual(self.manager.inspect(self.owner, identity)["status"], "completed")
        self.assertEqual(len(self.backend.calls), 1)

    def test_expired_dispatched_async_job_keeps_partial_results_after_cleanup(self):
        self.manager.submit(self.owner, [operation("StartPIE")])
        self.manager.run_once()
        identity = self.manager.submit(self.owner, [operation("activity"), operation("StopPIE")])["batch"]
        self.manager.run_once()
        self.now = 301
        self.manager.run_once()
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "failed")
        self.assertEqual(self.manager.jobs[identity]["completed"], 1)
        self.assertIsNone(self.manager.pie_owner)
        self.assertNotIn("capture:1", self.manager.activity_owners)
        self.assertEqual(len(self.manager.jobs[identity]["results"]), 1)





if __name__ == "__main__":
    unittest.main()
