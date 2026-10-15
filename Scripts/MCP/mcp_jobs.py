import copy
import secrets
import threading
import time

from MCP.mcp_result import McpBusinessError, public_value, result_artifacts, clean_result_artifacts
from pathlib import Path
from MCP.mcp_asset_scope import asset_targets, conflicting_packages
from MCP.mcp_clients import ClientRegistry
from MCP.mcp_asset_coordination import AssetCoordination


class JobConflict(McpBusinessError):
    """/** 任务操作的明确拒绝 */"""

    def __init__(self, code, details=None):
        """/** @param code 固定原因 @param details 必要证据 @return 拒绝结果 */"""
        super().__init__({"status": "rejected", "code": code, "details": details or {}})


class JobQueue:
    """/** 原项目批次执行槽与活动归属 */"""

    def __init__(self, backend, catalog, clock=time.monotonic, start_worker=True, state_path=None):
        """/** @param backend 官方后端 @param catalog 契约目录 @param clock 时间来源 @param start_worker 启动执行循环 @return 批次调度 */"""
        self.backend = backend
        self.catalog = catalog
        backend.catalog = catalog
        self.clock = clock
        self.changed = threading.Condition(threading.RLock())
        self.jobs = {}
        self.assets = AssetCoordination()
        self.queue = []
        self.clients = ClientRegistry(clock, state_path)
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
        self.activity_retry_at = 0
        self.observe(force=True)
        self._restore_jobs()
        if start_worker:
            self.worker = threading.Thread(target=self._loop, daemon=True, name="BBB-MCP-batches")
            self.worker.start()

    def connect(self, resume_key=None):
        """/** @param resume_key 原连接凭证 @return 本客户端私有凭证 */"""
        with self.changed:
            owners = {job["owner"] for job in self.jobs.values()} | set(self.activity_owners.values()) | self.client_owners
            if self.pie_owner is not None:
                owners.add(self.pie_owner)
            key = self.clients.connect(resume_key, owners)
            historical = "@" + self.clients.digest(key)
            for job in self.jobs.values():
                if job["owner"] == historical:
                    job["owner"] = key
            if self.pie_owner == historical:
                self.pie_owner = key
            self.activity_owners = {identity: key if owner == historical else owner for identity, owner in self.activity_owners.items()}
            return key

    def touch(self, client):
        """/** @param client 客户端凭证 @return 续期完成 */"""
        with self.changed:
            self.clients.touch(client)

    def _signal(self):
        self.revision += 1
        for job in self.jobs.values():
            signature = (job["owner"], job["status"], job["completed"], job["code"], tuple(job["dirty"]), repr(self.assets.view(job["id"])), repr(job.get("blocked")), job.get("execution"), tuple(sorted(job["activities"] & set(self.activity_owners))))
            if signature != job.get("signature"):
                job["signature"] = signature
                job["revision"] = job.get("revision", 0) + 1
                self._checkpoint(job)
        self.changed.notify_all()

    def _checkpoint(self, job):
        """/** @param job\t当前批次 @return 单向身份与执行边界的恢复证据 */"""
        record = {key: copy.deepcopy(job[key]) for key in ("id", "label", "status", "completed", "results", "access", "scoped", "baseline", "dirty", "effects_completed", "code", "failed_index", "timings")}
        record.update(owner=job["owner"][1:] if job["owner"].startswith("@") else self.clients.digest(job["owner"]),
            segment_dirty=sorted(job.get("segment_dirty", set(job["baseline"]))), effect_scope=sorted(job.get("effect_scope", set())), save_pending=job.get("save_pending", False),
            environment="editor",
            operations=[{"tool": item["contract"]["id"], "arguments": item["arguments"]} for item in job["operations"]],
            targets=sorted(asset_targets(job["targets"])), owned_dirty=sorted(job["owned_dirty"]),
            coordination=self.assets.view(job["id"]), uncertain=sorted(job["uncertain"]),
            activities=sorted(job["activities"]), pie=job["id"] == self.pie_batch, host=list(self.host_identity))
        for key in ("proof", "execution", "failure"):
            if key in job:
                record[key] = copy.deepcopy(job[key])
        self.clients.store_job(record)

    def _restore_jobs(self):
        """/** @return 恢复结果与保护范围 以核实流程接续中断写入 */"""
        active = {item["id"] if isinstance(item, dict) else item for item in self.activity.get("activities", [])}
        for record in self.clients.stored_jobs():
            if record["environment"] != "editor":
                continue
            if "coordination" not in record:
                if record["status"] in {"completed", "rejected", "cancelled", "closed"}:
                    self.clients.delete_job(record["id"])
                    continue
                raise JobConflict("STATE_HANDOVER_REQUIRED", {"batch": record["id"], "next": "finish_previous_gateway"})
            claim = record.pop("coordination")
            record.pop("environment")
            owner = "@" + record.pop("owner")
            self.clients[owner] = 0
            prepared = []
            try:
                prepared = self.catalog.prepare(record["operations"])
            except (ValueError, KeyError):
                prepared = [{"contract": {"id": item["tool"], "name": item["tool"].split(".")[-1]}, "arguments": item["arguments"], "access": record["access"], "world": "editor"} for item in record["operations"]]
            pie = record.pop("pie")
            host = tuple(record.pop("host"))
            record.update(owner=owner, operations=prepared, targets=set(record["targets"]), owned_dirty=set(record["owned_dirty"]), activities=set(record["activities"]),
                await_activity=set(), started=True, submitted_at=self.clock(), started_at=self.clock(), uncertain=set(record.pop("uncertain")))
            record["segment_dirty"] = set(record["segment_dirty"])
            record["effect_scope"] = set(record["effect_scope"])
            if record["status"] == "queued" and record["completed"] == 0:
                record.update(status="cancelled", code="INTERRUPTED_BEFORE_DISPATCH")
            interrupted = record["status"] in {"running", "queued"}
            if interrupted:
                code = "GATEWAY_RESTARTED" if host == self.host_identity else "HOST_EPOCH_CHANGED"
                record.update(status="failed", code=code, execution="unknown", failure={"code": code})
            if host == self.host_identity and (interrupted or claim["phase"] == "fault"):
                appeared = set(self.activity.get("dirty_packages", [])) - record["segment_dirty"]
                record["owned_dirty"].update(conflicting_packages(appeared, claim["packages"]))
                record["dirty"] = sorted(record["owned_dirty"] & set(self.activity.get("dirty_packages", [])))
                record["uncertain"].update(claim["packages"])
                self.assets.fault(record["id"], set(claim["packages"]) | set(record["dirty"]), record.get("code"), self.clock() - 2)
            if host != self.host_identity:
                record["owned_dirty"] = set()
                record["dirty"] = []
                record["uncertain"] = set()
            self.jobs[record["id"]] = record
            self.activity_owners.update({identity: owner for identity in record["activities"] & active})
            if pie and self.activity.get("pie_active"):
                self.pie_owner = owner
                self.pie_batch = record["id"]
        if self.jobs:
            with self.changed:
                self._prune_results()
                self._signal()

    def _prune_results(self):
        """/** @return 回收已交接短批次 保留必要结果重放 */"""
        finished = [job for job in self.jobs.values() if job["status"] in {"completed", "rejected", "failed", "cancelled", "closed"} and job["id"] not in self.assets.claims and job["id"] != self.pie_batch and not job["activities"] & set(self.activity_owners)]
        finished.sort(key=lambda job: job["submitted_at"])
        for job in finished:
            if self.clock() - job["submitted_at"] > 3600 or len(self.jobs) >= 256:
                del self.jobs[job["id"]]
                self.clients.delete_job(job["id"])
                self._clean_outputs(job["id"])

    def _clean_outputs(self, batch):
        """/** @param batch\t本队列批次 @return 回收所属图像输出 */"""
        if hasattr(self.backend, "project"):
            clean_result_artifacts(Path(self.backend.project) / "Saved/temp/McpResults" / batch)

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
            business = {key: snapshot.get(key) for key in ("process_id", "host_instance", "editor_world", "pie_active", "pie_generation", "worlds", "activities", "dirty_packages")}
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
        for item in prepared:
            if item["contract"].get("scope", {}).get("kind") == "world" and item["access"] != "read":
                item["targets"] = sorted(asset_targets(self.activity.get("editor_world")))
                item["scoped"] = bool(item["targets"])
        for item in prepared:
            if item["access"] == "write" and item["world"] == "editor" and not item.get("scoped"):
                raise JobConflict("ASSET_SCOPE_REQUIRED", {"tool": item["contract"]["id"], "next": "describe_tool"})
        with self.changed:
            self._prune_results()
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
                "activities": set(), "effects_completed": 0, "timings": {"operations_seconds": []},
                "code": None, "failed_index": None, "uncertain": set()}
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
        for conflict in self.assets.conflicts(job["id"], job["targets"]):
            holder = self.jobs[conflict["batch"]]
            correction = corrective and holder["owner"] == job["owner"] and bool(job["targets"]) and conflicting_packages(job["targets"], self.assets.view(holder["id"])["packages"]) == job["targets"]
            continuation = conflict["phase"] == "fault" and holder["owner"] == job["owner"] and conflicting_packages(job["targets"], self.assets.view(holder["id"])["packages"]) == job["targets"]
            if correction or continuation:
                continue
            job["blocked"] = {**conflict, "mine": holder["owner"] == job["owner"], "next": "inspect_tasks"}
            return "ASSET_BUSY"
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
        for identity, claim in self.assets.claims.items():
            if claim["phase"] == "fault" and self.jobs[identity]["owner"] == job["owner"]:
                dirty -= conflicting_packages(self.jobs[identity]["owned_dirty"], job["targets"])
        if job.get("yield_dirty") is not None:
            dirty.intersection_update(job["yield_dirty"])
        conflicts = conflicting_packages(dirty, job["targets"])
        if conflicts and not corrective:
            job["blocked"] = {"packages": sorted(conflicts)[:8], "count": len(conflicts), "next": "inspect_tasks"}
            return "ASSET_SAVE_REQUIRED"
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
        if self.pie_owner is not None and self.clock() >= self.clients.get(self.pie_owner, 0) and self.clock() >= self.activity_retry_at and not self.draining:
            self.activity_retry_at = self.clock() + 30
            try:
                contract = next(item for item in self.catalog.tools.values() if item["name"] == "StopPIE" or item.get("action") == "stop_pie")
                self.call_active = True
                self.backend.invoke(contract, {})
                self._wait_pie(False, self.jobs.get(self.pie_batch))
                self.cleanup_failure = None
            except Exception as error:
                self.cleanup_failure = {"code": "ACTIVITY_CLEANUP_FAILED", "error": str(error)}
            finally:
                self.call_active = False
            self.observe(force=True)
            return True
        with self.changed:
            now = self.clock()
            for identity in list(self.queue):
                job = self.jobs[identity]
                if now >= self.clients.get(job["owner"], 0):
                    job["status"], job["code"] = "cancelled", "CLIENT_EXPIRED"
                    if job["completed"] or job["owned_dirty"] or job["activities"]:
                        job["status"], job["execution"] = "failed", "partial"
                        job["dirty"] = sorted(job["owned_dirty"] & set(activity.get("dirty_packages", [])))
                        job["failure"] = {"code": "CLIENT_EXPIRED"}
                        self.assets.fault(job["id"], job["dirty"], "CLIENT_EXPIRED", self.clock())
                    if job["status"] == "cancelled":
                        self.assets.release(job["id"])
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
                recovery_id = self.assets.due(self.clock())
                if recovery_id is None or self.draining:
                    return False
                selected = self.jobs[recovery_id]
                self.writer = recovery_id
        if selected["status"] != "queued":
            self._reconcile(selected)
            return True
        with self.changed:
            self.queue.remove(selected["id"])
            selected["status"], selected["code"] = "running", None
            if not selected["started"]:
                selected["baseline"] = list(activity.get("dirty_packages", []))
                selected["started"] = True
                selected["started_at"] = self.clock()
                selected["timings"] = {"queue_seconds": self.clock() - selected["submitted_at"], "operations_seconds": []}
            if selected.get("yield_dirty") is not None:
                appeared = set(activity.get("dirty_packages", [])) - set(selected.pop("yield_dirty"))
                if selected["scoped"]:
                    appeared = conflicting_packages(appeared, selected["targets"])
                selected["owned_dirty"].update(appeared)
            selected["await_activity"].clear()
            if selected["access"] != "read":
                self.writer = selected["id"]
                for identity, claim in list(self.assets.claims.items()):
                    if claim["phase"] == "fault" and self.jobs[identity]["owner"] == selected["owner"]:
                        selected["owned_dirty"].update(conflicting_packages(self.jobs[identity]["owned_dirty"], selected["targets"]))
            self.assets.hold(selected["id"], selected["targets"] | selected["owned_dirty"], "executing")
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
                if hasattr(self.backend, "expand_scope"):
                    self.call_active = True
                    try:
                        for item in job["operations"][job["completed"]:]:
                            if item["access"] != "read":
                                job["targets"].update(self.backend.expand_scope(item))
                    finally:
                        self.call_active = False
                    current = self.observe(force=True)
                    job["owned_dirty"].update(set(current.get("dirty_packages", [])) - before_dirty)
                for item in job["operations"][job["completed"]:]:
                    if item["contract"].get("scope", {}).get("kind") == "world" and asset_targets(item["targets"]) != asset_targets(current.get("editor_world")):
                        raise JobConflict("EDITOR_WORLD_CHANGED")
                reason = self._reason(job, current)
                if reason:
                    with self.changed:
                        job["status"], job["code"] = "queued", reason
                        self.queue.append(job["id"])
                        self.assets.hold(job["id"], job["owned_dirty"], "waiting")
                        self.writer = None
                        self._signal()
                    return
                with self.changed:
                    self.assets.hold(job["id"], job["targets"] | job["owned_dirty"], "executing")
                    self._checkpoint(job)
            for index in range(job["completed"], len(job["operations"])):
                operation = job["operations"][index]
                job["failed_index"] = index
                job["effect_scope"] = asset_targets(operation.get("targets", []))
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
                with self.changed:
                    self._checkpoint(job)
                self.call_active = True
                called_at = self.clock()
                try:
                    result = self.backend.invoke(contract, operation["arguments"])
                finally:
                    self.call_active = False
                if result is False and operation["access"] != "read":
                    raise McpBusinessError({"success": False, "code": "OPERATION_FALSE", "execution": {"state": "unknown"}})
                job["timings"]["operations_seconds"].append(self.clock() - called_at)
                if hasattr(self.backend, "project"):
                    result = result_artifacts(result, Path(self.backend.project) / "Saved/temp/McpResults" / job["id"])
                job["results"].append(public_value(result))
                job["completed"] += 1
                with self.changed:
                    self._checkpoint(job)
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
                    with self.changed:
                        self._checkpoint(job)
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
            if not self._save_owned(job, current):
                self._recover(job, job.get("save_code", "SAVE_FAILED"), "partial", settle=False)
                return
            self._finish(job)
        except JobConflict as error:
            if job["effects_completed"]:
                job["failure"] = copy.deepcopy(error.value)
                self._recover(job, error.value["code"], "partial")
                return
            with self.changed:
                job["status"], job["code"] = "rejected", error.value["code"]
                self.assets.release(job["id"])
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
                self._recover(job, "READ_FAILED", "partial")
                return
            if job["access"] == "read" or operation.get("access") == "read":
                with self.changed:
                    job["status"], job["code"] = "rejected", "READ_FAILED"
                    self.assets.release(job["id"])
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
                    self._recover(job, "REJECTION_STATE_CHANGED", "partial")
                    return
                with self.changed:
                    job["status"], job["code"] = "rejected", code
                    self.assets.release(job["id"])
                    if self.writer == job["id"]:
                        self.writer = None
                    self._signal()
                return
            self._recover(job, code, state)
        except Exception as error:
            job["failure"] = {"error": str(error), "type": type(error).__name__}
            if operation.get("access") == "read" and job["effects_completed"]:
                self._recover(job, "READ_FAILED", "partial")
                return
            if job["access"] == "read" or operation.get("access") == "read":
                with self.changed:
                    job["status"], job["code"] = "rejected", "READ_FAILED"
                    self.assets.release(job["id"])
                    if self.writer == job["id"]:
                        self.writer = None
                    self._signal()
                return
            self._recover(job, "EXECUTION_UNVERIFIED", "unknown")

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

    def _save_owned(self, job, current=None):
        """/** @param job	所属批次 @return 自有修改完成保存与回读 */"""
        if not job["owned_dirty"]:
            return True
        for attempt in range(3):
            if current is None:
                current = self.observe(force=True)
            if not current["host_verified"] or self.draining:
                job["save_code"] = "HOST_UNVERIFIED"
                return False
            job["dirty"] = sorted(conflicting_packages(current.get("dirty_packages", []), job["owned_dirty"]))
            if not job["dirty"]:
                return True
            conflicts = self.assets.conflicts(job["id"], job["dirty"])
            if any(self.jobs[item["batch"]]["owner"] != job["owner"] for item in conflicts):
                job["save_code"] = "ASSET_OWNERSHIP_CONFLICT"
                return False
            with self.changed:
                self.assets.hold(job["id"], job["targets"] | job["owned_dirty"], "saving")
                self._signal()
            before = set(current.get("dirty_packages", []))
            started = self.clock()
            try:
                self.call_active = True
                proof = self.backend.finalize(list(job["dirty"]))
                evidence = job.setdefault("proof", {})
                for key in ("saved", "compiled"):
                    evidence[key] = sorted(set(evidence.get(key, [])) | set(proof.get(key, [])))
                evidence["readback"] = proof.get("readback", not proof.get("failures"))
            except Exception as error:
                job["uncertain"].update(job["dirty"])
                job["save_failure"] = copy.deepcopy(error.value) if isinstance(error, McpBusinessError) else {"error": str(error)}
                job["save_code"] = job["save_failure"].get("code", "SAVE_FAILED")
                return False
            finally:
                self.call_active = False
                job["timings"]["finalize_seconds"] = job["timings"].get("finalize_seconds", 0) + self.clock() - started
            current = self.observe(force=True)
            job["owned_dirty"].update(set(current.get("dirty_packages", [])) - before)
            job["dirty"] = sorted(conflicting_packages(current.get("dirty_packages", []), job["owned_dirty"]))
            if proof.get("failures"):
                job["save_failure"] = proof["failures"]
                job["save_code"] = "SAVE_FAILED"
                job["uncertain"].update(item["package"] for item in proof["failures"])
                return False
            if not job["dirty"] and current["host_verified"] and not self.draining:
                return True
            current = None
        job["save_code"] = "SAVE_INCOMPLETE"
        return not job["dirty"]

    def _finish(self, job):
        """/** @param job	已完成收尾批次 @return 发布结果并释放资产 */"""
        with self.changed:
            failed = bool(job.get("failure"))
            job["status"] = "failed" if failed else "completed"
            if not failed:
                job["code"] = None
                job["failed_index"] = None
                job["execution"] = "completed"
            job["dirty"] = []
            job["uncertain"].clear()
            job.pop("save_failure", None)
            job.pop("save_code", None)
            job.setdefault("proof", {})["dirty"] = []
            job["timings"]["total_seconds"] = self.clock() - job["submitted_at"]
            self.assets.release(job["id"])
            for identity, claim in list(self.assets.claims.items()):
                if job["access"] != "read" and claim["phase"] == "fault" and self.jobs[identity]["owner"] == job["owner"] and conflicting_packages(claim["packages"], job["targets"] | job["owned_dirty"]) == set(claim["packages"]):
                    previous = self.jobs[identity]
                    previous["dirty"] = []
                    previous["uncertain"].clear()
                    previous.setdefault("proof", {})["resolved_by"] = job["id"]
                    self.assets.release(identity)
            if self.writer == job["id"]:
                self.writer = None
            self._signal()

    def _recover(self, job, code, execution, settle=True):
        """/** @param job	失败批次 @param code	原因 @param execution	已知执行边界 @param settle	尝试已知修改收尾 @return 精确范围的恢复状态 */"""
        try:
            current = self.observe(force=True)
            job["owned_dirty"].update(set(current.get("dirty_packages", [])) - job.get("segment_dirty", set(job["baseline"])))
            job["dirty"] = sorted(conflicting_packages(current.get("dirty_packages", []), job["owned_dirty"]))
            for item in current.get("activities", []):
                identity = item["id"] if isinstance(item, dict) else item
                if identity not in job.get("segment_activities", set()) and identity not in self.activity_owners:
                    self.activity_owners[identity] = job["owner"]
                    job["activities"].add(identity)
        except Exception:
            current = self.activity
        job["code"] = code
        job["execution"] = execution
        job["save_pending"] = not settle and job["completed"] == len(job["operations"])
        job.setdefault("failure", {"code": code, "execution": {"state": execution}})
        if execution == "unknown":
            job["uncertain"].update(job.get("effect_scope", job["targets"]))
        if settle and execution != "unknown" and not job["activities"] & set(self.activity_owners):
            if self._save_owned(job, current):
                self._finish(job)
                return
        with self.changed:
            job["status"] = "failed"
            self.assets.fault(job["id"], set(job["dirty"]) | job["uncertain"], code, self.clock())
            if self.writer == job["id"]:
                self.writer = None
            self._signal()
        if execution == "unknown" and not self.draining and not job["activities"] & set(self.activity_owners):
            self._reconcile(job)

    def _reconcile(self, job):
        """/** @param job	已登记恢复请求 @return 读取实际状态并完成自有资产交接 */"""
        with self.changed:
            self.writer = job["id"]
            job["status"] = "running"
            self.assets.hold(job["id"], set(job["dirty"]) | job["uncertain"], "verifying")
            self._signal()
        try:
            if job["activities"] & set(self.activity_owners) or (self.pie_batch == job["id"] and self.activity.get("pie_active")):
                raise JobConflict("OWNED_ACTIVITY_PENDING")
            current = self.observe(force=True)
            if self.draining or not current["host_verified"]:
                raise JobConflict("HOST_UNVERIFIED")
            job["owned_dirty"].update(conflicting_packages(current.get("dirty_packages", []), job["uncertain"]))
            if not self._save_owned(job, current):
                raise JobConflict(job.get("save_code", "SAVE_FAILED"))
            scope = job["uncertain"] | job["owned_dirty"]
            self.call_active = True
            try:
                job.setdefault("proof", {})["reconciled"] = self.backend.reconcile(sorted(scope))
            finally:
                self.call_active = False
            if job.get("save_pending"):
                job["proof"]["recovered_failure"] = job.pop("failure", None)
                job["save_pending"] = False
            self._finish(job)
        except Exception as error:
            job["recovery_failure"] = copy.deepcopy(error.value) if isinstance(error, McpBusinessError) else {"error": str(error)}
            with self.changed:
                job["status"] = "failed"
                code = job["recovery_failure"].get("code", "ASSET_READBACK_FAILED")
                self.assets.fault(job["id"], set(job["dirty"]) | job["uncertain"], code, self.clock())
                if self.writer == job["id"]:
                    self.writer = None
                self._signal()

    def control(self, client, action, batch=None):
        """/** @param client	客户端 @param action	控制动作 @param batch	所属批次 @return 控制结果或恢复请求 */"""
        self.touch(client)
        if action == "shutdown_host":
            self.observe(force=True)
            with self.changed:
                if self.draining:
                    raise JobConflict("HOST_DRAINING")
                if self.queue or self.writer or self.assets.claims or self.activity.get("pie_active") or self.activity.get("worlds") or self.activity.get("activities") or self.activity.get("dirty_packages"):
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
            if foreign:
                raise JobConflict("BATCH_OWNERSHIP")
            if action == "cancel":
                if job["status"] != "queued" or job["completed"]:
                    raise JobConflict("BATCH_ALREADY_DISPATCHED")
                self.queue.remove(batch)
                job["status"] = "cancelled"
                self.assets.release(batch)
                self._signal()
                return self._job_view(job)
            if action == "close":
                if self.pie_batch == batch or job["activities"] & set(self.activity_owners):
                    raise JobConflict("OWNED_ACTIVITY_PENDING")
                if job["status"] not in {"completed", "failed", "rejected", "cancelled", "closed"}:
                    raise JobConflict("BATCH_ACTIVE")
                if batch in self.assets.claims:
                    job["results"] = []
                    self._clean_outputs(batch)
                    self._signal()
                    return {"batch": batch, "status": "closed", "asset_recovery": "automatic"}
                del self.jobs[batch]
                self.clients.delete_job(batch)
                self._clean_outputs(batch)
                self._signal()
                return {"batch": batch, "status": "closed"}
        raise JobConflict("CONTROL_ACTION")

    def _job_view(self, job, detail=False):
        result = {"batch": job["id"], "status": job["status"], "completed": job["completed"]}
        result["revision"] = job.get("revision", 0)
        if job["code"]:
            result["code"] = job["code"]
        if job.get("blocked"):
            result["blocked"] = copy.deepcopy(job["blocked"])
        failure = job.get("failure")
        if failure:
            result["failure"] = copy.deepcopy(failure)
            if isinstance(failure, dict) and failure.get("code") == "ARGUMENT_INVALID":
                result["hint"] = "按 failure.details 指出的字段路径补齐参数；调用 describe_tool 查询完整字段定义，再重新提交。"
                result["next"] = "describe_tool"
        claim = self.assets.view(job["id"])
        if claim["packages"]:
            result["assets"] = {**claim, "count": len(claim["packages"]), "packages": claim["packages"] if detail else claim["packages"][:8]}
        if job["status"] == "queued":
            result["ahead"] = self.queue.index(job["id"])
            if job["code"] == "ASSET_BUSY":
                result["hint"] = "冲突资产正在自动协调；本批次将在占用释放后继续。"
            if job["code"] == "ASSET_SAVE_REQUIRED":
                result["hint"] = "目标资产存在编辑器原有修改；核实归属后以 asset.save_assets 保存 blocked.packages，本批次自动继续。"
        if claim["phase"] == "fault":
            result["hint"] = "网关自动核实并恢复 assets 中的故障包；独立资产任务继续。"
            if job.get("save_failure"):
                result["save_failure"] = copy.deepcopy(job["save_failure"])
            if job.get("recovery_failure"):
                result["recovery_failure"] = copy.deepcopy(job["recovery_failure"])
        if detail or job["status"] in {"completed", "failed"}:
            result["results"] = copy.deepcopy(job["results"])
        if detail:
            result.update({"dirty": list(job["dirty"]), "failed_index": job["failed_index"]})
            result["timings"] = copy.deepcopy(job.get("timings", {}))
            result["elapsed_seconds"] = int(self.clock() - job.get("started_at", job["submitted_at"]))
            if job.get("failure"):
                result["failure"] = copy.deepcopy(job["failure"])
            if job.get("execution"):
                result["execution"] = job["execution"]
        if job.get("proof"):
            result["proof"] = copy.deepcopy(job["proof"])
        if "next" not in result:
            result["next"] = "submit_batch" if job["status"] in {"completed", "rejected", "failed", "cancelled", "closed"} else "inspect_tasks"
        return result

    def inspect(self, client, batch=None, detail=False, after_revision=None, wait_seconds=0):
        """/** @param client 客户端 @param batch 批次 @param detail 完整证据 @param after_revision 业务版本 @param wait_seconds 等待上限 @return 状态与下一步 */"""
        self.touch(client)
        deadline = self.clock() + wait_seconds
        while True:
            self.observe()
            with self.changed:
                revision = self.revision
                if batch:
                    job = self.jobs.get(batch)
                    if job is None or job["owner"] != client:
                        raise JobConflict("BATCH_OWNERSHIP")
                    revision = job.get("revision", 0)
                if after_revision is None or revision != after_revision or self.clock() >= deadline:
                    if batch:
                        job = self.jobs.get(batch)
                        if job is None or job["owner"] != client:
                            raise JobConflict("BATCH_OWNERSHIP")
                        return self._job_view(job, detail)
                    result = {"revision": self.revision, "host": {"process_id": self.activity["process_id"], "exclusive": self.activity["host_exclusive"], "verified": self.activity["host_verified"]}, "status": "draining" if self.draining else "ready", "available": ["read", "prepare"], "queued": len(self.queue), "pie": bool(self.activity.get("pie_active")), "activities": len(self.activity.get("activities", [])), "dirty": len(self.activity.get("dirty_packages", [])), "next": "submit_batch"}
                    blockers = [job for job in self.jobs.values() if job["status"] in {"running"}]
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
                    if not self.writer and not result["pie"] and not result["activities"] and not self.draining:
                        result["available"].append("edit")
                    occupancy = [{"batch": identity, "phase": claim["phase"], "packages": claim["packages"] if detail else claim["packages"][:8], "count": len(claim["packages"]), "mine": self.jobs[identity]["owner"] == client}
                        for identity, claim in self.assets.claims.items()]
                    result["asset_occupancy"] = occupancy if detail else occupancy[:8]
                    result["asset_occupancy_count"] = len(occupancy)
                    if getattr(self, "cleanup_failure", None):
                        result["activity_fault"] = copy.deepcopy(self.cleanup_failure)
                    if result["pie"]:
                        result["pie_owner"] = "mine" if self.pie_owner == client else "other"
                    if self.draining:
                        result["available"] = ["prepare", "inspect"]
                    owned = [job for job in self.jobs.values() if job["owner"] == client and job["status"] in {"queued", "running"}]
                    if not owned:
                        owned = [job for job in self.jobs.values() if job["owner"] == client]
                    if owned:
                        result["batch"] = self._job_view(owned[-1])
                        result["batch"].pop("results", None)
                        result["batch"].pop("proof", None)
                        result["next"] = result["batch"]["next"]
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
