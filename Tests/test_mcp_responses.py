import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "Scripts"), str(Path(__file__).resolve().parent)]
from BBBMcpCapabilities import validate_arguments
from MCP.mcp_call import McpSession
from MCP.mcp_response import argument_failure, field_schema, response
from MCP.mcp_result import McpBusinessError
from MCP.mcp_service import make_service_server
from MCP.mcp_task_gateway import TaskGateway, UnrealBackend, public_tools
from test_mcp_task_gateway import fixtures, operation


class ResponseTests(unittest.TestCase):
    """/** 完整后续调用 精确字段与紧凑状态验收 */"""

    def test_wait_action_is_a_valid_public_call(self):
        """/** @return 等待结果可以直接通过公开参数校验 */"""
        value = response({"batch": "batch", "status": "queued", "revision": 12})
        self.assertEqual(value["next"], {"tool": "inspect_tasks", "arguments": {"wait_seconds": 30, "batch": "batch", "after_revision": 12}})
        schema = next(row["inputSchema"] for row in public_tools() if row["name"] == "inspect_tasks")
        validate_arguments(value["next"]["arguments"], schema)
        terminal = response({"batch": "batch", "status": "completed", "proof": {"saved": ["/Game/A"]}})
        self.assertIsNone(terminal["next"])
        self.assertEqual(terminal["proof"]["saved"], ["/Game/A"])

    def test_array_reference_and_nested_field_fragments(self):
        """/** @return 嵌套字段与本地类型引用精确定位 */"""
        schema = {"type": "object", "$defs": {"mode": {"type": "string", "enum": ["a", "b"]}},
            "properties": {"points": {"type": "array", "items": {"type": "object", "properties": {"mode": {"$ref": "#/$defs/mode"}}}}}}
        value = argument_failure("/operations/2/arguments/points/0/mode: enum", schema, "test.write")
        self.assertEqual(value["operation"], 2)
        self.assertEqual(value["needs"][0]["schema"], {"type": "string", "enum": ["a", "b"]})
        self.assertIsNone(value["next"])

    def test_unknown_fields_state_exact_allowed_names(self):
        """/** @return 未声明字段直接携带可用名称 */"""
        value = argument_failure("/arguments/wrong: additionalProperties", {"properties": {"asset": {"type": "string"}}}, "test.write")
        self.assertEqual(value["needs"][0]["action"], "remove")
        self.assertEqual(value["needs"][0]["allowed_fields"], ["asset"])

    def test_unknown_execution_requests_global_evidence(self):
        """/** @return 结果不确定时核实连接与实际任务 */"""
        value = response({"status": "failed", "batch": "old", "code": "HOST_UNVERIFIED"})
        self.assertNotIn("batch", value["next"]["arguments"])
        self.assertEqual(value["next"]["tool"], "inspect_tasks")

    def test_dynamic_struct_error_includes_actual_field_type(self):
        """/** @return 动态结构错误直接提供实际反射类型 */"""
        backend = object.__new__(UnrealBackend)
        backend.remap = False
        backend._property_definitions = lambda instance: {"settings": {"type": "object", "properties": {"ambientCubemap": {"type": "string"}}, "required": ["ambientCubemap"]}}
        contract = {"id": "object.set_properties", "definition": "BBBTest", "toolset": "test", "name": "set", "access": "write", "world": "editor"}
        with self.assertRaises(McpBusinessError) as raised:
            backend.invoke(contract, {"instance": "/Game/A.A", "values": {"settings": {}}})
        value = raised.exception.value
        self.assertEqual(value["needs"][0]["schema"], {"type": "string"})
        self.assertEqual(value["needs"][0]["path"], "/arguments/values/settings/ambientCubemap")

    def test_scope_error_points_to_exact_tool_and_large_schema_is_bounded(self):
        """/** @return 范围错误有具体查询 参数片段控制体积 */"""
        value = response({"status": "rejected", "code": "ASSET_SCOPE_REQUIRED", "details": {"tool": "test.write"}})
        self.assertEqual(value["next"], {"tool": "describe_tool", "arguments": {"tool": "test.write"}})
        schema = {"type": "object", "properties": {"settings": {"type": "object", "properties": {str(index): {"type": "string"} for index in range(200)}}}}
        value = argument_failure("/arguments/settings: expected object", schema, "test.write")
        self.assertEqual(value["next"]["arguments"]["tool"], "test.write")
        self.assertLess(len(json.dumps(value)), 2048)

    def test_stale_graph_returns_a_read_call_before_mutation(self):
        """/** @return 快照过期仅执行预检读取 并给出重新分析调用 */"""
        backend = object.__new__(UnrealBackend)
        backend.remap = False
        inspector = {"id": "blueprint.inspect_blueprint_graph", "name": "inspect", "definition": "BBBTest", "toolset": "test", "access": "read", "world": "any", "codecs": {}, "parameters": {"type": "object"}}
        backend.catalog = SimpleNamespace(tools={inspector["id"]: inspector})
        calls = []
        def read(method, parameters):
            """/** @param method	动作 @param parameters	参数 @return 当前快照 */"""
            calls.append(parameters["tool_name"])
            return {"snapshot": "fresh"}
        backend._call = read
        contract = {"id": "blueprint.annotate_blueprint_graph", "name": "annotate", "toolset": "test", "access": "write"}
        with self.assertRaises(McpBusinessError) as raised:
            backend.invoke(contract, {"graph_path": "/Game/BP.BP:EventGraph", "annotations": {"expectedSnapshot": "old"}})
        self.assertEqual(calls, ["inspect"])
        self.assertEqual(raised.exception.value["code"], "GRAPH_SNAPSHOT_CHANGED")
        action = raised.exception.value["next"]
        self.assertEqual(action["arguments"]["operations"][0]["tool"], inspector["id"])

    def test_progress_omits_partial_payload_and_preserves_final_results(self):
        """/** @return 进度响应保持紧凑 完成结果保留完整数据 */"""
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        owner = queue.connect()
        batch = queue.submit(owner, [operation("read"), operation("long", asset="/Game/A")])["batch"]
        invoke = backend.invoke
        backend.invoke = lambda contract, arguments: {"payload": "x" * 50000} if contract["name"] == "read" else invoke(contract, arguments)
        thread = threading.Thread(target=queue.run_once)
        thread.start()
        self.assertTrue(backend.entered.wait(2))
        try:
            compact = queue.inspect(owner, batch)
            expanded = queue.inspect(owner, batch, True)
            self.assertNotIn("results", compact)
            self.assertLess(len(json.dumps(compact)), len(json.dumps(expanded)) / 20)
        finally:
            backend.release.set()
            thread.join(3)
        completed = queue.inspect(owner, batch)
        self.assertEqual(len(completed["results"][0]["payload"]), 50000)
        self.assertIsNone(completed["next"])

    def test_wait_helper_follows_only_same_batch_read_calls(self):
        """/** @return SDK 依据具体后续动作等待并核验批次归属 */"""
        session = object.__new__(McpSession)
        calls = []
        values = iter([response({"batch": "a", "status": "running", "revision": 3}), response({"batch": "a", "status": "completed"})])
        def inspect(**arguments):
            """/** @param arguments	等待参数 @return 下一份状态 */"""
            calls.append(arguments)
            return next(values)
        session.inspect_tasks = inspect
        self.assertEqual(session.wait_batch("a", 1)["status"], "completed")
        self.assertEqual(calls[1]["after_revision"], 3)
        self.assertFalse(calls[1]["detail"])
        session.inspect_tasks = lambda **arguments: {"batch": "a", "status": "running", "next": {"tool": "submit_batch", "arguments": {}}}
        with self.assertRaises(RuntimeError):
            session.wait_batch("a", 1)


    def test_owned_activity_wait_uses_revision_and_verified_host(self):
        """/** @return 所属采样结束后继续 外部活动保留且失联状态继续等待 */"""
        session = object.__new__(McpSession)
        calls = []
        values = iter([
            {"status": "completed", "revision": 2, "host": {"verified": True}, "owned_activities": ["weapon:probe"]},
            {"status": "completed", "revision": 3, "host": {"verified": False}, "owned_activities": []},
            {"status": "completed", "revision": 4, "host": {"verified": True}, "owned_activities": [], "activities": 1},
        ])
        def inspect(**arguments):
            """/** @param arguments 等待参数 @return 下一份状态 */"""
            calls.append(arguments)
            return next(values)
        session.inspect_tasks = inspect
        result = session.wait_activity("weapon:probe", batch="sampling", timeout_seconds=1)
        self.assertEqual(result["activities"], 1)
        self.assertEqual([row["after_revision"] for row in calls], [None, 2, 3])
        self.assertTrue(all(row["batch"] == "sampling" for row in calls))
        session.inspect_tasks = lambda **arguments: {"status": "failed", "code": "PROBE_FAILED"}
        with self.assertRaises(McpBusinessError):
            session.wait_activity("weapon:probe", timeout_seconds=1)

    def test_compact_activity_state_tracks_owner_and_verification(self):
        """/** @return 紧凑批次状态按所属活动及宿主核验变化推进版本 */"""
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        first, second = queue.connect(), queue.connect()
        batch = queue.submit(first, [operation("read")])["batch"]
        queue.run_once()
        with queue.changed:
            queue.activity_owners = {"weapon:probe": first, "foreign": second}
            queue._signal()
            active = queue._job_view(queue.jobs[batch])
            queue.activity_owners.pop("weapon:probe")
            queue._signal()
            finished = queue._job_view(queue.jobs[batch])
        self.assertEqual(active["owned_activities"], ["weapon:probe"])
        self.assertEqual(finished["owned_activities"], [])
        self.assertTrue(finished["host"]["verified"])
        self.assertGreater(finished["revision"], active["revision"])


