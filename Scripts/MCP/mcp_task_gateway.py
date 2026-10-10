import argparse
import atexit
import copy
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MCP.mcp_call import McpSession, _parse_response
from MCP.mcp_result import McpBusinessError, decode_tool_result
from MCP import mcp_access_policy as access_policy


_CONTROL_SPEC = {
    "acquire_editor_task": ("申请共享宿主任务占用", {
        "task_id": {"type": "string"}, "description": {"type": "string"},
        "mode": {"type": "string", "enum": ["read", "editor", "pie"]},
        "ttl_seconds": {"type": "integer", "minimum": 30, "maximum": 3600},
    }, ["task_id", "description", "mode"]),
    "renew_editor_task": ("续期或凭原凭证显式恢复失联任务", {
        "task_token": {"type": "string"}, "resume": {"type": "boolean"},
    }, ["task_token"]),
    "begin_editor_write": ("申请短期编辑阶段 按顺序等待写权限", {
        "task_token": {"type": "string"},
        "ttl_seconds": {"type": "integer", "minimum": 30, "maximum": 900},
        "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 60},
        "stage_label": {"type": "string", "maxLength": 160},
    }, ["task_token"]),
    "cancel_editor_write": ("取消本任务的排队申请 保留任务登记", {
        "task_token": {"type": "string"},
    }, ["task_token"]),
    "renew_editor_write": ("凭原编辑阶段凭证续期或显式恢复", {
        "task_token": {"type": "string"}, "write_token": {"type": "string"},
        "resume": {"type": "boolean"},
    }, ["task_token", "write_token"]),
    "end_editor_write": ("完成编辑批次后让出写权限 保留任务登记", {
        "task_token": {"type": "string"}, "write_token": {"type": "string"},
    }, ["task_token", "write_token"]),
    "release_editor_task": ("活动结束后释放本任务 不结束其他任务的 PIE", {
        "task_token": {"type": "string"},
    }, ["task_token"]),
    "inspect_editor_tasks": ("查询当前操作 阻塞原因 可执行工作 或等待状态变化", {
        "task_token": {"type": "string"},
        "after_revision": {"type": "integer", "minimum": 0},
        "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 60},
    }, []),
    "shutdown_editor_host": ("全部任务和活动结束后请求隐藏宿主退出", {}, []),
}


def control_tools():
    """
    /**
     * @return 网关工具注册信息
     */
    """
    return [{
        "name": name,
        "description": value[0],
        "inputSchema": {"type": "object", "properties": value[1], "required": value[2], "additionalProperties": False},
    } for name, value in _CONTROL_SPEC.items()]


class TaskConflict(RuntimeError):
    """/** 可回读的占用冲突 不泄露凭证 */"""

    def __init__(self, code, message, state=None):
        """
        /**
         * 初始化本对象的任务保护状态
         * @param code	本操作输入
         * @param message	本操作输入
         * @param state	本操作输入
         * @return 操作结果或验证完成
         */
        """
        self.value = {"success": False, "code": code, "message": message}
        if state is not None:
            self.value["state"] = state
        super().__init__(message)


def tool_identity(params):
    """
    /**
     * @param params	MCP 工具调用参数
     * @return 实际工具集 函数和业务参数
     */
    """
    return access_policy.tool_identity(params)


def is_read_call(params):
    """
    /**
     * 只认可明确审查过的查询 不按函数名前缀判断
     * @param params	工具调用参数
     * @return 是否可与占用任务并存
     */
    """
    return access_policy.is_read_call(params)


