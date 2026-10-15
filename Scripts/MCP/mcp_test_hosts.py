import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time

from MCP.mcp_jobs import JobQueue, JobConflict
from MCP.mcp_test_process import TestProcess


def project_version(root, inputs=None):
    """/** @param root\t原项目目录 @param inputs\t实际依赖文件 @return 已保存输入文件的版本证据 */"""
    root = Path(root)
    records = []
    def append_tree(directory):
        for parent, directories, files in os.walk(directory, followlinks=False):
            for name in directories:
                if (Path(parent) / name).is_symlink() or (Path(parent) / name).stat().st_file_attributes & 0x400:
                    raise RuntimeError("TEST_INPUT_LINK_REQUIRES_REVIEW")
            directories[:] = sorted(value for value in directories if value not in {"Saved", "Intermediate", ".git", "__pycache__"} and (inputs is None or value != "Content"))
            for filename in sorted(files):
                append_file(Path(parent) / filename)
    def append_file(path):
        if path.is_symlink():
            raise RuntimeError("TEST_INPUT_LINK_REQUIRES_REVIEW")
        state = path.stat()
        records.append((str(path), state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns))
    for name in (("Content",) if inputs is None else ()) + ("Config", "Source", "Binaries", "Plugins"):
        directory = root / name
        if not directory.exists():
            continue
        append_tree(directory)
    if inputs is not None:
        for item in sorted(inputs, key=lambda value: value["base"]):
            base = Path(item["base"])
            content = Path(item["content"])
            if not base.is_absolute() or not content.is_absolute() or not base.resolve().is_relative_to(content.resolve()):
                raise RuntimeError("TEST_INPUT_MOUNT_REQUIRED")
            found = False
            for extension in (".uasset", ".umap", ".uexp", ".ubulk", ".uptnl"):
                path = base.with_suffix(extension)
                if path.is_file():
                    found = True
                    append_file(path)
            if not found:
                raise RuntimeError("TEST_INPUT_FILE_REQUIRED: " + str(base))
            if base.with_suffix(".umap").exists():
                for folder in ("__ExternalActors__", "__ExternalObjects__"):
                    append_tree(content / folder / base.relative_to(content))
    for path in sorted(root.glob("*.uproject")):
        append_file(path)
    encoded = json.dumps(records, separators=(",", ":")).encode()
    return {"digest": hashlib.sha256(encoded).hexdigest(), "files": len(records)}


def free_port(kind=socket.SOCK_STREAM):
    """/** @param kind\t传输类型 @return 当前可用的本机端口 */"""
    with socket.socket(socket.AF_INET, kind) as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def clean_test_output(directory, output_root, batch):
    """/** @param directory\t所属输出目录 @param output_root\t原项目测试输出根 @param batch\t批次身份 @return 清理核验完成 */"""
    directory = Path(directory)
    output_root = Path(output_root)
    if directory != output_root / batch or output_root.name != "McpTests" or len(batch) != 16 or any(value not in "0123456789abcdef" for value in batch):
        raise ValueError("TEST_CLEANUP_IDENTITY")
    if not directory.exists():
        return
    paths = []
    for parent, directories, files in os.walk(directory, followlinks=False):
        current = Path(parent)
        for name in directories + files:
            item = current / name
            if item.is_symlink() or item.stat().st_file_attributes & 0x400:
                raise RuntimeError("TEST_OUTPUT_LINK_REQUIRES_REVIEW")
        paths.extend(str(current / name) for name in files)
    for parent, directories, files in os.walk(directory, topdown=False, followlinks=False):
        paths.append(str(Path(parent)))
    for item in (directory, output_root, *output_root.parents):
        if item.is_symlink() or (item.exists() and item.stat().st_file_attributes & 0x400):
            raise RuntimeError("TEST_OUTPUT_LINK_REQUIRES_REVIEW")
    command = "$ErrorActionPreference='Stop'; [Console]::InputEncoding=[Text.UTF8Encoding]::new($false); [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $items=[Console]::In.ReadToEnd()|ConvertFrom-Json; foreach($item in $items){Remove-Item -LiteralPath $item -ErrorAction Stop}"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        input=json.dumps(paths, ensure_ascii=False).encode("utf-8"), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or directory.exists():
        raise RuntimeError("TEST_OUTPUT_CLEANUP_FAILED: " + str(directory) + ": " + result.stderr.decode("utf-8", errors="replace"))


