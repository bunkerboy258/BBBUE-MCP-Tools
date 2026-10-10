import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import McpSession
from MCP.mcp_result import decode_tool_result
from MCP.mcp_task_gateway import TaskGateway, TaskConflict, make_server
from MCP.mcp_test_runner import TestRunner, TestRunnerError, test_tool_allowed, plain_path
from test_mcp_task_gateway import FakeBackend


class FakeProcess:
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @return 本操作结果
     */
    """
    next_pid = 1000

    def __init__(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        FakeProcess.next_pid += 1
        self.pid = FakeProcess.next_pid
        self.returncode = None

    def poll(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        return self.returncode


class FakeWorker:
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @return 本操作结果
     */
    """
    def __init__(self, record, engine, port):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @param engine	本操作输入
         * @param port	本操作输入
         * @return 本操作结果
         */
        """
        self.record = record
        self.process = FakeProcess()
        self.calls = []
        self.state = {"pie_active": False, "worlds": [], "activities": [], "dirty_packages": []}
        self.failure = False

    def ready(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        return self.probe()

    def start_pie(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.state.update(pie_active=True, worlds=["PIE_" + str(index) for index in range(self.record["players"])])
        return self.probe()

    def call(self, toolset, name, arguments):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param toolset	本操作输入
         * @param name	本操作输入
         * @param arguments	本操作输入
         * @return 本操作结果
         */
        """
        self.calls.append((toolset, name, arguments))
        if self.failure:
            raise ConnectionError("secret-backend-address")
        if arguments.get("action") == "stop_pie":
            self.state.update(pie_active=False, worlds=[])
        return {"result": {"content": [{"type": "text", "text": '{"success":true}'}]}}

    def probe(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        return copy.deepcopy(self.state)

    def stop(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.process.returncode = 0
        return 0


class TestRunnerTests(unittest.TestCase):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @return 本操作结果
     */
    """
    def setUp(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.temporary = tempfile.TemporaryDirectory(prefix="BBBMcpParallelPie-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / "Engine" / "Engine" / "Build").mkdir(parents=True)
        (self.directory / "Engine" / "Engine" / "Build" / "Build.version").write_text('{"BuildId":"test"}')
        self.project = self.directory / "Main"
        (self.project / "Content").mkdir(parents=True)
        (self.project / "Binaries" / "Win64").mkdir(parents=True)
        (self.project / "Content" / "Test.umap").write_bytes(b"saved-map")
        (self.project / "Main.uproject").write_text('{}', encoding="utf-8")
        (self.project / "Binaries" / "Win64" / "MainEditor.target").write_text('{"BuildProducts":[]}', encoding="utf-8")
        self.scripts = self.directory / "Tools"
        self.scripts.mkdir()
        (self.scripts / "BBBMcpBootstrap.py").write_text('version = 1', encoding="utf-8")
        self.script_patch = patch("MCP.mcp_test_runner.SCRIPT_ROOT", self.scripts)
        self.script_patch.start()
        self.addCleanup(self.script_patch.stop)
        self.memory = 64 * 1024 ** 3
        self.backend = FakeBackend()
        self.gateway = TaskGateway(self.backend, lambda authorize, release: TestRunner(
            self.project, self.directory / "Engine", authorize, release, worker_factory=FakeWorker,
            memory_probe=lambda: self.memory))
        self.runner = self.gateway.test_runner
        self.addCleanup(self.runner.close)
        self.tokens = {name: self.gateway.coordinator.acquire(name, name, "pie", 300)["task_token"] for name in "ABC"}

    def wait_status(self, run_id, status):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param run_id	本操作输入
         * @param status	本操作输入
         * @return 本操作结果
         */
        """
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = next(value for value in self.runner.inspect_test_runs()["runs"] if value["run_id"] == run_id)
            if value["status"] == status:
                return value
            if value["status"] == "failed" and status != "failed":
                self.fail(str(value))
            time.sleep(0.01)
        self.fail(str(self.runner.inspect_test_runs()))

    def snapshot(self, owner="A"):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param owner	本操作输入
         * @return 本操作结果
         */
        """
        result = self.runner.prepare_test_snapshot(self.tokens[owner], "/Game/Test")
        self.wait_status(result["run_id"], "prepared")
        return result["run_id"]

    def start(self, owner="A", players=1):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param owner	本操作输入
         * @param players	本操作输入
         * @return 本操作结果
         */
        """
        run_id = self.snapshot(owner)
        self.runner.start_test_run(self.tokens[owner], run_id, players=players)
        self.wait_status(run_id, "ready")
        return run_id

    def test_two_pie_runs_and_main_editor_write_execute_independently(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        first = self.start("A", 2)
        second = self.start("B", 3)
        self.assertNotEqual(self.runner.records[first]["network_port"], self.runner.records[second]["network_port"])
        self.assertNotEqual(self.runner.records[first]["project"], self.runner.records[second]["project"])
        self.assertNotEqual(self.runner.records[first]["worker"].process.pid, self.runner.records[second]["worker"].process.pid)
        self.assertEqual(len(self.runner.records[first]["activity"]["worlds"]), 2)
        stage = self.gateway.coordinator.begin_write(self.tokens["C"])
        self.assertEqual(stage["status"], "active")
        self.gateway.coordinator.end_write(self.tokens["C"], stage["write_token"])
        self.runner.stop_test_run(self.tokens["A"], first)
        self.assertTrue(self.runner.records[second]["worker"].probe()["pie_active"])
        self.assertEqual(self.backend.calls, [])

    def test_third_run_waits_and_stopping_owner_dispatches_queue(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        first = self.start("A")
        self.start("B")
        third = self.snapshot("C")
        self.runner.start_test_run(self.tokens["C"], third)
        time.sleep(0.3)
        self.assertEqual(self.wait_status(third, "queued")["queue_position"], 1)
        self.runner.stop_test_run(self.tokens["A"], first)
        self.wait_status(third, "ready")

    def test_cross_task_controls_are_rejected(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.start("A")
        for operation in [lambda: self.runner.stop_test_run(self.tokens["B"], run_id),
                lambda: self.runner.call_test_tool(self.tokens["B"], run_id, "BBBExternalToolset", "util", {"action": "stop_pie"}),
                lambda: self.runner.start_test_run(self.tokens["B"], run_id)]:
            with self.assertRaisesRegex(TestRunnerError, "TEST_RUN_OWNERSHIP_REQUIRED"):
                operation()
        self.assertTrue(self.runner.records[run_id]["worker"].probe()["pie_active"])

    def test_runtime_allowlist_rejects_assets_console_reflection_and_file_export(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        for toolset, name, arguments in [
                ("BBBGenericEditorToolset", "resave_asset", {}),
                ("BBBGenericEditorToolset", "invoke_pie_actor_function", {}),
                ("BBBExternalToolset", "util", {"action": "execute_console_command"}),
                ("BBBExternalToolset", "util", {"action": "save_all_dirty"}),
                ("BBBGenericEditorToolset", "export_sound_waves", {}),
                ("Unknown", "inspect_pie_characters", {})]:
            self.assertFalse(test_tool_allowed(toolset, name, arguments))
        self.assertTrue(test_tool_allowed("project.BBBControlRigAuthoringToolset_0x12345678", "inject_pie_action", {}))

    def test_worker_failure_keeps_uncertain_run_owned_and_main_available(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.start()
        self.runner.records[run_id]["worker"].failure = True
        with self.assertRaisesRegex(TestRunnerError, "TEST_CALL_UNCERTAIN"):
            self.runner.call_test_tool(self.tokens["A"], run_id, "BBBExternalToolset", "util", {"action": "stop_pie"})
        self.assertNotIn("secret", json.dumps(self.runner.inspect_test_runs()))
        self.assertFalse(self.runner.records[run_id]["inflight"])
        self.assertEqual(self.gateway.coordinator.begin_write(self.tokens["C"])["status"], "active")

    def test_snapshot_records_saved_bytes_and_ignores_live_dirty_packages(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.backend.state["dirty_packages"] = ["/Game/Unsaved"]
        run_id = self.snapshot()
        root = self.runner.records[run_id]["project"].parent
        self.assertEqual((root / "Content" / "Test.umap").read_bytes(), b"saved-map")
        self.assertIn('BBB_MCP_SCRIPTS', (root / "Content" / "Python" / "init_unreal.py").read_text())
        self.assertEqual((root / "BBBMcpScripts" / "BBBMcpBootstrap.py").read_text(), 'version = 1')
        self.assertEqual((self.project / "Content" / "Test.umap").read_bytes(), b"saved-map")

    def test_snapshot_tampering_fails_before_launch(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.snapshot()
        (self.runner.records[run_id]["project"].parent / "Content" / "Test.umap").write_bytes(b"changed")
        self.runner.start_test_run(self.tokens["A"], run_id)
        self.assertEqual(self.wait_status(run_id, "failed")["error_code"], "TEST_SNAPSHOT_CHANGED")
        self.assertIsNone(self.runner.records[run_id]["worker"])

    def test_source_change_during_copy_is_reported(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        import shutil
        copyfile = shutil.copyfile
        changed = False

        def mutate(source, target):
            """
            /**
             * 核对独立测试副本与实例的执行状态
             * @param source	本操作输入
             * @param target	本操作输入
             * @return 本操作结果
             */
            """
            nonlocal changed
            result = copyfile(source, target)
            if source.name == "Test.umap" and not changed:
                source.write_bytes(b"concurrent-save")
                changed = True
            return result

        with patch("MCP.mcp_test_runner.shutil.copyfile", side_effect=mutate):
            result = self.runner.prepare_test_snapshot(self.tokens["A"], "/Game/Test")
            self.assertEqual(self.wait_status(result["run_id"], "failed")["error_code"], "TEST_SOURCE_CHANGED")

    def test_low_memory_preserves_queue_until_resources_available(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.memory = 1024
        run_id = self.snapshot()
        self.runner.start_test_run(self.tokens["A"], run_id)
        time.sleep(0.3)
        self.assertEqual(self.wait_status(run_id, "queued")["error_code"], "TEST_MEMORY_BUDGET")
        self.memory = 64 * 1024 ** 3
        self.wait_status(run_id, "ready")

    def test_low_disk_reports_preparation_failure(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.runner.disk_probe = lambda path: type("Budget", (), {"free": 1})()
        result = self.runner.prepare_test_snapshot(self.tokens["A"], "/Game/Test")
        self.assertEqual(self.wait_status(result["run_id"], "failed")["error_code"], "TEST_DISK_BUDGET")

    def test_missing_build_product_blocks_preparation(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        receipt = self.project / "Binaries" / "Win64" / "MainEditor.target"
        receipt.write_text(json.dumps({"BuildProducts": [{"Type": "DynamicLibrary", "Path": "$(ProjectDir)/Binaries/Missing.dll"}]}))
        result = self.runner.prepare_test_snapshot(self.tokens["A"], "/Game/Test")
        self.assertEqual(self.wait_status(result["run_id"], "failed")["error_code"], "TEST_BUILD_PRODUCT_MISSING")

    def test_active_runs_pin_registration_and_credentials_stay_private(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.start()
        with self.assertRaisesRegex(TaskConflict, "先结束本任务"):
            self.gateway.coordinator.release(self.tokens["A"])
        with self.gateway.coordinator.lock:
            self.gateway.coordinator.tasks[self.tokens["A"]]["expires_at"] = 0
        self.gateway.coordinator.inspect()
        self.assertIn(self.tokens["A"], self.gateway.coordinator.tasks)
        self.assertNotIn(self.tokens["A"], json.dumps(self.runner.inspect_test_runs()))
        self.gateway.coordinator.renew(self.tokens["A"], resume=True)
        self.runner.stop_test_run(self.tokens["A"], run_id)
        self.gateway.coordinator.release(self.tokens["A"])

    def test_read_registration_and_bad_map_are_rejected(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        token = self.gateway.coordinator.acquire("Reader", "r", "read", 300)["task_token"]
        with self.assertRaises(TaskConflict):
            self.runner.prepare_test_snapshot(token, "/Game/Test")
        for path in ["/Game/../Test", "/Game/Missing", "C:/Test", ""]:
            with self.assertRaises(TestRunnerError):
                self.runner.prepare_test_snapshot(self.tokens["A"], path)

    def test_queued_settings_are_fixed_and_task_snapshot_count_is_bounded(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.memory = 1
        first = self.snapshot()
        self.runner.start_test_run(self.tokens["A"], first, players=2)
        self.runner.start_test_run(self.tokens["A"], first, players=2)
        self.assertEqual(self.runner.queue.count(first), 1)
        with self.assertRaisesRegex(TestRunnerError, "TEST_SETTINGS_ALREADY_FIXED"):
            self.runner.start_test_run(self.tokens["A"], first, players=3)
        self.snapshot()
        with self.assertRaisesRegex(TestRunnerError, "TEST_TASK_SNAPSHOT_LIMIT"):
            self.runner.prepare_test_snapshot(self.tokens["A"], "/Game/Test")
        self.assertEqual(self.gateway.coordinator.tasks[self.tokens["A"]]["test_resources"], 2)

    def test_stopped_outputs_allow_new_gateway_runs(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.start()
        result = self.runner.stop_test_run(self.tokens["A"], run_id)
        self.assertTrue(Path(result["output_directory"]).exists())
        self.runner.close()
        replacement = TestRunner(self.project, self.directory / "Engine", self.gateway._authorize_test,
            self.gateway._release_test, worker_factory=FakeWorker, memory_probe=lambda: self.memory)
        self.addCleanup(replacement.close)
        self.assertEqual(replacement.unresolved, [])
        self.assertIn(run_id, replacement.legacy)

    def test_uncertain_mutation_requires_review_while_queries_remain_available(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.start()
        worker = self.runner.records[run_id]["worker"]
        worker.failure = True
        with self.assertRaises(TestRunnerError):
            self.runner.call_test_tool(self.tokens["A"], run_id, "BBBExternalToolset", "util", {"action": "stop_pie"})
        worker.failure = False
        with self.assertRaisesRegex(TestRunnerError, "TEST_CALL_REVIEW_REQUIRED"):
            self.runner.call_test_tool(self.tokens["A"], run_id, "BBBExternalToolset", "util", {"action": "stop_pie"})
        self.runner.call_test_tool(self.tokens["A"], run_id, "BBBExternalToolset", "util", {"action": "is_in_pie"})
        self.runner.stop_test_run(self.tokens["A"], run_id)

    def test_snapshot_extra_file_and_engine_change_are_rejected(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.snapshot()
        (self.runner.records[run_id]["project"].parent / "Content" / "Extra.uasset").write_bytes(b"injected")
        self.runner.start_test_run(self.tokens["A"], run_id)
        self.assertEqual(self.wait_status(run_id, "failed")["error_code"], "TEST_SNAPSHOT_CHANGED")
        second = self.snapshot("B")
        (self.directory / "Engine" / "Engine" / "Build" / "Build.version").write_text('{"BuildId":"changed"}')
        self.runner.start_test_run(self.tokens["B"], second)
        self.assertEqual(self.wait_status(second, "failed")["error_code"], "TEST_ENGINE_CHANGED")

    def test_directory_links_are_rejected(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        value = (self.project / "Content" / "Test.umap").lstat()
        linked = type("Link", (), {"st_mode": value.st_mode, "st_file_attributes": 0x400})()
        with patch.object(Path, "lstat", return_value=linked):
            with self.assertRaisesRegex(TestRunnerError, "TEST_DIRECTORY_LINK"):
                plain_path(self.project / "Content" / "Test.umap")

    def test_launcher_descriptor_keeps_multiplayer_in_own_process(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        run_id = self.snapshot()
        project = self.runner.records[run_id]["project"]
        engine = self.directory / "Engine"
        editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        editor.parent.mkdir(parents=True)
        editor.write_bytes(b"fake executable descriptor only")
        launcher = Path(__file__).resolve().parents[1] / "Scripts" / "MCP" / "Start-UE58OfficialMcpEditor.ps1"
        result = subprocess.run(["powershell", "-NoProfile", "-File", str(launcher),
            "-HostRole", "TestWorker", "-ProjectPath", str(project), "-EnginePath", str(engine),
            "-TestRunId", run_id, "-TestMap", "/Game/Test", "-TestPlayers", "3",
            "-TestNetworkPort", "24567", "-BackendPort", "24568"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        plan = json.loads(result.stdout)
        arguments = plan["Arguments"]
        self.assertIn('-port=24567', arguments)
        self.assertIn('-NullRHI', arguments)
        self.assertIn('-NoSourceControl', arguments)
        self.assertIn('-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorPlaySettings]:PlayNumberOfClients=3', arguments)
        self.assertIn('-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorPlaySettings]:RunUnderOneProcess=True', arguments)
        self.assertIn('-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorPlaySettings]:bLaunchSeparateServer=False', arguments)
        self.assertNotIn('-ModelContextProtocolPort=8000', arguments)
        self.assertIn('bbb-test-', plan["BackendUrl"])

    def test_http_sdk_routes_tests_and_main_writes_concurrently(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        server = make_server(("127.0.0.1", 0), self.gateway)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:" + str(server.server_address[1]) + "/mcp"
            with McpSession(url, task_token=self.tokens["A"]) as client:
                value = client.prepare_test_snapshot("/Game/Test")
                run_id = value["run_id"]
                self.wait_status(run_id, "prepared")
                client.start_test_run(run_id, players=2)
                self.wait_status(run_id, "ready")
                with McpSession(url, task_token=self.tokens["B"]) as second:
                    snapshot = second.prepare_test_snapshot("/Game/Test")
                    self.wait_status(snapshot["run_id"], "prepared")
                    second.start_test_run(snapshot["run_id"], players=3)
                    self.wait_status(snapshot["run_id"], "ready")
                    with McpSession(url, task_token=self.tokens["C"]) as editor:
                        editor.begin_write(stage_label="模拟资产写入与回读")
                        decode_tool_result(editor.call_tool("call_tool", {
                            "toolset_name": "project.BBBGenericEditorToolset",
                            "tool_name": "resave_asset", "arguments": {"asset_path": "/Game/Test"}}))
                        editor.end_write()
                    client.stop_test_run(run_id)
                    self.assertTrue(self.runner.records[snapshot["run_id"]]["worker"].probe()["pie_active"])
                    second.stop_test_run(snapshot["run_id"])
                self.assertTrue(any(value[1] == "resave_asset" for value in self.backend.calls if isinstance(value, tuple)))
                snapshot = client.prepare_test_snapshot("/Game/Test")
                run_id = snapshot["run_id"]
                self.wait_status(run_id, "prepared")
                client.start_test_run(run_id)
                self.wait_status(run_id, "ready")
                result = client.call_test_tool(run_id, "BBBExternalToolset", "util", {"action": "is_in_pie"})
                self.assertTrue(result["decoded_result"]["success"])
                self.assertTrue(any(value["run_id"] == run_id and value["owned_by_caller"] for value in client.inspect_tasks()["test_runs"]["runs"]))
                self.assertEqual(client.editor_state["test_runs"]["max_parallel_runs"], 2)
                self.assertTrue(client.stop_test_run(run_id)["exited"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_sdk_test_heartbeat_renews_registration_without_main_stage(self):
        """
        /**
         * 验证测试登记心跳独立于主编辑阶段
         * @return 原凭证保持有效且心跳随客户端关闭结束
         */
        """
        native_event = threading.Event
        renewed = native_event()

        class FastEvent:
            """/** 测试中仅缩短登记心跳间隔 */"""

            def __init__(self):
                """/** @return 实际线程事件 */"""
                self.event = native_event()

            def wait(self, timeout=None):
                """
                /**
                 * @param timeout	事件等待秒数
                 * @return 实际事件等待结果
                 */
                """
                return self.event.wait(0.01 if timeout == 20 else timeout)

            def __getattr__(self, name):
                """
                /**
                 * @param name	实际事件操作
                 * @return 实际事件属性
                 */
                """
                return getattr(self.event, name)

        server = make_server(("127.0.0.1", 0), self.gateway)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = self.gateway.coordinator.renew

        def observe(*arguments, **keywords):
            """
            /**
             * @param arguments	原登记参数
             * @param keywords	原登记开关
             * @return 原登记续期结果
             */
            """
            value = original(*arguments, **keywords)
            renewed.set()
            return value

        try:
            url = "http://127.0.0.1:" + str(server.server_address[1]) + "/mcp"
            with patch("MCP.mcp_call.threading.Event", FastEvent), patch.object(self.gateway.coordinator, "renew", side_effect=observe):
                with McpSession(url, task_token=self.tokens["A"]) as client:
                    snapshot = client.prepare_test_snapshot("/Game/Test")
                    self.wait_status(snapshot["run_id"], "prepared")
                    self.assertTrue(renewed.wait(2))
                    self.assertIsNone(client.write_token)
                    client.stop_test_run(snapshot["run_id"])
                self.assertFalse(client._test_heartbeat_thread.is_alive())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
