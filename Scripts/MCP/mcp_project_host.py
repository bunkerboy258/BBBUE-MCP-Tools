import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time


def project_identity(path):
    """
    /**
     * @param path\t项目目录或项目文件
     * @return 消除目录链接和大小写差异的项目身份
     */
    """
    value = Path(path).resolve()
    if value.suffix.lower() == ".uproject":
        value = value.parent
    return os.path.normcase(str(value))


def editor_inventory():
    """
    /**
     * @return 本机编辑器的项目身份 进程编号和公开端口
     */
    """
    command = "$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); @(Get-CimInstance Win32_Process -Filter \"Name = 'UnrealEditor.exe' OR Name LIKE 'python%.exe'\" | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("PROJECT_HOST_INSPECTION_FAILED")
    items = json.loads(result.stdout.decode("utf-8-sig") or "[]")
    if isinstance(items, dict):
        items = [items]
    hosts = []
    for item in items:
        command_line = item.get("CommandLine") or ""
        if "mcp_task_gateway.py" in command_line:
            root = re.search(r'--project-root\s+(?:"([^"\r\n]+)"|([^\s"]+))', command_line)
            port = re.search(r"--port\s+(\d+)(?:\s|$)", command_line)
            if root is not None:
                hosts.append({"kind": "gateway", "process_id": item["ProcessId"],
                    "project_root": project_identity(root.group(1) or root.group(2)),
                    "public_port": int(port.group(1)) if port else None})
            continue
        match = re.search(r'(?:"([^"\r\n]+\.uproject)"|([^\s"]+\.uproject))', command_line, re.I)
        if match is None:
            continue
        port = re.search(r"-BBBProtectedMcpPort=(\d+)(?:\s|$)", command_line, re.I)
        hosts.append({"kind": "editor", "process_id": item["ProcessId"], "project_root": project_identity(match.group(1) or match.group(2)),
            "public_port": int(port.group(1)) if port else None})
    return hosts


class ProjectHostGuard:
    """/** 一个项目的全部端口共用同一网关生命周期锁 */"""

    def __init__(self, project, process_id, inventory=editor_inventory):
        """
        /**
         * @param project\t原项目目录
         * @param process_id\t绑定的宿主进程
         * @param inventory\t只读进程查询
         * @return 项目宿主保护
         */
        """
        self.project = project_identity(project)
        self.process_id = process_id
        self.inventory = inventory
        self.lock = threading.Lock()
        self.observed_at = 0
        self.state = None
        self.handle = None
        self.kernel = None

    def acquire(self):
        """/** @return 在本网关生命周期内持有项目唯一锁 */"""
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        identity = hashlib.sha256(self.project.encode("utf-8")).hexdigest()
        handle = self.kernel.CreateMutexW(None, False, "Global\\BBBMcpProjectGateway_" + identity)
        if not handle:
            raise RuntimeError("PROJECT_GATEWAY_LOCK_FAILED")
        status = self.kernel.WaitForSingleObject(handle, 0)
        if status not in {0, 0x80}:
            self.kernel.CloseHandle(handle)
            raise RuntimeError("PROJECT_GATEWAY_ALREADY_RUNNING")
        self.handle = handle
        state = self.inspect(force=True)
        if state["verified"] is not True or state["exclusive"] is not True:
            self.close()
            raise RuntimeError("PROJECT_HOST_CONFLICT")

    def inspect(self, force=False):
        """
        /**
         * @param force\t立即刷新实际进程
         * @return 可公开的同项目宿主清单与核验状态
         */
        """
        with self.lock:
            if not force and self.state is not None and time.monotonic() - self.observed_at < 2:
                return dict(self.state)
            try:
                matching = [item for item in self.inventory() if project_identity(item["project_root"]) == self.project]
                hosts = [item for item in matching if item.get("kind", "editor") == "editor"]
                gateways = [item for item in matching if item.get("kind") == "gateway" and item["process_id"] != os.getpid()]
                self.state = {"verified": True, "exclusive": len(hosts) == 1 and hosts[0]["process_id"] == self.process_id and not gateways,
                    "hosts": hosts, "gateways": gateways, "gateway_lock_held": self.handle is not None,
                    "observed_at_unix": time.time()}
            except Exception:
                self.state = {"verified": False, "exclusive": False, "hosts": [],
                    "error_code": "PROJECT_HOST_INSPECTION_FAILED", "observed_at_unix": time.time()}
            self.observed_at = time.monotonic()
            return dict(self.state)

    def close(self):
        """/** @return 释放本网关持有的项目锁 */"""
        if self.handle is not None:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
