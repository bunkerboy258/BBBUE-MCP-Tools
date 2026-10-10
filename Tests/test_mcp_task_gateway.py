import copy
import builtins
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch
import requests

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import McpSession, McpWriteBatchError
from MCP.mcp_result import decode_tool_result
from MCP.mcp_task_gateway import TaskCoordinator, TaskConflict, TaskGateway, is_read_call, make_server, tool_identity


def invocation(toolset, name, arguments=None):
    """
    /**
     * @param toolset	工具集
     * @param name	实际工具
     * @param arguments	业务参数
     * @return 工具搜索调用结构
     */
    """
    return {"name": "call_tool", "arguments": {"toolset_name": toolset, "tool_name": name, "arguments": arguments or {}}}


class FakeBackend:
    """/** 可控异步行为 不启动 UE 或修改资产 */"""

    def __init__(self):
        """
        /**
         * 初始化本对象的任务保护状态
         * @return 操作结果或验证完成
         */
        """
        self.state = {"process_id": 42, "host_instance": "one", "project_root": "project",
            "pie_active": False, "pie_generation": 0, "worlds": [], "activities": [], "dirty_packages": []}
        self.process_id = 42
        self.calls = []
        self.sequence = 0
        self.entered = threading.Event()
        self.complete = threading.Event()

    def probe(self):
        """/** @return 实际活动快照 */"""
        return copy.deepcopy(self.state)

    def shutdown(self):
        """/** @return 记录退出请求 */"""
        self.calls.append("shutdown")

    def relay(self, body, headers, method="POST"):
        """
        /**
         * @param body	协议请求
         * @param headers	协议会话
         * @param method	HTTP 方法
         * @return 最终协议结果
         */
        """
        if method == "DELETE" or body["method"] == "notifications/initialized":
            return 202, {}, b""
        request_id = body["id"]
        if body["method"] == "initialize":
            self.sequence += 1
            return 200, {"Mcp-Session-Id": str(self.sequence)}, {"jsonrpc": "2.0", "id": request_id,
                "result": {"protocolVersion": "2025-11-25"}}
        if body["method"] == "tools/list":
            return 200, {}, {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [{
                "name": "call_tool", "inputSchema": {"type": "object", "properties": {}},
            }]}}
        params = body["params"]
        toolset, name, arguments = tool_identity(params)
        self.calls.append((toolset, name, arguments, params.get("_meta")))
        if name == "util" and arguments.get("action") == "start_pie":
            self.state.update(pie_active=True, worlds=["PIE_0"], pie_generation=self.state["pie_generation"] + 1)
        if name == "util" and arguments.get("action") == "stop_pie":
            self.state.update(pie_active=False, worlds=[], pie_generation=self.state["pie_generation"] + 1)
        if name == "long_operation":
            self.entered.set()
            if not self.complete.wait(5):
                raise RuntimeError("隔离测试超时")
        if name == "fail_after_write":
            raise RuntimeError("连接中断")
        value = {"executed": name}
        if name == "get_mcp_usage_guide":
            value = {"returnValue": json.dumps({"document_path": "guide"})}
        if name == "describe_toolset":
            value = {"returnValue": json.dumps({"tools": [{"name": name, "inputSchema": {}}
                for name in ["find_assets", "delete"]]})}
        if name == "list_toolsets":
            value = "- project.BBBExternalToolset: 外部动作\n"
        return 200, {}, {"jsonrpc": "2.0", "id": request_id,
            "result": {"content": [{"type": "text", "text": json.dumps(value)}]}}


