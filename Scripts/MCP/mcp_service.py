import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BBBMcpCapabilities import ToolCatalog
from MCP.mcp_clients import ClientRegistry
from MCP.mcp_host_registry import HostRegistry, RegistryGuard, atomic_json, private_directory, process_identity, project_key
from MCP.mcp_project_host import project_identity
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import TaskGateway, UnrealBackend, public_tools
from MCP.mcp_test_hosts import TestHost, project_version


def service_directory():
    """/** @return 当前用户的常驻服务配置目录 */"""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
        local = os.path.expandvars(winreg.QueryValueEx(key, "Local AppData")[0])
    return private_directory(Path(local) / "BBBMcp")


def configuration(project_file=None, port=8000, directory=None):
    """/** @param project_file 首次接入项目 @param port 服务端口 @param directory 配置目录 @return 当前配置 */"""
    directory = private_directory(directory or service_directory())
    path = directory / "service.json"
    if path.is_symlink():
        raise ValueError("SERVICE_CONFIG_LINK")
    exists = path.exists()
    value = json.loads(path.read_text(encoding="utf-8")) if exists else {"port": port, "projects": []}
    changed = not exists
    if project_file is not None:
        project = str(Path(project_file).resolve())
        if not Path(project).is_file() or Path(project).suffix.lower() != ".uproject":
            raise ValueError("PROJECT_FILE_REQUIRED")
        if project_identity(project) not in {project_identity(item) for item in value["projects"]}:
            value["projects"].append(project)
            changed = True
    if not value["projects"] or value["port"] != port:
        raise ValueError("SERVICE_CONFIGURATION_REQUIRED")
    if changed:
        atomic_json(path, value)
    return value


def service_health(url):
    """/** @param url 本机 MCP 地址 @return 已验证服务的公开身份 */"""
    endpoint = urlparse(url)
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(endpoint._replace(path="/health", query="", fragment="").geturl()), timeout=2) as response:
        value = json.load(response)
    if value.get("service") != "BBB-MCP" or value.get("protocol") != 5:
        raise RuntimeError("SERVICE_HANDOVER_REQUIRED")
    return value


@contextmanager
def service_lock(directory, port):
    """/** @param directory 用户配置目录 @param port 服务端口 @return 串行化服务启动与项目登记 */"""
    import hashlib
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    key = hashlib.sha256((str(Path(directory).resolve()) + ":" + str(port)).encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, "Local\\BBBMcpServiceStart_" + key)
    if not handle:
        raise RuntimeError("SERVICE_START_LOCK_FAILED")
    acquired = kernel.WaitForSingleObject(handle, 30000) in {0, 0x80}
    try:
        if not acquired:
            raise RuntimeError("SERVICE_START_WAITING")
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def ensure_service(project_file=None, port=8000, timeout=15, directory=None, python=None):
    """/** @param project_file 接入项目 @param port 固定入口 @param timeout 就绪上限 @param directory 配置目录 @param python 运行时 @return 单实例常驻服务 */"""
    directory = Path(directory or service_directory()).resolve()
    with service_lock(directory, port):
        return _ensure_service(project_file, port, timeout, directory, python)


