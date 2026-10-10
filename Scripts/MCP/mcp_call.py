#!/usr/bin/env python3
"""UE5.8 官方 ModelContextProtocol 宿主的最小命令行客户端

用法
    python mcp_call.py list
    python mcp_call.py call <tool_name> <json_args>

示例
    python mcp_call.py call list_toolsets {}
    python mcp_call.py call describe_toolset "{\"toolset_name\":\"Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset\"}"
    python mcp_call.py call call_tool "{\"toolset_name\":\"...\",\"tool_name\":\"...\",\"arguments\":{}}"

默认地址 http://127.0.0.1:8000/mcp 可用环境变量 BBB_MCP_URL 覆盖
返回内容会把 content[0].text 直接打印 不再额外包装
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MCP.mcp_result import McpBusinessError, decode_tool_result

URL = os.environ.get("BBB_MCP_URL", "http://127.0.0.1:8000/mcp")
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class McpBatchError(RuntimeError):
    """/** 批量失败保留已完成结果和失败位置 不回滚或重试 */"""

    def __init__(self, index, call, completed, error):
        """
        /**
         * @param index	失败项的零基索引
         * @param call	失败请求
         * @param completed	已完成的协议结果
         * @param error	原始异常
         * @return 异常实例
         */
        """
        self.failed_index = index
        self.failed_call = call
        self.completed_results = list(completed)
        super().__init__("批量请求第 {} 项失败 前 {} 项已完成且未回滚: {}".format(index + 1, len(completed), error))


def _iter_sse_lines(response):
    """/** @param response 流式 HTTP 响应 @return 按完整 UTF-8 行读取 不逐字节重复复制长消息 */"""
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
    """解析 JSON 或 SSE 响应 返回最后一个 JSON 对象"""
    response.encoding = "utf-8"
    content_type = response.headers.get("Content-Type", "").lower()
    if "text/event-stream" not in content_type:
        result = response.json()
        if result.get("id") != request_id:
            raise RuntimeError("MCP 响应编号不匹配")
        return result

    event_lines = []
    for line in _iter_sse_lines(response):
        if line.startswith("data:"):
            event_lines.append(line[5:].lstrip())
            continue

        if line or not event_lines:
            continue

        result = json.loads("\n".join(event_lines))
        event_lines.clear()
        if result.get("method") == "notifications/tools/list_changed":
            on_tools_changed()
            continue

        if result.get("id") == request_id:
            return result

    raise RuntimeError("MCP 事件流结束但未收到当前请求结果")


class McpSession:
    def __init__(self, url, timeout_seconds=600, task_token=None, write_token=None):
        self.url = url
        self.task_token = task_token
        self.write_token = write_token
        self.session_id = None
        self._next_id = 0
        self._protocol_version = None
        self._discovery_cache = {}
        self._closed = False
        if timeout_seconds <= 0:
            raise ValueError("MCP 请求超时必须大于零")

        self._timeout = (5, timeout_seconds)
        self._http = requests.Session()
        if urlparse(url).hostname in {"127.0.0.1", "localhost", "::1"}:
            self._http.trust_env = False

        try:
            self._initialize()
        except Exception:
            self.close()
            raise

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

    def _post(self, method, params):
        if self._closed:
            raise RuntimeError("MCP 会话已关闭")

        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        try:
            with self._http.post(self.url, json=body, headers=self._headers(), timeout=self._timeout, stream=True) as response:
                response.raise_for_status()
                if self.session_id is None:
                    self.session_id = response.headers.get("Mcp-Session-Id")
                result = _parse_response(response, self._next_id, self.invalidate_discovery)
        except requests.RequestException as error:
            raise RuntimeError("MCP 传输失败 不自动重试 操作是否已执行需检查编辑器状态: {}".format(error)) from error

        if result.get("error"):
            raise RuntimeError("MCP 协议错误: {}".format(json.dumps(result["error"], ensure_ascii=False)))
        if result.get("result", {}).get("isError"):
            try:
                decode_tool_result(result)
            except McpBusinessError as error:
                arguments = params.get("arguments", {})
                metadata = params.get("_meta", {})
                supplied_task = arguments.get("task_token", metadata.get("bbb/task_token"))
                supplied_write = arguments.get("write_token", metadata.get("bbb/write_token"))
                if supplied_task == self.task_token:
                    if error.value.get("code") == "TASK_TOKEN_INVALID":
                        self.task_token = None
                        self.write_token = None
                    if error.value.get("code") in {"WRITE_TOKEN_INVALID", "EDITOR_WRITE_REQUIRED"} and supplied_write == self.write_token:
                        self.write_token = None
                raise
            raise RuntimeError("MCP 工具失败: {}".format(json.dumps(result["result"], ensure_ascii=False)))
        if method == "tools/call":
            decode_tool_result(result)
        return result

    def _notify(self, method):
        body = {"jsonrpc": "2.0", "method": method}
        with self._http.post(self.url, json=body, headers=self._headers(), timeout=(5, 30)) as response:
            response.raise_for_status()

    def _initialize(self):
        result = self._post("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "bbb-mcp-call", "version": "1.0"},
        })
        self._protocol_version = result["result"]["protocolVersion"]
        self._notify("notifications/initialized")
        return result

    def call_tool(self, name, arguments):
        cache_key = None
        if name in {"list_toolsets", "describe_toolset"}:
            cache_key = (name, json.dumps(arguments, sort_keys=True))
            if cache_key in self._discovery_cache:
                return json.loads(self._discovery_cache[cache_key])

        params = {"name": name, "arguments": arguments}
        if self.task_token:
            params["_meta"] = {"bbb/task_token": self.task_token}
        if self.write_token:
            params.setdefault("_meta", {})["bbb/write_token"] = self.write_token
        result = self._post("tools/call", params)
        if cache_key is not None:
            self._discovery_cache[cache_key] = json.dumps(result)
        return result

    def acquire_task(self, task_id, description, mode="editor", ttl_seconds=300):
        """
        /**
         * @param task_id	任务标识
         * @param description	可读说明
         * @param mode	read editor 或 pie
         * @param ttl_seconds	心跳有效期
         * @return 服务端任务凭证 不随 HTTP 关闭释放
         */
        """
        if self.task_token:
            raise RuntimeError("当前客户端已持有凭证 先释放原任务")
        value = decode_tool_result(self.call_tool("acquire_editor_task", {
            "task_id": task_id, "description": description, "mode": mode, "ttl_seconds": ttl_seconds,
        }))
        self.task_token = value["task_token"]
        return value

    def renew_task(self, resume=False):
        """
        /**
         * @param resume	显式恢复失联或不确定任务
         * @return 原任务续期状态
         */
        """
        return decode_tool_result(self.call_tool("renew_editor_task", {"task_token": self.task_token, "resume": resume}))

    def release_task(self):
        """
        /**
         * @return 任务实际释放结果 活动未结束时保留凭证
         */
        """
        value = decode_tool_result(self.call_tool("release_editor_task", {"task_token": self.task_token}))
        self.task_token = None
        return value

    def begin_write(self, ttl_seconds=120, wait_seconds=0):
        """
        /**
         * 申请一组连续编辑操作的短期写权限
         * @param ttl_seconds	编辑阶段有效期
         * @param wait_seconds	本次等待秒数
         * @return 编辑阶段凭证
         */
        """
        if self.write_token:
            raise RuntimeError("当前客户端仍持有编辑阶段凭证 先结束或核实该阶段")
        value = decode_tool_result(self.call_tool("begin_editor_write", {
            "task_token": self.task_token, "ttl_seconds": ttl_seconds, "wait_seconds": wait_seconds,
        }))
        self.write_token = value["write_token"]
        return value

    def renew_write(self, resume=False):
        """
        /**
         * 续期或凭两份原凭证显式恢复编辑阶段
         * @param resume	是否已经核实实际结果并确认恢复
         * @return 续期状态
         */
        """
        return decode_tool_result(self.call_tool("renew_editor_write", {
            "task_token": self.task_token, "write_token": self.write_token, "resume": resume,
        }))

    def end_write(self):
        """
        /**
         * 完成实际活动后让出写权限 保留任务登记
         * @return 编辑阶段结束结果
         */
        """
        value = decode_tool_result(self.call_tool("end_editor_write", {
            "task_token": self.task_token, "write_token": self.write_token,
        }))
        self.write_token = None
        return value

    def list_tools(self):
        return self._post("tools/list", {})

    def invalidate_discovery(self):
        """
        /**
         * 清空当前宿主会话内的工具发现缓存
         * @return 无返回值
         */
        """
        self._discovery_cache.clear()

    def call_many(self, calls):
        """
        /**
         * 在同一会话内顺序执行请求 失败立即停止且不回滚已完成操作
         * @param calls\t工具名称与参数对象数组
         * @return 按请求顺序排列的协议结果数组
         */
        """
        if not isinstance(calls, list) or not calls:
            raise ValueError("批量请求必须为非空数组")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not call["name"]:
                raise ValueError("每个批量请求必须包含非空 name")
            if not isinstance(call.get("arguments", {}), dict):
                raise ValueError("批量请求 arguments 必须为对象")

        results = []
        for index, call in enumerate(calls):
            try:
                result = self.call_tool(call["name"], call.get("arguments", {}))
                decode_tool_result(result)
                results.append(result)
            except Exception as error:
                raise McpBatchError(index, call, results, error) from error
        return results

    def close(self):
        """
        /**
         * 释放本客户端的服务端会话和 HTTP 连接 不关闭编辑器
         * @return 无返回值
         */
        """
        if self._closed:
            return

        try:
            if self.session_id:
                with self._http.delete(self.url, headers=self._headers(), timeout=(5, 5)) as response:
                    if response.status_code not in {200, 202, 204, 404, 405}:
                        print("MCP 会话释放失败 HTTP {}".format(response.status_code), file=sys.stderr)
        except requests.RequestException:
            print("MCP 会话释放失败 连接已失效", file=sys.stderr)
        finally:
            self._closed = True
            self._http.close()
            self.invalidate_discovery()


def _print_result(result):
    payload = result["result"]
    content = payload.get("content") if isinstance(payload, dict) else None
    if content:
        for item in content:
            if item.get("type") == "text":
                print(item["text"])
            else:
                print(json.dumps(item, ensure_ascii=False))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    command = sys.argv[1]
    if command not in {"list", "call", "batch"}:
        raise ValueError("未知命令 " + command)
    if command in {"call", "batch"} and len(sys.argv) < 3:
        raise ValueError("缺少工具名称或批量请求数组")

    arguments = {}
    if command == "call" and len(sys.argv) > 3:
        arguments = json.loads(sys.argv[3])
    if command == "call" and not isinstance(arguments, dict):
        raise ValueError("工具参数必须为 JSON 对象")

    calls = None
    if command == "batch":
        calls = json.loads(sys.argv[2])

    with McpSession(URL, task_token=os.environ.get("BBB_MCP_TASK_TOKEN"), write_token=os.environ.get("BBB_MCP_WRITE_TOKEN")) as session:
        if command == "list":
            _print_result(session.list_tools())
            return
        if command == "call":
            _print_result(session.call_tool(sys.argv[2], arguments))
            return
        print(json.dumps(session.call_many(calls), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, requests.RequestException) as error:
        print("MCP 调用失败: {}".format(error), file=sys.stderr)
        sys.exit(1)