class TaskCoordinator:
    """/** 服务端任务归属和完整生命周期保护 */"""

    def __init__(self, probe, clock=time.monotonic):
        """
        /**
         * 初始化本对象的任务保护状态
         * @param probe	本操作输入
         * @param clock	本操作输入
         * @return 操作结果或验证完成
         */
        """
        self.probe = probe
        self.clock = clock
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.observation_lock = threading.Lock()
        self.tasks = {}
        self.writer = None
        self.queue = []
        self.inflight = 0
        self.draining = False
        self.instance = None
        self.last_activity = None
        self.host_changed = False
        self.revision = 0
        self.observed_at = None
        self.probe_count = 0
        self.probe_seconds = 0.0
        self.claims = set()

    def _signal(self):
        """
        /**
         * 发布一次实际状态变化并唤醒等待者
         * @return 无返回值
         */
        """
        self.revision += 1
        self.changed.notify_all()

    def _safe_to_yield(self, record, activity):
        """
        /**
         * 只在操作和实际活动均已确认结束时让出写权限
         * @param record	所属任务
         * @param activity	实际宿主快照
         * @return 是否可安全让出
         */
        """
        return not (
            self.host_changed or record["inflight"] or record["uncertain"] or record["pie_request"]
            or activity["pie_active"] or activity["worlds"] or activity["activities"]
            or activity.get("dirty_packages")
        )

    def _retire_write(self, record, reason):
        """
        /**
         * 撤销本编辑阶段的凭证并唤醒等待者
         * @param record	所属任务
         * @param reason	结束原因
         * @return 无返回值
         */
        """
        record["write"] = None
        record["last_write_state"] = reason
        self.writer = None
        self._signal()

    def _observe(self, max_age=0):
        """
        /**
         * 回读实际宿主并核实世界变化
         * @return 操作结果或验证完成
         */
        """
        requested_at = time.monotonic()
        with self.observation_lock:
            if self.observed_at is not None and (self.observed_at >= requested_at or requested_at - self.observed_at < max_age):
                with self.lock:
                    self._expire()
                    return self.last_activity
            started_at = time.monotonic()
            activity = self.probe()
            with self.lock:
                self.probe_count += 1
                self.probe_seconds += time.monotonic() - started_at
                self.observed_at = time.monotonic()
                instance = (activity["process_id"], activity["host_instance"])
                if self.instance is not None and self.instance != instance:
                    self.host_changed = True
                self.instance = instance
                if self.last_activity != activity:
                    self._signal()
                self.last_activity = copy.deepcopy(activity)
                if self.writer in self.tasks:
                    record = self.tasks[self.writer]
                    requested = record["pie_request"]
                    if requested == "start_pie" and activity["pie_active"] and activity["worlds"]:
                        record["pie_request"] = None
                    if requested == "stop_pie" and not activity["pie_active"] and not activity["worlds"]:
                        record["pie_request"] = None
                    if activity["pie_generation"] != record["pie_generation"]:
                        if not record["write_inflight"] and requested is None:
                            record["uncertain"] = True
                        record["pie_generation"] = activity["pie_generation"]
                    stage = record["write"]
                    if self.clock() >= stage["expires_at"] and not record["inflight"] and stage["status"] != "releasing":
                        if self._safe_to_yield(record, activity):
                            self._retire_write(record, "expired")
                        if record["write"] is not None and record["write"]["status"] != "orphaned":
                            record["write"]["status"] = "orphaned"
                            record["status"] = "orphaned"
                            self._signal()
                self._expire()
            return activity

    def _expire(self):
        """
        /**
         * 只标记失联任务 保留占用和 PIE
         * @return 操作结果或验证完成
         */
        """
        for token, record in list(self.tasks.items()):
            if self.clock() < record["expires_at"] or record["inflight"]:
                continue
            if token in self.queue:
                self.queue.remove(token)
                record["queued_write"] = None
                self._signal()
            record["status"] = "orphaned"
            if record["write"] is None and not record["uncertain"]:
                self.tasks.pop(token)
                self._signal()

    def _blockers(self):
        """
        /**
         * 汇总编辑交接的实际阻塞原因
         * @return 结构化原因数组
         */
        """
        activity = self.last_activity or {}
        blockers = []
        if self.host_changed:
            blockers.append({"code": "HOST_CHANGED", "message": "核对宿主身份并恢复连接"})
        if self.draining:
            blockers.append({"code": "HOST_DRAINING", "message": "等待宿主退出"})
        if self.writer in self.tasks:
            writer = self.tasks[self.writer]
            blockers.append({"code": "EDITOR_OCCUPIED", "task_id": writer["task_id"], "message": "等待当前阶段完成并交接"})
            if writer["uncertain"] or writer["status"] == "orphaned":
                blockers.append({"code": "WRITE_RECOVERY_REQUIRED", "task_id": writer["task_id"], "message": "原任务回读实际结果并显式恢复"})
            if writer["pie_request"]:
                blockers.append({"code": "TASK_PIE_PENDING", "message": "等待 PIE 请求在实际世界中生效"})
        if activity.get("pie_active") or activity.get("worlds"):
            blockers.append({"code": "PIE_ACTIVE", "message": "由所属任务完成 PIE"})
        if activity.get("activities"):
            blockers.append({"code": "BACKGROUND_ACTIVITY", "count": len(activity["activities"]), "message": "由所属任务完成采样或录制"})
        if activity.get("dirty_packages"):
            blockers.append({"code": "DIRTY_PACKAGES", "count": len(activity["dirty_packages"]), "message": "由所属任务处理未保存资产"})
        return blockers

    def _guidance(self, task_token, blockers):
        """
        /**
         * 根据调用者归属给出可执行工作
         * @param task_token	调用者任务凭证
         * @param blockers	当前交接阻塞原因
         * @return 下一步工具和阶段能力
         */
        """
        record = self.tasks.get(task_token)
        guidance = {"can_read": not self.draining, "can_prepare": True, "can_write": False,
            "can_claim_write": False, "next_call": "acquire_editor_task", "task_id": None}
        if record is None:
            return guidance
        guidance["task_id"] = record["task_id"]
        guidance["queue_position"] = self.queue.index(task_token) + 1 if task_token in self.queue else None
        guidance["next_call"] = "inspect_editor_tasks"
        if self.host_changed or self.draining:
            return guidance
        if record["uncertain"] or record["status"] == "orphaned":
            guidance["next_call"] = "renew_editor_write" if record["write"] else "renew_editor_task"
            guidance["recovery_steps"] = ["回读实际操作结果", "凭原凭证显式 resume"]
            return guidance
        if record["write"]:
            guidance["can_write"] = record["write"]["status"] == "active" and not record["inflight"] and not record["pie_request"]
            if guidance["can_write"]:
                guidance["next_call"] = "call_tool"
            guidance["can_end_write"] = self._safe_to_yield(record, self.last_activity)
            return guidance
        if record["mode"] == "read":
            return guidance
        first = not self.queue or self.queue[0] == task_token
        guidance["can_claim_write"] = first and not blockers
        guidance["next_call"] = "begin_editor_write"
        if task_token in self.queue and not guidance["can_claim_write"]:
            guidance["next_call"] = "inspect_editor_tasks"
        if self.queue and not first:
            guidance["queue_ahead_task_id"] = self.tasks[self.queue[0]]["task_id"]
            guidance["wait_reason"] = "等待前序任务领取并完成阶段"
        guidance["waiting_work"] = ["shared_read", "本地分析", "准备下一批参数"]
        return guidance

    def _public(self, task_token=None, compact=False):
        """
        /**
         * 生成不含凭证的任务状态
         * @return 操作结果或验证完成
         */
        """
        with self.lock:
            self._expire()
            tasks = []
            for token, record in self.tasks.items():
                public = {key: record[key] for key in (
                    "task_id", "description", "mode", "ttl_seconds", "status", "inflight",
                    "write_inflight", "uncertain", "pie_request", "pie_generation", "last_write_state",
                )}
                public["remaining_seconds"] = max(0, round(record["expires_at"] - self.clock(), 1))
                public["write"] = None
                if record["write"] is not None:
                    stage = record["write"]
                    public["write"] = {
                        "status": stage["status"], "ttl_seconds": stage["ttl_seconds"],
                        "remaining_seconds": max(0, round(stage["expires_at"] - self.clock(), 1)),
                        "stage_label": stage["stage_label"],
                        "elapsed_seconds": max(0, round(self.clock() - stage["started_at"], 1)),
                    }
                public["queue_position"] = self.queue.index(token) + 1 if token in self.queue else None
                public["queue_wait_seconds"] = None
                if record["queued_write"] is not None:
                    public["queue_wait_seconds"] = max(0, round(self.clock() - record["queued_write"]["requested_at"], 1))
                    public["queued_stage_label"] = record["queued_write"]["stage_label"]
                public["operations"] = [{
                    "toolset": operation["toolset"], "tool": operation["tool"], "access": operation["access"],
                    "elapsed_seconds": max(0, round(self.clock() - operation["started_at"], 1)),
                } for operation in record["operations"].values()]
                tasks.append(public)
            blockers = self._blockers()
            writer = next((task for task in tasks if self.writer in self.tasks and task["task_id"] == self.tasks[self.writer]["task_id"]), None)
            summary = {"revision": self.revision,
                "writer": {key: writer[key] for key in ("task_id", "description", "write", "operations")} if writer else None,
                "queue_length": len(self.queue), "blockers": blockers,
                "caller": self._guidance(task_token, blockers),
                "observation_age_seconds": round(time.monotonic() - self.observed_at, 3) if self.observed_at is not None else None,
            }
            if compact:
                return summary
            return {
                "tasks": tasks, "inflight": self.inflight, "draining": self.draining,
                "host_changed": self.host_changed, "activity": copy.deepcopy(self.last_activity),
                "writer_task_id": self.tasks[self.writer]["task_id"] if self.writer in self.tasks else None,
                "write_queue": [self.tasks[token]["task_id"] for token in self.queue if token in self.tasks],
                "revision": self.revision, "summary": summary,
                "metrics": {"probe_count": self.probe_count, "probe_seconds": round(self.probe_seconds, 3)},
            }

    def inspect(self, task_token=None, after_revision=None, wait_seconds=0):
        """
        /**
         * @return 不包含占用凭证的实际状态
         */
        """
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 60:
            raise ValueError("等待秒数应为零至六十")
        if after_revision is not None and (isinstance(after_revision, bool) or not isinstance(after_revision, int) or after_revision < 0):
            raise ValueError("状态版本应为非负整数")
        if wait_seconds and after_revision is None:
            raise ValueError("等待变化需要 after_revision")
        deadline = time.monotonic() + wait_seconds
        while True:
            self._observe(max_age=1 if after_revision is not None else 0)
            with self.changed:
                if task_token:
                    self._record(task_token)
                if after_revision is not None and after_revision > self.revision:
                    raise ValueError("状态版本超出当前宿主版本")
                if after_revision is None or self.revision > after_revision or time.monotonic() >= deadline:
                    return self._public(task_token)
                self.changed.wait(min(1, max(0, deadline - time.monotonic())))

    def _record(self, token):
        """
        /**
         * 验证原任务凭证
         * @param token	本操作输入
         * @return 操作结果或验证完成
         */
        """
        record = self.tasks.get(token)
        if record is None:
            raise TaskConflict("TASK_TOKEN_INVALID", "任务凭证不存在或已释放")
        return record

    def _write_record(self, task_token, write_token):
        """
        /**
         * 核对任务和当前编辑阶段的两份凭证
         * @param task_token	任务凭证
         * @param write_token	当前编辑阶段凭证
         * @return 所属任务
         */
        """
        record = self._record(task_token)
        if self.writer != task_token or record["write"] is None:
            raise TaskConflict("EDITOR_WRITE_REQUIRED", "先申请编辑阶段 写权限不随任务登记授予", self._public(task_token))
        if not write_token or not secrets.compare_digest(record["write"]["token"], write_token):
            raise TaskConflict("WRITE_TOKEN_INVALID", "编辑阶段凭证不存在或已被撤销")
        return record

    def acquire(self, task_id, description, mode, ttl_seconds=300):
        """
        /**
         * 先保留任务占用再回读世界 防止并发申请穿透
         * @param task_id	客户端任务标识
         * @param description	可读任务说明
         * @param mode	read editor 或 pie
         * @param ttl_seconds	心跳有效期
         * @return 仅发给申请者的服务端凭证
         */
        """
        if not isinstance(task_id, str) or not task_id.strip() or not isinstance(description, str) or not description.strip():
            raise ValueError("任务标识和说明必须非空")
        if mode not in {"read", "editor", "pie"}:
            raise ValueError("任务模式无效")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 30 <= ttl_seconds <= 3600:
            raise ValueError("心跳有效期必须为三十至三千六百秒")
        activity = self._observe()
        with self.lock:
            if self.draining or self.host_changed:
                raise TaskConflict("HOST_UNAVAILABLE", "宿主正在退出或身份已变化", self._public())
            if any(record["task_id"] == task_id for record in self.tasks.values()):
                raise TaskConflict("TASK_ALREADY_EXISTS", "任务已存在 请凭原凭证续期", self._public())
            token = secrets.token_urlsafe(32)
            self.tasks[token] = {
                "token": token, "task_id": task_id, "description": description, "mode": mode,
                "ttl_seconds": ttl_seconds, "expires_at": self.clock() + ttl_seconds,
                "status": "active", "inflight": 0, "write_inflight": 0,
                "uncertain": False, "pie_request": None, "pie_generation": activity["pie_generation"],
                "write": None, "last_write_state": None, "queued_write": None, "operations": {},
                "write_cancel_generation": 0,
            }
            self._signal()
            return {"task_id": task_id, "task_token": token, "mode": mode, "ttl_seconds": ttl_seconds,
                "host_instance": activity["host_instance"], "pie_generation": activity["pie_generation"]}

    def begin_write(self, task_token, ttl_seconds=120, wait_seconds=0, stage_label=""):
        """
        /**
         * 按申请顺序等待短期编辑阶段 分析期间不持有写权限
         * @param task_token	任务凭证
         * @param ttl_seconds	编辑阶段有效期
         * @param wait_seconds	本次最多等待秒数
         * @return 编辑阶段凭证
         */
        """
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 30 <= ttl_seconds <= 900:
            raise ValueError("编辑阶段有效期必须为三十至九百秒")
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 60:
            raise ValueError("本次等待必须为零至六十秒")
        if not isinstance(stage_label, str) or len(stage_label) > 160:
            raise ValueError("阶段说明应为一百六十字以内的字符串")
        deadline = time.monotonic() + wait_seconds
        reserved = False
        record = None
        with self.changed:
            self._expire()
            record = self._record(task_token)
            if task_token in self.claims:
                raise TaskConflict("WRITE_APPLICATION_PENDING", "本任务已有领取请求正在执行")
            self.claims.add(task_token)
            cancellation_generation = record["write_cancel_generation"]
        try:
            while True:
                activity = self._observe(max_age=1)
                with self.changed:
                    self._expire()
                    record = self._record(task_token)
                    if record["write_cancel_generation"] != cancellation_generation:
                        return {"status": "cancelled", "state": self._public(task_token)}
                    if self.draining or self.host_changed:
                        raise TaskConflict("HOST_UNAVAILABLE", "宿主正在退出或身份已变化", self._public(task_token))
                    if record["mode"] == "read":
                        raise TaskConflict("EDITOR_TASK_REQUIRED", "只读任务不能申请写权限")
                    if record["status"] != "active" or record["uncertain"]:
                        raise TaskConflict("TASK_RECOVERY_REQUIRED", "先检查实际状态并恢复原任务")
                    if record["write"] is not None:
                        raise TaskConflict("WRITE_ALREADY_HELD", "本任务已经持有编辑阶段")
                    if record["queued_write"] is None:
                        record["queued_write"] = {"requested_at": self.clock(), "ttl_seconds": ttl_seconds,
                            "stage_label": stage_label or record["description"][:160]}
                        self.queue.append(task_token)
                        record["expires_at"] = self.clock() + record["ttl_seconds"]
                        self._signal()
                    first = not self.queue or self.queue[0] == task_token
                    if self.writer is None and first:
                        if activity["pie_active"] or activity["worlds"] or activity["activities"] or activity.get("dirty_packages"):
                            return {"status": "queued", "state": self._public(task_token)}
                        queued_stage = record["queued_write"]
                        record["write"] = {"token": secrets.token_urlsafe(32),
                            "ttl_seconds": queued_stage["ttl_seconds"],
                            "expires_at": self.clock() + queued_stage["ttl_seconds"], "status": "checking",
                            "stage_label": queued_stage["stage_label"], "started_at": self.clock()}
                        self.writer = task_token
                        record["pie_generation"] = activity["pie_generation"]
                        record["inflight"] += 1
                        self.inflight += 1
                        reserved = True
                        self._signal()
                        break
                    if time.monotonic() >= deadline:
                        return {"status": "queued", "state": self._public(task_token)}
                    self.changed.wait(min(1, max(0, deadline - time.monotonic())))
            activity = self._observe()
            with self.changed:
                if self.host_changed or record["uncertain"] or activity["pie_active"] or activity["worlds"] or activity["activities"] or activity.get("dirty_packages"):
                    self._retire_write(record, "preflight_failed")
                    raise TaskConflict("EXTERNAL_ACTIVITY", "申请期间宿主状态变化 请核对实际活动", self._public(task_token))
                stage = record["write"]
                stage["status"] = "active"
                self.queue.remove(task_token)
                record["queued_write"] = None
                record["expires_at"] = self.clock() + record["ttl_seconds"]
                self._signal()
                return {"task_id": record["task_id"], "write_token": stage["token"],
                    "ttl_seconds": stage["ttl_seconds"], "mode": record["mode"], "status": "active"}
        except Exception:
            with self.changed:
                if reserved and record["write"] is not None:
                    self._retire_write(record, "preflight_failed")
            raise
        finally:
            with self.changed:
                self.claims.discard(task_token)
                if reserved:
                    record["inflight"] -= 1
                    self.inflight -= 1
                    self._signal()

    def cancel_write(self, task_token):
        """
        /**
         * 取消本任务尚待领取的申请
         * @param task_token	任务凭证
         * @return 取消状态与当前队列
         */
        """
        with self.changed:
            self._expire()
            record = self._record(task_token)
            if record["write"] is not None:
                raise TaskConflict("WRITE_STAGE_ACTIVE", "编辑阶段已取得权限 请调用 end_editor_write")
            cancelled = task_token in self.queue or task_token in self.claims
            if cancelled:
                if task_token in self.queue:
                    self.queue.remove(task_token)
                record["queued_write"] = None
                record["write_cancel_generation"] += 1
                self._signal()
            return {"cancelled": cancelled, "task_registered": True, "state": self._public(task_token)}

    def renew(self, task_token, resume=False):
        """
        /**
         * @param task_token	原占用凭证
         * @param resume	显式恢复失联或不确定状态
         * @return 续期结果
         */
        """
        if not isinstance(resume, bool):
            raise ValueError("resume 必须为布尔值")
        activity = self._observe()
        with self.lock:
            record = self._record(task_token)
            if self.host_changed or self.draining:
                raise TaskConflict("HOST_UNAVAILABLE", "宿主身份已变化或正在退出")
            if record["write"] is not None and (record["uncertain"] or record["write"]["status"] == "orphaned"):
                raise TaskConflict("WRITE_RECOVERY_REQUIRED", "凭原编辑阶段凭证调用 renew_editor_write 显式恢复")
            if (record["status"] == "orphaned" or record["uncertain"]) and resume is not True:
                raise TaskConflict("TASK_RECOVERY_REQUIRED", "先检查实际状态 再凭原凭证显式 resume", self._public(task_token))
            if record["inflight"] and resume:
                raise TaskConflict("TASK_INFLIGHT", "请求仍在执行 不能确认恢复")
            if resume:
                record["uncertain"] = False
                record["pie_generation"] = activity["pie_generation"]
            record["status"] = "active"
            record["expires_at"] = self.clock() + record["ttl_seconds"]
            self._signal()
            return {"task_id": record["task_id"], "status": "active", "ttl_seconds": record["ttl_seconds"]}

    def renew_write(self, task_token, write_token, resume=False):
        """
        /**
         * 仅原编辑阶段可续期或显式恢复 不清除未生效的 PIE 请求
         * @param task_token	任务凭证
         * @param write_token	编辑阶段凭证
         * @param resume	是否已核实不确定结果并显式恢复
         * @return 续期结果
         */
        """
        if not isinstance(resume, bool):
            raise ValueError("resume 必须为布尔值")
        activity = self._observe()
        with self.lock:
            record = self._write_record(task_token, write_token)
            stage = record["write"]
            if self.host_changed or self.draining:
                raise TaskConflict("HOST_UNAVAILABLE", "宿主身份已变化或正在退出")
            if stage["status"] == "releasing":
                raise TaskConflict("WRITE_RELEASING", "编辑阶段正在释放")
            if (record["uncertain"] or stage["status"] == "orphaned" or record["status"] == "orphaned") and not resume:
                raise TaskConflict("WRITE_RECOVERY_REQUIRED", "先查询实际状态 再凭两份原凭证显式恢复")
            if resume and record["inflight"]:
                raise TaskConflict("TASK_INFLIGHT", "实际请求仍在执行")
            if resume and record["pie_request"]:
                raise TaskConflict("TASK_PIE_PENDING", "PIE 请求尚未生效 不能通过续期清除")
            if resume:
                record["uncertain"] = False
                record["pie_generation"] = activity["pie_generation"]
            stage["status"] = "active"
            stage["expires_at"] = self.clock() + stage["ttl_seconds"]
            record["status"] = "active"
            record["expires_at"] = self.clock() + record["ttl_seconds"]
            self._signal()
            return {"task_id": record["task_id"], "status": "active", "ttl_seconds": stage["ttl_seconds"]}

    def end_write(self, task_token, write_token):
        """
        /**
         * 编辑批次结束后让出写权限 保留任务登记供后续分析
         * @param task_token	任务凭证
         * @param write_token	编辑阶段凭证
         * @return 结束结果
         */
        """
        with self.lock:
            record = self._write_record(task_token, write_token)
            if record["inflight"]:
                raise TaskConflict("TASK_INFLIGHT", "实际请求仍在执行")
            previous_status = record["write"]["status"]
            record["write"]["status"] = "releasing"
            self._signal()
        try:
            activity = self._observe()
            with self.changed:
                if not self._safe_to_yield(record, activity):
                    raise TaskConflict("TASK_ACTIVITY_PENDING", "先结束本任务活动 核实不确定结果并处理未保存资产", self._public(task_token))
                self._retire_write(record, "completed")
                return {"ended": record["task_id"], "task_registered": True}
        except Exception:
            with self.lock:
                if record["write"] is not None:
                    record["write"]["status"] = previous_status
                    self._signal()
            raise

    def release(self, task_token):
        """
        /**
         * @param task_token	仅释放本任务的凭证
         * @return 剩余任务数量
         */
        """
        with self.changed:
            self._expire()
            record = self._record(task_token)
            if record["inflight"] or task_token in self.queue:
                raise TaskConflict("TASK_INFLIGHT", "请求或编辑申请尚未完成")
            if record["write"] is not None:
                raise TaskConflict("WRITE_STAGE_ACTIVE", "先结束编辑阶段 再结束任务登记")
            self.tasks.pop(task_token)
            self._signal()
            return {"released": record["task_id"], "remaining_tasks": len(self.tasks),
                "shutdown_allowed": not self.tasks and not self.inflight}

    def begin(self, params, token, write_token=None):
        """
        /**
         * 在转发前原子检查凭证 并持续计数到实际响应完成
         * @param params	完整工具调用参数
         * @param token	服务端占用凭证
         * @return 本请求占用记录
         */
        """
        readonly = is_read_call(params)
        toolset, name, business = tool_identity(params)
        definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
        opaque = {value.replace("_", "").lower() for value in access_policy.OPAQUE_TOOLS}
        if name.replace("_", "").lower() in opaque or (definition == "BBBExternalToolset" and name == "util" and business.get("action") == "execute_console_command"):
            raise TaskConflict("OPAQUE_EXECUTION_BLOCKED", "共享入口禁止任意脚本和控制台执行 批量使用逐项检查的 call_many 专用操作使用注册工具")
        if definition == "BBBGenericEditorToolset" and name == "generate_and_inspect_pcg" and business.get("generate", False):
            raise TaskConflict("ACTIVITY_TRACKING_REQUIRED", "PCG 异步生成尚无可回读完成状态 共享入口暂不执行生成 只读核验仍可由占用任务执行")
        with self.lock:
            self._expire()
            if self.draining:
                raise TaskConflict("HOST_DRAINING", "宿主退出中")
            record = self._record(token) if token else None
            if not readonly:
                if self.host_changed:
                    raise TaskConflict("HOST_CHANGED", "宿主身份变化 凭证失效")
                if record is None or record["mode"] == "read":
                    raise TaskConflict("EDITOR_TASK_REQUIRED", "本操作需要 editor 或 pie 任务登记", self._public(token))
                record = self._write_record(token, write_token)
                if record["status"] != "active" or record["uncertain"] or record["write"]["status"] != "active":
                    raise TaskConflict("WRITE_RECOVERY_REQUIRED", "编辑阶段尚未就绪或需要显式恢复", self._public(token))
                if record["inflight"]:
                    raise TaskConflict("TASK_INFLIGHT", "本编辑阶段的上一请求尚未完成")
                if record["pie_request"]:
                    raise TaskConflict("TASK_PIE_PENDING", "先回读实际 PIE 状态 等开始或结束请求生效")
            self.inflight += 1
            if record is not None:
                record["inflight"] += 1
                if not readonly:
                    record["write_inflight"] += 1
                record["expires_at"] = self.clock() + record["ttl_seconds"]
                record["operations"][threading.get_ident()] = {"toolset": definition, "tool": name,
                    "access": access_policy.tool_access(toolset, name, business), "started_at": self.clock()}
            self._signal()
            return record

    def finish(self, record, uncertain=False, readonly=False):
        """
        /**
         * @param record	本次请求记录
         * @param uncertain	传输失败导致执行结果不确定
         * @param readonly	本次是否为只读请求
         * @return 无返回值
         */
        """
        with self.changed:
            self.inflight -= 1
            if record is not None:
                record["operations"].pop(threading.get_ident(), None)
                record["inflight"] -= 1
                if not readonly:
                    record["write_inflight"] -= 1
                    record["uncertain"] = record["uncertain"] or uncertain
                    if record["write"] is not None:
                        record["write"]["expires_at"] = self.clock() + record["write"]["ttl_seconds"]
                record["expires_at"] = self.clock() + record["ttl_seconds"]
            self._signal()

    def prepare_shutdown(self):
        """
        /**
         * @return 全部活动结束后锁定退出状态
         */
        """
        self._observe()
        with self.lock:
            if self.tasks or self.inflight or self.draining or self.queue or self.writer is not None:
                raise TaskConflict("HOST_BUSY", "尚有任务 编辑阶段或请求 不关闭共享宿主", self._public())
            self.draining = True
            self._signal()
        try:
            activity = self._observe()
            if self.host_changed or activity["pie_active"] or activity["worlds"] or activity["activities"] or activity.get("dirty_packages"):
                raise TaskConflict("HOST_ACTIVITY_PENDING", "宿主尚有活动或身份已变化 不关闭", self._public())
            return activity
        except Exception:
            with self.lock:
                self.draining = False
                self._signal()
            raise


