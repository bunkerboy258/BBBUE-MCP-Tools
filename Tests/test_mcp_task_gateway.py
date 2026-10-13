import copy
import json
from pathlib import Path
import sys
import threading
import time
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from BBBMcpCapabilities import ToolCatalog, validate_arguments, tool_contract
from MCP.mcp_call import McpSession
from MCP.mcp_jobs import JobQueue, JobConflict
from MCP.mcp_result import McpBusinessError, McpExecutionError
from MCP.mcp_task_gateway import TaskGateway, make_server, public_tools, UnrealBackend


class FakeBackend:
    """/** 隔离后端 记录真正派发的操作 */"""

    def __init__(self):
        self.state = {"process_id": 42, "host_instance": "one", "pie_active": False, "pie_generation": 0, "worlds": [], "activities": [], "dirty_packages": []}
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def probe(self):
        return copy.deepcopy(self.state)

    def descriptors(self):
        return iter(())

    def external_contracts(self):
        return iter(())

    def invoke(self, contract, arguments):
        name = contract["name"]
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "read" and arguments.get("asset") == "raise":
            raise RuntimeError("read failed")
        if name == "StartPIE":
            self.state.update(pie_active=True, worlds=["PIE_0"], pie_generation=self.state["pie_generation"] + 1)
        if name == "StopPIE":
            self.state.update(pie_active=False, worlds=[], activities=[], pie_generation=self.state["pie_generation"] + 1)
        if name == "write":
            self.state["dirty_packages"].append(arguments["asset"])
        if name == "save_assets":
            self.state["dirty_packages"] = [path for path in self.state["dirty_packages"] if path not in arguments["asset_paths"]]
        if name == "reload_assets_from_disk" and arguments.get("dry_run", True) is False:
            self.state["dirty_packages"] = [path for path in self.state["dirty_packages"] if path not in arguments["discard_dirty_packages"]]
        if name == "activity":
            self.state["activities"] = [{"id": "capture:1", "status": "running"}]
            if arguments.get("asset") == "/Game/Continuous":
                self.state["activities"][0]["wait"] = False
        if name == "unknown":
            raise RuntimeError("connection lost")
        if name == "reject":
            raise McpExecutionError("rejected", "INVALID_ASSET", "参数拒绝")
        if name == "long":
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError("test deadline")
        return {"ok": name}

    def shutdown(self):
        self.calls.append(("shutdown", {}))


