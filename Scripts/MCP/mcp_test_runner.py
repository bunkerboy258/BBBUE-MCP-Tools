import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import threading
import time

from MCP.mcp_call import McpSession
from MCP.mcp_result import decode_tool_result, McpBusinessError
from MCP.mcp_access_policy import READ_TOOLS, tool_access


TEST_CONTROL_SPEC = {
    "prepare_test_snapshot": ("准备已保存资产与编译产物的独立 PIE 副本", {
        "task_token": {"type": "string"}, "map_path": {"type": "string"},
    }, ["task_token", "map_path"]),
    "start_test_run": ("将已准备副本加入双实例 PIE 队列", {
        "task_token": {"type": "string"}, "snapshot_id": {"type": "string"},
        "players": {"type": "integer", "minimum": 1, "maximum": 4},
        "rendering": {"type": "boolean"}, "audio": {"type": "boolean"},
    }, ["task_token", "snapshot_id"]),
    "call_test_tool": ("凭本任务归属调用指定 PIE 测试实例", {
        "task_token": {"type": "string"}, "run_id": {"type": "string"},
        "toolset_name": {"type": "string"}, "tool_name": {"type": "string"},
        "arguments": {"type": "object"},
    }, ["task_token", "run_id", "toolset_name", "tool_name"]),
    "inspect_test_runs": ("查询测试副本 运行实例与队列", {
        "task_token": {"type": "string"},
    }, []),
    "stop_test_run": ("停止本任务的测试实例并核实进程退出", {
        "task_token": {"type": "string"}, "run_id": {"type": "string"},
    }, ["task_token", "run_id"]),
}

RUNTIME_TOOLS = {
    "BBBGenericEditorToolset": {
        "request_pie_late_join", "apply_pie_damage", "capture_pie_player_view",
        "probe_pie_character_ground_contacts", "inspect_pie_niagara_system",
    },
    "BBBControlRigAuthoringToolset": {"inject_pie_action"},
    "BBBAnimationMigrationToolset": {
        "run_pie_input_sequence", "stop_pie_input_sequence", "probe_pie_character_animation_runtime",
    },
}
EXCLUDED = {".git", ".idea", ".vs", "__pycache__", "Intermediate", "Saved", "Source"}
SCRIPT_ROOT = Path(__file__).resolve().parents[1]


class TestRunnerError(RuntimeError):
    """/** 带固定错误码的测试状态 */"""

    def __init__(self, code):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param code	本操作输入
         * @return 本操作结果
         */
        """
        self.code = code
        super().__init__(code)


def digest(path):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param path	本操作输入
     * @return 本操作结果
     */
    """
    with path.open("rb") as source:
        value = hashlib.file_digest(source, "sha256").hexdigest()
    return value


def plain_path(path):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param path	本操作输入
     * @return 本操作结果
     */
    """
    for component in (path, *path.parents):
        if component.exists():
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise TestRunnerError("TEST_DIRECTORY_LINK")


def tree_files(base):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param base	本操作输入
     * @return 本操作结果
     */
    """
    files = []
    plain_path(base)
    for directory, folders, names in os.walk(base, followlinks=False):
        for folder in folders:
            plain_path(Path(directory) / folder)
        folders[:] = sorted(name for name in folders if name not in EXCLUDED)
        for name in sorted(names):
            path = Path(directory) / name
            plain_path(path)
            if path.suffix not in {".pyc", ".pdb"} and ".patch_" not in path.name:
                files.append(path)
    return sorted(files)


