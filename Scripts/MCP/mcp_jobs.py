import copy
import json
import secrets
import threading
import time

from MCP.mcp_result import McpBusinessError
from MCP.mcp_asset_scope import asset_targets, conflicting_packages


class JobConflict(McpBusinessError):
    """/** 任务操作的明确拒绝 */"""

    def __init__(self, code, details=None):
        """/** @param code 固定原因 @param details 必要证据 @return 拒绝结果 */"""
        super().__init__({"status": "rejected", "code": code, "details": details or {}})


class JobQueue:
    """/** 原项目批次执行槽与活动归属 */"""

    def __init__(self, backend, catalog, clock=time.monotonic, start_worker=True):
        """/** @param backend 官方后端 @param catalog 契约目录 @param clock 时间来源 @param start_worker 启动执行循环 @return 批次调度 */"""
        self.backend = backend
        self.catalog = catalog
        self.clock = clock
        self.changed = threading.Condition(threading.RLock())
        self.jobs = {}
        self.queue = []
        self.clients = {}
        self.client_owners = set()
        self.writer = None
        self.pie_owner = None
        self.pie_batch = None
        self.pie_pending = False
        self.activity_owners = {}
        self.activity = None
        self.host_identity = None
        self.revision = 0
        self.draining = False
        self.host_changed = False
        self.shutdown_requested = False
        self.closed = False
        self.worker = None
        self.probe_lock = threading.Lock()
        self.observed_at = None
        self.call_active = False
        self.observe(force=True)
        if start_worker:
            self.worker = threading.Thread(target=self._loop, daemon=True, name="BBB-MCP-batches")
            self.worker.start()

    def connect(self, resume_key=None):
        """/** @param resume_key 原连接凭证 @return 本客户端私有凭证 */"""
        with self.changed:
            owners = {job["owner"] for job in self.jobs.values()} | set(self.activity_owners.values()) | self.client_owners
            if self.pie_owner is not None:
                owners.add(self.pie_owner)
            self.clients = {key: deadline for key, deadline in self.clients.items() if deadline > self.clock() or key in owners or key == resume_key}
            if resume_key is not None and resume_key not in self.clients:
                raise JobConflict("CLIENT_KEY_INVALID")
            key = resume_key or secrets.token_urlsafe(32)
            self.clients[key] = self.clock() + 300
            return key

    def touch(self, client):
        """/** @param client 客户端凭证 @return 续期完成 */"""
        with self.changed:
            if client not in self.clients:
                raise JobConflict("CLIENT_KEY_INVALID")
            self.clients[client] = self.clock() + 300

    def _signal(self):
        self.revision += 1
        self.changed.notify_all()

    def observe(self, force=False):
        """/** @param force 边界立即核验 @return 共享实际快照 */"""
        if not force and self.call_active and self.activity is not None:
            return copy.deepcopy(self.activity)
        if not self.probe_lock.acquire(blocking=force):
            return copy.deepcopy(self.activity)
        try:
            if not force and self.observed_at is not None and self.clock() - self.observed_at < 1:
                return copy.deepcopy(self.activity)
            try:
                snapshot = self.backend.probe()
            except Exception:
                if self.activity is None:
                    raise
                with self.changed:
                    previous = self.activity
                    self.activity = {**previous, "host_verified": False}
                    self.draining = True
                    self.observed_at = self.clock()
                    if previous != self.activity:
                        self._signal()
                    return copy.deepcopy(self.activity)
            identity = (snapshot["process_id"], snapshot["host_instance"])
            business = {key: snapshot.get(key) for key in ("process_id", "host_instance", "pie_active", "pie_generation", "worlds", "activities", "dirty_packages")}
            hosts = snapshot.get("project_hosts", {})
            business["host_exclusive"] = hosts.get("verified", True) and hosts.get("exclusive", True)
            business["host_verified"] = True
            with self.changed:
                previous = self.activity
                if self.host_identity is None:
                    self.host_identity = identity
                if self.host_identity != identity:
                    self.host_changed = True
                self.draining = self.shutdown_requested or self.host_changed or not business["host_exclusive"]
                self.activity = business
                self.observed_at = self.clock()
                if previous != business:
                    self._signal()
                active = {item["id"] if isinstance(item, dict) else item for item in business.get("activities", [])}
                self.activity_owners = {key: owner for key, owner in self.activity_owners.items() if key in active}
                if not self.draining:
                    for job in self.jobs.values():
                        if job["status"] == "review" and job["code"] == "DIRTY_ASSETS" and job["completed"] == len(job["operations"]):
                            remaining = conflicting_packages(business.get("dirty_packages", []), job["owned_dirty"])
                            if not remaining and not job["activities"] & active:
                                job["status"] = "completed"
                                job["code"] = None
                                job["dirty"] = []
                                job["execution"] = "completed"
                                self._signal()
                if not self.pie_pending and not business.get("pie_active") and not business.get("worlds"):
                    self.pie_owner = None
                    self.pie_batch = None
                return copy.deepcopy(business)
        finally:
            self.probe_lock.release()

    def submit(self, client, operations, label=""):
        """/** @param client 客户端 @param operations 完整批次 @param label 阶段用途 @return 即时接收结果 */"""
        self.touch(client)
        prepared = self.catalog.prepare(operations)
        with self.changed:
            if self.draining:
                raise JobConflict("HOST_DRAINING")
            if len(self.queue) >= 64 or len(self.jobs) >= 256:
                raise JobConflict("QUEUE_CAPACITY", {"next": "control_task.close"})
            identity = secrets.token_hex(8)
            job = {"id": identity, "owner": client, "label": label, "operations": prepared,
                "status": "queued", "completed": 0, "results": [], "submitted_at": self.clock(),
                "access": "read" if all(item["access"] == "read" for item in prepared) else "write",
                "targets": set().union(*(asset_targets(item.get("targets", [])) for item in prepared)) if all(item.get("scoped", item["access"] == "read") for item in prepared) else set(),
                "scoped": all(item.get("scoped", item["access"] == "read") for item in prepared),
                "baseline": [], "dirty": [], "owned_dirty": set(), "await_activity": set(), "started": False,
                "activities": set(), "effects_completed": 0,
                "code": None, "failed_index": None, "review": None}
            self.jobs[identity] = job
            self.queue.append(identity)
            self._signal()
            return self._job_view(job)

    def _reason(self, job, activity):
        job.pop("blocked", None)
        if self.draining:
            return "HOST_DRAINING"
        active_ids = {item["id"] if isinstance(item, dict) else item for item in activity.get("activities", [])}
        if job["await_activity"] & active_ids:
            return "ACTIVITY_RUNNING"
        operations = job["operations"][job["completed"]:]
        if all(item["access"] == "read" for item in operations):
            return None
        if job["access"] == "read":
            return None
        corrective = all(self._is_corrective(item) for item in operations)
        for pending in self.jobs.values():
            if pending["status"] != "review" or pending["access"] == "read":
                continue
            scope = set(pending["targets"]) | set(pending["dirty"])
            if corrective and pending["owner"] == job["owner"] and conflicting_packages(job["targets"], scope) == job["targets"]:
                continue
            conflicts = conflicting_packages(scope, job["targets"])
            if not pending["scoped"] or not scope or not job["scoped"] or conflicts:
                job["blocked"] = {"batch": pending["id"], "mine": pending["owner"] == job["owner"], "packages": sorted(conflicts)[:8], "next": "owner_review"}
                return "RESULT_REVIEW_REQUIRED"
        blocking_activities = [item for item in activity.get("activities", []) if not isinstance(item, dict) or item.get("blocking", True)]
        if blocking_activities:
            owners = {self.activity_owners.get(item["id"] if isinstance(item, dict) else item) for item in blocking_activities}
            if owners - {job["owner"]}:
                return "ACTIVITY_OWNED"
            if operations[0]["access"] != "read" and operations[0]["world"] == "editor":
                return "ACTIVITY_RUNNING"
        if activity.get("pie_active") or activity.get("worlds"):
            if self.pie_owner != job["owner"]:
                return "PIE_OWNED"
            if operations[0]["access"] != "read" and operations[0]["world"] == "editor":
                return "EDITOR_WORLD_REQUIRED"
        dirty = set(activity.get("dirty_packages", [])) - job["owned_dirty"]
        if job.get("yield_dirty") is not None:
            dirty.intersection_update(job["yield_dirty"])
        conflicts = conflicting_packages(dirty, job["targets"])
        if conflicts and not corrective:
            job["blocked"] = {"packages": sorted(conflicts)[:8], "count": len(conflicts), "next": "owner_save"}
            return "TARGET_ALREADY_DIRTY"
        if dirty and not job["targets"] and not job["scoped"] and not corrective:
            job["blocked"] = {"next": "scope_required"}
            return "DIRTY_BASELINE_UNSCOPED"
        return None

    def _is_corrective(self, operation):
        """/** @param operation 已校验操作 @return 保存 停止或明确授权丢弃的重载收尾操作 */"""
        contract = operation["contract"]
        if contract["name"] in {"save_assets", "StopPIE"} or contract.get("action") == "stop_pie":
            return True

        if contract["id"] != "editor.reload_assets_from_disk":
            return False

        arguments = operation["arguments"]
        targets = asset_targets(arguments.get("asset_paths", []))
        discarded = asset_targets(arguments.get("discard_dirty_packages", []))
        return arguments.get("dry_run", True) is False and bool(targets) and targets == discarded

    def run_once(self):
        """/** @return 执行一个可调度批次 */"""
        activity = self.observe()
        with self.changed:
            now = self.clock()
            for identity in list(self.queue):
                job = self.jobs[identity]
                if now >= self.clients.get(job["owner"], 0):
                    job["status"], job["code"] = "cancelled", "CLIENT_EXPIRED"
                    if job["completed"]:
                        job["status"], job["execution"] = "review", "partial"
                        job["dirty"] = sorted(job["owned_dirty"] & set(activity.get("dirty_packages", [])))
                    self.queue.remove(identity)
                    self._signal()
            selected = None
            for identity in self.queue:
                job = self.jobs[identity]
                reason = self._reason(job, activity)
                if reason is None:
                    selected = job
                    break
                if job["code"] != reason:
                    job["code"] = reason
                    self._signal()
            if selected is None:
                return False
            self.queue.remove(selected["id"])
            selected["status"], selected["code"] = "running", None
            if not selected["started"]:
                selected["baseline"] = list(activity.get("dirty_packages", []))
                selected["started"] = True
                selected["started_at"] = self.clock()
            if selected.get("yield_dirty") is not None:
                appeared = set(activity.get("dirty_packages", [])) - set(selected.pop("yield_dirty"))
                if selected["scoped"]:
                    appeared = conflicting_packages(appeared, selected["targets"])
                selected["owned_dirty"].update(appeared)
            selected["await_activity"].clear()
            if selected["access"] != "read":
                self.writer = selected["id"]
            self._signal()
        self._execute(selected)
        return True

    def _execute(self, job):
        operation = {}
        before_dirty = set(self.activity.get("dirty_packages", []))
        job["segment_dirty"] = before_dirty
        job["segment_activities"] = {item["id"] if isinstance(item, dict) else item for item in self.activity.get("activities", [])}
        try:
            if job["access"] != "read":
                current = self.observe(force=True)
                reason = self._reason(job, current)
                if reason:
                    raise JobConflict(reason)
            for index in range(job["completed"], len(job["operations"])):
                operation = job["operations"][index]
                job["failed_index"] = index
                contract = operation["contract"]
                start_pie = contract["name"] == "StartPIE" or contract.get("action") == "start_pie"
                stop_pie = contract["name"] == "StopPIE" or contract.get("action") == "stop_pie"
                if operation["world"] == "pie" and not self.activity.get("pie_active"):
                    raise JobConflict("PIE_REQUIRED")
                if operation["access"] != "read" and operation["world"] == "editor" and (self.activity.get("pie_active") or self.activity.get("worlds")):
                    raise JobConflict("EDITOR_WORLD_REQUIRED")
                if start_pie:
                    with self.changed:
                        if self.activity.get("pie_active") or self.activity.get("worlds"):
                            raise JobConflict("PIE_ALREADY_ACTIVE")
                        if self.pie_owner not in {None, job["owner"]}:
                            raise JobConflict("PIE_OWNED")
                        self.pie_owner = job["owner"]
                        self.pie_batch = job["id"]
                        self.pie_pending = True
                before_activities = {item["id"] if isinstance(item, dict) else item for item in self.activity.get("activities", [])}
                job["segment_activities"] = before_activities
                before_dirty = set(self.activity.get("dirty_packages", []))
                job["segment_dirty"] = before_dirty
                self.call_active = True
                try:
                    result = self.backend.invoke(contract, operation["arguments"])
                finally:
                    self.call_active = False
                if result is False and operation["access"] != "read":
                    raise McpBusinessError({"success": False, "code": "OPERATION_FALSE", "execution": {"state": "unknown"}})
                job["results"].append(result)
                job["completed"] += 1
                if operation["access"] != "read":
                    job["effects_completed"] += 1
                if start_pie or stop_pie:
                    self._wait_pie(start_pie, job)
                    self.pie_pending = False
                if operation["access"] != "read":
                    snapshot = self.observe(force=True)
                    if not snapshot["host_verified"]:
                        raise RuntimeError("HOST_UNVERIFIED")
                    job["owned_dirty"].update(set(snapshot.get("dirty_packages", [])) - before_dirty)
                    for item in snapshot.get("activities", []):
                        identity = item["id"] if isinstance(item, dict) else item
                        if identity not in before_activities:
                            self.activity_owners[identity] = job["owner"]
                            job["activities"].add(identity)
                            if not isinstance(item, dict) or (item.get("blocking", True) and item.get("wait", True)):
                                job["await_activity"].add(identity)
                    if job["await_activity"]:
                        self._yield_activity(job, snapshot)
                        return
            current = self.observe(force=job["access"] != "read")
            if job["access"] != "read" and not current["host_verified"]:
                raise RuntimeError("HOST_UNVERIFIED")
            job["dirty"] = sorted(job["owned_dirty"] & set(current.get("dirty_packages", [])))
            if job["dirty"]:
                self._review(job, "DIRTY_ASSETS", "partial")
                return
            with self.changed:
                job["status"], job["failed_index"] = "completed", None
                if self.writer == job["id"]:
                    self.writer = None
                self._signal()
        except JobConflict as error:
            if job["effects_completed"]:
                self._review(job, error.value["code"], "partial")
                return
            with self.changed:
                job["status"], job["code"] = "rejected", error.value["code"]
                if self.writer == job["id"]:
                    self.writer = None
                if not self.activity.get("pie_active"):
                    self.pie_owner = None
                    self.pie_batch = None
                    self.pie_pending = False
                self._signal()
        except McpBusinessError as error:
            job["failure"] = copy.deepcopy(error.value)
            if operation.get("access") == "read" and job["effects_completed"]:
                self._review(job, "READ_FAILED", "partial")
                return
            if job["access"] == "read" or operation.get("access") == "read":
                with self.changed:
                    job["status"], job["code"] = "rejected", "READ_FAILED"
                    if self.writer == job["id"]:
                        self.writer = None
                    self._signal()
                return
            state = error.value.get("execution", {}).get("state", "unknown")
            code = error.value.get("code", "TOOL_FAILED")
            if state == "rejected":
                current = self.observe(force=True)
                if self.pie_batch == job["id"] and contract["name"] == "StartPIE":
                    self.pie_pending = False
                    if not current.get("pie_active") and not current.get("worlds"):
                        self.pie_owner = None
                        self.pie_batch = None
                dirty = sorted((job["owned_dirty"] | (set(current.get("dirty_packages", [])) - before_dirty)) & set(current.get("dirty_packages", [])))
                if dirty or job["effects_completed"]:
                    job["dirty"] = dirty
                    self._review(job, "REJECTION_STATE_CHANGED", "partial")
                    return
                with self.changed:
                    job["status"], job["code"] = "rejected", code
                    if self.writer == job["id"]:
                        self.writer = None
                    self._signal()
                return
            self._review(job, code, state)
        except Exception as error:
            job["failure"] = {"error": str(error), "type": type(error).__name__}
            if operation.get("access") == "read" and job["effects_completed"]:
                self._review(job, "READ_FAILED", "partial")
                return
            if job["access"] == "read" or operation.get("access") == "read":
                with self.changed:
                    job["status"], job["code"] = "rejected", "READ_FAILED"
                    if self.writer == job["id"]:
                        self.writer = None
                    self._signal()
                return
            self._review(job, "EXECUTION_UNVERIFIED", "unknown")

    def _wait_pie(self, running, job):
        deadline = self.clock() + 30
        while self.clock() < deadline and not self.closed:
            snapshot = self.observe(force=True)
            if not snapshot["host_verified"]:
                raise RuntimeError("HOST_UNVERIFIED")
            active = bool(snapshot.get("pie_active") or snapshot.get("worlds"))
            if active == running:
                return
            time.sleep(0.1)
        raise McpBusinessError({"success": False, "code": "PIE_TRANSITION_UNVERIFIED", "execution": {"state": "unknown"}})

    def _yield_activity(self, job, snapshot):
        """/** @param job 已派发批次 @param snapshot 活动证据 @return 让出执行槽等待活动 */"""
        with self.changed:
            job["status"], job["code"] = "queued", "ACTIVITY_RUNNING"
            job["yield_dirty"] = list(snapshot.get("dirty_packages", []))
            self.queue.insert(0, job["id"])
            if self.writer == job["id"]:
                self.writer = None
            self._signal()

    def _review(self, job, code, execution):
        try:
            current = self.observe(force=True)
            scope = job["owned_dirty"] | (set(current.get("dirty_packages", [])) - job.get("segment_dirty", set(job["baseline"])))
            dirty = sorted(scope & set(current.get("dirty_packages", [])))
            for item in current.get("activities", []):
                identity = item["id"] if isinstance(item, dict) else item
                if identity not in job.get("segment_activities", set()) and identity not in self.activity_owners:
                    self.activity_owners[identity] = job["owner"]
                    job["activities"].add(identity)
        except Exception:
            dirty = list(job["dirty"])
        with self.changed:
            job["status"], job["code"], job["dirty"] = "review", code, dirty
            job["execution"] = execution
            if self.writer == job["id"]:
                self.writer = None
            self._signal()

    def control(self, client, action, batch=None, confirmation=None):
        """/** @param client 客户端 @param action 控制动作 @param batch 批次 @param confirmation 核实确认 @return 操作结果 */"""
        self.touch(client)
        if action == "shutdown_host":
            with self.changed:
                if self.queue or self.writer or any(job["status"] == "review" for job in self.jobs.values()):
                    raise JobConflict("HOST_BUSY")
            self.observe(force=True)
            with self.changed:
                if self.draining:
                    raise JobConflict("HOST_DRAINING")
                if self.queue or self.writer or any(job["status"] == "review" for job in self.jobs.values()) or self.activity.get("pie_active") or self.activity.get("worlds") or self.activity.get("activities") or self.activity.get("dirty_packages"):
                    raise JobConflict("HOST_BUSY")
                self.draining = True
                self.shutdown_requested = True
                self._signal()
            self.backend.shutdown()
            return {"status": "shutdown_requested"}
        with self.changed:
            job = self.jobs.get(batch)
            if job is None:
                raise JobConflict("BATCH_OWNERSHIP")
            foreign = job["owner"] != client
            orphan = self.clock() >= self.clients.get(job["owner"], 0)
            if foreign and (not orphan or action not in {"review", "resume"}):
                raise JobConflict("BATCH_OWNERSHIP")
            if action == "review" and job["status"] != "review":
                holds_activity = self.pie_owner == job["owner"] or job["owner"] in self.activity_owners.values()
                if not (foreign and orphan and job["status"] == "completed" and holds_activity):
                    raise JobConflict("REVIEW_REQUIRED")
            if action == "resume" and job["status"] != "review":
                raise JobConflict("REVIEW_REQUIRED")
            if action == "cancel":
                if job["status"] != "queued" or job["completed"]:
                    raise JobConflict("BATCH_ALREADY_DISPATCHED")
                self.queue.remove(batch)
                job["status"] = "cancelled"
                self._signal()
                return self._job_view(job)
        if action == "review":
            current = self.observe(force=True)
            with self.changed:
                foreign = job["owner"] != client
                orphan = self.clock() >= self.clients.get(job["owner"], 0)
                if foreign and not orphan:
                    raise JobConflict("BATCH_OWNERSHIP")
                holds_activity = self.pie_owner == job["owner"] or job["owner"] in self.activity_owners.values()
                if foreign and orphan and job["status"] == "completed" and holds_activity:
                    job["status"] = "review"
                    job["code"] = "OWNER_EXPIRED"
                    self._signal()
                if job["status"] != "review":
                    raise JobConflict("REVIEW_REQUIRED")
                fingerprint = json.dumps({"host": self.host_identity, "pie": current.get("pie_generation"), "dirty": current.get("dirty_packages"), "activities": current.get("activities"), "completed": job["completed"]}, sort_keys=True)
                review_id = secrets.token_hex(12)
                job["review"] = {"id": review_id, "fingerprint": fingerprint, "reviewer": client}
                return {"batch": batch, "status": "review", "completed": job["completed"], "failed_index": job["failed_index"], "dirty": job["dirty"], "execution": job.get("execution"), "confirmation": review_id}
        if action == "resume":
            current = self.observe(force=True)
            with self.changed:
                foreign = job["owner"] != client
                orphan = self.clock() >= self.clients.get(job["owner"], 0)
                if foreign and not orphan:
                    raise JobConflict("BATCH_OWNERSHIP")
                review = job["review"]
                fingerprint = json.dumps({"host": self.host_identity, "pie": current.get("pie_generation"), "dirty": current.get("dirty_packages"), "activities": current.get("activities"), "completed": job["completed"]}, sort_keys=True)
                if not review or confirmation != review["id"] or fingerprint != review["fingerprint"] or review["reviewer"] != client:
                    raise JobConflict("REVIEW_CONFIRMATION_REQUIRED")
                if foreign and orphan:
                    previous_owner = job["owner"]
                    job["owner"] = client
                    if self.pie_owner == previous_owner:
                        self.pie_owner = client
                    self.activity_owners = {key: client if owner == previous_owner else owner for key, owner in self.activity_owners.items()}
                    job["review"] = None
                    self._signal()
                    return {**self._job_view(job), "next": "submit_batch", "dirty": list(job["dirty"])}
                if self.draining or set(job["dirty"]) & set(current.get("dirty_packages", [])) or current.get("activities") or current.get("pie_active") or current.get("worlds"):
                    raise JobConflict("REVIEW_ACTIVITY_PENDING")
                job["owner"] = client
                job["status"] = "closed"
                if self.pie_owner == client:
                    self.pie_owner = None
                    self.pie_batch = None
                    self.pie_pending = False
                if self.writer == batch:
                    self.writer = None
                self._signal()
                return self._job_view(job)
        if action == "close":
            with self.changed:
                if self.pie_batch == batch or job["activities"] & set(self.activity_owners):
                    raise JobConflict("OWNED_ACTIVITY_PENDING")
                if job["status"] not in {"completed", "rejected", "cancelled", "closed"}:
                    raise JobConflict("BATCH_ACTIVE")
                del self.jobs[batch]
                self._signal()
                return {"batch": batch, "status": "closed"}
        raise JobConflict("CONTROL_ACTION")

    def _job_view(self, job, detail=False):
        result = {"batch": job["id"], "status": job["status"], "completed": job["completed"]}
        if job["code"]:
            result["code"] = job["code"]
        if job.get("blocked"):
            result["blocked"] = copy.deepcopy(job["blocked"])
        if job["status"] == "queued":
            result["ahead"] = self.queue.index(job["id"])
        if job["status"] == "review":
            result["next"] = "control_task"
            if job["code"] == "DIRTY_ASSETS":
                result["next"] = "submit_batch"
                result["pending_save"] = {"packages": job["dirty"][:8], "count": len(job["dirty"])}
        if detail:
            result.update({"results": copy.deepcopy(job["results"]), "dirty": list(job["dirty"]), "failed_index": job["failed_index"]})
            result["elapsed_seconds"] = int(self.clock() - job.get("started_at", job["submitted_at"]))
            if job.get("failure"):
                result["failure"] = copy.deepcopy(job["failure"])
            if job.get("execution"):
                result["execution"] = job["execution"]
        return result

    def inspect(self, client, batch=None, detail=False, after_revision=None, wait_seconds=0):
        """/** @param client 客户端 @param batch 批次 @param detail 完整证据 @param after_revision 业务版本 @param wait_seconds 等待上限 @return 状态与下一步 */"""
        self.touch(client)
        deadline = self.clock() + wait_seconds
        while True:
            self.observe()
            with self.changed:
                if after_revision is None or self.revision != after_revision or self.clock() >= deadline:
                    if batch:
                        job = self.jobs.get(batch)
                        if job is None or job["owner"] != client:
                            raise JobConflict("BATCH_OWNERSHIP")
                        return {"revision": self.revision, **self._job_view(job, detail)}
                    result = {"revision": self.revision, "host": {"process_id": self.activity["process_id"], "exclusive": self.activity["host_exclusive"], "verified": self.activity["host_verified"]}, "status": "draining" if self.draining else "ready", "available": ["read", "prepare"], "queued": len(self.queue), "pie": bool(self.activity.get("pie_active")), "activities": len(self.activity.get("activities", [])), "dirty": len(self.activity.get("dirty_packages", [])), "next": "submit_batch"}
                    blockers = [job for job in self.jobs.values() if job["status"] in {"running", "review"}]
                    blockers.sort(key=lambda job: job["status"] != "running")
                    if blockers:
                        blocker = blockers[0]
                        result["occupant"] = {"batch": blocker["id"], "label": blocker["label"], "status": blocker["status"], "mine": blocker["owner"] == client}
                    if result["pie"] and not blockers:
                        owner = self.jobs.get(self.pie_batch)
                        if owner is not None:
                            result["occupant"] = {"batch": owner["id"], "label": owner["label"], "status": "pie", "mine": owner["owner"] == client}
                        if owner is None:
                            result["occupant"] = {"status": "pie", "source": "editor", "mine": False}
                    if result["activities"] and not blockers and not result.get("occupant"):
                        active = [job for job in self.jobs.values() if job["activities"] & set(self.activity_owners)]
                        if active:
                            owner = active[0]
                            result["occupant"] = {"batch": owner["id"], "label": owner["label"], "status": "activity", "mine": owner["owner"] == client}
                    global_review = any(job["status"] == "review" and not job["targets"] and not job["dirty"] for job in self.jobs.values())
                    if not self.writer and not result["pie"] and not result["activities"] and not self.draining and not global_review:
                        result["available"].append("edit")
                    if result["pie"]:
                        result["pie_owner"] = "mine" if self.pie_owner == client else "other"
                    if self.draining:
                        result["available"] = ["prepare", "inspect"]
                    owned = [job for job in self.jobs.values() if job["owner"] == client and job["status"] in {"queued", "running", "review"}]
                    if not owned:
                        owned = [job for job in self.jobs.values() if job["owner"] == client]
                    if owned:
                        result["batch"] = self._job_view(owned[-1])
                        result["next"] = "inspect_tasks" if owned[-1]["status"] in {"queued", "running"} else result["batch"].get("next", "control_task")
                    if detail:
                        result["evidence"] = copy.deepcopy(self.activity)
                        result["batches"] = [{**self._job_view(job), "label": job["label"]} for job in self.jobs.values() if job["owner"] == client]
                    if self.draining:
                        result["next"] = "inspect_tasks"
                    return result
                self.changed.wait(min(1, max(0, deadline - self.clock())))

    def _loop(self):
        while not self.closed:
            try:
                if self.run_once():
                    continue
            except Exception:
                with self.changed:
                    self.draining = True
                    self._signal()
            with self.changed:
                self.changed.wait(0.5 if self.queue or self.activity_owners else 2)

    def close(self):
        """/** @return 结束本调度循环 保留实际宿主 */"""
        with self.changed:
            self.closed = True
            self.changed.notify_all()
        if self.worker is not None:
            self.worker.join(2)
