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

    def test_orphan_requires_expiry_snapshot_confirmation_and_preserves_packages(self):
        identity = self.manager.submit(self.owner, [operation("unknown", asset="/Game/A")])["batch"]
        self.manager.run_once()
        packages = ["/Game/Old" + str(index) for index in range(191)]
        self.backend.state["dirty_packages"] = packages
        with self.assertRaises(JobConflict):
            self.manager.control(self.claimant, "review", identity)
        self.now = 301
        preview = self.manager.control(self.claimant, "review", identity)
        self.assertEqual(self.backend.state["dirty_packages"], packages)
        with self.assertRaises(JobConflict):
            self.manager.control(self.claimant, "resume", identity, "wrong")
        value = self.manager.control(self.claimant, "resume", identity, preview["confirmation"])
        self.assertEqual(value["status"], "review")
        self.assertEqual(self.manager.jobs[identity]["owner"], self.claimant)
        self.assertEqual(self.backend.state["dirty_packages"], packages)

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

    def test_expired_dispatched_async_job_keeps_activity_and_partial_results(self):
        self.manager.submit(self.owner, [operation("StartPIE")])
        self.manager.run_once()
        identity = self.manager.submit(self.owner, [operation("activity"), operation("StopPIE")])["batch"]
        self.manager.run_once()
        self.now = 301
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "review")
        self.assertEqual(self.manager.jobs[identity]["completed"], 1)
        self.assertEqual(self.manager.pie_owner, self.owner)
        self.assertEqual(self.manager.activity_owners["capture:1"], self.owner)

    def test_expired_pie_owner_is_transferable_after_confirmation(self):
        identity = self.manager.submit(self.owner, [operation("StartPIE")])["batch"]
        self.manager.run_once()
        self.now = 301
        preview = self.manager.control(self.claimant, "review", identity)
        self.manager.control(self.claimant, "resume", identity, preview["confirmation"])
        self.assertEqual(self.manager.pie_owner, self.claimant)
        stop = self.manager.submit(self.claimant, [operation("StopPIE")])["batch"]
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[stop]["status"], "completed")

    def test_changed_host_prevents_confirmed_release(self):
        identity = self.manager.submit(self.owner, [operation("unknown", asset="/Game/A")])["batch"]
        self.manager.run_once()
        preview = self.manager.control(self.owner, "review", identity)
        self.backend.state["host_instance"] = "different"
        with self.assertRaises(JobConflict):
            self.manager.control(self.owner, "resume", identity, preview["confirmation"])

    def test_original_owner_reconnecting_during_confirmation_keeps_ownership(self):
        identity = self.manager.submit(self.owner, [operation("unknown", asset="/Game/A")])["batch"]
        self.manager.run_once()
        self.now = 301
        preview = self.manager.control(self.claimant, "review", identity)
        observe = self.manager.observe
        def owner_returns(force=False):
            self.manager.touch(self.owner)
            return observe(force)
        self.manager.observe = owner_returns
        with self.assertRaises(JobConflict):
            self.manager.control(self.claimant, "resume", identity, preview["confirmation"])
        self.assertEqual(self.manager.jobs[identity]["owner"], self.owner)


if __name__ == "__main__":
    unittest.main()
