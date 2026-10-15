import copy
import json
import time
import unittest

from test_mcp_task_gateway import fixtures, operation
from BBBMcpCapabilities import write_scope, validate_arguments
from MCP.mcp_asset_scope import conflicting_packages
from MCP.mcp_jobs import JobConflict
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import public_tools


class AutomaticCoordinationTests(unittest.TestCase):
    """/** 多客户端保存 归属与恢复的行为验收 */"""

    def setUp(self):
        """/** @return 建立双客户端与隔离后端 */"""
        self.backend, self.catalog, self.queue = fixtures()
        self.first = self.queue.connect()
        self.second = self.queue.connect()
        self.addCleanup(self.queue.close)

    def submit(self, owner, *operations):
        """/** @param owner\t所属客户端 @param operations\t批次操作 @return 批次身份 */"""
        return self.queue.submit(owner, list(operations))["batch"]

    def fail_save(self, packages):
        """/** @param packages\t自有范围 @return 模拟保存失败 */"""
        raise McpBusinessError({"code": "SAVE_FAILED"})

    def test_failed_package_keeps_only_its_own_waiters(self):
        """/** @return 一包失败时已保存包和独立任务继续 */"""
        finalize = self.backend.finalize
        def partially_save(packages):
            saved = [package for package in packages if package != "/Game/A"]
            finalize(saved)
            return {"saved": saved, "failures": [{"package": "/Game/A", "failure": {"code": "READ_ONLY"}}] if "/Game/A" in packages else []}
        self.backend.finalize = partially_save
        owner = self.submit(self.first, operation("write", asset="/Game/A"), operation("write", asset="/Game/B"))
        self.queue.run_once()
        blocked = self.submit(self.second, operation("write", asset="/Game/A"))
        independent = self.submit(self.second, operation("write", asset="/Game/B"))
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[independent]["status"], "completed")
        self.assertEqual(self.queue.jobs[blocked]["code"], "ASSET_BUSY")
        self.assertEqual(self.queue.assets.view(owner)["packages"], ["/Game/A"])
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/A"])


    def test_partial_failure_saves_known_result_and_releases_asset(self):
        """/** @return 错误结果保留 已知修改保存后交给后续客户端 */"""
        failed = self.submit(self.first, operation("write", asset="/Game/A"), operation("reject", asset="/Game/A"))
        next_batch = self.submit(self.second, operation("write", asset="/Game/A"))
        self.queue.run_once()
        view = self.queue.inspect(self.first, failed, True)
        self.assertEqual(view["status"], "failed")
        self.assertEqual(view["completed"], 1)
        self.assertEqual(view["failure"]["code"], "INVALID_ASSET")
        self.assertEqual(self.backend.state["dirty_packages"], [])
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[next_batch]["status"], "completed")


    def test_zero_mutation_rejection_leaves_no_asset_occupancy(self):
        """/** @return 参数拒绝后同资产任务立即执行 */"""
        failed = self.submit(self.first, operation("reject", asset="/Game/A"))
        next_batch = self.submit(self.second, operation("write", asset="/Game/A"))
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[failed]["status"], "rejected")
        self.assertEqual(self.queue.assets.claims, {})
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[next_batch]["status"], "completed")

    def test_unknown_result_keeps_only_dispatched_operation_scope(self):
        """/** @return 后续尚未执行的独立目标保持可用 */"""
        self.backend.reconcile = lambda packages: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        failed = self.submit(self.first, operation("unknown", asset="/Game/A"), operation("write", asset="/Game/B"))
        self.queue.run_once()
        independent = self.submit(self.second, operation("write", asset="/Game/B"))
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[independent]["status"], "completed")
        self.assertEqual(self.queue.assets.view(failed)["packages"], ["/Game/A"])



    def test_actor_path_resolves_map_instead_of_unknown_scope(self):
        """/** @return 演员操作按所属地图登记范围 */"""
        contract = {"id": "object.set_properties", "name": "set_properties", "definition": "ObjectTools", "parameters": {}, "scope": {"fields": ["instance"]}, "access": "write", "world": "editor"}
        targets, scoped = write_scope(contract, {"instance": "/Game/Maps/Main.Main:PersistentLevel.Light_1"})
        self.assertTrue(scoped)
        self.assertEqual(conflicting_packages(["/Game/Maps/Main"], targets), {"/Game/Maps/Main"})

    def test_external_actor_and_object_packages_follow_map_ownership(self):
        """/** @return 外部包跟随所属地图 相似地图名称保持独立 */"""
        packages = ["/Game/__ExternalActors__/Maps/Main/A/BC/123", "/Game/__ExternalObjects__/Maps/Main/D/EF/456", "/Game/__ExternalActors__/Maps/MainExtra/A/BC/789"]
        self.assertEqual(conflicting_packages(packages, ["/Game/Maps/Main"]), set(packages[:2]))
        self.assertEqual(conflicting_packages(["/Game/Maps/Main"], packages[:1]), {"/Game/Maps/Main"})

    def test_map_change_before_dispatch_reports_specific_rejection(self):
        """/** @return 排队期间地图改变时在实际写入前明确拒绝 */"""
        self.backend.state["editor_world"] = "/Game/Maps/First.First"
        self.queue.observe(force=True)
        self.catalog.add({"id": "world.write", "name": "write", "definition": "Test", "toolset": "Test", "parameters": {"type": "object"}, "access": "write", "world": "editor", "scope": {"kind": "world"}})
        batch = self.queue.submit(self.first, [{"tool": "world.write", "arguments": {}}])["batch"]
        self.backend.state["editor_world"] = "/Game/Maps/Second.Second"
        self.queue.observe(force=True)
        self.queue.run_once()
        self.assertEqual(self.queue.jobs[batch]["code"], "EDITOR_WORLD_CHANGED")
        self.assertEqual(self.backend.calls, [])

    def test_recovery_occupancy_stays_bounded_in_default_context(self):
        """/** @return 多任务占用摘要保持有界 详细查询返回完整证据 */"""
        self.backend.reconcile = lambda packages: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        for index in range(20):
            self.submit(self.first, operation("unknown", asset="/Game/P" + str(index)))
            self.queue.run_once()
        summary = self.queue.inspect(self.second)
        self.assertEqual(summary["asset_occupancy_count"], 20)
        self.assertEqual(len(summary["asset_occupancy"]), 8)
        self.assertIn("edit", summary["available"])
        self.assertLess(len(json.dumps(summary)), 2400)

    def test_public_protocol_uses_one_automatic_completion_path(self):
        """/** @return 新协议保留单一写入完成和恢复流程 */"""
        schema = {tool["name"]: tool["inputSchema"] for tool in public_tools()}
        with self.assertRaises(ValueError):
            validate_arguments({"operations": [operation("read")], "completion": "review"}, schema["submit_batch"])
        with self.assertRaises(ValueError):
            validate_arguments({"action": "resume", "confirmation": "old"}, schema["control_task"])
        validate_arguments({"action": "close", "batch": "1234"}, schema["control_task"])


if __name__ == "__main__":
    unittest.main()
