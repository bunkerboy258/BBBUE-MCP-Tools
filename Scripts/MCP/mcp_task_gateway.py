import argparse
import ast
import atexit
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BBBMcpCapabilities import ToolCatalog, TOOL_DOMAINS, EXTERNAL_QUERIES, validate_arguments, write_scope
from MCP.mcp_call import McpSession
from MCP.mcp_jobs import JobQueue, JobConflict
from MCP.mcp_asset_scope import asset_targets
from MCP.mcp_project_host import ProjectHostGuard, project_identity
from MCP.mcp_result import McpBusinessError
from MCP.mcp_test_hosts import ProjectJobs, TestHost, project_version


def public_tools():
    """/** @return 唯一公开工具目录 */"""
    schemas = [
        ("find_tools", "按目标搜索工具，返回最多八项", {"query": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 8}}, ["query"]),
        ("describe_tool", "读取一个工具的参数与权限", {"tool": {"type": "string"}}, ["tool"]),
        ("submit_batch", "提交有序操作，立即返回批次编号", {"operations": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool", "arguments"], "additionalProperties": False}}, "label": {"type": "string", "maxLength": 120}, "environment": {"type": "string", "enum": ["editor", "test"], "default": "editor"}, "test_host": {"type": "string", "pattern": "^[0-9a-f]{16}$"}, "test_options": {"type": "object", "properties": {"map": {"type": "string", "pattern": "^/(Game|Engine)/[A-Za-z0-9_/]+$"}, "rendering": {"type": "boolean"}, "audio": {"type": "boolean"}, "players": {"type": "integer", "minimum": 1, "maximum": 8}, "net_mode": {"type": "string", "enum": ["standalone", "listen", "client"]}}, "required": ["map"], "additionalProperties": False}}, ["operations"]),
        ("inspect_tasks", "读取占用与批次结果，支持按业务版本等待", {"batch": {"type": "string"}, "detail": {"type": "boolean"}, "after_revision": {"type": "integer", "minimum": 0}, "wait_seconds": {"type": "number", "minimum": 0, "maximum": 60}}, []),
        ("control_task", "取消、核实、恢复或关闭批次，空闲时退出宿主", {"action": {"type": "string", "enum": ["cancel", "review", "resume", "close", "shutdown_host"]}, "batch": {"type": "string"}, "confirmation": {"type": "string"}}, ["action"]),
    ]
    return [{"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}} for name, description, properties, required in schemas]


def annotation_schema(node):
    """/** @param node Python 类型 @return 参数类型 */"""
    if node is None:
        return {}
    if isinstance(node, ast.Name):
        name = node.id
        return {"type": {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "dict": "object", "list": "array"}.get(name)} if name in {"str", "int", "float", "bool", "dict", "list"} else {}
    if isinstance(node, ast.Subscript):
        name = ast.unparse(node.value).rsplit(".", 1)[-1].lower()
        if name == "optional":
            return {"anyOf": [annotation_schema(node.slice), {"type": "null"}]}
        values = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if name in {"union"}:
            return {"anyOf": [annotation_schema(value) for value in values]}
        if name in {"list", "sequence"}:
            return {"type": "array", "items": annotation_schema(values[0])}
        if name in {"dict", "mapping"}:
            return {"type": "object", "additionalProperties": annotation_schema(values[-1])}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return {"anyOf": [annotation_schema(node.left), annotation_schema(node.right)]}
    if isinstance(node, ast.Constant) and node.value is None:
        return {"type": "null"}
    return {}


class UnrealBackend:
    """/** 当前原项目官方后端 查询与执行分别复用私有连接 */"""

    def __init__(self, url, project, process_id):
        """/** @param url 私有端口 @param project 原项目 @param process_id 宿主编号 @return 后端 */"""
        self.url = url
        self.project = project_identity(project)
        self.process_id = process_id
        self.guard = None
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.names = None
        self.task_name = None
        self.external_name = None
        self.remap = False

    def _call(self, name, arguments):
        inspection = name != "call_tool" or arguments.get("tool_name") in {"inspect_editor_activity", "inspect_saved_test_inputs"}
        channel = "inspection" if inspection else "operations"
        with self.session_lock:
            session = self.sessions.get(channel)
            if session is None:
                session = McpSession(self.url, 30 if inspection else 600, private_backend=True)
                self.sessions[channel] = session
        return session.request(name, arguments)

    def _toolsets(self):
        if self.names is None:
            value = self._call("list_toolsets", {})
            self.names = sorted(set(re.findall(r"(?m)^- ([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)(?=[:\s]|$)", value)))
            tasks = []
            external = []
            for name in self.names:
                definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", name.rsplit(".", 1)[-1])
                if definition == "BBBMcpTaskToolset":
                    tasks.append(name)
                if definition == "BBBExternalToolset":
                    external.append(name)
            if len(tasks) != 1 or len(external) != 1:
                raise RuntimeError("ACTIVITY_TOOL_REQUIRED")
            self.task_name = tasks[0]
            self.external_name = external[0]
        return self.names

    def descriptors(self):
        """/** @return 注册工具参数 */"""
        for name in self._toolsets():
            definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", name.rsplit(".", 1)[-1])
            known = definition in TOOL_DOMAINS or not definition.startswith("BBB")
            if known and definition not in {"BBBExternalToolset", "ProgrammaticToolset"}:
                value = self._call("describe_toolset", {"toolset_name": name})
                if isinstance(value, str):
                    value = json.loads(value)
                yield name, value["tools"]

    def external_contracts(self):
        """/** @return 第三方动作的明确参数契约 */"""
        if self.external_name is None:
            return
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "BBBExternalToolset.py").read_text(encoding="utf-8-sig"))
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"_DOMAIN_MODULES", "_DOMAIN_ACTIONS"}}
        for domain, actions in values["_DOMAIN_ACTIONS"].items():
            source = ast.parse((root / "MCP" / "ThirdParty" / "GenOrca" / (values["_DOMAIN_MODULES"][domain] + ".py")).read_text(encoding="utf-8-sig"))
            functions = {node.name: node for node in source.body if isinstance(node, ast.FunctionDef)}
            for action in sorted(actions):
                if action in {"execute_console_command", "save_all_dirty", "get_open_assets", "save_all_levels"}:
                    continue
                function = functions["ue_" + action]
                parameters = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
                default_start = len(function.args.args) - len(function.args.defaults)
                for index, argument in enumerate(function.args.args):
                    field = annotation_schema(argument.annotation)
                    if index < default_start:
                        parameters["required"].append(argument.arg)
                    if index >= default_start:
                        field["default"] = ast.literal_eval(function.args.defaults[index - default_start])
                        if field["default"] is None and field:
                            field = {"anyOf": [field, {"type": "null"}], "default": None}
                    parameters["properties"][argument.arg] = field
                access = "read" if action in EXTERNAL_QUERIES.get(domain, set()) else "write"
                world = "any" if access == "read" else "editor"
                if action in {"start_pie", "stop_pie"}:
                    access, world = "pie", "any"
                description = ast.get_docstring(function) or action
                yield {"id": "external." + domain + "." + action, "toolset": self.external_name, "name": domain, "action": action, "definition": "BBBExternalToolset", "parameters": parameters, "summary": description.strip().split("\n")[0][:100], "access": access, "world": world}

    def probe(self):
        """/** @return 实际宿主证据 */"""
        self._toolsets()
        value = self._call("call_tool", {"toolset_name": self.task_name, "tool_name": "inspect_editor_activity", "arguments": {}})
        if value["process_id"] != self.process_id or project_identity(value["project_root"]) != self.project:
            raise RuntimeError("HOST_IDENTITY_CHANGED")
        if self.guard is not None:
            value["project_hosts"] = self.guard.inspect()
        return value

    def invoke(self, contract, arguments):
        """/** @param contract 目录项 @param arguments 核验后的参数 @return 业务结果 */"""
        toolset = contract["toolset"]
        if self.remap:
            self._toolsets()
            candidates = [name for name in self.names if re.sub(r"_0x[0-9a-fA-F]{8}$", "", name.rsplit(".", 1)[-1]) == contract["definition"]]
            if len(candidates) != 1:
                raise McpBusinessError({"execution": {"state": "rejected"}, "code": "TEST_TOOLSET_IDENTITY"})
            toolset = candidates[0]
        if not contract["definition"].startswith("BBB") and contract["access"] == "write" and contract["world"] != "pie":
            targets, scoped = write_scope(contract, arguments)
            references = targets or arguments
            self._call("call_tool", {"toolset_name": self.task_name, "tool_name": "check_asset_write", "arguments": {"object_paths": sorted(asset_targets(references, normalize=False))}})
        if contract.get("action"):
            arguments = {"action": contract["action"], "params_json": json.dumps(arguments, ensure_ascii=False)}
        return self._call("call_tool", {"toolset_name": toolset, "tool_name": contract["name"], "arguments": arguments})

    def shutdown(self):
        """/** @return 正式请求空闲宿主退出 */"""
        self._call("call_tool", {"toolset_name": self.external_name, "tool_name": "util", "arguments": {"action": "execute_console_command", "params_json": json.dumps({"command": "QUIT_EDITOR"})}})

    def close(self):
        """/** @return 关闭本后端连接 */"""
        for session in self.sessions.values():
            session.close()