def fixtures(worker=False, clock=time.monotonic):
    backend = FakeBackend()
    catalog = ToolCatalog(backend)
    definitions = [("read", "read", "any"), ("write", "write", "editor"), ("save_assets", "write", "editor"), ("StartPIE", "pie", "any"), ("StopPIE", "pie", "any"), ("activity", "write", "pie"), ("unknown", "write", "editor"), ("reject", "write", "editor"), ("long", "write", "editor")]
    for name, access, world in definitions:
        properties = {"asset": {"type": "string"}}
        if name == "save_assets":
            properties = {"asset_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1}}
        catalog.add({"id": "test." + name, "name": name, "toolset": "test", "definition": "Test", "parameters": {"type": "object", "properties": properties, "additionalProperties": False}, "summary": name, "access": access, "world": world, "scope": {"fields": ["asset_paths" if name == "save_assets" else "asset"]}})
    manager = JobQueue(backend, catalog, clock=clock, start_worker=worker)
    return backend, catalog, manager


def operation(name, **arguments):
    return {"tool": "test." + name, "arguments": arguments}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.backend, self.catalog, self.manager = fixtures()
        self.first = self.manager.connect()
        self.second = self.manager.connect()

    def tearDown(self):
        self.manager.close()

    def submit(self, owner, *operations):
        return self.manager.submit(owner, list(operations))["batch"]

    def test_all_parameters_validated_before_enqueue(self):
        with self.assertRaises(ValueError):
            self.submit(self.first, operation("write", asset="/Game/A"), operation("read", extra=True))
        self.assertEqual(self.manager.queue, [])
        self.assertEqual(self.backend.calls, [])

    def test_batch_order_and_one_result_each(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"), operation("save_assets", asset_paths=["/Game/A"]), operation("read"))
        self.manager.run_once()
        value = self.manager.inspect(self.first, identity, True)
        self.assertEqual(value["status"], "completed")
        self.assertEqual(value["completed"], 3)
        self.assertEqual([name for name, args in self.backend.calls], ["write", "save_assets", "read"])

    def test_fifo_between_clients(self):
        one = self.submit(self.first, operation("read"))
        two = self.submit(self.second, operation("read"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[one]["status"], "completed")
        self.assertEqual(self.manager.jobs[two]["status"], "queued")
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[two]["status"], "completed")

    def test_pie_owner_read_pass_and_effect_wait(self):
        self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        edit = self.submit(self.second, operation("write", asset="/Game/B"))
        read = self.submit(self.second, operation("read"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[read]["status"], "completed")
        self.assertEqual(self.manager.jobs[edit]["code"], "PIE_OWNED")
        self.submit(self.first, operation("StopPIE"))
        self.assertTrue(self.manager.run_once())
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[edit]["status"], "review")

    def test_other_client_stop_pie_stays_queued(self):
        self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        identity = self.submit(self.second, operation("StopPIE"))
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[identity]["code"], "PIE_OWNED")

    def test_pie_owner_closes_completed_read_without_releasing_pie(self):
        start = self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        read = self.submit(self.first, operation("read"))
        self.manager.run_once()
        self.manager.control(self.first, "close", read)
        with self.assertRaises(JobConflict):
            self.manager.control(self.first, "close", start)
        self.assertEqual(self.manager.pie_owner, self.first)

    def test_explicit_rejection_after_reads_keeps_read_results_and_releases_slot(self):
        identity = self.submit(self.first, operation("read"), operation("reject", asset="/Game/A"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "rejected")
        self.assertEqual(self.manager.jobs[identity]["completed"], 1)
        self.assertIsNone(self.manager.writer)

    def test_failed_read_before_mutation_releases_the_batch(self):
        identity = self.submit(self.first, operation("read", asset="raise"), operation("write", asset="/Game/A"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "rejected")
        self.assertEqual(self.manager.jobs[identity]["code"], "READ_FAILED")
        self.assertIsNone(self.manager.writer)
        self.assertEqual(len(self.backend.calls), 1)

    def test_failed_read_after_mutation_keeps_partial_result(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"), operation("read", asset="raise"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "review")
        self.assertEqual(self.manager.jobs[identity]["execution"], "partial")
        self.assertEqual(self.manager.jobs[identity]["dirty"], ["/Game/A"])

    def test_owner_activity_does_not_own_unrelated_records(self):
        self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        self.submit(self.first, operation("activity"))
        self.manager.run_once()
        self.assertEqual(self.manager.activity_owners, {"capture:1": self.first})
        read = self.submit(self.second, operation("read"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[read]["status"], "completed")

    def test_dirty_191_baseline_is_local(self):
        self.backend.state["dirty_packages"] = ["/Game/Old" + str(index) for index in range(191)]
        self.manager.observe(force=True)
        identity = self.submit(self.second, operation("write", asset="/Game/Clean"), operation("save_assets", asset_paths=["/Game/Clean"]))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "completed")
        self.assertEqual(len(self.backend.state["dirty_packages"]), 191)

    def test_async_batch_yields_and_resumes_once_with_its_dirty_assets(self):
        self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        identity = self.submit(self.first, operation("activity", asset="/Game/A"), operation("StopPIE"), operation("save_assets", asset_paths=["/Game/A"]))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["completed"], 1)
        self.assertIsNone(self.manager.writer)
        read = self.submit(self.second, operation("read"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[read]["status"], "completed")
        self.backend.state["activities"] = []
        self.backend.state["dirty_packages"] = ["/Game/A"]
        self.manager.observe(force=True)
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "completed")
        self.assertEqual([name for name, arguments in self.backend.calls].count("activity"), 1)
        self.assertEqual(self.backend.state["dirty_packages"], [])

    def test_source_assets_never_define_mutation_scope(self):
        schema = {"type": "object", "properties": {"source_path": {"type": "string"}}}
        self.catalog.add({"id": "scene.copy", "name": "copy", "definition": "Scene", "toolset": "Scene", "parameters": schema, "summary": "copy", "access": "write", "world": "editor"})
        self.backend.state["dirty_packages"] = ["/Game/CurrentMap"]
        self.manager.observe(force=True)
        identity = self.manager.submit(self.first, [{"tool": "scene.copy", "arguments": {"source_path": "/Game/Source"}}])["batch"]
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[identity]["code"], "DIRTY_BASELINE_UNSCOPED")

    def test_continuous_recording_allows_its_owner_to_continue_and_stop(self):
        self.submit(self.first, operation("StartPIE"))
        self.manager.run_once()
        identity = self.submit(self.first, operation("activity", asset="/Game/Continuous"), operation("StopPIE"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "completed")
        self.assertEqual(self.manager.jobs[identity]["completed"], 2)
        self.assertEqual(self.backend.state["activities"], [])

    def test_status_uses_snapshot_while_another_probe_is_running(self):
        self.manager.probe_lock.acquire()
        try:
            started = time.monotonic()
            value = self.manager.inspect(self.second)
            self.assertLess(time.monotonic() - started, 0.1)
            self.assertEqual(value["host"]["process_id"], 42)
        finally:
            self.manager.probe_lock.release()

    def test_unsaved_result_read_and_unrelated_write_pass(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "review")
        read = self.submit(self.second, operation("read"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[read]["status"], "completed")
        other = self.submit(self.second, operation("write", asset="/Game/B"), operation("save_assets", asset_paths=["/Game/B"]))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[other]["status"], "completed")

    def test_owner_corrective_save_and_verified_close(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"))
        self.manager.run_once()
        save = self.submit(self.first, operation("save_assets", asset_paths=["/Game/A"]))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[save]["status"], "completed")
        self.assertEqual(self.manager.inspect(self.first, identity)["status"], "completed")
        self.assertEqual(self.manager.control(self.first, "close", identity)["status"], "closed")

    def add_reload_contract(self):
        self.catalog.add({"id": "editor.reload_assets_from_disk", "name": "reload_assets_from_disk",
            "toolset": "editor", "definition": "Test", "summary": "reload",
            "access": "write", "world": "editor", "parameters": {"type": "object",
            "properties": {"asset_paths": {"type": "array", "items": {"type": "string"}},
                "discard_dirty_packages": {"type": "array", "items": {"type": "string"}},
                "dry_run": {"type": "boolean", "default": True}}, "additionalProperties": False}})

    def test_owner_explicit_reload_resolves_failed_review(self):
        self.add_reload_contract()
        identity = self.submit(self.first, operation("write", asset="/Game/A"), operation("unknown", asset="/Game/A"))
        self.manager.run_once()
        reload = {"tool": "editor.reload_assets_from_disk", "arguments": {
            "asset_paths": ["/Game/A"], "discard_dirty_packages": ["/Game/A"], "dry_run": False}}
        foreign = self.submit(self.second, reload)
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[foreign]["code"], "RESULT_REVIEW_REQUIRED")
        own = self.submit(self.first, reload)
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[own]["status"], "completed")
        review = self.manager.control(self.first, "review", identity)
        self.assertEqual(self.manager.control(self.first, "resume", identity, review["confirmation"])["status"], "closed")

    def test_reload_requires_exact_explicit_discard_scope(self):
        self.add_reload_contract()
        identity = self.submit(self.first, operation("write", asset="/Game/A"), operation("unknown", asset="/Game/A"))
        self.manager.run_once()
        for discard, dry_run in [([], False), (["/Game/A", "/Game/B"], False)]:
            with self.subTest(discard=discard, dry_run=dry_run):
                batch = self.submit(self.first, {"tool": "editor.reload_assets_from_disk", "arguments": {
                    "asset_paths": ["/Game/A"], "discard_dirty_packages": discard, "dry_run": dry_run}})
                self.assertFalse(self.manager.run_once())
                self.assertEqual(self.manager.jobs[batch]["code"], "RESULT_REVIEW_REQUIRED")
        outside = self.submit(self.first, {"tool": "editor.reload_assets_from_disk", "arguments": {
            "asset_paths": ["/Game/A", "/Game/B"], "discard_dirty_packages": ["/Game/A", "/Game/B"], "dry_run": False}})
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[outside]["code"], "RESULT_REVIEW_REQUIRED")
        dry = self.submit(self.first, {"tool": "editor.reload_assets_from_disk", "arguments": {
            "asset_paths": ["/Game/A"], "discard_dirty_packages": ["/Game/A"], "dry_run": True}})
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[dry]["status"], "completed")
        self.assertEqual(self.backend.state["dirty_packages"], ["/Game/A"])

    def test_rejection_releases_without_unknown_result(self):
        identity = self.submit(self.first, operation("reject", asset="/Game/A"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "rejected")
        self.assertIsNone(self.manager.writer)

    def test_completed_effect_then_rejected_is_partial(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"), operation("reject", asset="/Game/A"))
        self.manager.run_once()
        self.assertEqual(self.manager.jobs[identity]["status"], "review")
        self.assertEqual(self.manager.jobs[identity]["execution"], "partial")
        self.assertEqual(self.manager.jobs[identity]["completed"], 1)

    def test_unknown_effect_blocks_only_scope(self):
        identity = self.submit(self.first, operation("unknown", asset="/Game/A"))
        self.manager.run_once()
        same = self.submit(self.second, operation("write", asset="/Game/A"))
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.manager.jobs[identity]["execution"], "unknown")
        self.assertEqual(self.manager.jobs[same]["code"], "RESULT_REVIEW_REQUIRED")

    def test_confirmation_rejects_changed_snapshot(self):
        identity = self.submit(self.first, operation("unknown", asset="/Game/A"))
        self.manager.run_once()
        review = self.manager.control(self.first, "review", identity)
        self.backend.state["dirty_packages"] = ["/Game/A"]
        with self.assertRaises(JobConflict):
            self.manager.control(self.first, "resume", identity, review["confirmation"])

    def test_foreign_client_cannot_cancel_or_read_result(self):
        identity = self.submit(self.first, operation("read"))
        with self.assertRaises(JobConflict):
            self.manager.control(self.second, "cancel", identity)
        with self.assertRaises(JobConflict):
            self.manager.inspect(self.second, identity, True)

    def test_host_identity_change_stops_dispatch(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"))
        self.backend.state["host_instance"] = "changed"
        self.manager.observe(force=True)
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.manager.jobs[identity]["code"], "HOST_DRAINING")

    def test_heartbeat_preserves_business_revision(self):
        revision = self.manager.revision
        self.manager.touch(self.first)
        self.manager.observe(force=True)
        self.assertEqual(self.manager.revision, revision)

    def test_probe_failure_keeps_occupancy_readable_and_holds_effects(self):
        identity = self.submit(self.first, operation("write", asset="/Game/A"))
        previous = self.backend.probe
        self.backend.probe = lambda: (_ for _ in ()).throw(RuntimeError("host unavailable"))
        self.manager.observe(force=True)
        state = self.manager.inspect(self.second)
        self.assertEqual(state["status"], "draining")
        self.assertFalse(state["host"]["verified"])
        self.assertFalse(self.manager.run_once())
        self.assertEqual(self.backend.calls, [])
        with self.assertRaises(JobConflict):
            self.manager.control(self.first, "shutdown_host")
        self.backend.probe = previous
        self.manager.observe(force=True)
        self.assertTrue(self.manager.run_once())
        self.assertEqual(self.manager.jobs[identity]["status"], "review")

    def test_default_context_budget_and_private_keys(self):
        value = self.manager.inspect(self.second)
        text = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.assertLessEqual(len(text), 1024)
        self.assertNotIn(self.first, text.decode("utf-8"))
        self.assertLessEqual(len(json.dumps(public_tools(), ensure_ascii=False).encode("utf-8")), 8192)

    def test_shutdown_checks_actual_pie_even_without_owner(self):
        self.backend.state.update(pie_active=True, worlds=["PIE_0"])
        with self.assertRaises(JobConflict):
            self.manager.control(self.first, "shutdown_host")
        self.assertEqual(self.backend.calls, [])


class HttpTests(unittest.TestCase):
    def test_official_write_prechecks_the_mutated_object_and_preserves_rejection(self):
        backend = UnrealBackend("http://127.0.0.1/private", Path(__file__).resolve().parents[1], 42)
        backend.task_name = "private.task"
        calls = []
        def invoke(name, arguments):
            calls.append((name, arguments))
            if arguments["tool_name"] == "check_asset_write":
                raise McpExecutionError("rejected", "ASSET_WRITE_PRECHECK", "他人独占")
        backend._call = invoke
        contract = tool_contract("ObjectTools", "set_properties", {"type": "object", "properties": {"instance": {"type": "string"}, "values": {"type": "object"}}})
        with self.assertRaises(McpExecutionError):
            backend.invoke(contract, {"instance": "/Game/Target.Target", "values": {"source": "/Game/Source.Source"}})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["arguments"]["object_paths"], ["/Game/Target.Target"])

    def test_node_pin_query_is_classified_by_its_actual_mutation(self):
        contract = tool_contract("BlueprintTools", "get_node_type_pins", {"type": "object"})
        self.assertEqual(contract["access"], "write")

    def test_two_http_clients_complete_and_resume_one_key(self):
        backend, catalog, unused = fixtures()
        unused.close()
        gateway = TaskGateway(backend, catalog)
        server = make_server(gateway, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:" + str(server.server_port) + "/mcp"
        try:
            with McpSession(url, 5) as first, McpSession(url, 5) as second:
                candidates = first.find_tools("test.read")
                self.assertEqual(candidates[0]["id"], "test.read")
                self.assertEqual(first.describe_tool("test.read")["access"], "read")
                identity = first.submit_batch([operation("read")])["batch"]
                self.assertEqual(first.wait_batch(identity, 5)["status"], "completed")
                self.assertNotEqual(first.client_key, second.client_key)
                key = first.client_key
                with self.assertRaises(McpBusinessError):
                    second.inspect_tasks(identity, True)
            with McpSession(url, 5, client_key=key) as resumed:
                self.assertEqual(resumed.inspect_tasks()["batch"]["batch"], identity)
                self.assertEqual(resumed.inspect_tasks(identity)["status"], "completed")
        finally:
            gateway.jobs.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_status_is_immediate_during_synchronous_backend(self):
        backend, catalog, manager = fixtures(True)
        try:
            owner = manager.connect()
            identity = manager.submit(owner, [operation("long", asset="/Game/A")])["batch"]
            self.assertTrue(backend.entered.wait(2))
            before = time.monotonic()
            self.assertEqual(manager.inspect(owner, identity)["status"], "running")
            self.assertLess(time.monotonic() - before, 0.2)
        finally:
            backend.release.set()
            manager.close()


if __name__ == "__main__":
    unittest.main()
