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
import threading
import time
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


class McpWriteBatchError(RuntimeError):
    """/** 编辑批次失败保留阶段与已经完成的结果 */"""

    def __init__(self, phase, completed, error):
        """
        /**
         * @param phase	排队 执行 或交接阶段
         * @param completed	已经完成的协议结果
         * @param error	原始异常
         * @return 批次异常
         */
        """
        self.phase = phase
        self.completed_results = list(completed)
        super().__init__("编辑批次 {} 阶段需处理 已完成 {} 项: {}".format(phase, len(completed), error))


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
    def __init__(self, url, timeout_seconds=600, task_token=None, write_token=None, auto_heartbeat=True):
        self.url = url
        self.task_token = task_token
        self.write_token = write_token
        self.session_id = None
        self._next_id = 0
        self._protocol_version = None
        self._discovery_cache = {}
        self._closed = False
        self.editor_state = None
        self._state_received_at = None
        self._auto_heartbeat = auto_heartbeat
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = None
        self.heartbeat_error = None
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
        if task_token and write_token:
            self._start_heartbeat(30)

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
            self._stop_heartbeat()
            raise RuntimeError("MCP 传输失败 不自动重试 操作是否已执行需检查编辑器状态: {}".format(error)) from error

        state = result.get("result", {}).get("_meta", {}).get("bbb/editor_state")
        if state is not None:
            self.editor_state = state
            self._state_received_at = time.monotonic()
            if state.get("caller", {}).get("next_call") == "renew_editor_write":
                self._stop_heartbeat()
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
                cached = json.loads(self._discovery_cache[cache_key])
                if self.editor_state is not None:
                    state = json.loads(json.dumps(self.editor_state))
                    age = state.get("observation_age_seconds")
                    if age is not None:
                        state["observation_age_seconds"] = round(age + time.monotonic() - self._state_received_at, 3)
                    cached["result"].setdefault("_meta", {})["bbb/editor_state"] = state
                    if name == "list_toolsets":
                        for item in cached["result"].get("content", []):
                            if item.get("type") == "text":
                                item["text"] += "\n当前占用: " + json.dumps(state, ensure_ascii=False)
                return cached

        params = {"name": name, "arguments": arguments}
        if self.task_token:
            params["_meta"] = {"bbb/task_token": self.task_token}
        if self.write_token:
            params.setdefault("_meta", {})["bbb/write_token"] = self.write_token
        result = self._post("tools/call", params)
        if cache_key is not None:
            structural = json.loads(json.dumps(result))
            structural.get("result", {}).get("_meta", {}).pop("bbb/editor_state", None)
            if name == "list_toolsets":
                for item in structural["result"].get("content", []):
                    if item.get("type") == "text":
                        item["text"] = item["text"].split("\n当前占用: ", 1)[0]
            self._discovery_cache[cache_key] = json.dumps(structural)
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

    def begin_write(self, ttl_seconds=120, wait_seconds=0, stage_label=""):
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
            "stage_label": stage_label,
        }))
        if value["status"] == "active":
            self.write_token = value["write_token"]
            self._start_heartbeat(value["ttl_seconds"])
        return value

    def inspect_tasks(self, after_revision=None, wait_seconds=0):
        """
        /**
         * 查询调用者的行动建议 或等待状态版本变化
         * @param after_revision	已知版本
         * @param wait_seconds	本次等待上限
         * @return 占用与实际活动
         */
        """
        arguments = {"wait_seconds": wait_seconds}
        if after_revision is not None:
            arguments["after_revision"] = after_revision
        return decode_tool_result(self.call_tool("inspect_editor_tasks", arguments))

    def prepare_test_snapshot(self, map_path):
        """
        /**
         * @param map_path	已保存的测试地图
         * @return 副本准备状态与编号
         */
        """
        value = decode_tool_result(self.call_tool("prepare_test_snapshot", {
            "task_token": self.task_token, "map_path": map_path}))
        self._start_test_heartbeat(value["run_id"])
        return value

    def start_test_run(self, snapshot_id, players=1, rendering=False, audio=False):
        """
        /**
         * @param snapshot_id	准备完成的副本编号
         * @param players	本组玩家数
         * @param rendering	渲染验收开关
         * @param audio	声音验收开关
         * @return 测试队列状态
         */
        """
        value = decode_tool_result(self.call_tool("start_test_run", {
            "task_token": self.task_token, "snapshot_id": snapshot_id,
            "players": players, "rendering": rendering, "audio": audio}))
        self._start_test_heartbeat(value["run_id"])
        return value

    def call_test_tool(self, run_id, toolset_name, tool_name, arguments=None):
        """
        /**
         * @param run_id	本任务测试编号
         * @param toolset_name	测试工具集
         * @param tool_name	测试工具
         * @param arguments	业务参数
         * @return 解码结果与回读状态
         */
        """
        value = decode_tool_result(self.call_tool("call_test_tool", {
            "task_token": self.task_token, "run_id": run_id,
            "toolset_name": toolset_name, "tool_name": tool_name, "arguments": arguments or {}}))
        value["decoded_result"] = decode_tool_result(value["tool_result"])
        return value

    def inspect_test_runs(self):
        """/** @return 实例占用与队列状态 */"""
        return decode_tool_result(self.call_tool("inspect_test_runs", {}))

    def stop_test_run(self, run_id):
        """
        /**
         * @param run_id	本任务测试编号
         * @return 进程退出核实与输出位置
         */
        """
        value = decode_tool_result(self.call_tool("stop_test_run", {
            "task_token": self.task_token, "run_id": run_id}))
        if value["status"] == "stopped":
            getattr(self, "_test_run_ids", set()).discard(run_id)
            if not getattr(self, "_test_run_ids", set()) and hasattr(self, "_test_heartbeat_stop"):
                self._test_heartbeat_stop.set()
        return value

    def _start_test_heartbeat(self, run_id):
        """
        /**
         * @param run_id	当前客户端持有的测试编号
         * @return 为测试任务维持登记心跳
         */
        """
        if not hasattr(self, "_test_run_ids"):
            self._test_run_ids = set()
            self._test_heartbeat_thread = None
        self._test_run_ids.add(run_id)
        if not self._auto_heartbeat or self._closed:
            return
        if self._test_heartbeat_thread is not None and self._test_heartbeat_thread.is_alive() and not self._test_heartbeat_stop.is_set():
            return
        task_token = self.task_token
        stop = threading.Event()
        self._test_heartbeat_stop = stop

        def keep_test_alive():
            """/** @return 按测试登记续期 失败后保留所属凭证 */"""
            try:
                with McpSession(self.url, 5, task_token=task_token, auto_heartbeat=False) as heartbeat:
                    while not stop.wait(20):
                        if self._closed or self.task_token != task_token or not self._test_run_ids:
                            return
                        heartbeat.renew_task()
            except Exception:
                self.heartbeat_error = "TEST_HEARTBEAT_STOPPED_CHECK_TEST_RUNS"
                print("MCP 测试任务续期暂停 请回读实例与登记状态", file=sys.stderr)

        self._test_heartbeat_thread = threading.Thread(target=keep_test_alive, daemon=True)
        self._test_heartbeat_thread.start()

    def cancel_write(self):
        """
        /**
         * @return 取消本任务等待申请的结果
         */
        """
        return decode_tool_result(self.call_tool("cancel_editor_write", {"task_token": self.task_token}))

    def run_write_batch(self, calls, stage_label, ttl_seconds=120, wait_seconds=60):
        """
        /**
         * 将已经准备好的编辑批次排队 执行并交接
         * @param calls	顺序执行的工具请求
         * @param stage_label	本阶段用途
         * @param ttl_seconds	阶段有效期
         * @param wait_seconds	排队总等待上限
         * @return 已经完成的协议结果数组
         */
        """
        self._validate_calls(calls)
        if not self.task_token or self.write_token:
            raise ValueError("编辑批次需要已登记且处于准备阶段的任务")
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 3600:
            raise ValueError("排队总等待秒数应为零至三千六百")
        deadline = time.monotonic() + wait_seconds
        heartbeat_at = time.monotonic()
        phase = "queue"
        completed = []
        try:
            stage = self.begin_write(ttl_seconds, 0, stage_label)
            state = stage.get("state")
            while stage["status"] == "queued":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("排队申请仍有效 可继续准备并领取 或调用 cancel_editor_write")
                state = self.inspect_tasks(state["revision"], min(20, max(1, int(remaining))))
                if time.monotonic() - heartbeat_at >= 20:
                    self.renew_task()
                    heartbeat_at = time.monotonic()
                if state["summary"]["caller"]["queue_position"] is None:
                    raise RuntimeError("原排队申请已结束 请核对占用状态")
                if state["summary"]["caller"]["can_claim_write"]:
                    stage = self.begin_write(ttl_seconds, 0, stage_label)
                    state = stage.get("state", state)
            if stage["status"] != "active":
                raise RuntimeError("编辑申请已取消 请核对任务安排")
            phase = "execute"
            completed = self.call_many(calls)
            phase = "handoff"
            self.end_write()
            return completed
        except McpBatchError as error:
            raise McpWriteBatchError(phase, error.completed_results, error) from error
        except Exception as error:
            raise McpWriteBatchError(phase, completed, error) from error

    @staticmethod
    def _validate_calls(calls):
        """
        /**
         * 在取得权限前检查整批请求结构
         * @param calls	工具请求数组
         * @return 无返回值
         */
        """
        if not isinstance(calls, list) or not calls:
            raise ValueError("批量请求必须为非空数组")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not call["name"]:
                raise ValueError("每个批量请求必须包含非空 name")
            if not isinstance(call.get("arguments", {}), dict):
                raise ValueError("批量请求 arguments 必须为对象")

    def renew_write(self, resume=False):
        """
        /**
         * 续期或凭两份原凭证显式恢复编辑阶段
         * @param resume	是否已经核实实际结果并确认恢复
         * @return 续期状态
         */
        """
        value = decode_tool_result(self.call_tool("renew_editor_write", {
            "task_token": self.task_token, "write_token": self.write_token, "resume": resume,
        }))
        self._start_heartbeat(value["ttl_seconds"])
        return value

    def _start_heartbeat(self, ttl_seconds):
        """
        /**
         * 为存活客户端的当前阶段维护独立续期连接
         * @param ttl_seconds	阶段有效期
         * @return 无返回值
         */
        """
        if not self._auto_heartbeat or self._closed or not self.task_token or not self.write_token:
            return
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive() and not self._heartbeat_stop.is_set():
            return
        task_token = self.task_token
        write_token = self.write_token
        stop = threading.Event()
        self._heartbeat_stop = stop
        self.heartbeat_error = None

        def keep_alive():
            """/** @return 为当前阶段续期 失败后保留恢复凭证 */"""
            interval = min(20, ttl_seconds / 3)
            try:
                with McpSession(self.url, 5, task_token, write_token, auto_heartbeat=False) as heartbeat:
                    while not stop.wait(interval):
                        if self._closed or self.task_token != task_token or self.write_token != write_token:
                            return
                        value = heartbeat.renew_write()
                        interval = min(20, value["ttl_seconds"] / 3)
            except Exception:
                if self.task_token == task_token and self.write_token == write_token and not stop.is_set():
                    self.heartbeat_error = "HEARTBEAT_STOPPED_CHECK_EDITOR_STATE"
                    print("MCP 编辑阶段续期已暂停 请查询占用并核实恢复步骤", file=sys.stderr)

        self._heartbeat_thread = threading.Thread(target=keep_alive, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        """/** @return 停止本客户端的续期工作 保留阶段凭证 */"""
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(1)

    def prepare_recovery(self, target_task_id):
        """
        /**
         * 读取已过期阶段的接管清单供用户审批
         * @param target_task_id	失联任务标识
         * @return 接管预览
         */
        """
        return decode_tool_result(self.call_tool("prepare_editor_recovery", {
            "task_token": self.task_token, "target_task_id": target_task_id,
        }))

    def recover_write(self, review_id, user_confirmation):
        """
        /**
         * 按用户已批准的清单接管失联阶段
         * @param review_id	接管预览标识
         * @param user_confirmation	用户批准的完整确认文本
         * @return 接管状态及结果核实要求
         */
        """
        if self.write_token:
            raise RuntimeError("请先完成当前客户端持有的编辑阶段")
        value = decode_tool_result(self.call_tool("recover_editor_write", {
            "task_token": self.task_token, "review_id": review_id, "user_confirmation": user_confirmation,
        }))
        self.write_token = value["write_token"]
        if not value["requires_result_review"]:
            self._start_heartbeat(value["ttl_seconds"])
        return value

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
        self._stop_heartbeat()
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
        self._validate_calls(calls)

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

        if hasattr(self, "_test_heartbeat_stop"):
            self._test_heartbeat_stop.set()
            if self._test_heartbeat_thread is not threading.current_thread():
                self._test_heartbeat_thread.join(1)
        self._stop_heartbeat()
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