def _ensure_service(project_file=None, port=8000, timeout=15, directory=None, python=None):
    """/** @param project_file 接入项目 @param port 固定入口 @param timeout 就绪上限 @param directory 配置目录 @param python 运行时 @return 常驻服务身份 */"""
    url = "http://127.0.0.1:" + str(port) + "/mcp"
    if project_file is not None:
        configuration(project_file, port, directory)
    try:
        health = service_health(url)
        if project_file is not None and project_key(project_file) not in health["projects"]:
            configuration(project_file, port, directory)
            deadline = time.monotonic() + timeout
            while project_key(project_file) not in health["projects"]:
                if time.monotonic() >= deadline:
                    raise RuntimeError("PROJECT_ENROLLMENT_WAITING")
                time.sleep(0.2)
                health = service_health(url)
        return health
    except Exception:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("SERVICE_HANDOVER_REQUIRED: existing listener retained")
    directory = Path(directory or service_directory()).resolve()
    configuration(project_file, port, directory)
    arguments = [python or sys.executable, "-B", str(Path(__file__).resolve()), "--directory", str(directory), "--port", str(port)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log_path = directory / "startup.log"
    mode = "wb" if log_path.exists() and log_path.stat().st_size > 65536 else "ab"
    with log_path.open(mode) as output:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=flags)
    threading.Thread(target=process.wait, daemon=True, name="BBB-MCP-service-process").start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return service_health(url)
        except Exception:
            if process.poll() is not None:
                raise RuntimeError("SERVICE_START_FAILED: inspect startup.log")
        time.sleep(0.2)
    raise RuntimeError("SERVICE_START_TIMEOUT: inspect startup.log")


class CachedCatalog(ToolCatalog):
    """/** 编辑器暂时离线时继续提供上次核验的工具目录 */"""

    def __init__(self, path):
        """/** @param path 已核验契约快照 @return 可离线查询的目录 */"""
        self.path = Path(path)
        self.tools = {}
        self.backend = None
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                self.tools = value["tools"]
                self.version()
            except (OSError, ValueError, KeyError, TypeError):
                self.tools = {}
                logging.warning("catalog_snapshot_invalid")

    def refresh(self, backend):
        """/** @param backend 已核实的执行端 @return 当前实际目录 */"""
        catalog = ToolCatalog(backend)
        atomic_json(self.path, {"tools": catalog.tools, "version": catalog.version()})
        self.tools = catalog.tools
        self.backend = backend
        return self