class UnrealBackend:
    """/** 官方后端连接和只读身份验证 */"""

    def __init__(self, url, project, process_id):
        """
        /**
         * 初始化本对象的任务保护状态
         * @param url	本操作输入
         * @param project	本操作输入
         * @param process_id	本操作输入
         * @return 操作结果或验证完成
         */
        """
        self.url = url
        self.project = os.path.normcase(os.path.realpath(project))
        self.process_id = process_id
        self.probe_lock = threading.Lock()
        self.task_toolset = None
        self.external_toolset = None
        self.inspection_session = None

    def probe(self):
        """
        /**
         * @return 匹配项目与进程的实际活动
         */
        """
        with self.probe_lock:
            try:
                if self.inspection_session is None:
                    self.inspection_session = McpSession(self.url, 30)
                session = self.inspection_session
                if self.task_toolset is None:
                    text = decode_tool_result(session.call_tool("list_toolsets", {}))
                    for definition in ("BBBMcpTaskToolset", "BBBExternalToolset"):
                        names = re.findall(r"(?m)^- ([^\r\n: ]+\." + definition + r"(?:_0x[0-9a-fA-F]{8})?)(?=:|\s|$)", text)
                        if len(names) != 1:
                            raise RuntimeError("活动或生命周期工具集未唯一注册 " + definition)
                        if definition == "BBBMcpTaskToolset":
                            self.task_toolset = names[0]
                        if definition == "BBBExternalToolset":
                            self.external_toolset = names[0]
                activity = decode_tool_result(session.call_tool("call_tool", {
                    "toolset_name": self.task_toolset, "tool_name": "inspect_editor_activity", "arguments": {},
                }))
                if activity["process_id"] != self.process_id or os.path.normcase(os.path.realpath(activity["project_root"])) != self.project:
                    raise RuntimeError("后端宿主项目或进程身份不匹配")
                return activity
            except Exception:
                if self.inspection_session is not None:
                    self.inspection_session.close()
                self.inspection_session = None
                self.task_toolset = None
                raise

    def shutdown(self):
        """
        /**
         * @return 官方退出请求结果 不将请求当作进程已退出
         */
        """
        with McpSession(self.url, 15) as session:
            return session.call_tool("call_tool", {"toolset_name": self.external_toolset, "tool_name": "util",
                "arguments": {"action": "execute_console_command", "params_json": json.dumps({"command": "QUIT_EDITOR"})}})

    def close(self):
        """
        /**
         * @return 释放本网关的只读检查会话 不结束任务或 UE
         */
        """
        with self.probe_lock:
            if self.inspection_session is not None:
                self.inspection_session.close()
                self.inspection_session = None

    def relay(self, body, headers, method="POST"):
        """
        /**
         * @param body	原始协议对象
         * @param headers	客户端协议会话头
         * @param method	HTTP 方法
         * @return HTTP 状态 响应头和最终协议对象
         */
        """
        forwarded = {name: value for name, value in headers.items() if name.lower() in {
            "mcp-session-id", "mcp-protocol-version", "content-type", "accept",
        }}
        forwarded["Accept"] = "application/json, text/event-stream"
        with requests.Session() as transport:
            transport.trust_env = False
            with transport.request(method, self.url, json=body, headers=forwarded, timeout=(5, 600), stream=True) as response:
                output_headers = {name: value for name, value in response.headers.items() if name.lower() in {
                    "mcp-session-id", "mcp-protocol-version",
                }}
                if method == "DELETE" or body is None or "id" not in body or not response.ok:
                    return response.status_code, output_headers, response.content
                result = _parse_response(response, body["id"], lambda: None)
                return response.status_code, output_headers, result