def inventory(project):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param project	本操作输入
     * @return 本操作结果
     */
    """
    plain_path(project)
    files = [project]
    for name in ("Content", "Config", "Binaries", "Plugins"):
        base = project.parent / name
        if not base.exists():
            continue
        files.extend(tree_files(base))
    return sorted(files)


def available_memory():
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @return 本操作结果
     */
    """
    if os.name != "nt":
        raise TestRunnerError("TEST_PLATFORM_UNSUPPORTED")

    class MemoryStatus(ctypes.Structure):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
            ("physical", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
            ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
            ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
            ("extended", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise TestRunnerError("TEST_RESOURCE_PROBE_FAILED")
    return status.available


def private_port(protocol=socket.SOCK_STREAM):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param protocol	本操作输入
     * @return 本操作结果
     */
    """
    with socket.socket(socket.AF_INET, protocol) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_tool_allowed(toolset, name, arguments):
    """
    /**
     * 核对独立测试副本与实例的执行状态
     * @param toolset	本操作输入
     * @param name	本操作输入
     * @param arguments	本操作输入
     * @return 本操作结果
     */
    """
    definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
    if name in READ_TOOLS.get(definition, set()):
        return True
    if name in RUNTIME_TOOLS.get(definition, set()):
        return True
    if definition == "BBBExternalToolset" and name == "util":
        return arguments.get("action") in {"start_pie", "stop_pie", "is_in_pie", "get_output_log"}
    return False


class PieWorker:
    """/** 单个副本中的独立编辑器进程与私有连接 */"""

    def __init__(self, record, engine, network_port):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @param engine	本操作输入
         * @param network_port	本操作输入
         * @return 本操作结果
         */
        """
        self.record = record
        self.process = None
        self.session = None
        self.backend = None
        launcher = record["project"].parent / "BBBMcpScripts" / "MCP" / "Start-UE58OfficialMcpEditor.ps1"
        command = ["powershell", "-NoProfile", "-File", str(launcher), "-HostRole", "TestWorker",
            "-ProjectPath", str(record["project"]), "-EnginePath", str(engine),
            "-TestRunId", record["run_id"], "-TestMap", record["map_path"],
            "-TestPlayers", str(record["players"]), "-TestNetworkPort", str(network_port),
            "-BackendPort", str(private_port())]
        if record["rendering"]:
            command.append("-EnableRendering")
        if record["audio"]:
            command.append("-EnableAudio")
        descriptor = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        plan = json.loads(descriptor.stdout)
        environment = os.environ.copy()
        for name in ("P4PASSWD", "P4TICKETS", "P4CLIENT", "P4PORT", "P4USER"):
            environment.pop(name, None)
        environment["BBB_MCP_TEST_RUN_ID"] = record["run_id"]
        environment["BBB_MCP_SCRIPTS"] = str(record["project"].parent / "BBBMcpScripts")
        self.process = subprocess.Popen([plan["EditorPath"], *plan["Arguments"]],
            cwd=record["project"].parent, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            startupinfo=self._hidden_window(),
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.url = plan["BackendUrl"]

    def _hidden_window(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        value = subprocess.STARTUPINFO()
        value.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        value.wShowWindow = subprocess.SW_HIDE
        return value

    def ready(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        from MCP.mcp_task_gateway import UnrealBackend
        self.backend = UnrealBackend(self.url, str(self.record["project"].parent), self.process.pid)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise TestRunnerError("TEST_WORKER_EXITED")
            try:
                activity = self.backend.probe()
                if activity.get("pie_active") or activity.get("worlds") or activity.get("dirty_packages"):
                    raise TestRunnerError("TEST_WORKER_INITIAL_ACTIVITY")
                self.instance = activity["host_instance"]
                self.session = McpSession(self.url, 120, auto_heartbeat=False)
                return activity
            except TestRunnerError:
                raise
            except Exception:
                time.sleep(0.25)
        raise TestRunnerError("TEST_WORKER_START_TIMEOUT")

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
        activity = self.probe()
        if activity["host_instance"] != self.instance:
            raise TestRunnerError("TEST_WORKER_IDENTITY_CHANGED")
        definitions = decode_tool_result(self.session.call_tool("list_toolsets", {}))
        definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
        names = re.findall(r"(?m)^- ([^\r\n: ]+\." + re.escape(definition) + r"(?:_0x[0-9a-fA-F]{8})?)(?=:|\s|$)", definitions)
        if len(names) != 1:
            raise TestRunnerError("TEST_TOOLSET_NOT_UNIQUE")
        return self.session.call_tool("call_tool", {"toolset_name": names[0], "tool_name": name, "arguments": arguments})

    def probe(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        if self.process.poll() is not None:
            raise TestRunnerError("TEST_WORKER_EXITED")
        return self.backend.probe()

    def stop(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        if self.process.poll() is None:
            if self.backend is None:
                self.process.terminate()
            if self.backend is not None:
                try:
                    self.backend.probe()
                    self.backend.shutdown()
                except Exception:
                    logging.warning("[BBBMcpTest] TEST_EXIT_RESPONSE_PENDING")
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise TestRunnerError("TEST_EXIT_PENDING")
        if self.session is not None:
            self.session.close()
        if self.backend is not None:
            self.backend.close()
        return self.process.returncode

    def start_pie(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        decode_tool_result(self.call("BBBExternalToolset", "util", {"action": "start_pie"}))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            activity = self.probe()
            if activity["pie_active"] and len(activity["worlds"]) == self.record["players"]:
                return activity
            time.sleep(0.2)
        raise TestRunnerError("TEST_PIE_PLAYERS_PENDING")


class TestRunner:
    """/** 双实例队列由本网关统一维护 主宿主保持独立 */"""

    def __init__(self, project_root, engine_root, authorize, release, worker_factory=PieWorker,
                 memory_probe=available_memory, disk_probe=shutil.disk_usage):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param project_root	本操作输入
         * @param engine_root	本操作输入
         * @param authorize	本操作输入
         * @param release	本操作输入
         * @param worker_factory	本操作输入
         * @param memory_probe	本操作输入
         * @param disk_probe	本操作输入
         * @return 本操作结果
         */
        """
        self.project_root = Path(project_root).resolve()
        self.engine_root = Path(engine_root).resolve()
        self.root = self.project_root / "Saved" / "temp" / "McpTestRuns"
        plain_path(self.root)
        self.authorize = authorize
        self.release = release
        self.worker_factory = worker_factory
        self.memory_probe = memory_probe
        self.disk_probe = disk_probe
        self.lock = threading.RLock()
        self.records = {}
        self.queue = []
        self.closed = False
        self.legacy = sorted(path.name for path in self.root.iterdir()) if self.root.exists() else []
        self.unresolved = []
        for run_id in self.legacy:
            path = self.root / run_id / "state.json"
            plain_path(path)
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if previous.get("status") in {"starting", "ready", "uncertain", "stopping"}:
                    self.unresolved.append(run_id)
                if previous.get("status") == "failed" and previous.get("process_id") and not previous.get("exited"):
                    self.unresolved.append(run_id)
            except Exception:
                self.unresolved.append(run_id)
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def prepare_test_snapshot(self, task_token, map_path):
        """
        /**
         * @param task_token	所属任务凭证
         * @param map_path	已保存测试地图
         * @return 异步准备状态与测试编号
         */
        """
        if not isinstance(map_path, str) or not re.fullmatch(r"/Game/[A-Za-z0-9_/]+", map_path):
            raise TestRunnerError("TEST_MAP_INVALID")
        if not (self.project_root / "Content" / (map_path[6:] + ".umap")).is_file():
            raise TestRunnerError("TEST_MAP_NOT_SAVED")
        owner = self.authorize(task_token, True)
        try:
            with self.lock:
                if self.closed:
                    raise TestRunnerError("TEST_RUNNER_CLOSED")
                if sum(record["owner"] == task_token and record["status"] != "stopped" for record in self.records.values()) >= 2:
                    raise TestRunnerError("TEST_TASK_SNAPSHOT_LIMIT")
                run_id = secrets.token_hex(12)
                record = {"run_id": run_id, "snapshot_id": run_id, "owner": task_token, "task_id": owner,
                    "map_path": map_path, "status": "preparing", "inflight": False, "worker": None,
                    "error_code": None, "progress_files": 0, "total_files": 0,
                    "root": self.root / run_id, "network_port": None, "players": 1,
                    "rendering": False, "audio": False, "activity": None, "snapshot_hash": None,
                    "stop_requested": False, "pinned": True}
                self.records[run_id] = record
                threading.Thread(target=self._prepare, args=(record,), daemon=True).start()
                return self._public(record)
        except Exception:
            self.release(task_token)
            raise

    def _prepare(self, record):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @return 本操作结果
         */
        """
        try:
            projects = list(self.project_root.glob("*.uproject"))
            if len(projects) != 1:
                raise TestRunnerError("TEST_PROJECT_NOT_UNIQUE")
            project = projects[0]
            descriptor = json.loads(project.read_text(encoding="utf-8-sig"))
            if descriptor.get("AdditionalPluginDirectories"):
                raise TestRunnerError("TEST_EXTERNAL_PLUGIN_DIRECTORY")
            receipts = list((self.project_root / "Binaries" / "Win64").glob("*Editor.target"))
            if not receipts:
                raise TestRunnerError("TEST_EDITOR_BUILD_MISSING")
            files = inventory(project)
            engine_version = self.engine_root / "Engine" / "Build" / "Build.version"
            engine_hash = digest(engine_version)
            record["engine_hash"] = engine_hash
            record["live_coding_patch_count"] = len(list((self.project_root / "Binaries" / "Win64").glob("*.patch_*.dll")))
            scripts = SCRIPT_ROOT
            script_files = tree_files(scripts)
            destinations = {path: path.relative_to(self.project_root) for path in files}
            destinations.update({path: Path("BBBMcpScripts") / path.relative_to(scripts) for path in script_files})
            files += script_files
            size = sum(path.stat().st_size for path in files)
            plain_path(record["root"])
            if self.disk_probe(self.project_root).free < size + 4 * 1024 ** 3:
                raise TestRunnerError("TEST_DISK_BUDGET")
            record["total_files"] = len(files)
            record["root"].mkdir(parents=True, exist_ok=False)
            self._persist(record)
            destination = record["root"] / "Project"
            manifest = {}
            for path in files:
                if record["stop_requested"]:
                    raise TestRunnerError("TEST_PREPARATION_CANCELLED")
                relative = destinations[path]
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                before = path.stat()
                source_hash = digest(path)
                shutil.copyfile(path, target)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest(target) != source_hash:
                    raise TestRunnerError("TEST_SOURCE_CHANGED")
                manifest[str(relative)] = source_hash
                record["progress_files"] += 1
            if digest(engine_version) != engine_hash:
                raise TestRunnerError("TEST_ENGINE_CHANGED")
            if inventory(project) + tree_files(scripts) != files:
                raise TestRunnerError("TEST_SOURCE_CHANGED")
            for path in files:
                if record["stop_requested"]:
                    raise TestRunnerError("TEST_PREPARATION_CANCELLED")
                if digest(path) != manifest[str(destinations[path])]:
                    raise TestRunnerError("TEST_SOURCE_CHANGED")
            for receipt_path in receipts:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
                for product in receipt.get("BuildProducts", []):
                    path = product["Path"]
                    if path.startswith("$(ProjectDir)/") and product["Type"] != "SymbolFile":
                        if not (destination / path[len("$(ProjectDir)/"):]).is_file():
                            raise TestRunnerError("TEST_BUILD_PRODUCT_MISSING")
            for module_path in destination.rglob("*.modules"):
                modules = json.loads(module_path.read_text(encoding="utf-8-sig"))
                for dll in modules.get("Modules", {}).values():
                    if Path(dll).name != dll or not (module_path.parent / dll).is_file():
                        raise TestRunnerError("TEST_MODULE_BINARY_MISSING")
            initializer = destination / "Content" / "Python" / "init_unreal.py"
            initializer.parent.mkdir(parents=True, exist_ok=True)
            initializer.write_text('import os\nimport sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, os.environ["BBB_MCP_SCRIPTS"])\nimport BBBMcpBootstrap\nBBBMcpBootstrap.register_mcp_toolsets()\n', encoding="utf-8")
            manifest[str(initializer.relative_to(destination))] = digest(initializer)
            record["project"] = destination / project.name
            (record["root"] / "snapshot.json").write_text(json.dumps({"run_id": record["run_id"],
                "files": manifest, "map_path": record["map_path"]}, sort_keys=True), encoding="utf-8")
            record["snapshot_hash"] = digest(record["root"] / "snapshot.json")
            record["status"] = "prepared"
            self._persist(record)
        except Exception as error:
            record["error_code"] = getattr(error, "code", "TEST_PREPARATION_FAILED")
            record["status"] = "failed"
            self._persist(record)
            logging.warning("[BBBMcpTest] %s", record["error_code"])

    def _owned(self, task_token, run_id):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param task_token	本操作输入
         * @param run_id	本操作输入
         * @return 本操作结果
         */
        """
        self.authorize(task_token, False)
        record = self.records.get(run_id)
        if record is None or not secrets.compare_digest(record["owner"], task_token):
            raise TestRunnerError("TEST_RUN_OWNERSHIP_REQUIRED")
        return record

    def start_test_run(self, task_token, snapshot_id, players=1, rendering=False, audio=False):
        """
        /**
         * @param task_token	所属任务凭证
         * @param snapshot_id	准备完成的副本编号
         * @param players	本组玩家数 一至四
         * @param rendering	渲染验收
         * @param audio	声音验收
         * @return 队列状态
         */
        """
        if type(players) is not int or players < 1 or players > 4 or type(rendering) is not bool or type(audio) is not bool:
            raise TestRunnerError("TEST_SETTINGS_INVALID")
        with self.lock:
            record = self._owned(task_token, snapshot_id)
            if record["status"] == "queued":
                if (players, rendering, audio) != (record["players"], record["rendering"], record["audio"]):
                    raise TestRunnerError("TEST_SETTINGS_ALREADY_FIXED")
                return self._public(record)
            if self.closed or record["status"] != "prepared":
                raise TestRunnerError("TEST_SNAPSHOT_NOT_READY")
            record.update(players=players, rendering=rendering, audio=audio, status="queued")
            self.queue.append(snapshot_id)
            self._persist(record)
            return self._public(record)

    def _pump(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        while not self.closed:
            with self.lock:
                for record in self.records.values():
                    worker = record["worker"]
                    if worker is not None and record["status"] in {"ready", "uncertain"} and worker.process.poll() is not None:
                        record.update(status="failed", error_code="TEST_WORKER_EXITED")
                running = sum(record["status"] in {"starting", "ready", "stopping"} or
                    record["worker"] is not None and record["worker"].process.poll() is None for record in self.records.values())
                if self.queue and running + len(self.unresolved) < 2:
                    record = self.records[self.queue[0]]
                    try:
                        pending = sum(item["status"] == "starting" for item in self.records.values())
                        if self.memory_probe() < (6 + 4 * pending) * 1024 ** 3:
                            raise TestRunnerError("TEST_MEMORY_BUDGET")
                        self.authorize(record["owner"], False)
                        record["error_code"] = None
                        record["status"] = "starting"
                        self._persist(record)
                        self.queue.pop(0)
                        threading.Thread(target=self._start, args=(record,), daemon=True).start()
                    except Exception as error:
                        record["error_code"] = getattr(error, "code", "TEST_RESOURCE_PROBE_FAILED")
            time.sleep(0.2)

    def _start(self, record):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @return 本操作结果
         */
        """
        try:
            if digest(self.engine_root / "Engine" / "Build" / "Build.version") != record["engine_hash"]:
                raise TestRunnerError("TEST_ENGINE_CHANGED")
            manifest_path = record["root"] / "snapshot.json"
            if digest(manifest_path) != record["snapshot_hash"]:
                raise TestRunnerError("TEST_SNAPSHOT_CHANGED")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            actual_files = inventory(record["project"]) + tree_files(record["project"].parent / "BBBMcpScripts")
            if {str(path.relative_to(record["project"].parent)) for path in actual_files} != set(manifest["files"]):
                raise TestRunnerError("TEST_SNAPSHOT_CHANGED")
            for relative, expected in manifest["files"].items():
                plain_path(record["project"].parent / relative)
                if digest(record["project"].parent / relative) != expected:
                    raise TestRunnerError("TEST_SNAPSHOT_CHANGED")
            with self.lock:
                reserved = {item["network_port"] for item in self.records.values()}
                port = private_port(socket.SOCK_DGRAM)
                while port in reserved:
                    port = private_port(socket.SOCK_DGRAM)
                record["network_port"] = port
                if record["stop_requested"] or self.closed:
                    raise TestRunnerError("TEST_START_CANCELLED")
            worker = self.worker_factory(record, self.engine_root, port)
            with self.lock:
                record["worker"] = worker
                self._persist(record)
                if record["stop_requested"] or self.closed:
                    worker.stop()
                    raise TestRunnerError("TEST_START_CANCELLED")
            record["activity"] = worker.ready()
            if record["stop_requested"] or self.closed:
                worker.stop()
                raise TestRunnerError("TEST_START_CANCELLED")
            record["activity"] = worker.start_pie()
            record["observed_at_unix"] = time.time()
            record["status"] = "ready"
            self._persist(record)
        except Exception as error:
            record["error_code"] = getattr(error, "code", "TEST_START_FAILED")
            record["status"] = "failed"
            self._persist(record)
            logging.warning("[BBBMcpTest] %s", record["error_code"])

    def call_test_tool(self, task_token, run_id, toolset_name, tool_name, arguments=None):
        """
        /**
         * @param task_token	所属任务凭证
         * @param run_id	测试编号
         * @param toolset_name	审核工具集
         * @param tool_name	运行时工具
         * @param arguments	业务参数
         * @return 原工具协议结果与回读活动
         */
        """
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict) or not test_tool_allowed(toolset_name, tool_name, arguments):
            raise TestRunnerError("TEST_TOOL_ACCESS_REQUIRED")
        with self.lock:
            record = self._owned(task_token, run_id)
            readonly = tool_access(toolset_name, tool_name, arguments) == "shared_read"
            if record["status"] not in {"ready", "uncertain"} or record["inflight"]:
                raise TestRunnerError("TEST_RUN_BUSY")
            if record["status"] == "uncertain" and not readonly:
                raise TestRunnerError("TEST_CALL_REVIEW_REQUIRED")
            record["inflight"] = True
            record["operation"] = {"toolset": toolset_name, "tool": tool_name, "started_at_unix": time.time()}
        try:
            if tool_name == "request_pie_late_join":
                activity = record["worker"].probe()
                if len(activity["worlds"]) >= 4:
                    raise TestRunnerError("TEST_PLAYER_LIMIT")
            result = record["worker"].call(toolset_name, tool_name, arguments)
            record["activity"] = record["worker"].probe()
            record["observed_at_unix"] = time.time()
            try:
                decode_tool_result(result)
            except McpBusinessError:
                record["error_code"] = "TEST_TOOL_RESULT_REVIEW_REQUIRED"
                if not readonly:
                    record["status"] = "uncertain"
            return {"run_id": run_id, "tool_result": result, "activity": record["activity"]}
        except Exception as error:
            record["error_code"] = getattr(error, "code", "TEST_CALL_UNCERTAIN")
            if not readonly:
                record["status"] = "uncertain"
                self._persist(record)
            raise TestRunnerError(record["error_code"]) from None
        finally:
            record["inflight"] = False
            record["operation"] = None

    def _public(self, record):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @return 本操作结果
         */
        """
        result = {name: record[name] for name in ("run_id", "snapshot_id", "task_id", "map_path", "status",
            "error_code", "progress_files", "total_files", "players", "rendering", "audio", "snapshot_hash", "inflight")}
        result["queue_position"] = self.queue.index(record["run_id"]) + 1 if record["run_id"] in self.queue else None
        result["process_id"] = record["worker"].process.pid if record["worker"] else None
        activity = record["activity"]
        result["operation"] = record.get("operation")
        result["observed_at_unix"] = record.get("observed_at_unix")
        result["build_basis"] = "saved_files_and_disk_binaries"
        result["live_coding_patch_count"] = record.get("live_coding_patch_count", 0)
        if activity is not None:
            result["activity"] = {name: activity.get(name) for name in ("pie_active", "worlds", "activities", "dirty_packages")}
        return result

    def _persist(self, record):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @param record	本操作输入
         * @return 本操作结果
         */
        """
        if not record["root"].exists():
            return
        plain_path(record["root"])
        value = {"run_id": record["run_id"], "task_id": record["task_id"], "status": record["status"],
            "process_id": record["worker"].process.pid if record["worker"] else None,
            "exited": record["worker"] is None or record["worker"].process.poll() is not None}
        (record["root"] / "state.json").write_text(json.dumps(value), encoding="utf-8")

    def inspect_test_runs(self, task_token=None):
        """/** @return 测试占用与队列的凭证隐藏状态 */"""
        with self.lock:
            runs = [self._public(record) for record in self.records.values()]
            for result in runs:
                result["owned_by_caller"] = task_token == self.records[result["run_id"]]["owner"]
            return {"max_parallel_runs": 2, "runs": runs,
                "previous_output_ids": self.legacy, "previous_workers_review_ids": self.unresolved, "closed": self.closed}

    def stop_test_run(self, task_token, run_id):
        """
        /**
         * @param task_token	所属任务凭证
         * @param run_id	本任务测试编号
         * @return 退出核实与保留输出目录
         */
        """
        with self.lock:
            record = self._owned(task_token, run_id)
            if record["inflight"] or record["status"] in {"starting", "stopping"}:
                raise TestRunnerError("TEST_RUN_BUSY")
            if record["status"] == "preparing":
                record["stop_requested"] = True
                return {"run_id": run_id, "status": "cancellation_requested"}
            record["status"] = "stopping"
            if run_id in self.queue:
                self.queue.remove(run_id)
        try:
            if record["worker"] is not None:
                record["worker"].stop()
            record["status"] = "stopped"
            self._persist(record)
            if record["pinned"]:
                self.release(task_token)
                record["pinned"] = False
            return {"run_id": run_id, "status": "stopped", "exited": True,
                "output_directory": str(record["root"]), "cleanup": "owner_review_required"}
        except Exception as error:
            record["status"] = "failed"
            record["error_code"] = getattr(error, "code", "TEST_STOP_FAILED")
            self._persist(record)
            raise TestRunnerError(record["error_code"]) from None

    def close(self):
        """
        /**
         * 核对独立测试副本与实例的执行状态
         * @return 本操作结果
         */
        """
        self.closed = True
        with self.lock:
            for record in self.records.values():
                record["stop_requested"] = True
                if record["worker"] is not None:
                    try:
                        record["worker"].stop()
                        record["status"] = "stopped"
                        self._persist(record)
                    except Exception:
                        logging.error("[BBBMcpTest] TEST_EXIT_PENDING")