class ProjectRuntime:
    """/** 服务进程内持续存在的项目连接与调度上下文 */"""

    def __init__(self, project_file, registry, test_limit=2):
        """/** @param project_file 项目 @param registry 进程登记 @param test_limit 测试容量 @return 项目上下文 */"""
        self.project_file = Path(project_file).resolve()
        self.project = project_identity(project_file)
        self.registry = registry
        self.test_limit = test_limit
        self.lock = threading.RLock()
        self.state = "offline"
        self.error = None
        self.identity = None
        self.backend = None
        self.gateway = None
        self.revision = 0
        self.view_signature = None
        self.view_revision = 0
        self.retry_at = 0
        state = private_directory(self.project_file.parent / "Saved/McpState")
        self.clients = ClientRegistry(state_path=state / "gateway.sqlite")
        self.catalog = CachedCatalog(state / "catalog.json")
        self.protocol = object.__new__(TaskGateway)
        self.protocol.catalog = self.catalog
        self.protocol.clients = self.clients
        self.protocol.jobs = self
        self.protocol.tools = {row["name"]: row for row in public_tools()}

    def connect(self, resume_key=None):
        """/** @param resume_key 客户端恢复凭据 @return 已登记身份 */"""
        with self.lock:
            if self.gateway:
                return self.gateway.jobs.connect(resume_key)
            return self.clients.connect(resume_key)

    def touch(self, client):
        """/** @param client 私有客户端身份 @return 已续期 */"""
        self.clients.touch(client)

    def reconcile(self):
        """/** @return 核验登记连接并在空闲边界接续新宿主 */"""
        row = self.registry.candidate(self.project)
        if row is None:
            if self.state != "offline":
                self.state = "offline"
                self.revision += 1
            return
        identity = (row["process_id"], row["created"])
        if identity == self.identity and self.backend is not None:
            queue = self.gateway.jobs.editor
            if queue.call_active:
                return
            try:
                queue.observe(force=True)
                if not queue.activity.get("host_verified"):
                    raise RuntimeError("HOST_RESPONSE_TIMEOUT")
                self.registry.mark(row["process_id"], "ready")
                if self.state != "ready":
                    self.state = "ready"
                    self.revision += 1
            except Exception:
                self.state = "unresponsive"
                self.registry.mark(row["process_id"], "unresponsive", "HOST_RESPONSE_TIMEOUT")
                self.backend.close()
            return
        if time.monotonic() < self.retry_at:
            return
        self.retry_at = time.monotonic() + 5
        if self.gateway and (self.gateway.jobs.editor.call_active or self.gateway.jobs.editor.writer):
            return
        self.state = "connecting"
        self.registry.mark(row["process_id"], "connecting")
        backend = UnrealBackend(row["backend_url"], self.project, row["process_id"])
        backend.guard = RegistryGuard(self.registry, self.project, row["process_id"])
        try:
            backend.probe()
            catalog = ToolCatalog(backend)
            backend.remap = True
            with self.lock:
                if self.gateway is not None:
                    old = self.gateway.jobs.editor
                    old.close()
                    if old.worker and old.worker.is_alive():
                        raise RuntimeError("PREVIOUS_EXECUTION_SETTLING")
                self.catalog.tools = catalog.tools
                self.catalog.backend = backend
                atomic_json(self.catalog.path, {"tools": catalog.tools, "version": catalog.version()})
                previous_backend = self.backend
                self.backend = backend
                self.identity = identity
                if self.gateway is None:
                    self.gateway = TaskGateway(backend, catalog=self.catalog, test_factory=self._test_factory,
                        version=self._version, test_limit=self.test_limit,
                        test_output_root=self.project_file.parent / "Saved/temp/McpTests", clients=self.clients,
                        test_restore=self._restore_test)
                if previous_backend is not None:
                    from MCP.mcp_jobs import JobQueue
                    self.gateway.jobs.editor = JobQueue(backend, self.catalog, clients=self.clients)
                    for client in list(self.clients):
                        if not client.startswith("@"):
                            self.gateway.jobs.connect(client)
                    previous_backend.close()
                self.backend = backend
                self.identity = identity
                self.state = "ready"
                self.error = None
                self.revision += 1
            self.registry.mark(row["process_id"], "ready")
            logging.info("host_connected project=%s pid=%s", project_key(self.project), row["process_id"])
        except Exception as error:
            backend.close()
            self.state = "connecting"
            self.error = type(error).__name__
            self.registry.mark(row["process_id"], "connecting", self.error)
            logging.warning("host_connect_failed project=%s pid=%s type=%s", project_key(self.project), row["process_id"], type(error).__name__)

    def _test_factory(self, batch, options):
        """/** @param batch 批次 @param options 测试配置 @return 受限原项目测试宿主 */"""
        return TestHost(batch, options, self.project_file, Path(self.identity_row()["editor_path"]), self.backend.guard, UnrealBackend)

    def _restore_test(self, batch, options, pid):
        """/** @param batch 原测试 @param options 原配置 @param pid 原进程 @return 核验后接回的测试宿主 */"""
        with self.registry.lock:
            row = self.registry.hosts.get(pid)
            if row is None or row.get("batch") != batch or row["project"] != self.project:
                raise RuntimeError("TEST_HOST_IDENTITY_REQUIRED")
            row = dict(row)
        return TestHost.adopt(row, self.backend.guard, UnrealBackend)

    def identity_row(self):
        """/** @return 当前资产宿主的已登记身份 */"""
        row = self.registry.candidate(self.project)
        if row is None or (row["process_id"], row["created"]) != self.identity:
            raise RuntimeError("HOST_EPOCH_CHANGED")
        return row

    def _version(self, record):
        """/** @param record 测试批次 @return 原项目输入的当前版本 */"""
        from MCP.mcp_asset_scope import asset_targets
        if "input_files" not in record:
            paths = sorted({record["options"]["map"]} | asset_targets(record["operations"]))
            self.backend._toolsets()
            record["input_files"] = self.backend._call("call_tool", {"toolset_name": self.backend.task_name,
                "tool_name": "inspect_saved_test_inputs", "arguments": {"asset_paths": paths}})["files"]
        return project_version(self.project, record["input_files"])

    def submit(self, client, operations, label="", environment="editor", test_options=None, test_host=None):
        """/** @param client 所属客户端 @param operations 操作 @param label 用途 @param environment 执行环境 @param test_options 测试配置 @param test_host 测试归属 @return 已提交批次 */"""
        with self.lock:
            if self.gateway is None or self.state != "ready":
                raise McpBusinessError({"status": "waiting", "code": "EDITOR_CONNECTING" if self.state == "connecting" else "EDITOR_OFFLINE",
                    "next": "inspect_tasks", "retry_after_seconds": 2, "hint": "编辑器接入后重新提交；使用 inspect_tasks 等待状态变为 ready"})
            return self.gateway.jobs.submit(client, operations, label, environment, test_options, test_host)

    def inspect(self, client, batch=None, detail=False, after_revision=None, wait_seconds=0):
        """/** @param client 所属客户端 @param batch 批次 @param detail 详细信息 @param after_revision 上次版本 @param wait_seconds 等待上限 @return 项目与连接状态 */"""
        deadline = time.monotonic() + wait_seconds
        while True:
            with self.lock:
                gateway = self.gateway
                if gateway:
                    value = gateway.jobs.inspect(client, batch, detail)
                if gateway is None:
                    value = {"revision": 0, "host": {"process_id": None, "verified": False, "exclusive": False},
                        "queued": 0, "pie": False, "activities": 0, "dirty": 0, "asset_occupancy": [],
                        "tests": {"running": 0, "queued": 0, "limit": self.test_limit}}
                    if batch:
                        stored = next((item for item in self.clients.stored_jobs() if item["id"] == batch and item["owner"] == self.clients.digest(client)), None)
                        if stored is None:
                            raise McpBusinessError({"status": "rejected", "code": "BATCH_OWNERSHIP"})
                        value = {"batch": batch, "status": stored["status"], "completed": stored["completed"], "results": stored["results"], "next": "inspect_tasks"}
                if batch is None:
                    value["connection"] = self.state
                    value["service"] = "ready"
                    value["hosts"] = self.registry.public()
                    if self.state != "ready":
                        value.update(status=self.state, available=["prepare", "inspect"], next="inspect_tasks", retry_after_seconds=2)
                        value["host"] = {**value["host"], "verified": False}
                        if self.state == "offline":
                            value["host"]["process_id"] = None
                        value["stale"] = gateway is not None
                    signature = (value.get("revision", 0), self.revision, self.registry.revision)
                    if signature != self.view_signature:
                        self.view_signature = signature
                        self.view_revision += 1
                    value["revision"] = self.view_revision
                revision = value.get("revision", 0)
            if after_revision is None or after_revision != revision or time.monotonic() >= deadline:
                return value
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def control(self, client, action, batch=None):
        """/** @param client 所属客户端 @param action 控制动作 @param batch 批次 @return 归属范围内的结果 */"""
        with self.lock:
            if self.gateway is None:
                raise McpBusinessError({"status": "waiting", "code": "EDITOR_OFFLINE", "next": "inspect_tasks"})
            return self.gateway.jobs.control(client, action, batch)


