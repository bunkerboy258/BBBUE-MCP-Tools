import copy
import json
import threading
import unittest
from unittest.mock import patch

import test_mcp_task_gateway as fixtures
from MCP.mcp_call import McpSession
from MCP.mcp_result import decode_tool_result
from MCP.mcp_task_gateway import TaskCoordinator, TaskConflict


class RecoveryCoordinatorTests(unittest.TestCase):
    """/** 核实失联接管的资产保留 身份撤销和确认边界 */"""

    def setUp(self):
        """/** @return 建立两个任务和一个携带待核实资产的过期阶段 */"""
        self.backend = fixtures.FakeBackend()
        self.now = 0
        self.manager = TaskCoordinator(self.backend.probe, lambda: self.now)
        self.owner = self.manager.acquire("owner", "原编辑任务", "editor")["task_token"]
        self.old_stage = self.manager.begin_write(self.owner, 30)["write_token"]
        self.claimant = self.manager.acquire("claimant", "接管收尾", "editor")["task_token"]
        record = self.manager.begin(fixtures.invocation("official.AssetTools", "import_assets"), self.owner, self.old_stage)
        self.packages = ["/Game/Test/Asset{}".format(index) for index in range(191)]
        self.backend.state["dirty_packages"] = list(self.packages)
        self.manager._observe()
        self.manager.record_result(record, "partial", "tool_execution_evidence")
        self.manager.finish(record)
        self.now = 31
        self.manager.inspect()

    def test_recovery_preserves_191_packages_and_revokes_both_old_credentials(self):
        """/** @return 确认接管保留资产与执行证据 后续仍需核实收尾 */"""
        self.manager.begin_write(self.claimant)
        preview = self.manager.prepare_recovery(self.claimant, "owner")
        self.assertEqual(preview["dirty_packages"], self.packages)
        self.assertEqual(preview["last_operation"]["dirty_added"], sorted(self.packages))
        self.assertEqual(preview["last_operation"]["execution_state"], "partial")
        result = self.manager.recover_write(self.claimant, preview["review_id"], preview["user_confirmation"])
        self.assertTrue(result["requires_result_review"])
        self.assertEqual(self.backend.state["dirty_packages"], self.packages)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.manager.writer, self.claimant)
        self.assertEqual(self.manager.inspect()["write_queue"], [])
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.renew_write(self.owner, self.old_stage, True)
        self.assertEqual(rejected.exception.value["code"], "TASK_TOKEN_INVALID")
        with self.assertRaises(TaskConflict):
            self.manager.begin(fixtures.invocation("official.AssetTools", "save_asset"), self.claimant, result["write_token"])
        self.manager.renew_write(self.claimant, result["write_token"], True)
        with self.assertRaises(TaskConflict):
            self.manager.end_write(self.claimant, result["write_token"])
        self.backend.state["dirty_packages"] = []
        self.manager.end_write(self.claimant, result["write_token"])
        self.assertIsNone(self.manager.writer)

    def test_live_owner_and_running_activity_keep_their_stage(self):
        """/** @return 有效阶段和实际后台活动保持原任务归属 */"""
        self.manager.renew_write(self.owner, self.old_stage, True)
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.prepare_recovery(self.claimant, "owner")
        self.assertEqual(rejected.exception.value["code"], "RECOVERY_OWNER_ACTIVE")
        self.now += 31
        self.backend.state["activities"] = ["capture"]
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.prepare_recovery(self.claimant, "owner")
        self.assertEqual(rejected.exception.value["code"], "RECOVERY_ACTIVITY_PENDING")
        self.assertEqual(self.manager.writer, self.owner)

    def test_confirmation_and_snapshot_change_are_checked(self):
        """/** @return 错误确认和变化后的包清单要求重新审批 */"""
        preview = self.manager.prepare_recovery(self.claimant, "owner")
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.recover_write(self.claimant, preview["review_id"], "批准")
        self.assertEqual(rejected.exception.value["code"], "RECOVERY_CONFIRMATION_REQUIRED")
        self.backend.state["dirty_packages"].pop()
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.recover_write(self.claimant, preview["review_id"], preview["user_confirmation"])
        self.assertEqual(rejected.exception.value["code"], "RECOVERY_EVIDENCE_CHANGED")
        self.assertEqual(self.manager.writer, self.owner)

    def test_preview_is_bound_to_claimant_one_use_and_expiry(self):
        """/** @return 预览由所属任务使用且在确认或到期后失效 */"""
        preview = self.manager.prepare_recovery(self.claimant, "owner")
        other = self.manager.acquire("other", "第三个任务", "editor")["task_token"]
        with self.assertRaises(TaskConflict):
            self.manager.recover_write(other, preview["review_id"], preview["user_confirmation"])
        self.manager.recover_write(self.claimant, preview["review_id"], preview["user_confirmation"])
        with self.assertRaises(TaskConflict) as rejected:
            self.manager.recover_write(self.claimant, preview["review_id"], preview["user_confirmation"])
        self.assertEqual(rejected.exception.value["code"], "RECOVERY_REVIEW_INVALID")

    def test_expired_preview_and_changed_host_preserve_owner(self):
        """/** @return 到期预览和宿主变化保持资产保护 */"""
        preview = self.manager.prepare_recovery(self.claimant, "owner")
        self.now += 301
        with self.assertRaises(TaskConflict):
            self.manager.recover_write(self.claimant, preview["review_id"], preview["user_confirmation"])
        self.assertEqual(self.manager.writer, self.owner)
        self.backend.state["host_instance"] = "replacement"
        with self.assertRaises(TaskConflict):
            self.manager.prepare_recovery(self.claimant, "owner")

    def test_original_credentials_recover_with_another_client_identity(self):
        """/** @return 恢复按凭证归属判断 客户端身份可变化 */"""
        self.manager.renew_write(self.owner, self.old_stage, True)
        self.assertFalse(self.manager.tasks[self.owner]["uncertain"])
        self.assertEqual(self.backend.state["dirty_packages"], self.packages)
        self.assertEqual(self.manager.writer, self.owner)

    def test_pending_pie_and_inflight_requests_preserve_owner(self):
        """/** @return 未生效 PIE 和实际请求完成后才能预览接管 */"""
        record = self.manager.tasks[self.owner]
        for changed in [{"pie_request": "start_pie"}, {"inflight": 1}]:
            original = {key: record[key] for key in changed}
            record.update(changed)
            with self.assertRaises(TaskConflict) as rejected:
                self.manager.prepare_recovery(self.claimant, "owner")
            self.assertEqual(rejected.exception.value["code"], "RECOVERY_ACTIVITY_PENDING")
            record.update(original)
        for changed in [{"pie_active": True}, {"worlds": ["PIE_0"]}]:
            original = {key: self.backend.state[key] for key in changed}
            self.backend.state.update(changed)
            with self.assertRaises(TaskConflict):
                self.manager.prepare_recovery(self.claimant, "owner")
            self.backend.state.update(original)
        self.assertEqual(self.manager.writer, self.owner)

    def test_public_state_hides_credentials_and_exposes_actionable_queue(self):
        """/** @return 公共证据隐藏凭证 清洁交接提供下一次调用参数 */"""
        self.manager.begin_write(self.claimant)
        self.manager.prepare_recovery(self.claimant, "owner")
        state = self.manager.inspect(self.claimant)
        self.assertEqual(state["summary"]["caller"]["recovery_preview"]["target_task_id"], "owner")
        for secret in [self.owner, self.claimant, self.old_stage]:
            self.assertNotIn(secret, json.dumps(state))
        self.manager.renew_write(self.owner, self.old_stage, True)
        self.backend.state["dirty_packages"] = []
        self.manager.end_write(self.owner, self.old_stage)
        advice = self.manager.inspect(self.claimant)["summary"]["caller"]
        self.assertTrue(advice["can_claim_write"])
        self.assertEqual(advice["next_call"], "begin_editor_write")
        self.assertEqual(advice["next_arguments"]["wait_seconds"], 0)


