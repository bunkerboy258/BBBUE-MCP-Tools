import copy
import json
import secrets
import time
import unicodedata

from MCP.mcp_result import McpBusinessError


class OperatorPool:
    """/** 逻辑会话身份 等级和临时调度租期 */"""

    def __init__(self, clients, clock=time.time):
        """/** @param clients 客户端登记 @param clock 持久时间来源 @return 项目干员池 */"""
        self.clients = clients
        self.clock = clock
        self.lock = clients.condition
        self.rows = {}
        self.pauses = {}
        self.revision = 0
        self.audit = []
        database = clients.database
        if database is not None:
            database.execute("CREATE TABLE IF NOT EXISTS operators (owner TEXT PRIMARY KEY, payload TEXT)")
            database.execute("CREATE TABLE IF NOT EXISTS operator_pauses (target TEXT PRIMARY KEY, payload TEXT)")
            database.execute("CREATE TABLE IF NOT EXISTS operator_audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)")
            for owner, payload in database.execute("SELECT owner,payload FROM operators"):
                self.rows[owner] = json.loads(payload)
            for target, payload in database.execute("SELECT target,payload FROM operator_pauses"):
                self.pauses[target] = json.loads(payload)
            database.commit()

    def owner(self, client):
        """/** @param client 运行凭证或恢复身份 @return 单向会话身份 */"""
        if client.startswith("@"):
            return client[1:]
        return self.clients.digest(client)

    def _store(self, owner):
        """/** @param owner	单向归属 @return 已持久化的干员记录 */"""
        if self.clients.database is not None:
            self.clients.database.execute("INSERT OR REPLACE INTO operators VALUES (?,?)", (owner, json.dumps(self.rows[owner], ensure_ascii=False)))
            self.clients.database.commit()

    def record(self, client, action, target, **details):
        """/** @param client 操作者 @param action 动作 @param target 目标 @param details 结果证据 @return 已登记审计 */"""
        with self.lock:
            actor = self.rows.get(self.owner(client), {}).get("id")
            row = {"at": self.clock(), "actor": actor, "action": action, "target": target, **details}
            self.audit.append(row)
            del self.audit[:-64]
            if self.clients.database is not None:
                self.clients.database.execute("INSERT INTO operator_audit(payload) VALUES (?)", (json.dumps(row, ensure_ascii=False),))
                self.clients.database.execute("DELETE FROM operator_audit WHERE sequence < (SELECT MAX(sequence)-2048 FROM operator_audit)")
                self.clients.database.commit()

    def manage(self, client, action="join", task=None, level=None, operator=None):
        """/** @param client 会话凭证 @param action 登记 更新或结束 @param task 单行任务 @param level 等级 @param operator 目标干员 @return 干员视图 */"""
        with self.lock:
            owner = self.owner(client)
            target = owner
            if operator is not None:
                target = next((key for key, row in self.rows.items() if row["id"] == operator), None)
                if target is None:
                    raise McpBusinessError({"status": "rejected", "code": "OPERATOR_UNKNOWN", "next": None})
                if target != owner:
                    self.require(client, level=0)
            row = self.rows.get(target)
            if action == "finish":
                if row is None:
                    raise McpBusinessError({"status": "rejected", "code": "OPERATOR_REQUIRED", "next": None})
                row.update(ended=True, level=2, last_seen=self.clock())
                self.pauses.pop(row["id"], None)
                if self.clients.database is not None:
                    self.clients.database.execute("DELETE FROM operator_pauses WHERE target=?", (row["id"],))
                self._store(target)
                self.revision += 1
                self.record(client, action, row["id"])
                return self.view(target)
            if action not in {"join", "update"}:
                raise ValueError("OPERATOR_ACTION")
            if level is not None and (type(level) is not int or level not in {0, 1, 2}):
                raise ValueError("OPERATOR_LEVEL")
            if task is not None:
                task = unicodedata.normalize("NFC", task).strip()
                if not 1 <= len(task) <= 20 or "\n" in task or "\r" in task:
                    raise McpBusinessError({"status": "rejected", "code": "OPERATOR_TASK_INVALID", "hint": "task 使用单行 1 至 20 字符", "next": None})
            if row is None or row.get("ended"):
                if row is None and len(self.rows) >= 256:
                    expired = [key for key, item in self.rows.items() if item.get("ended")]
                    if not expired:
                        raise McpBusinessError({"status": "rejected", "code": "OPERATOR_CAPACITY", "next": None})
                    oldest = min(expired, key=lambda key: self.rows[key]["last_seen"])
                    del self.rows[oldest]
                    if self.clients.database is not None:
                        self.clients.database.execute("DELETE FROM operators WHERE owner=?", (oldest,))
                if task is None:
                    raise McpBusinessError({"status": "rejected", "code": "OPERATOR_TASK_REQUIRED", "next": None})
                row = {"id": secrets.token_hex(6), "task": task, "level": 2, "joined": self.clock(), "ended": False}
                self.rows[target] = row
            if task is not None:
                row["task"] = task
            if level is not None:
                row["level"] = level
            row["last_seen"] = self.clock()
            self._store(target)
            self.revision += 1
            self.record(client, action, row["id"], level=row["level"], task=row["task"])
            return self.view(target)

    def require(self, client, level=None):
        """/** @param client 会话身份 @param level 精确权限等级 @return 当前干员记录 */"""
        with self.lock:
            row = self.rows.get(self.owner(client))
            if row is None or row.get("ended"):
                raise McpBusinessError({"status": "rejected", "code": "OPERATOR_REQUIRED", "hint": "先调用 manage_operator 登记单行任务，默认等级 2", "next": None})
            if level is not None and row["level"] != level:
                raise McpBusinessError({"status": "rejected", "code": "OPERATOR_LEVEL_REQUIRED", "required_level": level, "next": None})
            return copy.deepcopy(row)

    def touch(self, client):
        """/** @param client	会话凭证 @return 已更新在线状态 */"""
        with self.lock:
            row = self.rows.get(self.owner(client))
            if row is not None and not row.get("ended"):
                previous = row.get("last_seen", 0)
                row["last_seen"] = self.clock()
                if self.clock() - previous > 300:
                    self.revision += 1
                if self.clock() - row.get("persisted_at", 0) > 60:
                    row["persisted_at"] = self.clock()
                    self._store(self.owner(client))

    def level(self, client):
        """/** @param client	会话凭证 @return 当前等级 */"""
        with self.lock:
            row = self.rows.get(self.owner(client))
            if row is None or row.get("ended"):
                return 2
            return row["level"]

    def identity(self, client):
        """/** @param client	会话凭证 @return 干员公开标识 */"""
        with self.lock:
            return self.rows.get(self.owner(client), {}).get("id")

    def ended(self, client, identity=None):
        """/** @param client	会话凭证 @param identity	原干员代际 @return 会话已经结束 */"""
        with self.lock:
            row = self.rows.get(self.owner(client))
            if row is None:
                return False
            return row.get("ended", False) or identity is not None and row["id"] != identity

    def pause(self, client, operator, seconds=60):
        """/** @param client 操作者 @param operator 目标干员 @param seconds 有界暂停租期 @return 暂停状态 */"""
        self.require(client, level=0)
        if type(seconds) not in {int, float} or not 1 <= seconds <= 300:
            raise ValueError("PAUSE_LEASE_RANGE")
        with self.lock:
            if not any(row["id"] == operator and not row.get("ended") for row in self.rows.values()):
                raise ValueError("OPERATOR_UNKNOWN")
            value = {"until": self.clock() + seconds, "by": self.identity(client)}
            self.pauses[operator] = value
            if self.clients.database is not None:
                self.clients.database.execute("INSERT OR REPLACE INTO operator_pauses VALUES (?,?)", (operator, json.dumps(value)))
                self.clients.database.commit()
            self.revision += 1
            self.record(client, "pause", operator, until=value["until"])
            return {"operator": operator, **value}

    def resume(self, client, operator):
        """/** @param client 操作者 @param operator 目标干员 @return 已恢复的排队状态 */"""
        self.require(client, level=0)
        with self.lock:
            self.pauses.pop(operator, None)
            if self.clients.database is not None:
                self.clients.database.execute("DELETE FROM operator_pauses WHERE target=?", (operator,))
                self.clients.database.commit()
            self.revision += 1
            self.record(client, "resume", operator)
            return {"operator": operator, "status": "resumed"}

    def paused(self, client):
        """/** @param client	会话凭证 @return 有效暂停租期或空值 */"""
        with self.lock:
            identity = self.identity(client)
            value = self.pauses.get(identity)
            if value is not None and value["until"] > self.clock():
                return copy.deepcopy(value)
            if value is not None:
                self.pauses.pop(identity, None)
                if self.clients.database is not None:
                    self.clients.database.execute("DELETE FROM operator_pauses WHERE target=?", (identity,))
                    self.clients.database.commit()
                self.revision += 1
            return None

    def view(self, owner):
        """/** @param owner	单向归属 @return 脱敏干员状态 */"""
        row = self.rows[owner]
        state = "ended" if row.get("ended") else "idle"
        if state != "ended" and self.clock() - row.get("last_seen", 0) > 300:
            state = "offline"
        pause = self.paused("@" + owner)
        result = {key: row[key] for key in ("id", "task", "level")}
        result.update(state="paused" if pause else state, last_seen=row.get("last_seen"))
        if pause:
            result["pause"] = pause
        return result

    def snapshot(self, jobs=(), limit=16):
        """/** @param jobs 当前批次 @param limit 展示上限 @return 脱敏干员池 */"""
        with self.lock:
            rows = {owner: self.view(owner) for owner, row in self.rows.items() if not row.get("ended")}
            for job in jobs:
                row = rows.get(self.owner(job["owner"]))
                if row is None or job.get("status") not in {"queued", "running"}:
                    continue
                state = "running" if job["status"] == "running" else "waiting"
                if row["state"] not in {"paused", "running"}:
                    row.update(state=state, batch=job.get("id", job.get("batch")))
                    if job.get("code"):
                        row["reason"] = job["code"]
            ordered = sorted(rows.values(), key=lambda row: (row["level"], row["id"]))
            return {"revision": self.revision, "count": len(ordered), "items": ordered[:limit]}