class TaskGateway:
    """/** 五入口公开协议 */"""

    def __init__(self, backend, catalog=None, start_worker=True, test_factory=None, version=None, test_limit=2, test_output_root=None):
        """/** @param backend 官方后端 @param catalog 测试目录 @param start_worker 启动执行循环 @return 网关 */"""
        self.catalog = catalog or ToolCatalog(backend)
        self.jobs = ProjectJobs(JobQueue(backend, self.catalog, start_worker=start_worker), test_factory, version, test_limit, test_output_root)
        self.sessions = {}
        self.lock = threading.Lock()
        self.tools = {item["name"]: item for item in public_tools()}

    def handle(self, method, headers, body):
        """/** @param method HTTP 方法 @param headers 会话头 @param body 请求 @return 状态 头 响应 */"""
        session_id = headers.get("Mcp-Session-Id")
        if method == "DELETE":
            with self.lock:
                self.sessions.pop(session_id, None)
            return 204, {}, None
        request_id = body.get("id")
        response_headers = {}
        def reply(value, error=False):
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return 200, response_headers, {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": error}}
        try:
            if body.get("jsonrpc") != "2.0":
                raise ValueError("JSONRPC_VERSION")
            parameters = body.get("params", {})
            if body.get("method") == "initialize":
                client = self.jobs.connect(parameters.get("_meta", {}).get("bbb/client_key"))
                session_id = secrets.token_urlsafe(24)
                with self.lock:
                    self.sessions[session_id] = client
                response_headers["Mcp-Session-Id"] = session_id
                return 200, response_headers, {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "BBB-MCP", "version": "2"}, "_meta": {"bbb/client_key": client}}}
            with self.lock:
                client = self.sessions.get(session_id)
            if client is None:
                return 404, {}, {"error": "SESSION_REQUIRED"}
            self.jobs.touch(client)
            if body.get("method") == "notifications/initialized":
                return 202, {}, None
            if body.get("method") == "ping":
                return 200, {}, {"jsonrpc": "2.0", "id": request_id, "result": {}}
            if body.get("method") == "tools/list":
                return 200, {}, {"jsonrpc": "2.0", "id": request_id, "result": {"tools": list(self.tools.values())}}
            if body.get("method") != "tools/call":
                raise ValueError("METHOD_UNKNOWN")
            name = parameters["name"]
            arguments = parameters.get("arguments", {})
            if name not in self.tools:
                raise ValueError("TOOL_UNKNOWN")
            validate_arguments(arguments, self.tools[name]["inputSchema"])
            if name == "find_tools":
                return reply(self.catalog.find(**arguments))
            if name == "describe_tool":
                return reply(self.catalog.describe(arguments["tool"]))
            if name == "submit_batch":
                return reply(self.jobs.submit(client, **arguments))
            if name == "inspect_tasks":
                return reply(self.jobs.inspect(client, **arguments))
            return reply(self.jobs.control(client, **arguments))
        except McpBusinessError as error:
            return reply(error.value, True)
        except (ValueError, KeyError, TypeError) as error:
            return reply({"status": "rejected", "code": "ARGUMENT_INVALID", "details": str(error)}, True)
        except Exception:
            return reply({"status": "review", "code": "HOST_UNVERIFIED", "next": "inspect_tasks"}, True)