class RecoveryHttpTests(unittest.TestCase):
    """/** 使用独立随机端口核实真实协议与客户端续期 */"""

    tearDown = fixtures.HttpGatewayTests.tearDown

    def setUp(self):
        """/** @return 复用隔离后端并由各用例明确控制续期 */"""
        fixtures.HttpGatewayTests.setUp(self)
        self.A._auto_heartbeat = False
        self.B._auto_heartbeat = False
        self.A.acquire_task("A", "执行证据")
        self.A.begin_write(ttl_seconds=30)

    def write_with_response(self, result, dirty=None):
        """
        /**
         * 通过真实 HTTP 返回指定执行证据
         * @param result	后端协议内容
         * @param dirty	操作后的包状态
         * @return 无返回值
         */
        """
        original = self.backend.relay

        def relay(body, headers, method="POST"):
            """/** @param body 请求 @param headers 会话 @param method 方法 @return 指定响应 */"""
            if method == "POST" and body.get("method") == "tools/call" and fixtures.tool_identity(body["params"])[1] == "save_asset":
                if dirty is not None:
                    self.backend.state["dirty_packages"] = dirty
                payload = copy.deepcopy(result)
                payload.update(jsonrpc="2.0", id=body["id"])
                return 200, {}, payload
            return original(body, headers, method)

        with patch.object(self.backend, "relay", relay):
            try:
                self.A.call_tool("official.AssetTools.save_asset", {"private": "secret-input"})
            except RuntimeError:
                pass

    def test_protocol_parameter_rejection_keeps_stage_usable(self):
        """/** @return 明确调用前拒绝保留可用阶段和结构化原因 */"""
        self.write_with_response({"error": {"code": -32602, "message": "参数校验失败"}})
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertFalse(task["uncertain"])
        self.assertEqual(task["last_operation"]["execution_state"], "rejected")
        self.assertNotIn("secret-input", json.dumps(task))
        self.A.end_write()

    def test_declared_rejection_partial_and_unverified_business_failure(self):
        """/** @return 工具证据与待核实业务失败各自保持正确恢复要求 */"""
        failure = {"content": [{"type": "text", "text": json.dumps({"success": False, "code": "INVALID_TARGET"})}], "isError": True}
        failure["_meta"] = {"bbb/execution": {"state": "rejected"}}
        self.write_with_response({"result": failure})
        self.assertFalse(self.B.inspect_tasks()["tasks"][0]["uncertain"])
        failure["_meta"]["bbb/execution"]["state"] = "partial"
        self.write_with_response({"result": failure}, ["/Game/Test/Partial"])
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertTrue(task["uncertain"])
        self.assertEqual(task["last_operation"]["execution_state"], "partial")
        self.assertEqual(task["last_operation"]["dirty_added"], ["/Game/Test/Partial"])
        self.A.renew_write(True)
        failure.pop("_meta")
        self.write_with_response({"result": failure})
        self.assertEqual(self.B.inspect_tasks()["tasks"][0]["uncertainty_reason"], "business_error_without_execution_evidence")

    def test_official_string_execution_evidence_keeps_rejection_usable(self):
        """/** @return 官方字符串返回值传递拒绝证据 客户端继续原阶段 */"""
        from MCP.mcp_result import McpExecutionError
        value = McpExecutionError("rejected", "HIT_CAPTURE_EXISTS", "使用新前缀").value
        self.write_with_response({"result": {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(value)})}]}})
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertFalse(task["uncertain"])
        self.assertEqual(task["last_operation"]["execution_state"], "rejected")
        self.assertEqual(task["last_operation"]["error_code"], "HIT_CAPTURE_EXISTS")
        self.A.end_write()

    def test_second_original_host_blocks_write_and_retains_reads(self):
        """/** @return 多宿主冲突保留查询与阶段归属 并阻止实际资产写入 */"""
        self.backend.state["project_hosts"] = {"verified": True, "exclusive": False,
            "hosts": [{"process_id": 100, "public_port": 8010}, {"process_id": 200, "public_port": 8011}]}
        calls = len(self.backend.calls)
        with self.assertRaisesRegex(RuntimeError, "PROJECT_HOST_CONFLICT"):
            self.A.call_tool("official.AssetTools.save_asset", {})
        self.assertEqual(len(self.backend.calls), calls)
        state = self.B.inspect_tasks()
        self.assertIn("PROJECT_HOST_CONFLICT", [item["code"] for item in state["summary"]["blockers"]])
        self.assertFalse(state["tasks"][0]["uncertain"])
        self.backend.state["project_hosts"]["exclusive"] = True
        self.A.call_tool("official.AssetTools.save_asset", {})

    def test_rejection_conflicting_with_actual_write_requires_review(self):
        """/** @return 拒绝声明与实际包变化冲突时保留核实要求 */"""
        self.write_with_response({"error": {"code": -32602}}, ["/Game/Test/Unexpected"])
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertTrue(task["uncertain"])
        self.assertEqual(task["last_operation"]["reason"], "rejection_conflicts_with_host_changes")

    def test_transport_failure_preserves_operation_and_credentials(self):
        """/** @return 传输中断记录工具及包变化并保留原凭证 */"""
        self.backend.state["dirty_packages"] = ["/Game/Test/Before"]
        original = self.backend.relay

        def fail(body, headers, method="POST"):
            """/** @param body 请求 @param headers 会话 @param method 方法 @return 模拟写后断连 */"""
            if body and body.get("method") == "tools/call":
                self.backend.state["dirty_packages"].append("/Game/Test/After")
                raise RuntimeError("private-endpoint-and-secret")
            return original(body, headers, method)

        with patch.object(self.backend, "relay", fail):
            with self.assertRaises(RuntimeError):
                self.A.call_tool("official.AssetTools.save_asset", {})
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertEqual(task["last_operation"]["tool"], "save_asset")
        self.assertEqual(task["last_operation"]["execution_state"], "unknown")
        self.assertEqual(task["last_operation"]["dirty_added"], ["/Game/Test/After"])
        self.assertNotIn("private-endpoint", json.dumps(task))
        self.assertIsNotNone(self.A.write_token)

    def test_recovery_via_sdk_requires_explicit_review_then_preserves_assets(self):
        """/** @return 接管客户端保留阶段凭证并按证据核实资产 */"""
        self.backend.state["dirty_packages"] = ["/Game/Test/Dirty"]
        self.gateway.coordinator.tasks[self.A.task_token]["uncertain"] = True
        self.gateway.coordinator.tasks[self.A.task_token]["write"]["expires_at"] = 0
        self.B.acquire_task("B", "用户批准接管")
        preview = self.B.prepare_recovery("A")
        result = self.B.recover_write(preview["review_id"], preview["user_confirmation"])
        self.assertTrue(result["requires_result_review"])
        self.assertIsNotNone(self.B.write_token)
        with self.assertRaises(RuntimeError):
            self.A.renew_write(True)
        self.assertIsNone(self.A.task_token)
        self.B.renew_write(True)
        self.backend.state["dirty_packages"] = []
        self.B.end_write()

    def test_malformed_response_and_failed_observation_preserve_review_requirement(self):
        """/** @return 解析与探针失败提供准确证据并保留阶段保护 */"""
        self.write_with_response({"result": {"content": None}})
        task = self.B.inspect_tasks()["tasks"][0]
        self.assertTrue(task["uncertain"])
        self.assertEqual(task["last_operation"]["reason"], "response_decode_failed")
        self.assertFalse(task["last_operation"]["observation_verified"])
        self.A.renew_write(True)
        original_relay = self.backend.relay
        original_probe = self.backend.probe
        dispatched = threading.Event()

        def relay(body, headers, method="POST"):
            """/** @param body 请求 @param headers 会话 @param method 方法 @return 返回后标记已派发 */"""
            result = original_relay(body, headers, method)
            if body and body.get("method") == "tools/call":
                dispatched.set()
            return result

        def probe():
            """/** @return 模拟派发后的探针中断 */"""
            if dispatched.is_set():
                raise RuntimeError("private-probe-path")
            return original_probe()

        with patch.object(self.backend, "relay", relay), patch.object(self.gateway.coordinator, "probe", probe):
            with self.assertRaises(RuntimeError):
                self.A.call_tool("official.AssetTools.save_asset", {})
        task = self.B.inspect_tasks()["tasks"][0]
        evidence = task["last_operation"]
        self.assertEqual(evidence["execution_state"], "unknown")
        self.assertFalse(evidence["observation_verified"])
        self.assertIsNone(evidence["dirty_after_count"])
        self.assertIsNone(evidence["dirty_added"])

    def test_heartbeat_runs_beside_real_inflight_request(self):
        """/** @return 独立续期连接与实际执行连接并存且保持计数 */"""
        renewed = threading.Event()
        errors = []
        original = self.gateway.coordinator.renew_write

        def renew(*args, **kwargs):
            """/** @param args 凭证 @param kwargs 选项 @return 续期结果 */"""
            value = original(*args, **kwargs)
            renewed.set()
            return value

        def work():
            """/** @return 记录实际请求结果 */"""
            try:
                self.A.call_tool("official.EditorTools.long_operation", {})
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=work)
        worker.start()
        try:
            self.assertTrue(self.backend.entered.wait(2))
            self.A._auto_heartbeat = True
            with patch.object(self.gateway.coordinator, "renew_write", renew):
                self.A._start_heartbeat(0.3)
                self.assertTrue(renewed.wait(2))
                self.assertEqual(self.gateway.coordinator.tasks[self.A.task_token]["write_inflight"], 1)
                self.assertEqual(self.B.inspect_tasks()["writer_task_id"], "A")
        finally:
            self.backend.complete.set()
            worker.join(5)
            self.A._stop_heartbeat()
        self.assertEqual(errors, [])
        self.A.end_write()

    def test_heartbeat_renews_idle_owner_and_stops_with_client(self):
        """/** @return 空闲客户端续期一次 关闭后续期结束且资产保留 */"""
        owner = self.gateway.coordinator.tasks[self.A.task_token]
        original_expiry = owner["write"]["expires_at"]
        renewed = threading.Event()
        original = self.gateway.coordinator.renew_write

        def renew(*args, **kwargs):
            """/** @param args 凭证 @param kwargs 恢复参数 @return 真实续期结果 */"""
            result = original(*args, **kwargs)
            renewed.set()
            return result

        self.A._auto_heartbeat = True
        with patch.object(self.gateway.coordinator, "renew_write", renew):
            self.A._start_heartbeat(0.3)
            self.assertTrue(renewed.wait(3))
            self.assertGreater(owner["write"]["expires_at"], original_expiry)
            self.backend.state["dirty_packages"] = ["/Game/Test/Owned"]
            self.A.close()
        self.assertFalse(self.A._heartbeat_thread.is_alive())
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/Test/Owned"])
        self.assertEqual(self.B.inspect_tasks()["writer_task_id"], "A")

    def test_heartbeat_failure_stops_without_resuming_uncertain_work(self):
        """/** @return 续期失败后等待显式恢复并保留原凭证 */"""
        owner = self.gateway.coordinator.tasks[self.A.task_token]
        owner["uncertain"] = True
        self.A._auto_heartbeat = True
        self.A._start_heartbeat(0.3)
        self.A._heartbeat_thread.join(3)
        self.assertFalse(self.A._heartbeat_thread.is_alive())
        self.assertEqual(self.A.heartbeat_error, "HEARTBEAT_STOPPED_CHECK_EDITOR_STATE")
        self.assertIsNotNone(self.A.write_token)
        self.assertTrue(owner["uncertain"])


if __name__ == "__main__":
    unittest.main()
