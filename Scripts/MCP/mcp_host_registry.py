import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

from MCP.mcp_project_host import editor_inventory, project_identity


def process_identity(pid):
    """/** @param pid 本机进程编号 @return 创建时间与程序路径组成的实际身份 */"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            return None
        if values[1].dwHighDateTime or values[1].dwLowDateTime:
            return None
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return None
        created = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        return {"process_id": int(pid), "created": str(created), "editor_path": str(Path(path.value).resolve())}
    finally:
        kernel.CloseHandle(handle)


def private_directory(path):
    """/** @param path 当前用户持有的运行记录目录 @return 已限制权限的真实目录 */"""
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("STATE_DIRECTORY_LINK")
    if path.exists():
        return path
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = subprocess.run(["whoami"], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode().strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", user + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
                       capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return path


def atomic_json(path, value):
    """/** @param path 目标记录 @param value 可序列化状态 @return 已原子替换的记录 */"""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("STATE_FILE_LINK")
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def host_directory(project_file):
    """/** @param project_file 项目文件 @return 所属进程的私有登记目录 */"""
    return private_directory(Path(project_file).resolve().parent / "Saved/McpState/hosts")


def publish_host(project_file, backend_url, role="editor", batch=None):
    """/** @param project_file 项目 @param backend_url 私有后端 @param role 用途 @param batch 测试归属 @return 本次进程登记记录 */"""
    identity = process_identity(os.getpid())
    if identity is None:
        raise RuntimeError("PROCESS_IDENTITY_REQUIRED")
    value = {**identity, "project_file": str(Path(project_file).resolve()), "backend_url": backend_url,
             "role": role, "batch": batch, "heartbeat": time.time()}
    write_host(value)
    return value


def write_host(value):
    """/** @param value 已核实的进程登记 @return 已更新心跳 */"""
    value["heartbeat"] = time.time()
    directory = host_directory(value["project_file"])
    atomic_json(directory / (str(value["process_id"]) + ".json"), value)


class HostRegistry:
    """/** 进程发现与项目宿主归属的唯一维护来源 */"""

    def __init__(self, projects, inventory=editor_inventory, identify=process_identity):
        """/** @param projects 接入项目 @param inventory 进程发现 @param identify 实际身份核验 @return 登记簿 */"""
        self.projects = {project_identity(path): Path(path).resolve() for path in projects}
        self.inventory = inventory
        self.identify = identify
        self.lock = threading.RLock()
        self.hosts = {}
        self.selected = {}
        self.discovered = []
        self.error = None
        self.revision = 0

    def refresh(self):
        """/** @return 缓存后的进程发现与私有登记核验结果 */"""
        try:
            discovered = self.inventory()
        except Exception:
            with self.lock:
                self.error = "PROCESS_DISCOVERY_FAILED"
            return
        actual = {row["process_id"]: row for row in discovered if row.get("kind", "editor") == "editor"}
        hosts = {}
        for project, project_file in self.projects.items():
            directory = host_directory(project_file)
            for path in directory.glob("*.json"):
                try:
                    if path.is_symlink() or path.stat().st_size > 16384:
                        continue
                    value = json.loads(path.read_text(encoding="utf-8"))
                    pid = value["process_id"]
                    identity = self.identify(pid)
                    if identity is None:
                        path.unlink(missing_ok=True)
                        continue
                    if value["created"] != identity["created"]:
                        path.unlink(missing_ok=True)
                        continue
                    if pid not in actual or project_identity(actual[pid]["project_root"]) != project:
                        continue
                    if project_identity(value["project_file"]) != project:
                        continue
                    if os.path.normcase(value["editor_path"]) != os.path.normcase(identity["editor_path"]):
                        continue
                    endpoint = urlparse(value["backend_url"])
                    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port or endpoint.username or endpoint.query or endpoint.fragment:
                        continue
                    if re.fullmatch(r"/bbb-mcp-[0-9a-f]{32}", endpoint.path) is None:
                        continue
                    if value.get("role") not in {"editor", "test"} or value["role"] != actual[pid].get("role", "editor"):
                        continue
                    if value["role"] == "test" and (re.fullmatch(r"[0-9a-f]{16}", str(value.get("batch"))) is None or value["batch"] != actual[pid].get("batch")):
                        continue
                    value["project"] = project
                    value["connection"] = "registered"
                    hosts[pid] = value
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        with self.lock:
            previous = self.public()
            for pid, row in hosts.items():
                old = self.hosts.get(pid)
                if old and old["created"] == row["created"]:
                    row["connection"] = old.get("connection", "registered")
                    row["error"] = old.get("error")
            self.hosts = hosts
            self.discovered = list(actual.values())
            self.error = None
            for project in self.projects:
                selected = self.selected.get(project)
                if selected not in hosts:
                    candidates = [pid for pid, row in hosts.items() if row["project"] == project and row["role"] == "editor"]
                    self.selected[project] = min(candidates, key=lambda pid: int(hosts[pid]["created"])) if candidates else None
            if previous != self.public():
                self.revision += 1

    def candidate(self, project):
        """/** @param project 项目身份 @return 已登记的资产编辑宿主副本 */"""
        with self.lock:
            row = self.hosts.get(self.selected.get(project_identity(project)))
            return dict(row) if row else None

    def mark(self, pid, connection, error=None):
        """/** @param pid 实际进程 @param connection 连接阶段 @param error 脱敏原因 @return 已更新的状态 */"""
        with self.lock:
            row = self.hosts.get(pid)
            if row and (row.get("connection"), row.get("error")) != (connection, error):
                row.update(connection=connection, error=error)
                self.revision += 1

    def public(self):
        """/** @return 适合面板与 AI 阅读的进程清单 */"""
        with self.lock:
            rows = []
            for found in self.discovered:
                pid = found["process_id"]
                row = self.hosts.get(pid)
                project = project_identity(found["project_root"])
                state = row.get("connection", "registered") if row else "discovered"
                if row and row["role"] == "editor" and self.selected.get(project) != pid:
                    state = "waiting_assignment"
                item = {"process_id": pid, "project": Path(project).name, "role": found.get("role", "editor"), "state": state}
                if row:
                    item["created"] = row["created"]
                    if row.get("batch"):
                        item["batch"] = row["batch"]
                    if row.get("error"):
                        item["code"] = row["error"]
                rows.append(item)
            return sorted(rows, key=lambda item: item["process_id"])


class RegistryGuard:
    """/** 资产宿主与独立测试使用登记簿维护实际归属 */"""

    def __init__(self, registry, project, process_id):
        """/** @param registry 进程登记簿 @param project 项目 @param process_id 资产宿主 @return 项目归属检查 */"""
        self.registry = registry
        self.project = project_identity(project)
        self.process_id = process_id
        self.lock = registry.lock
        self.tests = {}
        row = registry.hosts.get(process_id)
        self.created = row.get("created") if row else None

    def verify(self):
        """/** @return 派发边界实际进程与登记身份一致 */"""
        value = self.registry.identify(self.process_id)
        if value is None or value["created"] != self.created:
            raise RuntimeError("HOST_PROCESS_OFFLINE")

    def inspect(self, force=False):
        """/** @param force 调用边界标记 @return 当前归属证据 */"""
        with self.lock:
            selected = self.registry.selected.get(self.project)
            return {"verified": self.registry.error is None, "exclusive": selected == self.process_id,
                    "hosts": [row for row in self.registry.public() if row["process_id"] in self.registry.hosts and self.registry.hosts[row["process_id"]]["project"] == self.project]}

    def register_test(self, batch, process_id):
        """/** @param batch 测试归属 @param process_id 测试进程 @return 已登记的测试编号 */"""
        with self.lock:
            self.tests[batch] = process_id

    def release_test(self, batch):
        """/** @param batch 已退出测试 @return 已释放归属 */"""
        with self.lock:
            self.tests.pop(batch, None)


def project_key(project):
    """/** @param project 项目路径 @return 稳定路由身份 */"""
    return hashlib.sha256(project_identity(project).encode()).hexdigest()[:16]