def make_server(gateway, host, port):
    """/** @param gateway 网关 @param host 本机地址 @param port 公开端口 @return HTTP 服务 */"""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("LOCALHOST_REQUIRED")
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.dispatch()
        def do_DELETE(self):
            self.dispatch()
        def dispatch(self):
            if self.path != "/mcp" or self.headers.get("Origin"):
                self.send_error(403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1048576:
                self.send_error(413)
                return
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body, dict):
                    raise ValueError("REQUEST_OBJECT")
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            status, headers, value = gateway.handle(self.command, self.headers, body)
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if value is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, format, *arguments):
            pass
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    """/** @return 启动原项目唯一网关 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host-pid", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--editor-path", required=True)
    parser.add_argument("--project-file", required=True)
    parser.add_argument("--test-hosts", type=int, choices=(1, 2), default=2)
    arguments = parser.parse_args()
    project_file = Path(arguments.project_file).resolve()
    editor_path = Path(arguments.editor_path).resolve()
    if project_identity(project_file) != project_identity(arguments.project_root) or not project_file.is_file() or project_file.suffix.lower() != ".uproject" or editor_path.name != "UnrealEditor.exe" or not editor_path.is_file():
        raise ValueError("TEST_HOST_PATH_IDENTITY")
    private = urlparse(arguments.backend_url)
    if private.hostname not in {"127.0.0.1", "localhost"} or re.fullmatch(r"/bbb-mcp-[0-9a-f]{32}", private.path) is None or private.port == arguments.port:
        raise ValueError("PRIVATE_BACKEND_REQUIRED")
    guard = ProjectHostGuard(arguments.project_root, arguments.host_pid)
    guard.acquire()
    atexit.register(guard.close)
    backend = UnrealBackend(arguments.backend_url, arguments.project_root, arguments.host_pid)
    backend.guard = guard
    def factory(batch, options):
        return TestHost(batch, options, project_file, editor_path, guard, UnrealBackend)
    def version(record):
        if "input_files" not in record:
            paths = sorted({record["options"]["map"]} | asset_targets(record["operations"]))
            backend._toolsets()
            record["input_files"] = backend._call("call_tool", {"toolset_name": backend.task_name,
                "tool_name": "inspect_saved_test_inputs", "arguments": {"asset_paths": paths}})["files"]
        return project_version(arguments.project_root, record["input_files"])
    gateway = TaskGateway(backend, test_factory=factory, version=version, test_limit=arguments.test_hosts,
        test_output_root=project_file.parent / "Saved" / "temp" / "McpTests")
    atexit.register(backend.close)
    atexit.register(gateway.jobs.close)
    server = make_server(gateway, arguments.host, arguments.port)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, arguments.host_pid)
    if not handle:
        raise RuntimeError("HOST_PROCESS_REQUIRED")
    def watch():
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        gateway.jobs.close()
        server.shutdown()
    threading.Thread(target=watch, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