class McpService:
    """/** 与 UE 生命周期独立的本机服务 */"""

    def __init__(self, projects, test_limit=2, registry=None, config_path=None):
        """/** @param projects 项目文件列表 @param test_limit 并行测试容量 @param registry 进程发现 @return 常驻服务 */"""
        self.registry = registry or HostRegistry(projects)
        self.projects = {project_key(path): ProjectRuntime(path, self.registry, test_limit) for path in projects}
        self.default = next(iter(self.projects))
        self.config_path = config_path
        self.test_limit = test_limit
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._monitor, daemon=True, name="BBB-MCP-hosts")

    def _monitor(self):
        """/** @return 后台发现与连接循环 */"""
        while not self.stop_event.is_set():
            try:
                if self.config_path is not None:
                    config = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
                    for path in config["projects"]:
                        key = project_key(path)
                        if key not in self.projects:
                            self.registry.projects[project_identity(path)] = Path(path).resolve()
                            self.projects[key] = ProjectRuntime(path, self.registry, self.test_limit)
                self.registry.refresh()
                for context in list(self.projects.values()):
                    context.reconcile()
            except Exception as error:
                logging.error("host_monitor_failed type=%s", type(error).__name__)
            self.stop_event.wait(3)

    def close(self):
        """/** @return 停止服务调度并保留 UE 进程 */"""
        self.stop_event.set()
        for context in self.projects.values():
            if context.gateway:
                context.gateway.jobs.detach()
            if context.backend:
                context.backend.close()