class TaskGateway:
    """/** 所有客户端共享的 MCP 调用边界 */"""

    def __init__(self, backend):
        """
        /**
         * 初始化本对象的任务保护状态
         * @param backend	本操作输入
         * @return 操作结果或验证完成
         */
        """
        self.backend = backend
        self.coordinator = TaskCoordinator(backend.probe)
        self.sessions = set()
        self.session_lock = threading.Lock()

    def _control(self, name, arguments):
        """
        /**
         * 执行任务管理接口
         * @param name	本操作输入
         * @param arguments	本操作输入
         * @return 操作结果或验证完成
         */
        """
        specification = _CONTROL_SPEC[name]
        if not isinstance(arguments, dict) or set(arguments) - set(specification[1]) or set(specification[2]) - set(arguments):
            raise ValueError("任务工具参数不符合发现结构")
        if name == "acquire_editor_task":
            return self.coordinator.acquire(**arguments)
        if name == "renew_editor_task":
            return self.coordinator.renew(**arguments)
        if name == "begin_editor_write":
            return self.coordinator.begin_write(**arguments)
        if name == "cancel_editor_write":
            return self.coordinator.cancel_write(**arguments)
        if name == "renew_editor_write":
            return self.coordinator.renew_write(**arguments)
        if name == "end_editor_write":
            return self.coordinator.end_write(**arguments)
        if name == "release_editor_task":
            return self.coordinator.release(**arguments)
        if name == "inspect_editor_tasks":
            return self.coordinator.inspect(**arguments)
        self.coordinator.prepare_shutdown()
        try:
            self.backend.shutdown()
        except RuntimeError:
            pass
        return {"status": "shutdown_requested", "process_id": self.backend.process_id, "exited": False}

    def _reply(self, request_id, value, error=False):
        """
        /**
         * 构造最终协议业务响应
         * @param request_id	本操作输入
         * @param value	本操作输入
         * @param error	本操作输入
         * @return 操作结果或验证完成
         */
        """
        return 200, {}, {"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": error,
        }}

    def _annotate_discovery(self, payload, toolset=""):
        """
        /**
         * 将统一权限分类写入实际发现结果
         * @param payload	协议结果或描述对象
         * @param toolset	描述目标工具集
         * @return 无返回值
         */
        """
        if not isinstance(payload, dict):
            return
        for tool in payload.get("tools", []):
            name = tool.get("name", "")
            if name in _CONTROL_SPEC:
                continue
            definition = toolset
            if "." in name:
                definition, name = name.rsplit(".", 1)
            access = access_policy.tool_access(definition, name)
            if name == "call_tool":
                access = "conditional"
            label = {"shared_read": "共享查询 可在其他任务编辑期间读取",
                "editor_write": "编辑操作 取得编辑阶段后执行",
                "pie_write": "PIE 操作 由持有阶段的任务控制",
                "conditional": "按实际参数检查权限 参照 bbb_task 权限清单",
                "blocked": "共享入口使用已注册的专用工具"}[access]
            tool.setdefault("_meta", {})["bbb/access"] = access
            tool["description"] = tool.get("description", "") + "\n" + label
        for key, value in list(payload.items()):
            if key == "tools":
                continue
            if isinstance(value, dict):
                self._annotate_discovery(value, toolset)
            if isinstance(value, list):
                for child in value:
                    self._annotate_discovery(child, toolset)
            if key in {"text", "returnValue"} and isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (ValueError, TypeError):
                    continue
                self._annotate_discovery(parsed, toolset)
                payload[key] = json.dumps(parsed, ensure_ascii=False)

    def _guide_state(self, value, state):
        """
        /**
         * 将实时占用附加到 AI 使用指南的业务内容
         * @param value	指南结果包装
         * @param state	精简占用信息
         * @return 保持原包装类型的结果
         */
        """
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return value
            return json.dumps(self._guide_state(parsed, state), ensure_ascii=False)
        if isinstance(value, dict) and "returnValue" in value:
            value["returnValue"] = self._guide_state(value["returnValue"], state)
            return value
        if isinstance(value, dict):
            value["editor_state"] = state
        return value

    def handle(self, body, headers, method="POST"):
        """
        /**
         * @param body	完整 JSON RPC 请求
         * @param headers	协议会话头
         * @param method	HTTP 方法
         * @return 可发送的协议结果
         */
        """
        session_id = next((value for key, value in headers.items() if key.lower() == "mcp-session-id"), None)
        rpc_method = body.get("method") if isinstance(body, dict) else None
        if rpc_method != "initialize":
            with self.session_lock:
                if session_id not in self.sessions:
                    return 404, {}, b"MCP session unknown"
        if method == "DELETE":
            try:
                return self.backend.relay(None, headers, method)
            except requests.RequestException:
                return 404, {}, b"MCP backend session unavailable"
            finally:
                with self.session_lock:
                    self.sessions.discard(session_id)
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return 400, {}, b"Invalid JSON RPC"
        request_id = body.get("id")
        record = None
        counted = False
        token = None
        outgoing = None
        name = None
        forwarded = copy.deepcopy(body)
        try:
            if rpc_method == "tools/call":
                params = forwarded.get("params", {})
                if not isinstance(params, dict) or not isinstance(params.get("arguments", {}), dict):
                    raise ValueError("工具参数必须为对象")
                toolset, name, arguments = tool_identity(params)
                token = params.get("arguments", {}).get("task_token", params.get("_meta", {}).get("bbb/task_token"))
                if not toolset and name in _CONTROL_SPEC:
                    if name == "inspect_editor_tasks" and token and "task_token" not in arguments:
                        arguments["task_token"] = token
                    outgoing = self._reply(request_id, self._control(name, arguments))
                    return outgoing
                if not toolset and name == "describe_toolset" and arguments.get("toolset_name") == "bbb_task":
                    outgoing = self._reply(request_id, {"tools": control_tools(), "access_policy": access_policy.access_catalog()})
                    return outgoing
                token = params.get("arguments", {}).pop("task_token", None)
                write_token = params.get("arguments", {}).pop("write_token", None)
                metadata = params.get("_meta", {})
                if token is None:
                    token = metadata.get("bbb/task_token")
                if write_token is None:
                    write_token = metadata.get("bbb/write_token")
                metadata.pop("bbb/task_token", None)
                metadata.pop("bbb/write_token", None)
                if not is_read_call(params):
                    self.coordinator._observe()
                    if self.coordinator.host_changed:
                        raise TaskConflict("HOST_CHANGED", "宿主身份变化 凭证失效")
                record = self.coordinator.begin(params, token, write_token)
                counted = True
                definition, function, business = tool_identity(params)
                normalized_definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", definition.rsplit(".", 1)[-1])
                if normalized_definition == "BBBExternalToolset" and function == "util" and business.get("action") in {"start_pie", "stop_pie"}:
                    record["pie_request"] = business["action"]
                if normalized_definition == "EditorAppToolset" and function in {"StartPIE", "StopPIE"}:
                    record["pie_request"] = {"StartPIE": "start_pie", "StopPIE": "stop_pie"}[function]
                result = self.backend.relay(forwarded, headers)
                if record is not None and not is_read_call(params):
                    self.coordinator._observe()
                    failed = result[0] >= 400
                    if isinstance(result[2], dict):
                        failed = failed or bool(result[2].get("error") or result[2].get("result", {}).get("isError"))
                        if not failed:
                            try:
                                decode_tool_result(result[2])
                            except McpBusinessError:
                                failed = True
                    if failed:
                        with self.coordinator.lock:
                            record["uncertain"] = True
                if not toolset and name == "list_toolsets" and isinstance(result[2], dict):
                    result[2]["result"]["content"][0]["text"] += "\n- bbb_task: 当前占用 可执行工作 持续排队与编辑交接\n"
                if not toolset and name == "describe_toolset" and isinstance(result[2], dict):
                    self._annotate_discovery(result[2], arguments.get("toolset_name", ""))
                outgoing = result
                return outgoing
            if rpc_method not in {"initialize", "notifications/initialized", "ping", "tools/list", "notifications/cancelled"}:
                raise TaskConflict("PROTOCOL_OPERATION_BLOCKED", "未审查的协议操作不转发")
            if rpc_method == "notifications/cancelled":
                raise TaskConflict("CANCELLATION_BLOCKED", "取消不能解除后台活动 请使用本任务的停止工具")
            result = self.backend.relay(forwarded, headers)
            if rpc_method == "initialize" and 200 <= result[0] < 300:
                created_session = next((value for key, value in result[1].items() if key.lower() == "mcp-session-id"), None)
                if created_session:
                    with self.session_lock:
                        self.sessions.add(created_session)
            if rpc_method == "tools/list" and isinstance(result[2], dict):
                result[2]["result"]["tools"].extend(control_tools())
                for tool in result[2]["result"]["tools"]:
                    if tool["name"] not in _CONTROL_SPEC:
                        tool["inputSchema"].setdefault("properties", {})["task_token"] = {"type": "string", "description": "共享宿主任务占用凭证"}
                        tool["inputSchema"]["properties"]["write_token"] = {"type": "string", "description": "当前编辑阶段凭证"}
                self._annotate_discovery(result[2])
            outgoing = result
            return outgoing
        except TaskConflict as error:
            logging.warning("[BBBMcpTask] %s", error.value["code"])
            outgoing = self._reply(request_id, error.value, True)
            return outgoing
        except (ValueError, TypeError, KeyError) as error:
            outgoing = self._reply(request_id, {"success": False, "code": "INVALID_ARGUMENTS", "message": str(error)}, True)
            return outgoing
        except Exception:
            if counted and record is not None and not is_read_call(forwarded["params"]):
                with self.coordinator.lock:
                    record["uncertain"] = True
            logging.error("[BBBMcpTask] 后端请求失败 执行状态需回读")
            outgoing = self._reply(request_id, {"success": False, "code": "BACKEND_UNCERTAIN", "message": "后端状态不确定 先检查宿主 再凭原凭证恢复 不自动重试"}, True)
            return outgoing
        finally:
            if counted:
                self.coordinator.finish(record, readonly=is_read_call(forwarded["params"]))
            if outgoing is not None and rpc_method in {"tools/call", "tools/list"} and isinstance(outgoing[2], dict):
                payload = outgoing[2].get("result")
                if isinstance(payload, dict):
                    state = self.coordinator._public(token, compact=True)
                    payload.setdefault("_meta", {})["bbb/editor_state"] = state
                    if name == "list_toolsets":
                        for item in payload.get("content", []):
                            if item.get("type") == "text":
                                item["text"] += "\n当前占用: " + json.dumps(state, ensure_ascii=False)
                    if name == "get_mcp_usage_guide" and not payload.get("isError"):
                        if "structuredContent" in payload:
                            payload["structuredContent"] = self._guide_state(payload["structuredContent"], state)
                        for item in payload.get("content", []):
                            if item.get("type") == "text":
                                item["text"] = self._guide_state(item["text"], state)


