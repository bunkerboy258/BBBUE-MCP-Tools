import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MCP.mcp_result import decode_tool_result, McpBusinessError

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _iter_sse_lines(response):
    """/** @param response 流式响应 @return 完整 UTF8 行 */"""
    fragments = []
    while True:
        chunk = response.raw.read1(65536, decode_content=True)
        if not chunk:
            break
        parts = chunk.split(b"\n")
        fragments.append(parts[0])
        if len(parts) == 1:
            continue
        yield b"".join(fragments).rstrip(b"\r").decode("utf-8")
        for part in parts[1:-1]:
            yield part.rstrip(b"\r").decode("utf-8")
        fragments = [parts[-1]]
    if fragments and any(fragments):
        yield b"".join(fragments).rstrip(b"\r").decode("utf-8")


def _parse_response(response, request_id, on_tools_changed):
    """/** @param response HTTP 响应 @param request_id 请求编号 @param on_tools_changed 目录变化回调 @return 唯一协议结果 */"""
    response.encoding = "utf-8"
    if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
        result = response.json()
        if result.get("id") != request_id:
            raise RuntimeError("RESPONSE_ID_MISMATCH")
        return result
    lines = []
    for line in _iter_sse_lines(response):
        if line.startswith("data:"):
            lines.append(line[5:].lstrip())
            continue
        if line or not lines:
            continue
        result = json.loads("\n".join(lines))
        lines.clear()
        if result.get("method") == "notifications/tools/list_changed":
            on_tools_changed()
        if result.get("id") == request_id:
            return result
    raise RuntimeError("RESPONSE_STREAM_ENDED")


