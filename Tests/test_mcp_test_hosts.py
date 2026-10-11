import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import secrets
import threading
import time
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_jobs import JobConflict
from MCP.mcp_project_host import ProjectHostGuard, project_identity
from MCP.mcp_test_hosts import ProjectJobs, clean_test_output, project_version
from MCP.mcp_test_process import TestProcess
from test_mcp_task_gateway import fixtures, operation, FakeBackend


class FakeTestHost:
    def __init__(self, number):
        self.backend = FakeBackend()
        self.backend.state["process_id"] = number
        self.backend.process_id = number
        self.closed = False

    def close(self):
        self.closed = True
        self.backend.state.update(pie_active=False, worlds=[], activities=[])


class TestHostRoutingTests(unittest.TestCase):
    def setUp(self):
        self.backend, self.catalog, editor = fixtures()
        self.catalog.tools["test.long"]["access"] = "pie"
        self.catalog.tools["test.long"]["world"] = "pie"
        self.hosts = []
        self.version = {"digest": "saved-one", "files": 1}
        def factory(batch, options):
            host = FakeTestHost(100 + len(self.hosts))
            self.hosts.append(host)
            return host
        self.jobs = ProjectJobs(editor, factory, lambda record: copy.deepcopy(self.version))
        self.first = self.jobs.connect()
        self.second = self.jobs.connect()

    def tearDown(self):
        for host in self.hosts:
            host.backend.release.set()
        self.jobs.close()
        for record in list(self.jobs.tests.values()):
            thread = record.get("thread")
            if thread is not None:
                thread.join(3)
        self.assertTrue(all(host.closed for host in self.hosts))

    def submit_test(self, client, operations=None):
        return self.jobs.submit(client, operations or [operation("StartPIE"), operation("long"), operation("StopPIE")],
            environment="test", test_options={"map": "/Engine/Maps/Entry"})["batch"]

    def wait_running(self, count):
        deadline = time.monotonic() + 2
        while len(self.hosts) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(self.hosts), count)
        for host in self.hosts:
            self.assertTrue(host.backend.entered.wait(1))

    def wait_finished(self, client, batch):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            value = self.jobs.inspect(client, batch, True)
            if self.jobs.tests[batch].get("finished"):
                return value
            time.sleep(0.01)
        self.fail("测试批次结束超时")

    def test_two_pie_hosts_and_original_asset_editor_progress_together(self):
        one = self.submit_test(self.first)
        two = self.submit_test(self.second)
        self.wait_running(2)
        self.assertTrue(all(host.backend.state["pie_active"] for host in self.hosts))
        self.assertFalse(self.backend.state["pie_active"])
        edit = self.jobs.submit(self.second, [operation("write", asset="/Game/A"), operation("save_assets", asset_paths=["/Game/A"])])["batch"]
        self.jobs.editor.run_once()
        self.assertEqual(self.jobs.inspect(self.second, edit)["status"], "completed")
        state = self.jobs.inspect(self.first)
        self.assertEqual(state["tests"]["running"], 2)
        self.assertIn("edit", state["available"])
        self.assertIn("test", state["available"])
        for host in self.hosts:
            host.backend.release.set()
        self.assertEqual(self.wait_finished(self.first, one)["status"], "completed")
        self.assertEqual(self.wait_finished(self.second, two)["status"], "completed")
        self.assertEqual([name for name, arguments in self.backend.calls], ["write", "save_assets"])

    def test_asset_write_rejected_before_host_launch(self):
        with self.assertRaises(JobConflict) as error:
            self.submit_test(self.first, [operation("write", asset="/Game/A")])
        self.assertEqual(error.exception.value["code"], "TEST_HOST_READ_ONLY")
        self.assertEqual(self.hosts, [])
        self.assertEqual(self.jobs.tests, {})

    def test_entire_batch_validates_before_host_launch(self):
        with self.assertRaises(ValueError):
            self.submit_test(self.first, [operation("StartPIE"), operation("read", extra=True)])
        self.assertEqual(self.hosts, [])

    def test_test_capacity_queues_and_cancellation_preserves_other_pie(self):
        self.jobs.limit = 1
        one = self.submit_test(self.first)
        self.wait_running(1)
        two = self.submit_test(self.second)
        self.assertEqual(self.jobs.inspect(self.second, two)["status"], "queued")
        with self.assertRaises(JobConflict):
            self.jobs.control(self.first, "cancel", two)
        self.assertEqual(self.jobs.control(self.second, "cancel", two)["status"], "cancelled")
        self.assertTrue(self.hosts[0].backend.state["pie_active"])
        self.hosts[0].backend.release.set()
        self.wait_finished(self.first, one)

    def test_changed_saved_inputs_marks_results_for_rerun_and_releases_editor(self):
        batch = self.submit_test(self.first)
        self.wait_running(1)
        self.version["digest"] = "saved-two"
        self.hosts[0].backend.release.set()
        value = self.wait_finished(self.first, batch)
        self.assertEqual(value["status"], "review")
        self.assertEqual(value["code"], "TEST_INPUT_CHANGED")
        self.assertFalse(value["input_stable"])
        self.assertEqual(len(value["results"]), 3)
        self.assertIn("edit", self.jobs.inspect(self.second)["available"])
        self.assertEqual(self.jobs.control(self.first, "close", batch)["status"], "closed")

    def test_test_failure_and_expired_client_keep_original_host_available(self):
        batch = self.submit_test(self.first, [operation("read", asset="raise")])
        value = self.wait_finished(self.first, batch)
        self.assertEqual(value["status"], "rejected")
        self.assertEqual(value["code"], "READ_FAILED")
        self.assertIn("edit", self.jobs.inspect(self.second)["available"])
        self.jobs.editor.clients[self.first] = 0
        self.jobs.connect()
        self.assertEqual(self.jobs.connect(self.first), self.first)
        self.assertEqual(self.jobs.inspect(self.first)["batch"]["batch"], batch)

    def test_shutdown_waits_for_owned_test_hosts(self):
        batch = self.submit_test(self.first)
        self.wait_running(1)
        with self.assertRaises(JobConflict) as error:
            self.jobs.control(self.second, "shutdown_host")
        self.assertEqual(error.exception.value["code"], "HOST_BUSY")
        self.assertEqual(self.backend.calls, [])
        self.hosts[0].backend.release.set()
        self.wait_finished(self.first, batch)

    def test_registered_test_hosts_preserve_one_writer_rule(self):
        project = project_identity("project")
        hosts = [{"process_id": 1, "project_root": project, "role": "editor"},
            {"process_id": 2, "project_root": project, "role": "test", "batch": "a" * 16},
            {"process_id": 3, "project_root": project, "role": "test", "batch": "b" * 16}]
        guard = ProjectHostGuard(project, 1, lambda: hosts)
        guard.register_test("a" * 16, 2)
        guard.register_test("b" * 16, 3)
        self.assertTrue(guard.inspect()["exclusive"])
        hosts.append({"process_id": 4, "project_root": project, "role": "test", "batch": "c" * 16})
        self.assertFalse(guard.inspect(force=True)["exclusive"])
        hosts.pop()
        hosts.append({"process_id": 4, "project_root": project, "role": "editor"})
        self.assertFalse(guard.inspect(force=True)["exclusive"])

    def test_pie_continues_across_batches_and_reclaims_after_stop(self):
        root = self.submit_test(self.first, [operation("StartPIE")])
        started = self.wait_finished(self.first, root)
        self.assertEqual(started["host_status"], "running")
        self.assertTrue(self.hosts[0].backend.state["pie_active"])
        follow = self.jobs.submit(self.first, [operation("read")], environment="test", test_host=root)["batch"]
        result = self.wait_finished(self.first, follow)
        self.assertEqual(result["process_id"], started["process_id"])
        self.assertEqual(result["test_host"], root)
        stop = self.jobs.submit(self.first, [operation("StopPIE")], environment="test", test_host=root)["batch"]
        self.assertEqual(self.wait_finished(self.first, stop)["host_status"], "closed")
        self.assertTrue(self.hosts[0].closed)
        self.assertEqual(self.jobs.inspect(self.first)["tests"]["running"], 0)
        self.jobs.control(self.first, "close", root)
        self.jobs.control(self.first, "close", follow)
        self.jobs.control(self.first, "close", stop)
        self.assertEqual(self.jobs.contexts, {})

    def test_continuation_ownership_and_explicit_owned_host_close(self):
        root = self.submit_test(self.first, [operation("StartPIE")])
        self.wait_finished(self.first, root)
        with self.assertRaises(JobConflict) as error:
            self.jobs.submit(self.second, [operation("StopPIE")], environment="test", test_host=root)
        self.assertEqual(error.exception.value["code"], "TEST_HOST_OWNERSHIP")
        with self.assertRaises(JobConflict):
            self.jobs.control(self.second, "close", root)
        self.assertTrue(self.hosts[0].backend.state["pie_active"])
        self.jobs.control(self.first, "close", root)
        self.assertTrue(self.hosts[0].closed)

    def test_expired_test_owner_releases_capacity_for_queued_test(self):
        self.jobs.limit = 1
        root = self.submit_test(self.first, [operation("StartPIE")])
        self.wait_finished(self.first, root)
        next_batch = self.submit_test(self.second, [operation("read")])
        self.jobs.editor.clients[self.first] = 0
        self.assertEqual(self.wait_finished(self.second, next_batch)["status"], "completed")
        self.assertTrue(self.hosts[0].closed)
        self.assertIn("edit", self.jobs.inspect(self.second)["available"])


