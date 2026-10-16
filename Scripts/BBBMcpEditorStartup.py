import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from urllib.request import build_opener, ProxyHandler

import unreal

from MCP.mcp_host_registry import publish_host, write_host


_startup = None


def _argument(command, name, default):
    """/** @param command 启动参数 @param name 参数名称 @param default 默认值 @return 完整参数值 */"""
    match = re.search(r'(?:^|\s)-' + re.escape(name) + r'=(?:"([^"\r\n]+)"|([^\s"]+))', command, re.I)
    if match is not None:
        return match.group(1) or match.group(2)
    return default


def _port_available(port):
    """/** @param port 需要核验的本机端口 @return 当前可绑定的端口 */"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
        return probe.getsockname()[1]


def _heartbeat(state):
    """/** @param state 本次编辑器接入状态 @return 持续登记并在服务恢复后重新接入 */"""
    opener = build_opener(ProxyHandler({}))
    delay = 2
    while True:
        try:
            write_host(state["registration"])
            try:
                with opener.open(state["endpoint"].replace("/mcp", "/health"), timeout=2) as response:
                    health = json.load(response)
                if health.get("service") != "BBB-MCP" or health.get("protocol") != 6:
                    raise RuntimeError("SERVICE_HANDOVER_REQUIRED")
            except Exception:
                command = [state["python"], "-B", str(Path(__file__).parent / "MCP/mcp_service.py"),
                           "--ensure", "--project-file", state["registration"]["project_file"], "--port", str(state["port"])]
                result = subprocess.run(command, capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError("SERVICE_START_FAILED")
            state["status"] = "registered"
            state["error"] = None
            delay = 5
        except Exception as error:
            state["status"] = "reconnecting"
            state["error"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            delay = min(30, delay * 2)
        time.sleep(delay)


def _report_state(delta):
    """/** @param delta 编辑器帧间隔 @return 在主线程报告接入状态变化 */"""
    state = _startup
    signature = (state["status"], state.get("error"))
    if signature == state.get("reported"):
        return
    state["reported"] = signature
    message = "[BBBMcpEditorStartup]PID {} {} {}".format(os.getpid(), state["status"], state.get("error") or state["endpoint"])
    if state.get("error"):
        unreal.log_warning(message)
        return
    unreal.log(message)


def start_editor_mcp():
    """
    /**
     * 将正常打开的编辑器登记到独立常驻服务
     * @return 当前接入状态 测试宿主由所属调度登记
     */
    """
    global _startup
    command = unreal.SystemLibrary.get_command_line()
    role = _argument(command, "BBBMcpHostRole", "editor").lower()
    if role == "test" or os.environ.get("BBB_MCP_HOST_ROLE") == "test" or _argument(command, "run", None) is not None:
        return {"status": "skipped"}
    if _startup is not None:
        return {"status": _startup["status"], "endpoint": _startup["endpoint"]}
    if not hasattr(unreal, "BBBMcpEditorStartupLibrary"):
        raise RuntimeError("MCP_STARTUP_NATIVE_LIBRARY_REQUIRED")
    identity = json.loads(unreal.BBBMcpEditorStartupLibrary.inspect_private_backend())
    if identity.get("commandlet"):
        return {"status": "skipped"}
    if identity["process_id"] != os.getpid():
        raise RuntimeError("MCP_STARTUP_PROCESS_IDENTITY")
    project_file = Path(identity["project_file"]).resolve()
    editor = Path(identity["editor_path"]).resolve()
    if not project_file.is_file() or project_file.suffix.lower() != ".uproject" or not editor.is_file() or editor.name != "UnrealEditor.exe":
        raise RuntimeError("MCP_STARTUP_PROJECT_IDENTITY")
    port = int(_argument(command, "BBBMcpServicePort", "8000"))
    if not 1 <= port <= 65535:
        raise RuntimeError("MCP_STARTUP_OPTIONS")
    python = _argument(command, "BBBMcpServicePython", shutil.which("python"))
    if not python or not Path(python).is_file():
        raise RuntimeError("MCP_STARTUP_RUNTIME_REQUIRED")
    key = secrets.token_hex(16)
    backend_port = _port_available(0)
    backend = json.loads(unreal.BBBMcpEditorStartupLibrary.start_private_backend(backend_port, key))
    if not backend.get("success") or not backend.get("owned") or not backend.get("running"):
        raise RuntimeError(backend.get("error", "MCP_STARTUP_BACKEND_FAILED"))
    registration = publish_host(project_file, backend["backend_url"])
    _startup = {"status": "starting", "endpoint": "http://127.0.0.1:{}/mcp".format(port),
                "port": port, "python": str(Path(python).resolve()), "registration": registration}
    _startup["tick"] = unreal.register_slate_post_tick_callback(_report_state)
    threading.Thread(target=_heartbeat, args=(_startup,), daemon=True, name="BBB-MCP-registration").start()
    unreal.log("[BBBMcpEditorStartup]登记开始 PID {}".format(os.getpid()))
    return {"status": "starting", "endpoint": _startup["endpoint"]}
