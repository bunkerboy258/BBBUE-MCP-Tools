import copy
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "Scripts"), str(Path(__file__).resolve().parent)]
from BBBMcpCapabilities import ArgumentValidationError, validate_arguments
from MCP.mcp_result import McpBusinessError, McpExecutionError
from MCP.mcp_response import response
from MCP.mcp_task_gateway import UnrealBackend, TaskGateway
from test_mcp_task_gateway import fixtures, operation


class EfficiencyTests(unittest.TestCase):
    """/** 批量收尾 调度公平与一次补参的隔离检查 */"""

    def test_all_batch_fields_are_reported_before_execution(self):
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        catalog.tools["test.write"]["parameters"]["required"] = ["asset"]
        gateway = TaskGateway(backend, catalog, start_worker=False)
        self.addCleanup(gateway.jobs.close)
        operations = [operation("write"), operation("write", asset=12)]
        with self.assertRaises(ArgumentValidationError) as caught:
            catalog.prepare(operations)
        value = gateway._argument_failure({"name": "submit_batch", "arguments": {"operations": operations}}, caught.exception)
        self.assertEqual([need["path"] for need in value["needs"]], [
            "/operations/0/arguments/asset", "/operations/1/arguments/asset"])
        self.assertEqual(value["needs"][1]["schema"]["type"], "string")
        self.assertEqual(backend.calls, [])

    def test_nested_validation_is_bounded_and_branch_errors_stay_local(self):
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {
            "anyOf": [{"type": "integer"}, {"type": "null"}]}}}, "required": ["items"]}
        validate_arguments({"items": [None, 2]}, schema)
        with self.assertRaises(ArgumentValidationError) as caught:
            validate_arguments({"items": ["bad"] * 100}, schema)
        self.assertEqual(len(caught.exception.issues), 16)

    def test_failed_batch_delivers_completed_results(self):
        backend, catalog, queue = fixtures()
        self.addCleanup(queue.close)
        owner = queue.connect()
        batch = queue.submit(owner, [operation("read"), operation("unknown", asset="/Game/A")])["batch"]
        queue.run_once()
        value = queue.inspect(owner, batch)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["completed"], 1)
        self.assertEqual(value["results"], [{"ok": "read"}])

    def test_due_recovery_runs_before_later_same_level_work(self):
        now = [0]
        backend, catalog, queue = fixtures(clock=lambda: now[0])
        self.addCleanup(queue.close)
        owner = queue.connect()
        finalize = backend.finalize
        backend.finalize = lambda packages: (_ for _ in ()).throw(McpBusinessError({"code": "SAVE_FAILED"}))
        failed = queue.submit(owner, [operation("write", asset="/Game/A")])["batch"]
        queue.run_once()
        backend.finalize = finalize
        now[0] = 3
        later = queue.submit(owner, [operation("read")])["batch"]
        queue.run_once()
        self.assertEqual(queue.jobs[failed]["status"], "completed")
        self.assertEqual(queue.jobs[later]["status"], "queued")
        queue.run_once()
        self.assertEqual(queue.jobs[later]["status"], "completed")

    def test_operator_recovery_is_an_executable_call(self):
        value = response({"status": "rejected", "code": "OPERATOR_REQUIRED"})
        self.assertEqual(value["next"]["tool"], "manage_operator")
        self.assertTrue(value["next"]["arguments"]["task"])

    def backend(self, blueprints=(), compile_failure=(), save_failure=()):
        """/** @param blueprints 蓝图 @param compile_failure 编译故障 @param save_failure 保存故障 @return 收尾后端与调用记录 */"""
        backend = object.__new__(UnrealBackend)
        ids = ("editor.inspect_asset_properties", "blueprint_base.compile_blueprint", "assets.resave_assets")
        backend.catalog = SimpleNamespace(tools={key: {"id": key} for key in ids})
        calls = []
        compiled = set()
        def invoke(contract, arguments):
            """/** @param contract 契约 @param arguments 参数 @return 实际分阶段证据 */"""
            identity = contract["id"]
            calls.append((identity, copy.deepcopy(arguments)))
            if identity == "blueprint_base.compile_blueprint":
                compiled.add(arguments["blueprint"])
                return True
            if identity == "assets.resave_assets":
                saved = [p for p in arguments["asset_paths"] if p not in save_failure]
                if len(saved) != len(arguments["asset_paths"]):
                    raise McpExecutionError("partial", "SAVE_FAILED", "保存故障", {"resaved": saved})
                return {"resaved": saved}
            return {"assets": [{"assetPath": path + "." + path.rsplit("/", 1)[-1],
                "classPath": "/Script/Engine.Blueprint" if path in blueprints else "/Script/Engine.StaticMesh",
                "propertyErrors": {}, "properties": {"status": "BS_UP_TO_DATE" if path in compiled and path not in compile_failure else "BS_DIRTY"}}
                for path in arguments["asset_paths"]]}
        backend.invoke = invoke
        return backend, calls

    def test_one_hundred_assets_use_three_host_calls(self):
        backend, calls = self.backend()
        paths = ["/Game/A" + str(i) for i in range(100)]
        proof = backend.finalize(paths)
        self.assertEqual(set(proof["saved"]), set(paths))
        self.assertEqual(proof["failures"], [])
        self.assertEqual(len(calls), 3)

    def test_compile_and_save_failures_preserve_other_successes(self):
        backend, calls = self.backend(blueprints={"/Game/A", "/Game/B"},
            compile_failure={"/Game/B"}, save_failure={"/Game/C"})
        proof = backend.finalize(["/Game/A", "/Game/B", "/Game/C", "/Game/D"])
        self.assertEqual(proof["saved"], ["/Game/A", "/Game/D"])
        self.assertEqual({row["package"] for row in proof["failures"]}, {"/Game/B", "/Game/C"})
        saved_call = next(args for identity, args in calls if identity == "assets.resave_assets")
        self.assertNotIn("/Game/B", saved_call["asset_paths"])


if __name__ == "__main__":
    unittest.main()