class McpSession:
    """/** 五入口客户端 连接层维护私有归属凭证 */"""

    def __init__(self, url=None, timeout_seconds=600, client_key=None, private_backend=False, task=None, level=None, conversation_id=None):
        """/** @param url 公开入口 @param timeout_seconds 请求超时 @param client_key 原客户端凭证 @param private_backend 官方后端连接 @return 已连接会话 */"""
        self.url = url or os.environ.get("BBB_MCP_URL", "http://127.0.0.1:8000/mcp")
        if url is None and not os.environ.get("BBB_MCP_URL") and os.environ.get("BBB_MCP_PROJECT") and not private_backend:
            from MCP.mcp_service import ensure_service
            from MCP.mcp_host_registry import project_key
            project = os.environ["BBB_MCP_PROJECT"]
            port = int(os.environ.get("BBB_MCP_SERVICE_PORT", "8000"))
            ensure_service(project, port, directory=os.environ.get("BBB_MCP_SERVICE_DIRECTORY"))
            self.url = "http://127.0.0.1:" + str(port) + "/projects/" + project_key(project) + "/mcp"
        if timeout_seconds <= 0:
            raise ValueError("TIMEOUT_RANGE")
        self.client_key = client_key
        self.private_backend = private_backend
        self.operator = None
        self.recovery = None
        self.registration = {"task": task}
        if level is not None:
            self.registration["level"] = level
        if task is None:
            self.registration = None
        self.identity_path = None
        self.identity_lock = None
        if conversation_id is None and task is not None and client_key is None:
            conversation_id = os.environ.get("CODEX_THREAD_ID") or None
        self.session_id = None
        self._protocol_version = None
        self._next_id = 0
        self._timeout = (5, timeout_seconds)
        self._lock = threading.RLock()
        self._cache = {}
        self._closed = False
        self._heartbeat_stop = threading.Event()
        self._heartbeat = None
        self._http = requests.Session()
        if urlparse(self.url).hostname in {"127.0.0.1", "localhost", "::1"}:
            self._http.trust_env = False
        try:
            if conversation_id is not None and not private_backend:
                self._conversation_identity(conversation_id)
            self._initialize()
            if not private_backend:
                self._heartbeat = threading.Thread(target=self._keepalive, daemon=True)
                self._heartbeat.start()
        except Exception:
            self.close()
            raise
        finally:
            if self.identity_lock is not None:
                self.identity_lock.close()
                self.identity_lock = None

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.close()

    def _headers(self):
        headers = dict(HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _initialize(self):
        """/** @return 使用原客户端身份建立传输会话 */"""
        self.session_id = None
        parameters = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "bbb-mcp", "version": "3"}}
        if self.client_key:
            parameters["_meta"] = {"bbb/client_key": self.client_key}
        if self.registration is not None and not self.private_backend:
            parameters.setdefault("_meta", {})["bbb/operator"] = self.registration
        response = self._post("initialize", parameters)
        value = response["result"]
        if "protocolVersion" not in value:
            decode_tool_result(response)
            raise RuntimeError("INITIALIZE_CONTRACT_REQUIRED")
        self._protocol_version = value["protocolVersion"]
        if not self.private_backend:
            self.client_key = value["_meta"]["bbb/client_key"]
            self.operator = value["_meta"].get("bbb/operator")
            self.recovery = value["_meta"].get("bbb/operator_recovery")
            self.registration = None
            if self.identity_path is not None:
                from MCP.mcp_host_registry import atomic_json
                atomic_json(self.identity_path, {"key": self.client_key})
        self._identity_recovered = value.get("_meta", {}).get("bbb/client_recovered", False)
        version = value.get("_meta", {}).get("bbb/catalog_version")
        if getattr(self, "_catalog_version", None) != version:
            self.invalidate_discovery()
        self._catalog_version = version
        self._notify("notifications/initialized")

    def _conversation_identity(self, conversation_id):
        """/** @param conversation_id 本聊天稳定标识 @return 私有凭证文件的互斥恢复 */"""
        import hashlib
        import msvcrt
        from MCP.mcp_host_registry import private_directory
        from MCP.mcp_service import service_directory
        directory = private_directory(service_directory() / "clients")
        identity = hashlib.sha256((self.url + "\n" + conversation_id).encode()).hexdigest()
        self.identity_path = directory / (identity + ".json")
        self.identity_lock = open(directory / (identity + ".lock"), "a+b")
        if self.identity_lock.tell() == 0:
            self.identity_lock.write(b"0")
            self.identity_lock.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                self.identity_lock.seek(0)
                msvcrt.locking(self.identity_lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self.identity_lock.close()
                    raise TimeoutError("CONVERSATION_CONNECT_BUSY")
                time.sleep(0.05)
        if self.identity_path.exists():
            self.client_key = json.loads(self.identity_path.read_text(encoding="utf-8"))["key"]

    def _post(self, method, parameters):
        with self._lock:
            if self._closed:
                raise RuntimeError("SESSION_CLOSED")
            self._next_id += 1
            body = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": parameters}
            for attempt in range(2):
                try:
                    with self._http.post(self.url, json=body, headers=self._headers(), timeout=self._timeout, stream=True) as response:
                        response.raise_for_status()
                        if self.session_id is None:
                            self.session_id = response.headers.get("Mcp-Session-Id")
                        result = _parse_response(response, body["id"], self.invalidate_discovery)
                    break
                except (requests.RequestException, RuntimeError) as error:
                    endpoint = urlparse(self.url)
                    if not attempt and not self.private_backend and method == "initialize" and isinstance(error, requests.ConnectionError) and endpoint.hostname in {"127.0.0.1", "localhost"}:
                        from MCP.mcp_service import ensure_service
                        ensure_service(os.environ.get("BBB_MCP_PROJECT"), endpoint.port or 8000,
                            directory=os.environ.get("BBB_MCP_SERVICE_DIRECTORY"))
                        continue
                    if attempt or self.private_backend or method == "initialize":
                        raise RuntimeError("TRANSPORT_UNCERTAIN: inspect_tasks") from error
                    self._initialize()
                    if method == "tools/call" and parameters.get("name") in {"submit_batch", "control_task", "manage_operator"} and not self._identity_recovered:
                        raise RuntimeError("TRANSPORT_UNCERTAIN: inspect_tasks") from error
            if result.get("error"):
                raise RuntimeError("PROTOCOL_ERROR: " + json.dumps(result["error"], ensure_ascii=False))
            return result

    def _notify(self, method):
        with self._http.post(self.url, json={"jsonrpc": "2.0", "method": method}, headers=self._headers(), timeout=(5, 30)) as response:
            response.raise_for_status()

    def invalidate_discovery(self):
        """/** @return 清空变化后的单工具缓存 */"""
        self._cache.clear()

    def request(self, name, arguments):
        """/** @param name 工具名 @param arguments 参数 @return 一次解码后的业务结果 */"""
        parameters = {"name": name, "arguments": arguments}
        if not self.private_backend and name == "submit_batch" and self.operator is None:
            label = (arguments.get("label") or "编辑器任务").replace("\r", " ").replace("\n", " ").strip()
            self.manage_operator(task=label[:20] or "编辑器任务")
        if not self.private_backend and name in {"submit_batch", "control_task", "manage_operator"}:
            parameters["_meta"] = {"bbb/request_id": uuid.uuid4().hex}
        result = self._post("tools/call", parameters)
        version = result["result"].get("_meta", {}).get("bbb/catalog_version")
        if version != self._catalog_version:
            self.invalidate_discovery()
            self._catalog_version = version
        try:
            value = decode_tool_result(result)
        except McpBusinessError as error:
            if error.value.get("code") in {"OPERATOR_REQUIRED", "OPERATOR_DRAINING"}:
                self.operator = None
            raise
        if name == "manage_operator" and arguments.get("operator") is None:
            self.operator = value if arguments.get("action") != "finish" else None
        return value

    def manage_operator(self, action="join", task=None, level=None, operator=None):
        """/** @param action 登记 更新或结束 @param task 单行任务 @param level 等级 @param operator 目标 @return 干员状态 */"""
        arguments = {"action": action}
        for name, value in (("task", task), ("level", level), ("operator", operator)):
            if value is not None:
                arguments[name] = value
        return self.request("manage_operator", arguments)

    def find_tools(self, query, limit=3):
        """/** @param query 目标关键字 @param limit 上限 @return 精简候选 */"""
        result = self.request("find_tools", {"query": query, "limit": limit})
        for item in result:
            if "parameters" in item:
                self._cache[item["id"]] = json.loads(json.dumps(item))
        return result

    def describe_tool(self, tool):
        """/** @param tool 稳定 ID @return 单工具参数 */"""
        if tool not in self._cache:
            self._cache[tool] = self.request("describe_tool", {"tool": tool})
        return json.loads(json.dumps(self._cache[tool]))

    def submit_batch(self, operations, label="", environment="editor", test_options=None, test_host=None, await_seconds=2):
        """/** @param operations 有序操作 @param label 阶段用途 @return 即时批次编号 */"""
        arguments = {"operations": operations, "label": label, "environment": environment, "await_seconds": await_seconds}
        if test_options is not None:
            arguments["test_options"] = test_options
        if test_host is not None:
            arguments["test_host"] = test_host
        return self.request("submit_batch", arguments)

    def inspect_tasks(self, batch=None, detail=False, after_revision=None, wait_seconds=0, operators=False):
        """/** @param batch 批次 @param detail 按需证据 @param after_revision 业务版本 @param wait_seconds 等待上限 @return 状态 */"""
        arguments = {"detail": detail, "wait_seconds": wait_seconds}
        if operators:
            arguments["operators"] = True
        if batch is not None:
            arguments["batch"] = batch
        if after_revision is not None:
            arguments["after_revision"] = after_revision
        return self.request("inspect_tasks", arguments)

    def control_task(self, action, batch=None, operator=None, lease_seconds=None, host=None):
        """/** @param action 控制动作 @param batch 批次 @return 控制结果 */"""
        arguments = {"action": action}
        if batch is not None:
            arguments["batch"] = batch
        for name, value in (("operator", operator), ("lease_seconds", lease_seconds), ("host", host)):
            if value is not None:
                arguments[name] = value
        return self.request("control_task", arguments)

    def wait_batch(self, batch, timeout_seconds=600):
        """/** @param batch 批次编号 @param timeout_seconds 等待上限 @return 终态与结果 */"""
        deadline = time.monotonic() + timeout_seconds
        arguments = {"batch": batch, "wait_seconds": 30}
        while time.monotonic() < deadline:
            arguments["wait_seconds"] = min(arguments.get("wait_seconds", 30), max(0, deadline - time.monotonic()))
            value = self.inspect_tasks(**arguments)
            if value["status"] in {"completed", "rejected", "failed", "cancelled", "closed"} and not value.get("recovering") and value.get("assets", {}).get("phase") != "fault":
                return value
            action = value.get("next")
            if not isinstance(action, dict) or action.get("tool") != "inspect_tasks" or action.get("arguments", {}).get("batch") != batch:
                raise RuntimeError("BATCH_CONTINUATION_INVALID")
            arguments = dict(action["arguments"])
            arguments["detail"] = False
        raise TimeoutError("BATCH_WAIT_TIMEOUT: inspect_tasks")

    def _keepalive(self):
        while not self._heartbeat_stop.wait(30):
            try:
                self._post("ping", {})
            except Exception:
                continue

    def wait_activity(self, activity, batch=None, timeout_seconds=600):
        """/** @param activity\t所属活动标识 @param batch\t采样批次或测试根批次 @param timeout_seconds\t等待上限 @return 活动结束时的实际状态 */"""
        deadline = time.monotonic() + timeout_seconds
        revision = None
        while time.monotonic() < deadline:
            value = self.inspect_tasks(batch=batch, after_revision=revision, wait_seconds=min(30, max(0, deadline - time.monotonic())))
            if value.get("status") in {"failed", "rejected", "cancelled"} and not value.get("recovering"):
                raise McpBusinessError(value)
            verified = value.get("host", {}).get("verified", value.get("host_state", {}).get("verified", False))
            if verified and "owned_activities" in value and activity not in value["owned_activities"] and value.get("status") not in {"queued", "running"}:
                return value
            revision = value.get("revision")
        raise TimeoutError("ACTIVITY_WAIT_TIMEOUT: inspect_tasks")

    def close(self):
        """/** @return 关闭连接 保留客户端凭证与已提交批次 */"""
        self._heartbeat_stop.set()
        with self._lock:
            if self._closed:
                return
            if self.session_id:
                try:
                    with self._http.delete(self.url, headers=self._headers(), timeout=(5, 5)):
                        pass
                except requests.RequestException:
                    pass
            self._closed = True
            self.operator = None
            self._http.close()


def main():
    """/** @return 执行一个公开请求 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=("manage_operator", "find_tools", "describe_tool", "submit_batch", "inspect_tasks", "control_task"))
    parser.add_argument("arguments", type=json.loads)
    parser.add_argument("--url", default=os.environ.get("BBB_MCP_URL"))
    parser.add_argument("--client-state", default=os.environ.get("BBB_MCP_CLIENT_STATE"))
    parser.add_argument("--task")
    parser.add_argument("--level", type=int, choices=(0, 1, 2))
    arguments = parser.parse_args()
    if arguments.tool in {"manage_operator", "submit_batch", "control_task"} or arguments.arguments.get("batch"):
        if not arguments.client_state:
            parser.error("此请求需要当前客户端专属 --client-state 文件")
    state_path = Path(arguments.client_state).resolve() if arguments.client_state else None
    key = None
    if state_path is not None and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["url"] != arguments.url:
            parser.error("CLIENT_ENDPOINT_CHANGED")
        key = state["key"]
    with McpSession(arguments.url, client_key=key, task=arguments.task, level=arguments.level) as session:
        if state_path is not None and key is None:
            descriptor = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"url": arguments.url, "key": session.client_key}, handle)
        print(json.dumps(session.request(arguments.tool, arguments.arguments), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