class TestHost:
    """/** 原项目受限测试宿主 */"""

    def __init__(self, batch, options, project_file, editor, guard, backend_type):
        """
        /**
         * @param batch\t所属批次
         * @param options\t地图和运行参数
         * @param project_file\t原项目文件
         * @param editor\t官方编辑器程序
         * @param guard\t项目宿主登记
         * @param backend_type\t官方后端连接类型
         * @return 已核实的测试宿主
         */
        """
        self.batch = batch
        self.guard = guard
        self.backend = None
        self.process = None
        self.directory = Path(project_file).parent / "Saved" / "temp" / "McpTests" / batch
        if self.directory.parent.resolve() != self.directory.parent:
            raise RuntimeError("TEST_OUTPUT_LINK_REQUIRES_REVIEW")
        self.directory.mkdir(parents=True, exist_ok=False)
        self.server_port = free_port(socket.SOCK_DGRAM)
        port = free_port()
        key = secrets.token_hex(16)
        arguments = [str(editor), str(project_file), "/Engine/Maps/Entry",
            "-BBBMcpHostRole=Test", "-BBBMcpTestId=" + batch,
            "-UserDir=" + str(self.directory), "-ShaderWorkingDir=" + str(self.directory / "Shaders"),
            "-abslog=" + str(self.directory / "Editor.log"),
            "-ModelContextProtocolStartServer", "-ModelContextProtocolPort=" + str(port),
            "-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]:ServerUrlPath=/bbb-mcp-" + key,
            "-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.EditorLoadingSavingSettings]:bEnableAutoSave=False",
            "-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorPlaySettings]:RunUnderOneProcess=True,ServerPort=" + str(self.server_port)
                + ",PlayNumberOfClients=" + str(options.get("players", 1)) + ",PlayNetMode="
                + {"standalone": "PIE_Standalone", "listen": "PIE_ListenServer", "client": "PIE_Client"}[options.get("net_mode", "standalone")]
                + ",bLaunchSeparateServer=False",
            "-DDC=(ProjectPak,EnginePak,ZenLocal,Local)", "-ZenLocalDataCacheReadOnly=true",
            "-LocalDataCachePath=" + str(self.directory / "DDC"),
            "-BBBMcpPerformanceProfile=Economy", "-BBBMcpMaxFPS=30",
            "-ExecCmds=t.MaxFPS 30,t.IdleWhenNotForeground 0",
            "-Unattended", "-Multiprocess", "-NoSplash", "-AutoDeclinePackageRecovery", "-RenderOffscreen", "-SCCProvider=None"]
        if not options.get("rendering", False):
            arguments.append("-NullRHI")
        if options.get("audio", False):
            arguments.extend(["-AudioMixer", "-MuteAudio", "-ini:Engine:[Audio]:UnfocusedVolumeMultiplier=1.0"])
        if not options.get("audio", False):
            arguments.append("-NoSound")
        environment = {**os.environ, "BBB_MCP_HOST_ROLE": "test", "BBB_MCP_TEST_OUTPUT": str(self.directory)}
        environment.pop("P4PASSWD", None)
        environment.pop("P4TICKETS", None)
        try:
            with guard.lock:
                self.process = TestProcess(arguments, self.directory, environment)
                guard.register_test(batch, self.process.pid)
            self.backend = backend_type("http://127.0.0.1:" + str(port) + "/bbb-mcp-" + key, Path(project_file).parent, self.process.pid)
            self.backend.remap = True
            deadline = time.monotonic() + (900 if options.get("rendering", False) else 180)
            last_error = None
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("TEST_HOST_EXITED: " + str(self.process.poll()))
                try:
                    state = self.backend.probe()
                except Exception as error:
                    last_error = type(error).__name__
                    time.sleep(0.5)
                    continue
                if state.get("host_role") != "test" or Path(state["saved_directory"]).resolve() != (self.directory / "Saved").resolve():
                    raise RuntimeError("TEST_HOST_OUTPUT_IDENTITY")
                self.backend._call("call_tool", {"toolset_name": self.backend.task_name,
                    "tool_name": "configure_test_host", "arguments": {"map_path": options["map"],
                    "server_port": self.server_port, "players": options.get("players", 1), "net_mode": options.get("net_mode", "standalone")}})
                return
            raise RuntimeError("TEST_HOST_START_TIMEOUT: " + str(last_error))
        except Exception:
            self.close()
            raise

    def close(self):
        """/** @return 正式退出并回收所属进程树 */"""
        if self.process is not None:
            if self.backend is not None and self.process.poll() is None:
                try:
                    self.backend.shutdown()
                    self.process.wait(10)
                except Exception:
                    pass
            self.process.close()
            self.process = None
            self.guard.release_test(self.batch)
        if self.backend is not None:
            self.backend.close()
            self.backend = None