def make_server(address, gateway):
    """
    /**
     * @param address	仅本机的监听地址和端口
     * @param gateway	任务网关
     * @return HTTP 服务
     */
    """
    class Handler(BaseHTTPRequestHandler):
        """/** 单请求协议转发 不记录占用凭证 */"""

        def do_POST(self):
            """
            /**
             * 处理 MCP 请求
             * @return 操作结果或验证完成
             */
            """
            self._serve("POST")

        def do_DELETE(self):
            """
            /**
             * 只释放 HTTP 会话
             * @return 操作结果或验证完成
             */
            """
            self._serve("DELETE")

        def _serve(self, method):
            """
            /**
             * 处理本机 HTTP 请求
             * @param method	本操作输入
             * @return 操作结果或验证完成
             */
            """
            if self.path != "/mcp":
                self.send_error(404)
                return
            if self.headers.get("Origin") or self.headers.get("Host") not in {
                "127.0.0.1:{}".format(self.server.server_port), "localhost:{}".format(self.server.server_port),
            }:
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 16 * 1024 * 1024:
                    raise ValueError("请求过大")
                body = json.loads(self.rfile.read(size)) if size else None
                status, headers, result = gateway.handle(body, dict(self.headers), method)
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
                return
            payload = result if isinstance(result, bytes) else json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            """
            /**
             * 禁止记录请求中的任务凭证
             * @param format	本操作输入
             * @param args	本操作输入
             * @return 操作结果或验证完成
             */
            """
            return

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def main():
    """
    /**
     * @return 后端身份匹配后启动唯一网关
     */
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host-pid", type=int, required=True)
    options = parser.parse_args()
    parsed = urlparse(options.backend_url)
    if parsed.hostname != "127.0.0.1" or parsed.scheme != "http" or parsed.path == "/mcp" or parsed.port == options.port:
        raise ValueError("后端必须使用独立本机端口和私有路径")
    backend = UnrealBackend(options.backend_url, options.project_root, options.host_pid)
    atexit.register(backend.close)
    gateway = TaskGateway(backend)
    gateway.coordinator.inspect()
    with make_server(("127.0.0.1", options.port), gateway) as server:
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x00100000, False, options.host_pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())

            def watch_host():
                """/** 宿主退出后只关闭本网关 不终止其他进程 */"""
                try:
                    while kernel.WaitForSingleObject(handle, 1000) == 0x102:
                        pass
                    server.shutdown()
                finally:
                    kernel.CloseHandle(handle)

            threading.Thread(target=watch_host, daemon=True).start()
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
