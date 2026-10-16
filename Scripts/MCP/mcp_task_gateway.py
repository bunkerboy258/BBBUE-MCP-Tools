import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from urllib.parse import urlparse

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BBBMcpCapabilities import ToolCatalog, TOOL_DOMAINS, validate_arguments, write_scope
from MCP.mcp_contracts import TOOL_POLICIES, backend_arguments
from MCP.mcp_call import McpSession
from MCP.mcp_jobs import JobQueue, JobConflict
from MCP.mcp_response import response, argument_failure, next_call
from MCP.mcp_asset_scope import asset_targets
from MCP.mcp_project_host import project_identity
from MCP.mcp_test_hosts import ProjectJobs
from MCP.mcp_result import McpBusinessError, public_value, requested_values_match, property_schema, native_property_values


def public_tools():
    """/** @return 唯一公开工具目录 */"""
    schemas = [
        ("manage_operator", "登记单行任务 更新等级或结束逻辑会话 默认2级", {"action": {"type": "string", "enum": ["join", "update", "finish"], "default": "join"}, "task": {"type": "string", "minLength": 1, "maxLength": 20}, "level": {"type": "integer", "enum": [0, 1, 2]}, "operator": {"type": "string"}}, []),
        ("find_tools", "按中英文目标搜索 最多三项 首项包含调用参数", {"query": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3}}, ["query"]),
        ("describe_tool", "读取一个工具的参数与权限", {"tool": {"type": "string"}}, ["tool"]),
        ("submit_batch", "执行有序操作 短调用直接返回结果 长调用返回批次和下一步", {"operations": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool", "arguments"], "additionalProperties": False}}, "await_seconds": {"type": "number", "minimum": 0, "maximum": 10, "default": 2}, "label": {"type": "string", "maxLength": 120}, "environment": {"type": "string", "enum": ["editor", "test"], "default": "editor"}, "test_host": {"type": "string", "pattern": "^[0-9a-f]{16}$"}, "test_options": {"type": "object", "properties": {"map": {"type": "string", "pattern": "^/(Game|Engine)/[A-Za-z0-9_/]+$"}, "rendering": {"type": "boolean"}, "scene_performance": {"type": "boolean"}, "audio": {"type": "boolean"}, "players": {"type": "integer", "minimum": 1, "maximum": 8}, "net_mode": {"type": "string", "enum": ["standalone", "listen", "client"]}}, "required": ["map"], "additionalProperties": False}}, ["operations"]),
        ("inspect_tasks", "读取占用与批次结果 operators=true展开干员池", {"batch": {"type": "string"}, "detail": {"type": "boolean"}, "operators": {"type": "boolean"}, "after_revision": {"type": "integer", "minimum": 0}, "wait_seconds": {"type": "number", "minimum": 0, "maximum": 60}}, []),
        ("control_task", "批次收尾 0级可暂停干员 取消阻塞批次或定向终止UE", {"action": {"type": "string", "enum": ["cancel", "close", "shutdown_host", "pause_operator", "resume_operator", "cancel_blocker", "terminate_host"]}, "batch": {"type": "string", "description": "cancel close cancel_blocker 的目标批次"}, "operator": {"type": "string", "description": "pause_operator resume_operator 的干员ID"}, "lease_seconds": {"type": "number", "minimum": 1, "maximum": 300, "default": 60}, "host": {"type": "string", "description": "terminate_host 使用 inspect_tasks.hosts.id"}}, ["action"]),
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
        if self.guard is not None and hasattr(self.guard, "verify"):
            self.guard.verify()
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
                access = TOOL_POLICIES.get("external." + domain + "." + action, {}).get("access", "write")
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
        if contract["id"].startswith("blueprint.") and contract["access"] == "write" and arguments.get("graph_path"):
            request = arguments.get("annotations", arguments.get("request", {}))
            expected = arguments.get("expected_snapshot") or (request.get("expectedSnapshot") if isinstance(request, dict) else None)
            inspector = self.catalog.tools.get("blueprint.inspect_blueprint_graph")
            if expected and inspector is not None:
                path = arguments["graph_path"]
                current = self.invoke(inspector, {"graph_path": path, "view": "overview"})
                if current["snapshot"] != expected:
                    raise McpBusinessError({"status": "rejected", "code": "GRAPH_SNAPSHOT_CHANGED", "execution": {"state": "rejected"},
                        "needs": [{"path": "/arguments", "rule": "按当前图表重新核实节点范围与修改方案"}],
                        "next": next_call("submit_batch", operations=[{"tool": inspector["id"], "arguments": {"graph_path": path, "view": "logic"}}])})
        if self.remap:
            self._toolsets()
            candidates = [name for name in self.names if re.sub(r"_0x[0-9a-fA-F]{8}$", "", name.rsplit(".", 1)[-1]) == contract["definition"]]
            if len(candidates) != 1:
                raise McpBusinessError({"execution": {"state": "rejected"}, "code": "TEST_TOOLSET_IDENTITY"})
            toolset = candidates[0]
        if (not contract["definition"].startswith("BBB") or contract.get("action")) and contract["access"] == "write" and contract["world"] != "pie" and contract.get("scope", {}).get("kind") != "session":
            targets, scoped = write_scope(contract, arguments)
            references = targets or arguments
            self._call("call_tool", {"toolset_name": self.task_name, "tool_name": "check_asset_write", "arguments": {"object_paths": sorted(asset_targets(references, normalize=False))}})
        requested = arguments if contract["id"] == "object.set_properties" else None
        if contract["id"] == "editor.create_asset_with_factory" and arguments.get("factory_properties"):
            properties = self._property_definitions(arguments["factory_class_path"])
            try:
                validate_arguments(arguments["factory_properties"], {"type": "object", "properties": property_schema(properties), "additionalProperties": False}, "/arguments/factory_properties")
            except ValueError as error:
                details = str(error)
                raise McpBusinessError({**argument_failure(details, {"type": "object", "properties": property_schema(properties)}, contract["id"], prefix="/arguments/factory_properties"), "execution": {"state": "rejected"}}) from error
            arguments = copy.deepcopy(arguments)
            arguments["factory_properties"] = native_property_values(arguments["factory_properties"], {"properties": properties})
        if requested is not None:
            properties = self._property_definitions(requested["instance"])
            try:
                validate_arguments(requested["values"], {"type": "object", "properties": property_schema(properties), "additionalProperties": False}, "/arguments/values")
            except ValueError as error:
                details = str(error)
                raise McpBusinessError({**argument_failure(details, {"type": "object", "properties": property_schema(properties)}, contract["id"], prefix="/arguments/values"), "execution": {"state": "rejected"}}) from error
            arguments = copy.deepcopy(arguments)
            arguments["values"] = native_property_values(requested["values"], {"properties": properties})
        if contract["id"] == "object.list_properties":
            properties = property_schema(self._property_definitions(arguments["instance"]))
            version = hashlib.sha256(json.dumps(properties, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
            offset = arguments.get("offset", 0)
            if (offset and not arguments.get("expected_version")) or (arguments.get("expected_version") and arguments["expected_version"] != version):
                refreshed = {**arguments, "offset": 0, "expected_version": ""}
                raise McpBusinessError({"execution": {"state": "rejected"}, "code": "PROPERTY_SCHEMA_CHANGED", "next": next_call("submit_batch", operations=[{"tool": contract["id"], "arguments": refreshed}])})
            query = re.sub(r"[^a-z0-9]", "", arguments.get("query", "").casefold())
            names = sorted(name for name in properties if query in re.sub(r"[^a-z0-9]", "", name.casefold()))
            page = names[offset:offset + arguments.get("limit", 24)]
            view = {"properties": {name: properties[name] for name in page}, "total": len(names), "version": version}
            if offset + len(page) < len(names):
                view["next_page"] = {"offset": offset + len(page), "expected_version": version}
            return view
        if contract.get("action"):
            arguments = {"action": contract["action"], "params_json": json.dumps(arguments, ensure_ascii=False)}
        if not contract.get("action"):
            arguments = backend_arguments(contract, arguments)
        result = self._call("call_tool", {"toolset_name": toolset, "tool_name": contract["name"], "arguments": arguments})
        if requested is not None:
            current = self.invoke(self.catalog.tools["object.get_properties"], {"instance": requested["instance"], "properties": list(requested["values"])})
            if not requested_values_match(public_value(requested["values"]), public_value(current)):
                raise McpBusinessError({"execution": {"state": "partial"}, "code": "PROPERTY_READBACK_MISMATCH", "next": None})
        return result

    def _property_definitions(self, instance):
        """/** @param instance\t对象或类路径 @return 当前反射字段的原生定义 */"""
        contract = self.catalog.tools["object.list_properties"]
        return self._call("call_tool", {"toolset_name": contract["toolset"], "tool_name": contract["name"], "arguments": backend_arguments(contract, {"instance": instance})})

    def shutdown(self):
        """/** @return 正式请求空闲宿主退出 */"""
        self._call("call_tool", {"toolset_name": self.external_name, "tool_name": "util", "arguments": {"action": "execute_console_command", "params_json": json.dumps({"command": "QUIT_EDITOR"})}})

    def finalize(self, packages):
        """/** @param packages	本批次自有包 @return 逐包编译 保存 回读与失败证据 */"""
        inspector = self.catalog.tools["editor.inspect_asset_properties"]
        proof = {"saved": [], "compiled": [], "failures": [], "readback": True}
        for package in sorted(packages):
            try:
                before = self.invoke(inspector, {"asset_paths": [package], "property_names": []})["assets"][0]
                if before["classPath"].endswith((".Blueprint", ".AnimBlueprint", ".ControlRigBlueprint")):
                    status = self.invoke(inspector, {"asset_paths": [package], "property_names": ["status"]})["assets"][0]
                    if status["propertyErrors"] or "BS_UP_TO_DATE" not in str(status["properties"].get("status", "")):
                        self.invoke(self.catalog.tools["blueprint_base.compile_blueprint"], {"blueprint": package, "warnings_as_errors": False})
                        proof["compiled"].append(package)
                        status = self.invoke(inspector, {"asset_paths": [package], "property_names": ["status"]})["assets"][0]
                    if status["propertyErrors"] or "BS_UP_TO_DATE" not in str(status["properties"].get("status", "")):
                        raise McpBusinessError({"code": "COMPILE_VALIDATION_FAILED", "asset": package})
                self.invoke(self.catalog.tools["editor.resave_asset"], {"asset_path": package})
                after = self.invoke(inspector, {"asset_paths": [package], "property_names": []})["assets"][0]
                if after["assetPath"] != before["assetPath"]:
                    raise McpBusinessError({"code": "SAVE_READBACK_CHANGED", "asset": package})
                proof["saved"].append(package)
            except Exception as error:
                evidence = copy.deepcopy(error.value) if isinstance(error, McpBusinessError) else {"error": str(error)}
                proof["failures"].append({"package": package, "failure": evidence})
                proof["readback"] = False
        return proof

    def expand_scope(self, operation):
        """/** @param operation\t引用改写操作 @return 磁盘及内存引用者的写入范围 */"""
        if not operation["contract"].get("scope", {}).get("referencers"):
            return set()
        packages = set()
        content = Path(self.project) / "Content"
        for target in asset_targets(operation["targets"]):
            directory = content / target.removeprefix("/Game/")
            if directory.is_dir():
                packages.update("/Game/" + path.relative_to(content).with_suffix("").as_posix()
                    for path in directory.rglob("*") if path.suffix in {".uasset", ".umap"})
            if not directory.is_dir():
                packages.add(target)
        if len(packages) > 5000:
            raise JobConflict("ASSET_SCOPE_TOO_LARGE", {"next": None})
        if not packages:
            return set()
        result = self.invoke(self.catalog.tools["assets.inspect_asset_packages"], {"asset_paths": sorted(packages), "include_soft_referencers": True})
        return asset_targets([row[key] for row in result["packages"] for key in ("referencers", "soft_referencers")])

    def reconcile(self, packages):
        """/** @param packages	待核实包或目录 @return 当前磁盘与可加载资产证据 保留原操作的不确定结果 */"""
        evidence = []
        content = Path(self.project) / "Content"
        for package in packages:
            base = content / package.removeprefix("/Game/")
            files = [base.with_suffix(extension) for extension in (".uasset", ".umap") if base.with_suffix(extension).is_file()]
            if base.is_dir():
                files = sorted(path for path in base.rglob("*") if path.suffix in {".uasset", ".umap"})
            if len(files) > 256:
                raise McpBusinessError({"code": "RECOVERY_SCOPE_TOO_LARGE", "package": package})
            assets = []
            for file in files:
                if file.is_symlink() or not file.resolve().is_relative_to(content.resolve()):
                    raise McpBusinessError({"code": "RECOVERY_PATH_INVALID", "package": package})
                asset_path = "/Game/" + file.relative_to(content).with_suffix("").as_posix()
                asset = self.invoke(self.catalog.tools["editor.inspect_asset_properties"], {"asset_paths": [asset_path], "property_names": []})["assets"][0]
                if asset["classPath"].endswith((".Blueprint", ".AnimBlueprint", ".ControlRigBlueprint")):
                    status = self.invoke(self.catalog.tools["editor.inspect_asset_properties"], {"asset_paths": [asset_path], "property_names": ["status"]})["assets"][0]
                    if status["propertyErrors"] or "BS_UP_TO_DATE" not in str(status["properties"].get("status", "")):
                        raise McpBusinessError({"code": "COMPILE_VALIDATION_FAILED", "asset": asset_path})
                assets.append({"asset": asset, "size": file.stat().st_size, "mtime_ns": file.stat().st_mtime_ns})
            evidence.append({"package": package, "assets": assets, "exists_on_disk": bool(files)})
        return {"observed": evidence, "operation_replayed": False}

    def close(self):
        """/** @return 关闭本后端连接 */"""
        with self.session_lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()


class TaskGateway:
    """/** 五入口公开协议 */"""

    def __init__(self, backend, catalog=None, start_worker=True, test_factory=None, version=None, test_limit=2, test_output_root=None, clients=None, test_restore=None):
        """/** @param backend 官方后端 @param catalog 测试目录 @param start_worker 启动执行循环 @return 网关 */"""
        self.catalog = catalog or ToolCatalog(backend)
        backend.catalog = self.catalog
        state_path = Path(backend.project) / "Saved" / "McpState" / "gateway.sqlite" if hasattr(backend, "project") else None
        self.jobs = ProjectJobs(JobQueue(backend, self.catalog, start_worker=start_worker, state_path=state_path, clients=clients), test_factory, version, test_limit, test_output_root, test_restore)
        self.clients = self.jobs.editor.clients
        self.tools = {item["name"]: item for item in public_tools()}

    def handle(self, method, headers, body):
        """/** @param method HTTP 方法 @param headers 会话头 @param body 请求 @return 状态 头 响应 */"""
        session_id = headers.get("Mcp-Session-Id")
        if method == "DELETE":
            self.clients.unbind(session_id)
            return 204, {}, None
        request_id = body.get("id")
        response_headers = {}
        def reply(value, error=False):
            text = json.dumps(response(value), ensure_ascii=False, separators=(",", ":"))
            return 200, response_headers, {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": error, "_meta": {"bbb/catalog_version": self.catalog.version()}}}
        try:
            if body.get("jsonrpc") != "2.0":
                raise ValueError("JSONRPC_VERSION")
            parameters = body.get("params", {})
            if not isinstance(parameters, dict):
                parameters = {}
                raise ValueError("/params: expected object")
            self.clients.operators.collect()
            if body.get("method") == "initialize":
                resume_key = parameters.get("_meta", {}).get("bbb/client_key")
                recovered = self.clients.known(resume_key)
                client = self.jobs.connect(resume_key)
                operator = None
                registration = parameters.get("_meta", {}).get("bbb/operator")
                if registration is not None:
                    validate_arguments(registration, {"type": "object", "properties": {"task": {"type": "string", "minLength": 1, "maxLength": 20}, "level": {"type": "integer", "enum": [0, 1, 2]}}, "required": ["task"], "additionalProperties": False})
                    operator = self.clients.operators.manage(client, **registration)
                if registration is None:
                    with self.clients.condition:
                        owner = self.clients.operators.owner(client)
                        row = self.clients.operators.rows.get(owner)
                        if row is not None and not row.get("ended"):
                            operator = self.clients.operators.view(owner)
                session_id = self.clients.bind(client)
                response_headers["Mcp-Session-Id"] = session_id
                return 200, response_headers, {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "BBB-MCP", "version": "6"}, "_meta": {"bbb/client_key": client, "bbb/client_recovered": recovered, "bbb/catalog_version": self.catalog.version(), "bbb/operator": operator}}}
            client = self.clients.resolve(session_id)
            if client is None:
                return 404, {}, {"error": "SESSION_REQUIRED"}
            if body.get("method") == "ping":
                self.clients.touch(client, operator=False)
            if body.get("method") != "ping":
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
            if name == "control_task":
                required = {"cancel": "batch", "close": "batch", "cancel_blocker": "batch", "pause_operator": "operator", "resume_operator": "operator", "terminate_host": "host"}.get(arguments["action"])
                if required is not None and not arguments.get(required):
                    raise ValueError("/arguments/" + required + ": required")
            if name == "manage_operator":
                identity = parameters.get("_meta", {}).get("bbb/request_id", session_id + ":" + str(request_id))
                value = self.clients.replay(client, identity, {"name": name, "arguments": arguments}, lambda: self.clients.operators.manage(client, **arguments))
                self.jobs.wake()
                return reply(value)
            if name == "find_tools":
                return reply(self.catalog.find(**arguments))
            if name == "describe_tool":
                return reply(self.tools[arguments["tool"]] if arguments["tool"] in self.tools else self.catalog.describe(arguments["tool"]))
            if name == "submit_batch":
                self.clients.operators.require(client)
                identity = parameters.get("_meta", {}).get("bbb/request_id", session_id + ":" + str(request_id))
                return reply(self.clients.replay(client, identity, {"name": name, "arguments": arguments}, lambda: self.submit(client, **arguments)))
            if name == "inspect_tasks":
                arguments = dict(arguments)
                include_pool = arguments.pop("operators", False)
                value = self.jobs.inspect(client, **arguments)
                if include_pool:
                    value["operators"] = self.clients.operators.snapshot(self.jobs.operator_jobs(), 256)
                return reply(value)
            identity = parameters.get("_meta", {}).get("bbb/request_id", session_id + ":" + str(request_id))
            return reply(self.clients.replay(client, identity, {"name": name, "arguments": arguments}, lambda: self.jobs.control(client, **arguments)))
        except McpBusinessError as error:
            value = copy.deepcopy(error.value)
            return reply(value, True)
        except (ValueError, KeyError, TypeError) as error:
            details = str(error)
            return reply(self._argument_failure(parameters, details), True)
        except Exception:
            return reply({"status": "failed", "code": "HOST_UNVERIFIED", "next": None}, True)

    def _argument_failure(self, parameters, details):
        """/** @param parameters	原始调用 @param details	校验原因 @return 可重放的完整补参证据 */"""
        target = parameters.get("name", "initialize")
        schema = self.tools.get(target, {}).get("inputSchema", {})
        unknown = re.match(r"/operations/(\d+)/tool: unknown tool", details)
        if target == "submit_batch" and unknown:
            index = int(unknown.group(1))
            identity = parameters["arguments"]["operations"][index]["tool"]
            return {"status": "rejected", "code": "TOOL_UNKNOWN", "operation": index, "tool": identity,
                    "next": next_call("find_tools", query=identity.replace(".", " ").replace("_", " "))}
        if details == "TOOL_UNKNOWN":
            return {"status": "rejected", "code": "TOOL_UNKNOWN", "needs": [{"path": "/params/name", "schema": {"enum": sorted(self.tools)}}], "next": None}
        match = re.match(r"/operations/(\d+)/arguments", details)
        if target == "submit_batch" and match:
            index = int(match.group(1))
            operations = parameters.get("arguments", {}).get("operations", [])
            if index < len(operations):
                target = operations[index].get("tool", target)
                schema = self.catalog.tools.get(target, {}).get("parameters", {})
        return argument_failure(details, schema, target)

    def submit(self, client, operations, label="", environment="editor", test_options=None, test_host=None, await_seconds=2):
        """/** @param client\t客户端 @param operations\t有序操作 @param label\t用途 @param environment\t宿主类别 @param test_options\t测试配置 @param test_host\t所属测试宿主 @param await_seconds\t短等待时间 @return 执行结果或唯一继续动作 */"""
        try:
            accepted = self.jobs.submit(client, operations, label, environment, test_options, test_host)
        except ValueError as error:
            raise McpBusinessError(self._argument_failure({"name": "submit_batch", "arguments": {"operations": operations}}, str(error))) from error
        if not await_seconds:
            return accepted
        deadline = time.monotonic() + await_seconds
        view = accepted
        while view["status"] in {"queued", "running"} and time.monotonic() < deadline:
            view = self.jobs.inspect(client, accepted["batch"], after_revision=view["revision"], wait_seconds=max(0, deadline - time.monotonic()))
        return view