class ResponseHttpTests(unittest.TestCase):
    """/** 真实 HTTP 的发现缓存与补参行为 */"""

    def setUp(self):
        """/** @return 独立 HTTP 网关与隔离执行端 */"""
        self.backend, self.catalog, unused = fixtures()
        unused.close()
        self.gateway = TaskGateway(self.backend, self.catalog)
        service = SimpleNamespace(default="test", projects={"test": SimpleNamespace(protocol=self.gateway)})
        self.server = make_service_server(service, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = McpSession("http://127.0.0.1:" + str(self.server.server_address[1]) + "/mcp", 5)

    def tearDown(self):
        """/** @return 回收本组连接和执行端 */"""
        self.client.close()
        self.gateway.jobs.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_first_discovery_contract_populates_cache_without_more_requests(self):
        """/** @return 发现后参数查询复用同版契约 */"""
        item = self.client.find_tools("test.write")[0]
        index = self.client._next_id
        item["parameters"]["properties"].clear()
        contract = self.client.describe_tool("test.write")
        self.assertEqual(self.client._next_id, index)
        self.assertIn("asset", contract["parameters"]["properties"])
        self.catalog.tools["test.write"]["summary"] = "变更后的说明"
        self.client.inspect_tasks()
        index = self.client._next_id
        self.client.describe_tool("test.write")
        self.assertEqual(self.client._next_id, index + 1)

    def test_batch_argument_error_returns_inline_schema_before_execution(self):
        """/** @return 多操作批次按错误序号补参且执行端保持原状 */"""
        with self.assertRaises(McpBusinessError) as raised:
            self.client.submit_batch([operation("write", asset="/Game/A"), operation("write", asset=42)])
        value = raised.exception.value
        self.assertEqual(value["tool"], "test.write")
        self.assertEqual(value["operation"], 1)
        self.assertEqual(value["needs"][0]["schema"]["type"], "string")
        self.assertEqual(self.backend.calls, [])
        self.assertIsNone(value["next"])

    def test_unknown_tool_has_an_exact_discovery_call(self):
        """/** @return 错误工具标识给出具体搜索动作 */"""
        with self.assertRaises(McpBusinessError) as raised:
            self.client.submit_batch([{"tool": "test.missing_tool", "arguments": {}}])
        value = raised.exception.value
        self.assertEqual(value["operation"], 0)
        self.assertEqual(value["next"], {"tool": "find_tools", "arguments": {"query": "test missing tool"}})

    def test_replayed_argument_failure_preserves_identical_inline_evidence(self):
        """/** @return 同请求重放返回同一份字段证据 */"""
        self.client.manage_operator(task="验证补参重放")
        parameters = {"name": "submit_batch", "arguments": {"operations": [operation("write", asset=42)]}, "_meta": {"bbb/request_id": "same-invalid-request"}}
        from MCP.mcp_result import decode_tool_result
        errors = []
        for index in range(2):
            with self.assertRaises(McpBusinessError) as raised:
                decode_tool_result(self.client._post("tools/call", parameters))
            errors.append(raised.exception.value)
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(errors[0]["needs"][0]["schema"]["type"], "string")
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