def make_service_server(service, port):
    """/** @param service 常驻上下文 @param port 回环端口 @return 本机 HTTP 入口 */"""
    class Handler(BaseHTTPRequestHandler):
        def local_request(self):
            host = urlparse("//" + self.headers.get("Host", ""))
            return host.hostname in {"127.0.0.1", "localhost"} and host.port == self.server.server_address[1] and not self.headers.get("Origin")

        def do_GET(self):
            if self.path != "/health" or not self.local_request():
                self.send_error(403)
                return
            self.send_value(200, {}, {"service": "BBB-MCP", "protocol": 5, "process_id": os.getpid(),
                "projects": list(service.projects), "default": service.default})

        def do_POST(self):
            self.dispatch()

        def do_DELETE(self):
            self.dispatch()

        def send_value(self, status, headers, value):
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if value is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self):
            route = self.path
            key = service.default
            if route.startswith("/projects/") and route.endswith("/mcp"):
                key = route[len("/projects/"):-len("/mcp")]
                route = "/mcp"
            if route != "/mcp" or not self.local_request() or key not in service.projects:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 1048576:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body, dict):
                    raise ValueError("REQUEST_OBJECT")
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            try:
                self.send_value(*service.projects[key].protocol.handle(self.command, self.headers, body))
            except Exception as error:
                logging.error("request_failed type=%s", type(error).__name__)
                self.send_value(500, {}, {"error": "SERVICE_REQUEST_FAILED"})

        def log_message(self, format, *arguments):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    """/** @return 启动当前用户的独立 MCP 服务 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-file", action="append")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ensure", action="store_true")
    parser.add_argument("--supervise", action="store_true")
    parser.add_argument("--test-hosts", type=int, choices=(1, 2), default=2)
    arguments = parser.parse_args()
    directory = arguments.directory or service_directory()
    if arguments.supervise:
        handler = RotatingFileHandler(directory / "supervisor.log", maxBytes=262144, backupCount=1, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        while True:
            try:
                ensure_service(port=arguments.port, directory=directory)
            except Exception as error:
                logging.warning("service_supervision_retry type=%s", type(error).__name__)
            time.sleep(3)
    if arguments.ensure:
        print(json.dumps(ensure_service((arguments.project_file or [None])[0], arguments.port, directory=directory)))
        return
    config = configuration((arguments.project_file or [None])[0], arguments.port, directory)
    for project in (arguments.project_file or [])[1:]:
        config = configuration(project, arguments.port, directory)
    handler = RotatingFileHandler(directory / "service.log", maxBytes=1048576, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    service = McpService(config["projects"], arguments.test_hosts, config_path=directory / "service.json")
    try:
        server = make_service_server(service, arguments.port)
    except OSError:
        service_health("http://127.0.0.1:" + str(arguments.port) + "/mcp")
        return
    service.thread.start()
    logging.info("service_ready port=%s pid=%s", arguments.port, os.getpid())
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        server.server_close()


if __name__ == "__main__":
    main()