@unittest.skipUnless(os.name == "nt", "需要 Windows 受限令牌")
class TestProcessPermissionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2] / ("HostPermission-" + secrets.token_hex(8))
        self.root.mkdir()
        self.output_root = self.root / "Saved" / "temp" / "McpTests"
        self.output_root.mkdir(parents=True)
        (self.root / "Content").mkdir()
        self.asset = self.root / "Content" / "Input.txt"
        self.asset.write_text("saved-version", encoding="utf-8")

    def tearDown(self):
        for directory in list(self.output_root.iterdir()):
            clean_test_output(directory, self.output_root, directory.name)
        paths = list((self.root / "Content").iterdir()) + [self.root / "Content", self.output_root, self.root / "Saved" / "temp", self.root / "Saved", self.root]
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; $items=[Console]::In.ReadToEnd()|ConvertFrom-Json; foreach($item in $items){Remove-Item -LiteralPath $item -ErrorAction Stop}"],
            input=json.dumps([str(path) for path in paths]).encode(), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())

    def run_process(self, batch, other=None):
        output = self.output_root / batch
        output.mkdir()
        program = "\n".join([
            "import json, socket", "from pathlib import Path",
            "asset=Path(" + repr(str(self.asset)) + ")",
            "output=Path(" + repr(str(output)) + ")",
            "result={'read':asset.read_text()}",
            "try:", "    asset.write_text('changed')", "    result['asset_blocked']=False",
            "except PermissionError:", "    result['asset_blocked']=True",
            "with socket.socket() as connection:", "    connection.bind(('127.0.0.1',0))", "    result['network']=True",
            "other=" + repr(str(other) if other else ""),
            "if other:", "    try:", "        Path(other).write_text('changed')", "        result['other_blocked']=False",
            "    except PermissionError:", "        result['other_blocked']=True",
            "output.joinpath('result.json').write_text(json.dumps(result))",
        ])
        program = "import traceback\ntry:\n" + "\n".join("    " + line for line in program.splitlines()) + "\nexcept Exception:\n    Path(" + repr(str(output / "error.txt")) + ").write_text(traceback.format_exc())\n    raise SystemExit(1)"
        process = TestProcess([sys.executable, "-B", "-c", program], output, os.environ)
        try:
            self.assertEqual(process.wait(10), 0, (output / "error.txt").read_text() if (output / "error.txt").exists() else "")
        finally:
            process.close()
        return json.loads((output / "result.json").read_text())

    def test_actual_process_reads_project_and_writes_its_own_outputs(self):
        before = project_version(self.root)
        first = self.run_process("a" * 16)
        second = self.run_process("b" * 16, self.output_root / ("a" * 16) / "result.json")
        self.assertEqual(first["read"], "saved-version")
        self.assertTrue(first["asset_blocked"])
        self.assertTrue(first["network"])
        self.assertTrue(second["other_blocked"])
        self.assertEqual(self.asset.read_text(), "saved-version")
        self.assertEqual(project_version(self.root), before)
        self.assertEqual(json.loads((self.output_root / ("a" * 16) / "result.json").read_text()), first)

    def test_versions_track_dependencies_and_allow_unrelated_asset_updates(self):
        content = self.root / "Content"
        selected = content / "Selected.uasset"
        other = content / "Other.uasset"
        selected.write_bytes(b"selected-one")
        other.write_bytes(b"other-one")
        inputs = [{"base": str(content / "Selected"), "content": str(content)}]
        before = project_version(self.root, inputs)
        other.write_bytes(b"other-two")
        self.assertEqual(project_version(self.root, inputs), before)
        selected.write_bytes(b"selected-two")
        self.assertNotEqual(project_version(self.root, inputs), before)