class ProjectJobs:
    """/** 一个公开入口协调资产编辑与并行测试流程 */"""

    def __init__(self, editor_jobs, factory=None, version=None, limit=2, output_root=None):
        """/** @param editor_jobs\t编辑调度 @param factory\t受限宿主工厂 @param version\t资产版本读取 @param limit\t测试并行上限 @param output_root\t测试输出根 @return 项目调度 */"""
        self.editor = editor_jobs
        self.factory = factory
        self.version = version
        self.limit = limit
        self.output_root = Path(output_root) if output_root is not None else None
        self.tests = {}
        self.contexts = {}
        self.condition = threading.Condition(threading.RLock())
        self.revision = 0
        self.signature = None
        self.closed = False
        self.stopping = False
        self._restore_tests()

    def connect(self, resume_key=None):
        key = self.editor.connect(resume_key)
        historical = "@" + self.editor.clients.digest(key)
        with self.condition:
            for record in self.tests.values():
                if record["owner"] == historical:
                    record["owner"] = key
            for context in self.contexts.values():
                if context["owner"] == historical:
                    context["owner"] = key
            if any(record["owner"] == key for record in self.tests.values()):
                self.editor.client_owners.add(key)
        return key

    def _restore_tests(self):
        """/** @return 通过已结束世界的证据恢复原测试结果与输出归属 */"""
        for record in self.editor.clients.stored_jobs():
            if record["environment"] != "test":
                continue
            owner = "@" + record["owner"]
            self.editor.clients[owner] = 0
            record.update(owner=owner, queue=None, finished=True, submitted_at=time.monotonic())
            record.pop("id")
            if record["status"] in {"queued", "running"}:
                record.update(status="failed", code="TEST_INTERRUPTED")
            self.tests[record["batch"]] = record
            self.contexts.setdefault(record["test_host"], {"id": record["test_host"], "owner": owner, "label": record["label"],
                "options": record["options"], "state": "closed", "queue": None, "host": record["host"], "close_requested": True})

    def _checkpoint_test(self, record):
        """/** @param record\t测试批次 @return 输出与结果的恢复记录 */"""
        if self.editor.clients.database is None:
            return
        value = {key: copy.deepcopy(record[key]) for key in ("batch", "test_host", "label", "status", "completed", "environment", "operations", "options", "host", "results", "code", "finished")}
        value.update(id=record["batch"], owner=record["owner"][1:] if record["owner"].startswith("@") else self.editor.clients.digest(record["owner"]))
        for key in ("outcome", "input_version", "input_stable"):
            if key in record:
                value[key] = copy.deepcopy(record[key])
        self.editor.clients.store_job(value)

    def touch(self, client):
        self.editor.touch(client)

    def submit(self, client, operations, label="", environment="editor", test_options=None, test_host=None):
        """/** @param client\t客户端 @param operations\t有序操作 @param label\t用途 @param environment\t运行环境 @param test_options\t首次测试参数 @param test_host\t继续所属测试流程 @return 即时批次身份 */"""
        self.touch(client)
        if self.closed or self.stopping:
            raise JobConflict("HOST_DRAINING")
        if environment == "editor":
            if test_options is not None or test_host is not None:
                raise JobConflict("TEST_OPTIONS_REQUIRE_TEST_ENVIRONMENT")
            return {**self.editor.submit(client, operations, label), "environment": "editor"}
        if environment != "test":
            raise JobConflict("ENVIRONMENT_INVALID")
        if self.factory is None:
            raise JobConflict("TEST_HOST_CONFIGURATION_REQUIRED")
        prepared = self.editor.catalog.prepare(operations)
        if any(item["access"] != "read" and item["world"] != "pie" and item["access"] != "pie" for item in prepared):
            raise JobConflict("TEST_HOST_READ_ONLY")
        with self.condition:
            if self.closed or self.editor.draining:
                raise JobConflict("HOST_DRAINING")
            if len(self.tests) >= 64:
                raise JobConflict("QUEUE_CAPACITY", {"next": "control_task.close"})
            batch = secrets.token_hex(8)
            if test_host is None:
                if not test_options or "map" not in test_options:
                    raise JobConflict("TEST_MAP_REQUIRED")
                context = {"id": batch, "owner": client, "label": label, "options": copy.deepcopy(test_options),
                    "state": "queued", "queue": None, "host": None, "close_requested": False}
                self.contexts[batch] = context
            if test_host is not None:
                context = self.contexts.get(test_host)
                if context is None or context["owner"] != client:
                    raise JobConflict("TEST_HOST_OWNERSHIP")
                if test_options is not None:
                    raise JobConflict("TEST_OPTIONS_FIXED")
                if context["state"] not in {"starting", "running", "queued"} or context["close_requested"]:
                    raise JobConflict("TEST_HOST_CLOSED", {"next": "submit_batch"})
            record = {"batch": batch, "test_host": context["id"], "owner": client, "label": label,
                "status": "queued", "completed": 0, "environment": "test", "operations": copy.deepcopy(operations),
                "options": context["options"], "submitted_at": time.monotonic(), "host": None,
                "results": [], "code": "TEST_HOST_WAITING", "finished": False}
            self.tests[batch] = record
            self._checkpoint_test(record)
            with self.editor.changed:
                self.editor.client_owners.add(client)
            self._dispatch()
            self.condition.notify_all()
            return self._view(record)

    def _records(self, context):
        return [record for record in self.tests.values() if record["test_host"] == context["id"]]

    def _dispatch(self):
        if self.closed or self.stopping:
            return
        active = sum(context["state"] in {"starting", "running", "finishing"} for context in self.contexts.values())
        for context in self.contexts.values():
            if active >= self.limit:
                return
            if context["state"] != "queued":
                continue
            if time.monotonic() >= self.editor.clients.get(context["owner"], 0):
                context["state"] = "closed"
                for record in self._records(context):
                    record.update(status="cancelled", code="CLIENT_EXPIRED", finished=True)
                continue
            context["state"] = "starting"
            thread = threading.Thread(target=self._run, args=(context,), daemon=True, name="BBB-test-" + context["id"])
            context["thread"] = thread
            self.tests[context["id"]]["thread"] = thread
            thread.start()
            active += 1

    def _publish(self, record, view, context):
        record.update(completed=view["completed"], results=view.get("results", []),
            status=view["status"], code=view.get("code"), host=context["host"])
        if view["status"] in {"queued", "running"} or (view["status"] == "failed" and view.get("next") == "inspect_tasks"):
            record["next"] = "inspect_tasks"
            return
        record.pop("next", None)
        if "outcome" in record:
            return
        after = self.version(record)
        stable = record["input_version"] == after and context["input_version"] == self.version(context["input_record"])
        record["input_stable"] = stable
        record["outcome"] = copy.deepcopy(view)
        if not stable:
            record["outcome"].update(status="failed", code="TEST_INPUT_CHANGED")
            record.update(status="failed", code="TEST_INPUT_CHANGED")

    def _run(self, context):
        host = None
        queue = None
        try:
            root = self.tests[context["id"]]
            root["input_version"] = self.version(root)
            context.update(input_version=root["input_version"], input_record=root)
            host = self.factory(context["id"], context["options"])
            context["handle"] = host
            queue = JobQueue(host.backend, self.editor.catalog, start_worker=False)
            queue.clients = self.editor.clients
            with self.condition:
                context.update(queue=queue, host=host.backend.process_id, state="running")
                self.condition.notify_all()
            while not self.closed and not context["close_requested"]:
                with self.editor.changed:
                    expires = self.editor.clients.get(context["owner"], 0)
                if time.monotonic() >= expires:
                    context["close_requested"] = True
                    break
                with self.condition:
                    pending = [record for record in self._records(context) if record["status"] == "queued" and "child" not in record]
                for record in pending:
                    record.setdefault("input_version", self.version(record))
                    child = queue.submit(context["owner"], record["operations"], record["label"])["batch"]
                    with self.condition:
                        record.update(child=child, queue=queue, host=context["host"], code=None)
                queue.run_once()
                with self.condition:
                    records = self._records(context)
                for record in records:
                    if record.get("finished") and "outcome" in record:
                        continue
                    if "child" not in record:
                        continue
                    with queue.changed:
                        view = queue._job_view(queue.jobs[record["child"]], True)
                    with self.condition:
                        self._publish(record, view, context)
                        self.condition.notify_all()
                state = queue.observe(force=True)
                with self.condition:
                    context["host_state"] = {"pie": bool(state.get("pie_active")), "activities": len(state.get("activities", [])),
                        "dirty": len(state.get("dirty_packages", [])), "verified": state.get("host_verified", False)}
                    pending = any(record["status"] in {"queued", "running"} for record in self._records(context))
                    active = state.get("pie_active") or state.get("worlds") or state.get("activities")
                    if not pending and not active:
                        context["state"] = "finishing"
                        break
                    for record in self._records(context):
                        if "outcome" in record:
                            record["finished"] = True
                    self.condition.wait(0.1)
        except Exception as error:
            with self.condition:
                for record in self._records(context):
                    if "outcome" not in record:
                        record.update(status="rejected", code="TEST_HOST_FAILED",
                            outcome={"status": "rejected", "code": "TEST_HOST_FAILED",
                                "failure": {"type": type(error).__name__, "error": str(error)}})
        finally:
            if queue is not None:
                queue.close()
            failure = None
            if host is not None:
                try:
                    host.close()
                except Exception as error:
                    failure = {"type": type(error).__name__, "error": str(error)}
            with self.condition:
                context.update(queue=None, state="closed" if failure is None else "failed")
                for record in self._records(context):
                    if "outcome" not in record:
                        record.update(status="cancelled", code="GATEWAY_CLOSED" if self.closed else "CLIENT_EXPIRED")
                    if failure is not None:
                        record.update(status="failed", code="TEST_HOST_EXIT_UNVERIFIED",
                            outcome={**record.get("outcome", {}), "failure": failure})
                    record.update(queue=None, finished=True)
                self._dispatch()
                self.condition.notify_all()

    def _view(self, record, detail=False):
        signature = (record["status"], record["completed"], record["code"], record.get("input_stable"), record["finished"], self.contexts[record["test_host"]]["state"])
        if signature != record.get("signature"):
            record["signature"] = signature
            record["revision"] = record.get("revision", 0) + 1
            self._checkpoint_test(record)
        result = {key: record[key] for key in ("batch", "environment", "test_host", "status", "completed")}
        result["revision"] = record.get("revision", 0)
        result["next"] = record.get("next", "inspect_tasks" if record["status"] in {"queued", "running"} else "submit_batch")
        context = self.contexts[record["test_host"]]
        result["host_status"] = context["state"]
        if record["code"]:
            result["code"] = record["code"]
        if context["host"] is not None:
            result["process_id"] = context["host"]
        if detail or record["status"] == "completed":
            result["results"] = copy.deepcopy(record["results"])
            result["elapsed_seconds"] = int(time.monotonic() - record["submitted_at"])
            for key in ("input_version", "input_stable"):
                if key in record:
                    result[key] = record[key]
            result.update({key: value for key, value in record.get("outcome", {}).items() if key in {"failure", "failed_index", "execution"}})
            if "host_state" in context:
                result["host_state"] = copy.deepcopy(context["host_state"])
        return result

    def inspect(self, client, batch=None, detail=False, after_revision=None, wait_seconds=0):
        """/** @param client\t客户端 @param batch\t批次 @param detail\t结果证据 @param after_revision\t业务版本 @param wait_seconds\t等待上限 @return 项目占用与结果 */"""
        self.touch(client)
        if batch is not None:
            with self.condition:
                is_test = batch in self.tests
            if not is_test:
                return {**self.editor.inspect(client, batch, detail, after_revision, wait_seconds), "environment": "editor"}
        if batch is not None and detail:
            with self.condition:
                record = self.tests.get(batch)
                if record is not None and record["owner"] != client:
                    raise JobConflict("BATCH_OWNERSHIP")
                context = self.contexts[record["test_host"]] if record is not None else None
                queue = context.get("queue") if context is not None else None
            if queue is not None:
                state = queue.observe(force=True)
                with self.condition:
                    context["host_state"] = {"pie": bool(state.get("pie_active")), "activities": len(state.get("activities", [])),
                        "dirty": len(state.get("dirty_packages", [])), "verified": state.get("host_verified", False)}
        deadline = time.monotonic() + wait_seconds
        while True:
            editor = self.editor.inspect(client, None, detail)
            with self.condition:
                signature = (editor["revision"],
                    tuple((key, record["status"], record["completed"], record["code"]) for key, record in self.tests.items()),
                    tuple((key, context["state"], context["host"]) for key, context in self.contexts.items()))
                if signature != self.signature:
                    self.signature = signature
                    self.revision += 1
                revision = self._view(self.tests[batch])["revision"] if batch in self.tests else self.revision
                if after_revision is None or after_revision != revision or time.monotonic() >= deadline:
                    if batch in self.tests:
                        record = self.tests[batch]
                        if record["owner"] != client:
                            raise JobConflict("BATCH_OWNERSHIP")
                        return self._view(record, detail)
                    if batch:
                        return {**self.editor.inspect(client, batch, detail), "revision": self.revision, "environment": "editor"}
                    editor["revision"] = self.revision
                    running = [context for context in self.contexts.values() if context["state"] in {"starting", "running", "finishing"}]
                    editor["tests"] = {"running": len(running), "queued": sum(context["state"] == "queued" for context in self.contexts.values()), "limit": self.limit}
                    if running:
                        editor["tests"]["occupants"] = [{"label": context["label"], "status": context["state"], "mine": context["owner"] == client} for context in running]
                    if self.factory is not None and not self.editor.draining:
                        editor["available"].append("test")
                    if detail:
                        editor["test_batches"] = [{**self._view(record, True), "label": record["label"], "mine": True}
                            for record in self.tests.values() if record["owner"] == client]
                    owned = [record for record in self.tests.values() if record["owner"] == client and record["status"] in {"queued", "running"}]
                    if not owned and editor.get("batch", {}).get("status") not in {"queued", "running", "failed"}:
                        owned = [record for record in self.tests.values() if record["owner"] == client]
                    if owned:
                        editor["batch"] = self._view(owned[-1])
                        editor["next"] = "inspect_tasks"
                    return editor
                self.condition.wait(min(0.5, max(0, deadline - time.monotonic())))

    def control(self, client, action, batch=None):
        """/** @param client\t客户端 @param action\t控制动作 @param batch\t批次 @return 归属范围内的控制结果 */"""
        self.touch(client)
        closing = None
        context = None
        with self.condition:
            record = self.tests.get(batch)
            if record is not None:
                if record["owner"] != client:
                    raise JobConflict("BATCH_OWNERSHIP")
                context = self.contexts[record["test_host"]]
                if action == "cancel" and record["status"] == "queued" and "child" in record:
                    queue = context.get("queue")
                    if queue is None:
                        raise JobConflict("TEST_HOST_CLOSED")
                    view = queue.control(client, "cancel", record["child"])
                    self._publish(record, view, context)
                    record["finished"] = True
                    self.condition.notify_all()
                    return self._view(record)
                if action == "cancel" and record["status"] == "queued" and "child" not in record:
                    record.update(status="cancelled", code=None, finished=True)
                    if batch == context["id"] and context["state"] == "queued":
                        context["state"] = "closed"
                    self.condition.notify_all()
                    return self._view(record)
                if action == "close" and record.get("finished") and not record.get("closing"):
                    if batch == context["id"]:
                        if any(item["status"] in {"queued", "running"} for item in self._records(context)):
                            raise JobConflict("TEST_BATCH_ACTIVE", {"next": "inspect_tasks"})
                        context["close_requested"] = True
                    record["closing"] = True
                    closing = record
                    self.condition.notify_all()
                if closing is None:
                    raise JobConflict("TEST_BATCH_ACTIVE" if not record.get("finished") else "TEST_RERUN_REQUIRED",
                        {"next": "inspect_tasks" if not record.get("finished") else "submit_batch"})
            if action == "shutdown_host":
                if any(item["state"] != "closed" for item in self.contexts.values()):
                    raise JobConflict("HOST_BUSY", {"next": "inspect_tasks"})
                self.stopping = True
        if closing is not None:
            try:
                if batch == context["id"]:
                    thread = context.get("thread")
                    if thread is not None:
                        thread.join(30)
                        if thread.is_alive():
                            raise RuntimeError("TEST_HOST_EXIT_WAITING")
                    if context["state"] == "failed":
                        context["handle"].close()
                        context["state"] = "closed"
                    if self.output_root is not None:
                        clean_test_output(self.output_root / batch, self.output_root, batch)
            except Exception as error:
                with self.condition:
                    closing["closing"] = False
                raise JobConflict("TEST_OUTPUT_CLEANUP_REQUIRED",
                    {"batch": batch, "error": str(error), "next": "control_task.close"}) from error
            with self.condition:
                del self.tests[batch]
                self.editor.clients.delete_job(batch)
                if not self._records(context):
                    del self.contexts[context["id"]]
                if not any(item["owner"] == client for item in self.tests.values()):
                    with self.editor.changed:
                        self.editor.client_owners.discard(client)
                self.condition.notify_all()
                return {"batch": batch, "status": "closed"}
        try:
            return self.editor.control(client, action, batch)
        finally:
            with self.condition:
                self.stopping = False
                self.condition.notify_all()

    def close(self):
        """/** @return 回收所属测试宿主并结束调度 */"""
        self.closed = True
        self.editor.close()
        with self.condition:
            contexts = list(self.contexts.values())
            for context in contexts:
                context["close_requested"] = True
            self.condition.notify_all()
        for context in contexts:
            handle = context.get("handle")
            if handle is not None and context["state"] in {"starting", "running"}:
                handle.close()
            thread = context.get("thread")
            if thread is not None and thread is not threading.current_thread():
                thread.join(10)