class CoordinatorTests(unittest.TestCase):
    """/** 归属 失联 世界变更与释放边界 */"""

    def setUp(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.backend = FakeBackend()
        self.now = 0
        self.manager = TaskCoordinator(self.backend.probe, lambda: self.now)
        self.stages = {}

    def acquire(self, name="A", mode="pie"):
        """/** @param name 任务 @param mode 模式 @return 凭证 */"""
        token = self.manager.acquire(name, "测试 " + name, mode, 300)["task_token"]
        if mode != "read":
            stage = self.manager.begin_write(token, 30)
            if stage["status"] == "active":
                self.stages[token] = stage["write_token"]
        return token

    def test_exclusive_owner_and_registered_readers(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        owner = self.acquire()
        reader = self.acquire("B", "read")
        contender = self.manager.acquire("C", "等待编辑", "editor")["task_token"]
        self.assertEqual(self.manager.begin_write(contender)["status"], "queued")
        with self.assertRaises(TaskConflict):
            self.manager.begin(invocation("official.AssetTools", "save_asset"), reader)
        snapshot = self.manager.inspect()
        for secret in [owner, reader, self.stages[owner]]:
            self.assertNotIn(secret, json.dumps(snapshot))
        self.manager.end_write(owner, self.stages[owner])
        self.manager.release(owner)
        self.manager.cancel_write(contender)
        self.manager.release(contender)
        with self.assertRaises(TaskConflict):
            self.manager.prepare_shutdown()
        self.manager.release(reader)
        self.manager.prepare_shutdown()
        with self.assertRaises(TaskConflict):
            self.acquire("C")

    def test_expiry_freezes_operations_and_never_stops_pie(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        token = self.acquire()
        self.backend.state.update(pie_active=True, worlds=["PIE_0"])
        self.now = 31
        self.manager.inspect()
        with self.assertRaises(TaskConflict):
            self.manager.begin(invocation("project.BBBExternalToolset", "util", {"action": "stop_pie"}), token, self.stages[token])
        contender = self.acquire("B")
        self.assertNotIn(contender, self.stages)
        self.assertEqual(self.manager.inspect()["write_queue"], ["B"])
        with self.assertRaises(TaskConflict):
            self.manager.renew(token)
        self.manager.renew_write(token, self.stages[token], resume=True)
        self.assertTrue(self.backend.state["pie_active"])
        self.assertEqual(self.backend.calls, [])

    def test_external_pie_and_background_jobs_block_acquisition(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        for activity in [{"pie_active": True}, {"worlds": ["PIE_0"]}, {"activities": ["capture"]}]:
            self.backend.state.update(activity)
            token = self.acquire()
            self.assertNotIn(token, self.stages)
            self.assertEqual(self.manager.inspect()["write_queue"], ["A"])
            self.assertEqual(len(self.manager.tasks), 1)
            self.assertIsNone(self.manager.writer)
            self.backend = FakeBackend()
            self.manager = TaskCoordinator(self.backend.probe, lambda: self.now)

    def test_background_capture_and_pending_start_block_release(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        token = self.acquire()
        record = self.manager.tasks[token]
        record["pie_request"] = "start_pie"
        with self.assertRaises(TaskConflict):
            self.manager.end_write(token, self.stages[token])
        self.backend.state.update(pie_active=True, worlds=["PIE_0"], pie_generation=1)
        self.manager.inspect()
        self.assertIsNone(record["pie_request"])
        record["pie_request"] = "stop_pie"
        self.backend.state.update(pie_active=False, worlds=[], pie_generation=2, activities=["capture"])
        self.manager.inspect()
        with self.assertRaises(TaskConflict):
            self.manager.end_write(token, self.stages[token])
        self.backend.state["activities"] = []
        self.manager.end_write(token, self.stages[token])
        self.manager.release(token)

    def test_uncertain_request_requires_original_token_and_explicit_recovery(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        token = self.acquire()
        record = self.manager.begin(invocation("official.AssetTools", "save_asset"), token, self.stages[token])
        self.manager.finish(record, uncertain=True)
        with self.assertRaises(TaskConflict):
            self.manager.end_write(token, self.stages[token])
        with self.assertRaises(TaskConflict):
            self.manager.renew_write("wrong", self.stages[token], resume=True)
        with self.assertRaises(TaskConflict):
            self.manager.renew(token, resume=True)
        self.manager.renew_write(token, self.stages[token], resume=True)
        self.manager.end_write(token, self.stages[token])
        self.manager.release(token)
        with self.assertRaises(TaskConflict):
            self.manager.begin(invocation("official.AssetTools", "save_asset"), token, self.stages[token])

    def test_host_replacement_and_external_world_change_fence_owner(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        token = self.acquire()
        self.backend.state["pie_generation"] = 1
        self.assertTrue(self.manager.inspect()["tasks"][0]["uncertain"])
        self.manager.renew_write(token, self.stages[token], resume=True)
        self.backend.state["host_instance"] = "two"
        self.assertTrue(self.manager.inspect()["host_changed"])
        with self.assertRaises(TaskConflict):
            self.manager.renew_write(token, self.stages[token], resume=True)
        with self.assertRaises(TaskConflict):
            self.manager.begin(invocation("official.AssetTools", "save_asset"), token, self.stages[token])

    def test_dirty_packages_and_external_activity_prevent_shutdown(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        for key, value in [("dirty_packages", ["/Game/Unsaved"]), ("activities", ["audio"]), ("pie_active", True)]:
            self.backend.state[key] = value
            with self.assertRaises(TaskConflict):
                self.manager.prepare_shutdown()
            self.assertFalse(self.manager.draining)
            self.backend.state[key] = [] if isinstance(value, list) else False

    def test_operation_classification_uses_effects_and_dynamic_actions(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.assertTrue(is_read_call(invocation("PythonTypes.BBBExternalToolset_0x1234ABCD", "util", {"action": "is_in_pie"})))
        self.assertFalse(is_read_call(invocation("project.BBBExternalToolset", "util", {"action": "stop_pie"})))
        self.assertFalse(is_read_call(invocation("project.BBBAnimationPreviewToolset", "inspect_mass_inspection_population", {"pause_game": True})))
        self.assertTrue(is_read_call(invocation("project.BBBAnimationPreviewToolset", "inspect_mass_inspection_population")))
        self.assertFalse(is_read_call(invocation("official.UnknownTools", "inspect_with_side_effects")))
        token = self.acquire()
        for params in [invocation("official.ProgrammaticToolset", "execute_tool_script"), invocation("PythonTypes.BBBExternalToolset_0x1234ABCD", "util", {"action": "execute_console_command"})]:
            with self.assertRaises(TaskConflict):
                self.manager.begin(params, token)

    def test_simultaneous_acquisition_has_single_winner(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        barrier = threading.Barrier(3)
        outcomes = []

        def acquire(name):
            """/** @param name 任务 @return 记录并发申请结果 */"""
            barrier.wait()
            try:
                token = self.acquire(name)
                outcomes.append("owner" if token in self.stages else "blocked")
            except TaskConflict:
                outcomes.append("blocked")

        threads = [threading.Thread(target=acquire, args=(name,)) for name in ["A", "B"]]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(5)
        self.assertCountEqual(outcomes, ["owner", "blocked"])
        self.assertEqual(len(self.manager.tasks), 2)


    def test_idle_registration_allows_other_editor_and_clean_expiry_fences_old_stage(self):
        """/** @return 分析任务不挡编辑 清洁超时阶段撤销旧凭证 */"""
        first = self.manager.acquire("A", "分析任务", "editor")["task_token"]
        second = self.manager.acquire("B", "实际编辑", "editor")["task_token"]
        stage = self.manager.begin_write(second, 30)["write_token"]
        self.now = 31
        state = self.manager.inspect()
        self.assertIsNone(state["writer_task_id"])
        self.assertEqual(state["tasks"][1]["last_write_state"], "expired")
        next_stage = self.manager.begin_write(first)["write_token"]
        with self.assertRaises(TaskConflict):
            self.manager.begin(invocation("official.AssetTools", "save_asset"), second, stage)
        self.manager.end_write(first, next_stage)
        replacement = self.manager.begin_write(second)["write_token"]
        with self.assertRaises(TaskConflict) as failure:
            self.manager.begin(invocation("official.AssetTools", "save_asset"), second, stage)
        self.assertEqual(failure.exception.value["code"], "WRITE_TOKEN_INVALID")
        record = self.manager.begin(invocation("official.AssetTools", "save_asset"), second, replacement)
        self.manager.finish(record)

    def test_expired_dirty_or_uncertain_stage_keeps_protection(self):
        """/** @return 未保存内容和不确定结果不会通过超时转给其他任务 */"""
        token = self.acquire()
        self.backend.state["dirty_packages"] = ["/Game/Unsaved"]
        self.now = 31
        self.assertEqual(self.manager.inspect()["writer_task_id"], "A")
        self.backend.state["dirty_packages"] = []
        self.manager.tasks[token]["uncertain"] = True
        self.assertEqual(self.manager.inspect()["writer_task_id"], "A")
        self.assertEqual(self.manager.tasks[token]["write"]["status"], "orphaned")

    def test_actual_response_keeps_stage_alive_beyond_its_deadline(self):
        """/** @return 请求仍在执行时超时不会让出写权限 */"""
        token = self.acquire()
        record = self.manager.begin(invocation("official.AssetTools", "save_asset"), token, self.stages[token])
        self.now = 31
        self.assertEqual(self.manager.inspect()["writer_task_id"], "A")
        self.manager.finish(record)
        self.assertEqual(self.manager.inspect()["writer_task_id"], "A")

    def test_idle_expired_registration_does_not_keep_host_alive_forever(self):
        """/** @return 没有请求或编辑阶段的失联登记可安全回收 */"""
        token = self.manager.acquire("A", "已失联分析", "editor", 30)["task_token"]
        self.now = 31
        self.assertEqual(self.manager.inspect()["tasks"], [])
        with self.assertRaises(TaskConflict):
            self.manager.begin_write(token)
        self.manager.prepare_shutdown()


class HttpGatewayTests(unittest.TestCase):
    """/** 使用真实 HTTP 的双客户端验证 */"""

    def setUp(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.backend = FakeBackend()
        self.gateway = TaskGateway(self.backend)
        self.server = make_server(("127.0.0.1", 0), self.gateway)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = "http://127.0.0.1:{}/mcp".format(self.server.server_port)
        self.A = McpSession(self.url, 10)
        self.B = McpSession(self.url, 10)

    def tearDown(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.A.close()
        self.B.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(5)

    def call(self, session, action):
        """/** @param session 客户端 @param action 动作 @return 外部工具结果 */"""
        return session.call_tool("call_tool", {"toolset_name": "project.BBBExternalToolset", "tool_name": "util", "arguments": {"action": action}})

    def test_other_client_cannot_start_pause_stop_or_write_owner_pie(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.A.acquire_task("A", "PIE 验收", "pie")
        self.A.begin_write()
        self.call(self.A, "start_pie")
        self.call(self.B, "is_in_pie")
        self.B.acquire_task("B", "登记可并存", "editor")
        before = len(self.backend.calls)
        for action in ["start_pie", "stop_pie", "set_cvar", "save_all_dirty"]:
            with self.assertRaises(RuntimeError) as failure:
                self.call(self.B, action)
            self.assertEqual(failure.exception.value["state"]["summary"]["caller"]["task_id"], "B")
        with self.assertRaises(RuntimeError):
            self.B.call_tool("official.LevelTools.pause_pie", {})
        self.assertEqual(self.B.begin_write()["status"], "queued")
        self.assertEqual(len(self.backend.calls), before)
        self.call(self.A, "stop_pie")
        self.A.end_write()
        self.A.release_task()

    def test_reconnect_preserves_task_and_explicit_release_invalidates_token(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        lease = self.A.acquire_task("A", "跨连接任务")
        stage = self.A.begin_write()
        self.A.close()
        self.B.acquire_task("B", "其他登记")
        self.assertEqual(self.B.begin_write()["status"], "queued")
        self.A = McpSession(self.url, 10, lease["task_token"], stage["write_token"])
        self.A.renew_write()
        self.call(self.A, "set_cvar")
        self.A.end_write()
        self.B.begin_write()
        self.A.release_task()

    def test_real_response_lifetime_blocks_release_and_competing_writer(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        lease = self.A.acquire_task("A", "异步请求")
        self.A.begin_write()
        self.B.acquire_task("B", "等待写权限")
        failure = []

        def work():
            """/** @return 保留实际请求异常 */"""
            try:
                self.A.call_tool("official.EditorTools.long_operation", {})
            except Exception as error:
                failure.append(error)

        thread = threading.Thread(target=work)
        thread.start()
        self.assertTrue(self.backend.entered.wait(3))
        with self.assertRaises(RuntimeError):
            self.B.call_tool("release_editor_task", {"task_token": lease["task_token"]})
        self.assertEqual(self.B.begin_write()["status"], "queued")
        self.backend.complete.set()
        thread.join(5)
        self.assertEqual(failure, [])
        self.A.end_write()
        self.A.release_task()

    def test_discovery_and_call_tool_access_to_control_tools(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        tools = self.B.list_tools()["result"]["tools"]
        self.assertIn("begin_editor_write", {tool["name"] for tool in tools})
        schema = next(tool for tool in tools if tool["name"] == "call_tool")["inputSchema"]["properties"]
        self.assertIn("task_token", schema)
        self.assertIn("write_token", schema)
        guide = decode_tool_result(self.B.call_tool("describe_toolset", {"toolset_name": "bbb_task"}))
        self.assertEqual(len(guide["tools"]), 11)
        state = decode_tool_result(self.B.call_tool("call_tool", {"tool_name": "inspect_editor_tasks", "arguments": {}}))
        self.assertEqual(state["activity"]["process_id"], 42)

    def test_transmission_failure_does_not_release_or_retry(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        self.A.acquire_task("A", "不确定写入")
        self.A.begin_write()
        with self.assertRaises(RuntimeError):
            self.A.call_tool("official.AssetTools.fail_after_write", {})
        with self.assertRaises(RuntimeError):
            self.call(self.A, "set_cvar")
        with self.assertRaises(RuntimeError):
            self.A.end_write()
        with self.assertRaises(RuntimeError):
            self.A.renew_task(resume=True)
        self.A.renew_write(resume=True)
        self.A.end_write()
        self.A.release_task()
        self.assertEqual(sum(call[1] == "fail_after_write" for call in self.backend.calls), 1)

    def test_task_token_argument_is_removed_before_official_dispatch(self):
        """
        /**
         * 验证本项任务保护和实际调用结果
         * @return 操作结果或验证完成
         */
        """
        lease = self.A.acquire_task("A", "参数凭证")
        stage = self.A.begin_write()
        self.B.call_tool("call_tool", {
            "task_token": lease["task_token"], "write_token": stage["write_token"],
            "toolset_name": "official.AssetTools", "tool_name": "save_asset", "arguments": {"asset": "A"},
        })
        self.assertEqual(self.backend.calls[-1][2], {"asset": "A"})

    def test_failed_read_does_not_freeze_an_edit_stage(self):
        """/** @return 查询失败不会把没有写入的阶段标为不确定 */"""
        self.A.acquire_task("A", "只读失败验证")
        self.A.begin_write()
        original = self.backend.relay
        for transport_failure in [False, True]:
            def failing_read(body, headers, method="POST"):
                """/** @param body 请求 @param headers 会话 @param method 方法 @return 查询失败 */"""
                if method == "POST" and body.get("method") == "tools/call" and tool_identity(body["params"])[1] == "IsPIERunning":
                    if transport_failure:
                        raise RuntimeError("查询连接中断")
                    return 200, {}, {"jsonrpc": "2.0", "id": body["id"], "result": {
                        "content": [{"type": "text", "text": json.dumps({"success": False})}], "isError": True,
                    }}
                return original(body, headers, method)

            with patch.object(self.backend, "relay", failing_read):
                with self.assertRaises(RuntimeError):
                    self.A.call_tool("official.EditorAppToolset.IsPIERunning", {})
            snapshot = decode_tool_result(self.B.call_tool("inspect_editor_tasks", {}))
            self.assertFalse(snapshot["tasks"][0]["uncertain"])
            self.call(self.A, "set_cvar")
        self.A.end_write()

    def test_business_failure_after_write_requires_recovery(self):
        """/** @return 未设置协议错误的业务写入失败也保留阶段归属 */"""
        self.A.acquire_task("A", "业务失败验证")
        self.A.begin_write()
        original = self.backend.relay

        def failed_write(body, headers, method="POST"):
            """/** @param body 请求 @param headers 会话 @param method 方法 @return 业务失败 */"""
            result = original(body, headers, method)
            if method == "POST" and body.get("method") == "tools/call" and tool_identity(body["params"])[1] == "save_asset":
                result[2]["result"]["content"][0]["text"] = json.dumps({"success": False})
            return result

        with patch.object(self.backend, "relay", failed_write):
            with self.assertRaises(RuntimeError):
                self.A.call_tool("official.AssetTools.save_asset", {})
        with self.assertRaises(RuntimeError):
            self.A.end_write()
        self.A.renew_write(resume=True)
        self.A.end_write()

    def test_session_close_after_backend_exit_does_not_log_private_endpoint(self):
        """/** @return 后端已退出时仅清理协议会话 保留任务且不输出私有地址 */"""
        self.A.acquire_task("A", "退出连接验证")
        self.A.begin_write()
        with patch.object(self.backend, "relay", side_effect=requests.ConnectionError("private-backend-path")):
            self.A.close()
        snapshot = decode_tool_result(self.B.call_tool("inspect_editor_tasks", {}))
        self.assertEqual(snapshot["writer_task_id"], "A")
        self.assertEqual(len(snapshot["tasks"]), 1)

    def test_failed_pie_request_keeps_pending_effect_until_actual_observation(self):
        """/** @return 报错不能抹去可能已经排入 UE 的世界变更请求 */"""
        self.A.acquire_task("A", "延迟 PIE 请求", "pie")
        self.A.begin_write()
        original = self.backend.relay

        def delayed_failure(body, headers, method="POST"):
            """/** @param body 请求 @param headers 会话 @param method 方法 @return 延迟请求错误 */"""
            if method == "POST" and body.get("method") == "tools/call" and tool_identity(body["params"])[2].get("action") == "start_pie":
                return 200, {}, {"jsonrpc": "2.0", "id": body["id"], "result": {
                    "content": [{"type": "text", "text": json.dumps({"success": False})}], "isError": True,
                }}
            return original(body, headers, method)

        with patch.object(self.backend, "relay", delayed_failure):
            with self.assertRaises(RuntimeError):
                self.call(self.A, "start_pie")
        snapshot = decode_tool_result(self.B.call_tool("inspect_editor_tasks", {}))
        self.assertEqual(snapshot["tasks"][0]["pie_request"], "start_pie")
        with self.assertRaises(RuntimeError):
            self.A.renew_write(resume=True)
        with self.assertRaises(RuntimeError):
            self.A.end_write()
        self.backend.state.update(pie_active=True, worlds=["PIE_0"], pie_generation=1)
        self.B.call_tool("inspect_editor_tasks", {})
        self.A.renew_write(resume=True)
        self.call(self.A, "stop_pie")
        self.A.end_write()

    def test_external_world_change_is_detected_before_owner_write(self):
        """/** @return 外部世界变更阻止下一次写请求到达后端 */"""
        self.A.acquire_task("A", "世界归属验证")
        self.A.begin_write()
        self.backend.state.update(pie_active=True, worlds=["external"], pie_generation=1)
        before = len(self.backend.calls)
        with self.assertRaises(RuntimeError):
            self.call(self.A, "set_cvar")
        self.assertEqual(len(self.backend.calls), before)
        state = decode_tool_result(self.B.call_tool("inspect_editor_tasks", {}))
        self.assertTrue(state["tasks"][0]["uncertain"])

    def test_untracked_pcg_generation_is_blocked_and_logic_query_is_readonly(self):
        """/** @return 无活动探针的生成被拒绝 逻辑查询可并存 */"""
        self.A.acquire_task("A", "异步活动保护")
        self.A.begin_write()
        before = len(self.backend.calls)
        with self.assertRaises(RuntimeError):
            self.A.call_tool("project.BBBGenericEditorToolset.generate_and_inspect_pcg", {"generate": True})
        self.assertEqual(len(self.backend.calls), before)
        self.B.call_tool("PythonTypes.BBBBlueprintGraphToolset_0x1234ABCD.inspect_blueprint_graph_logic", {"graph_path": "/Game/Probe.Graph"})
        self.assertEqual(self.backend.calls[-1][1], "inspect_blueprint_graph_logic")


    def test_two_registered_editors_can_take_turns_without_ending_tasks(self):
        """/** @return 两个分析任务保留登记并交替完成编辑阶段 */"""
        self.A.acquire_task("A", "持续分析")
        self.B.acquire_task("B", "持续分析")
        self.A.begin_write()
        self.call(self.A, "set_cvar")
        self.A.end_write()
        self.B.begin_write()
        self.call(self.B, "set_cvar")
        self.B.end_write()
        snapshot = decode_tool_result(self.A.call_tool("inspect_editor_tasks", {}))
        self.assertEqual(len(snapshot["tasks"]), 2)
        self.assertIsNone(snapshot["writer_task_id"])

    def test_wait_timeout_preserves_its_queue_entry(self):
        """/** @return 等待超时不会取消所属任务或占用者 */"""
        self.A.acquire_task("A", "编辑中")
        self.A.begin_write()
        self.B.acquire_task("B", "等待中")
        pending = self.B.begin_write(wait_seconds=1)
        self.assertEqual(pending["status"], "queued")
        self.assertIsNone(self.B.write_token)
        snapshot = decode_tool_result(self.A.call_tool("inspect_editor_tasks", {}))
        self.assertEqual(snapshot["write_queue"], ["B"])
        self.assertEqual(snapshot["writer_task_id"], "A")
        self.A.end_write()
        self.B.begin_write()

    def test_waiters_receive_write_stages_in_request_order(self):
        """/** @return 实际 HTTP 等待者按顺序获得写权限 */"""
        self.A.acquire_task("A", "当前编辑")
        self.A.begin_write()
        self.B.acquire_task("B", "先等待")
        with McpSession(self.url, 10) as third:
            third.acquire_task("C", "后等待")
            order = []
            failures = []
            first_granted = threading.Event()
            release_first = threading.Event()

            def wait_for_write(session, label):
                """/** @param session 客户端 @param label 任务 @return 实际编辑申请结果 */"""
                try:
                    session.begin_write(wait_seconds=5)
                    order.append(label)
                    if label == "B":
                        first_granted.set()
                        if not release_first.wait(5):
                            raise AssertionError("等待释放超时")
                    session.end_write()
                except Exception as error:
                    failures.append(error)

            threads = []
            try:
                for session, label, count in [(self.B, "B", 1), (third, "C", 2)]:
                    worker = threading.Thread(target=wait_for_write, args=(session, label))
                    threads.append(worker)
                    worker.start()
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        snapshot = decode_tool_result(self.A.call_tool("inspect_editor_tasks", {}))
                        if len(snapshot["write_queue"]) == count:
                            break
                        time.sleep(0.01)
                    self.assertEqual(len(snapshot["write_queue"]), count)
                    if label == "B":
                        with self.assertRaises(RuntimeError) as duplicate:
                            self.A.call_tool("begin_editor_write", {"task_token": self.B.task_token, "wait_seconds": 1})
                        self.assertIn("WRITE_APPLICATION_PENDING", str(duplicate.exception))
                        snapshot = decode_tool_result(self.A.call_tool("inspect_editor_tasks", {}))
                        self.assertEqual(snapshot["write_queue"], ["B"])
                self.A.end_write()
                self.assertTrue(first_granted.wait(3))
            finally:
                release_first.set()
                for worker in threads:
                    worker.join(6)
            self.assertEqual(failures, [])
            self.assertEqual(order, ["B", "C"])

    def test_confirmed_revocation_clears_only_invalid_client_credentials(self):
        """/** @return 明确失效后可重新申请 传输不确定时不清除凭证 */"""
        now = [0]
        self.gateway.coordinator.clock = lambda: now[0]
        self.A.acquire_task("A", "凭证失效验证", "editor", 300)
        self.A.begin_write(ttl_seconds=30)
        original = self.A.write_token
        now[0] = 31
        self.B.call_tool("inspect_editor_tasks", {})
        with self.assertRaises(RuntimeError):
            self.call(self.A, "set_cvar")
        self.assertIsNone(self.A.write_token)
        self.assertIsNotNone(self.A.task_token)
        self.A.begin_write()
        self.assertNotEqual(self.A.write_token, original)
        now[0] = 400
        self.B.call_tool("inspect_editor_tasks", {})
        with self.assertRaises(RuntimeError):
            self.call(self.A, "set_cvar")
        self.assertIsNone(self.A.task_token)
        self.assertIsNone(self.A.write_token)
        self.A.acquire_task("A", "重新登记")


class ActivityProbeTests(unittest.TestCase):
    """/** 核实 UE 只读探针跟踪真实字段和世界身份 */"""

    def test_world_generation_and_background_capture_registry(self):
        """/** @return 世界和异步活动均被实际回读 不结束或修改对象 */"""
        worlds = []
        status = {"state": "idle"}
        unreal = types.ModuleType("unreal")
        unreal.uclass = lambda: lambda definition: definition
        unreal.ToolsetDefinition = object
        unreal.EditorLevelLibrary = types.SimpleNamespace(get_pie_worlds=lambda include: list(worlds))
        unreal.GameplayStatics = types.SimpleNamespace(is_game_paused=lambda world: False)
        unreal.LevelEditorSubsystem = object
        unreal.get_editor_subsystem = lambda kind: types.SimpleNamespace(is_in_play_in_editor=lambda: bool(worlds))
        unreal.register_slate_post_tick_callback = lambda callback: 1
        unreal.Paths = types.SimpleNamespace(project_dir=lambda: "project")
        unreal.EditorLoadingAndSavingUtils = types.SimpleNamespace(get_dirty_content_packages=lambda: [], get_dirty_map_packages=lambda: [])
        unreal.BBBPIEInputEditorLibrary = types.SimpleNamespace(get_pie_input_sequence_status=lambda: json.dumps(status))
        registration = types.ModuleType("toolset_registry.registration")
        registration.Registration = lambda definitions: object()
        modules = {"unreal": unreal, "toolset_registry.registration": registration,
            "BBBAnimationPreviewToolset": types.SimpleNamespace(_transition_captures={"one": {"status": "pending"}, "done": {"status": "completed"}}, _population_runs={}),
            "BBBHitReactionToolset": types.SimpleNamespace(_captures={"two": {"status": "running"}}),
            "BBBAnimationMotionTools": types.SimpleNamespace(_capture_handle=0),
            "BBBGenericEditorToolset": types.SimpleNamespace(_pie_audio_capture={})}
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBMcpTaskToolset.py"
        with patch.dict(sys.modules, modules), patch("BBBMcpCapabilities.mcp_tool", lambda method: method.__func__), patch.object(builtins, "BBB_BACKWARD_RECOIL_RUNTIME_PROBE", {"status": "running"}, create=True), patch.object(builtins, "BBB_MCP_HOST_ACTIVITY_STATE", {"host_instance": "test", "pie_generation": 0, "world_identity": ()}, create=True):
            spec = importlib.util.spec_from_file_location("task_probe_isolation", source)
            probe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(probe)
            value = json.loads(probe.BBBMcpTaskToolset.inspect_editor_activity())
            self.assertEqual(value["pie_generation"], 0)
            self.assertEqual(len(value["activities"]), 5)

            class World:
                """/** 保持对象身份的测试世界 */"""

                def get_path_name(self):
                    """/** @return 测试世界名称 */"""
                    return "PIE_0"

            worlds.append(World())
            first = json.loads(probe.BBBMcpTaskToolset.inspect_editor_activity())
            again = json.loads(probe.BBBMcpTaskToolset.inspect_editor_activity())
            self.assertEqual(first["pie_generation"], again["pie_generation"])
            worlds[0] = World()
            replacement = json.loads(probe.BBBMcpTaskToolset.inspect_editor_activity())
            self.assertGreater(replacement["pie_generation"], first["pie_generation"])
            reloaded = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reloaded)
            after_reload = json.loads(reloaded.BBBMcpTaskToolset.inspect_editor_activity())
            self.assertEqual(after_reload["host_instance"], replacement["host_instance"])
            self.assertEqual(after_reload["pie_generation"], replacement["pie_generation"])
            status.update(state="running", releaseError="输入释放失败")
            value = json.loads(probe.BBBMcpTaskToolset.inspect_editor_activity())
            self.assertIn("BBBPIEInputEditorLibrary:input_sequence", value["activities"])
            self.assertIn("BBBPIEInputEditorLibrary:input_release_failed", value["activities"])

    def test_pending_begin_cannot_be_overwritten_or_cleared_by_renewal(self):
        """/** @return 未生效的开始请求保持占用 不能伪装成已结束 */"""
        backend = FakeBackend()
        manager = TaskCoordinator(backend.probe)
        token = manager.acquire("A", "开始请求", "pie")["task_token"]
        stage = manager.begin_write(token)["write_token"]
        manager.tasks[token]["pie_request"] = "start_pie"
        with self.assertRaises(TaskConflict):
            manager.begin(invocation("project.BBBExternalToolset", "util", {"action": "stop_pie"}), token, stage)
        with self.assertRaises(TaskConflict):
            manager.renew_write(token, stage, resume=True)

    def test_native_and_script_console_routes_are_both_blocked(self):
        """/** @return 大小写不同的原生控制台入口也不能绕过审查 */"""
        manager = TaskCoordinator(FakeBackend().probe)
        token = manager.acquire("A", "脚本入口", "editor")["task_token"]
        for name in ["ExecuteConsoleCommand", "execute_python_script", "execute_tool_script"]:
            with self.assertRaises(TaskConflict):
                manager.begin(invocation("official.EditorTools", name), token)


class PipelineTests(unittest.TestCase):
    """/** 多客户端持续排队与可执行工作验收 */"""

    setUp = HttpGatewayTests.setUp
    tearDown = HttpGatewayTests.tearDown
    call = HttpGatewayTests.call

    def test_persistent_queue_reconnect_rank_and_cancel(self):
        """/** @return 断开连接后保留顺序 取消仅影响本申请 */"""
        self.A.acquire_task("A", "当前编辑")
        self.A.begin_write(stage_label="第一批")
        task = self.B.acquire_task("B", "准备第二批")
        self.assertEqual(self.B.begin_write()["status"], "queued")
        self.B.close()
        with McpSession(self.url, 10) as third:
            third.acquire_task("C", "第三批")
            third.begin_write()
            self.assertEqual(third.inspect_tasks()["summary"]["caller"]["queue_ahead_task_id"], "B")
            self.B = McpSession(self.url, 10, task["task_token"])
            pending = self.B.begin_write()
            self.assertEqual(pending["state"]["write_queue"], ["B", "C"])
            self.assertEqual(pending["state"]["summary"]["caller"]["queue_position"], 1)
            third.cancel_write()
            self.assertEqual(self.B.inspect_tasks()["write_queue"], ["B"])
            self.A.end_write()
            self.assertTrue(self.B.inspect_tasks()["summary"]["caller"]["can_claim_write"])
            self.B.begin_write()
            self.assertEqual(self.B.inspect_tasks()["writer_task_id"], "B")
            self.B.end_write()
            third.release_task()

    def test_cancel_pending_wait_wakes_original_request(self):
        """/** @return 原任务通过重连取消等待 请求及时返回 */"""
        self.A.acquire_task("A", "当前编辑")
        self.A.begin_write()
        task = self.B.acquire_task("B", "等待编辑")
        result = []
        failure = []

        def wait():
            """/** @return 保存等待响应与异常 */"""
            try:
                result.append(self.B.begin_write(wait_seconds=5))
            except Exception as error:
                failure.append(error)

        thread = threading.Thread(target=wait)
        thread.start()
        try:
            with McpSession(self.url, 10, task["task_token"]) as reconnect:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    state = reconnect.inspect_tasks()
                    if state["write_queue"] == ["B"]:
                        break
                self.assertEqual(state["write_queue"], ["B"])
                self.assertTrue(reconnect.cancel_write()["cancelled"])
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failure, [])
            self.assertEqual(result[0]["status"], "cancelled")
            self.assertEqual(self.A.inspect_tasks()["write_queue"], [])
        finally:
            thread.join(6)

    def test_revision_wait_observes_operation_and_caller_guidance(self):
        """/** @return 操作开始后显示工具与耗时 其他任务继续准备 */"""
        lease = self.A.acquire_task("A", "执行测试")
        stage = self.A.begin_write(stage_label="连续操作")
        self.B.acquire_task("B", "参数准备")
        initial = self.B.inspect_tasks()
        failure = []

        def work():
            """/** @return 保存执行异常 */"""
            try:
                self.A.call_tool("official.EditorTools.long_operation", {})
            except Exception as error:
                failure.append(error)

        thread = threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(self.backend.entered.wait(3))
            state = self.B.inspect_tasks(initial["revision"], 2)
            writer = state["summary"]["writer"]
            self.assertEqual(writer["write"]["stage_label"], "连续操作")
            self.assertEqual(writer["operations"][0]["tool"], "long_operation")
            self.assertGreater(state["revision"], initial["revision"])
            self.assertTrue(state["summary"]["caller"]["can_read"])
            self.assertFalse(state["summary"]["caller"]["can_write"])
            self.assertIn("EDITOR_OCCUPIED", {item["code"] for item in state["summary"]["blockers"]})
            for token in [lease["task_token"], stage["write_token"], self.B.task_token]:
                self.assertNotIn(token, json.dumps(state))
        finally:
            self.backend.complete.set()
            thread.join(5)
        self.assertEqual(failure, [])
        self.assertEqual(self.B.inspect_tasks()["summary"]["writer"]["operations"], [])

    def test_discovery_status_and_policy_share_actual_classification(self):
        """/** @return 描述与执行使用同一分类 指南带当前占用 */"""
        self.A.acquire_task("A", "占用报告")
        self.A.begin_write(stage_label="准备验收")
        guide = decode_tool_result(self.B.call_tool("project.BBBMcpRuntimeToolset.get_mcp_usage_guide", {}))
        self.assertEqual(guide["editor_state"]["writer"]["task_id"], "A")
        schema = decode_tool_result(self.B.call_tool("describe_toolset", {"toolset_name": "official.AssetTools"}))
        listing = decode_tool_result(self.B.call_tool("list_toolsets", {}))
        self.assertEqual(json.loads(listing.split("\n当前占用: ")[1])["writer"]["task_id"], "A")
        self.assertEqual(schema["tools"][0]["_meta"]["bbb/access"], "shared_read")
        self.assertEqual(schema["tools"][1]["_meta"]["bbb/access"], "editor_write")
        result = self.B.call_tool("official.AssetTools.find_assets", {"folder_path": "/Game"})
        self.assertEqual(result["result"]["_meta"]["bbb/editor_state"]["writer"]["task_id"], "A")
        with self.assertRaises(RuntimeError):
            self.B.call_tool("official.AssetTools.delete", {"path": "/Game"})
        self.A.end_write()
        self.B.inspect_tasks()
        cached = self.B.call_tool("describe_toolset", {"toolset_name": "official.AssetTools"})
        self.assertIsNone(cached["result"]["_meta"]["bbb/editor_state"]["writer"])
        listing = decode_tool_result(self.B.call_tool("list_toolsets", {}))
        self.assertIsNone(json.loads(listing.split("\n当前占用: ")[1])["writer"])

    def test_batch_handoff_and_partial_failure_keep_evidence(self):
        """/** @return 成功交接 失败保留已完成结果和原凭证 */"""
        self.A.acquire_task("A", "批次测试")
        completed = self.A.run_write_batch([{"name": "official.EditorTools.set_value"},
            {"name": "official.AssetTools.find_assets"}], "编辑并回读")
        self.assertEqual(len(completed), 2)
        self.assertIsNone(self.A.write_token)
        self.assertIsNone(self.B.inspect_tasks()["writer_task_id"])
        with self.assertRaises(McpWriteBatchError) as failed:
            self.A.run_write_batch([{"name": "official.EditorTools.set_value"},
                {"name": "official.EditorTools.fail_after_write"}, {"name": "official.EditorTools.later"}], "异常证据")
        self.assertEqual(failed.exception.phase, "execute")
        self.assertEqual(len(failed.exception.completed_results), 1)
        self.assertIsNotNone(self.A.write_token)
        self.assertEqual(self.B.inspect_tasks()["writer_task_id"], "A")
        self.assertNotIn("later", [call[1] for call in self.backend.calls])
        self.A.renew_write(resume=True)
        self.A.end_write()

    def test_batch_waits_for_handoff_and_observes_cancellation(self):
        """/** @return 排队批次在交接后执行 或响应原任务取消 */"""
        self.A.acquire_task("A", "先执行")
        self.A.begin_write()
        task = self.B.acquire_task("B", "准备好的批次")
        completed = []
        failures = []

        def batch():
            """/** @return 记录排队批次结果 */"""
            try:
                completed.append(self.B.run_write_batch([{"name": "official.EditorTools.set_value"}], "排队批次", wait_seconds=5))
            except Exception as error:
                failures.append(error)

        for cancel in [False, True]:
            thread = threading.Thread(target=batch)
            thread.start()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    state = self.A.inspect_tasks()
                    if state["write_queue"] == ["B"]:
                        break
                self.assertEqual(state["write_queue"], ["B"])
                if cancel:
                    with McpSession(self.url, 10, task["task_token"]) as reconnect:
                        reconnect.cancel_write()
                if not cancel:
                    self.A.end_write()
                thread.join(3)
                self.assertFalse(thread.is_alive())
            finally:
                thread.join(6)
            if not cancel:
                self.assertEqual(failures, [])
                self.assertEqual(len(completed[0]), 1)
                self.assertIsNone(self.B.write_token)
                self.A.begin_write()
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], McpWriteBatchError)
        self.assertEqual(failures[0].phase, "queue")
        self.assertEqual(self.A.inspect_tasks()["write_queue"], [])
        self.assertEqual([call[1] for call in self.backend.calls].count("set_value"), 1)

    def test_batch_queue_timeout_and_handoff_failure_keep_ownership(self):
        """/** @return 等待到期保留申请 交接受阻保留阶段 */"""
        self.A.acquire_task("A", "先编辑")
        self.B.acquire_task("B", "后编辑")
        self.A.begin_write()
        with self.assertRaises(McpWriteBatchError) as waiting:
            self.B.run_write_batch([{"name": "official.EditorTools.set_value"}], "等待批次", wait_seconds=0)
        self.assertEqual(waiting.exception.phase, "queue")
        self.assertEqual(self.B.inspect_tasks()["write_queue"], ["B"])
        self.B.cancel_write()
        self.A.end_write()
        self.backend.state["dirty_packages"] = ["/Game/External"]
        with self.assertRaises(McpWriteBatchError):
            self.A.run_write_batch([{"name": "official.EditorTools.set_value"}], "外部资产检查", wait_seconds=0)
        self.backend.state["dirty_packages"] = []
        self.A.cancel_write()
        self.A.inspect_tasks()
        original = self.backend.relay

        def dirty_after_call(body, headers, method="POST"):
            """
            /**
             * @param body	请求
             * @param headers	会话
             * @param method	HTTP 方法
             * @return 带未保存结果的响应
             */
            """
            result = original(body, headers, method)
            if body and body.get("method") == "tools/call" and tool_identity(body["params"])[1] == "set_value":
                self.backend.state["dirty_packages"] = ["/Game/Owned"]
            return result

        self.backend.relay = dirty_after_call
        with self.assertRaises(McpWriteBatchError) as blocked:
            self.A.run_write_batch([{"name": "official.EditorTools.set_value"}], "保留脏资产")
        self.assertEqual(blocked.exception.phase, "handoff")
        self.assertEqual(len(blocked.exception.completed_results), 1)
        self.assertIsNotNone(self.A.write_token)
        self.backend.state["dirty_packages"] = []
        self.A.end_write()


class QueueObservationTests(unittest.TestCase):
    """/** 队列到期与宿主查询合并 */"""

    def test_expired_queue_allows_next_task_and_preflight_checks_actual_state(self):
        """/** @return 到期队列清理后保持下一任务顺序 交接核对最新状态 */"""
        backend = FakeBackend()
        now = [0]
        manager = TaskCoordinator(backend.probe, lambda: now[0])
        first = manager.acquire("A", "第一批", "editor")["task_token"]
        stage = manager.begin_write(first)["write_token"]
        second = manager.acquire("B", "第二批", "editor", 30)["task_token"]
        third = manager.acquire("C", "第三批", "editor")["task_token"]
        manager.begin_write(second)
        manager.begin_write(third)
        now[0] = 31
        state = manager.inspect(third)
        self.assertEqual(state["write_queue"], ["C"])
        self.assertNotIn("B", [task["task_id"] for task in state["tasks"]])
        manager.end_write(first, stage)
        backend.state["dirty_packages"] = ["/Game/External"]
        with self.assertRaises(TaskConflict):
            manager.begin_write(third)
        state = manager.inspect(third)
        self.assertIsNone(state["writer_task_id"])
        self.assertEqual(state["write_queue"], ["C"])
        self.assertIn("DIRTY_PACKAGES", {item["code"] for item in state["summary"]["blockers"]})
        backend.state["dirty_packages"] = []
        manager.inspect()
        self.assertEqual(manager.begin_write(third)["status"], "active")

    def test_waiters_share_probe_work(self):
        """/** @return 两个等待者共享宿主探测并保留等待顺序 */"""
        manager = TaskCoordinator(FakeBackend().probe)
        first = manager.acquire("A", "当前编辑", "editor")["task_token"]
        manager.begin_write(first)
        tokens = [manager.acquire(name, name, "editor")["task_token"] for name in ["B", "C"]]
        results = []
        before = manager.probe_count
        threads = [threading.Thread(target=lambda token=token: results.append(manager.begin_write(token, wait_seconds=2))) for token in tokens]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(4)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["status"] == "queued" for result in results))
        self.assertLessEqual(manager.probe_count - before, 3)
        self.assertEqual(len(manager.inspect()["write_queue"]), 2)

    def test_overlapping_inspections_share_actual_probe(self):
        """/** @return 同时查询共享一次实际观测 */"""
        backend = FakeBackend()
        barrier = threading.Barrier(9)
        observed = []

        def probe():
            """/** @return 为并发查询提供可观察的宿主延迟 */"""
            time.sleep(0.1)
            return backend.probe()

        manager = TaskCoordinator(probe)

        def inspect():
            """/** @return 记录同步开始的观测结果 */"""
            barrier.wait()
            observed.append(manager.inspect())

        threads = [threading.Thread(target=inspect) for unused in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
        self.assertEqual(len(observed), 8)
        self.assertEqual(manager.probe_count, 1)


if __name__ == "__main__":
    unittest.main()
