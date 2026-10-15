import copy
import hashlib
import json
import secrets
import threading
import time
import sqlite3
import re
from pathlib import Path
from collections.abc import MutableMapping

from MCP.mcp_result import McpBusinessError


class ClientRegistry(MutableMapping):
    """/** 客户端身份 会话引用与请求重放的唯一维护来源 */"""

    def __init__(self, clock=time.monotonic, state_path=None):
        """/** @param clock\t单调时间来源 @return 客户端登记簿 */"""
        self.clock = clock
        self.condition = threading.Condition(threading.RLock())
        self.deadlines = {}
        self.sessions = {}
        self.requests = {}
        self.database = None
        if state_path is not None:
            path = Path(state_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("CLIENT_STATE_PATH_REQUIRED")
            self.database = sqlite3.connect(path, check_same_thread=False)
            self.database.execute("PRAGMA journal_mode=WAL")
            self.database.execute("CREATE TABLE IF NOT EXISTS clients (digest TEXT PRIMARY KEY, touched REAL)")
            self.database.execute("CREATE TABLE IF NOT EXISTS requests (owner TEXT, identity TEXT, fingerprint TEXT, outcome TEXT, finished REAL, PRIMARY KEY(owner, identity))")
            self.database.execute("CREATE TABLE IF NOT EXISTS jobs (identity TEXT PRIMARY KEY, owner TEXT, payload TEXT, updated REAL)")
            self.database.commit()

    def digest(self, key):
        """/** @param key\t私有凭证 @return 日志与持久状态使用的单向身份 */"""
        return hashlib.sha256(key.encode()).hexdigest()

    def known(self, key):
        """/** @param key\t恢复凭证 @return 已登记身份 */"""
        with self.condition:
            if not isinstance(key, str):
                return False
            if key in self.deadlines:
                return True
            if self.database is not None:
                return self.database.execute("SELECT 1 FROM clients WHERE digest=?", (self.digest(key),)).fetchone() is not None
            return False

    def store_job(self, payload):
        """/** @param payload\t批次恢复证据 @return 已原子记录的业务边界 */"""
        if self.database is None:
            return
        with self.condition:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self.database.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)", (payload["id"], payload["owner"], serialized, time.time()))
            self.database.commit()

    def stored_jobs(self):
        """/** @return 原网关记录的批次证据 */"""
        if self.database is None:
            return []
        with self.condition:
            return [json.loads(row[0]) for row in self.database.execute("SELECT payload FROM jobs ORDER BY updated")]

    def delete_job(self, identity):
        """/** @param identity\t完成交接的批次 @return 已回收的恢复记录 */"""
        if self.database is None:
            return
        with self.condition:
            self.database.execute("DELETE FROM jobs WHERE identity=?", (identity,))
            self.database.commit()

    def __getitem__(self, key):
        with self.condition:
            return self.deadlines[key]

    def __setitem__(self, key, value):
        with self.condition:
            self.deadlines[key] = value

    def __delitem__(self, key):
        with self.condition:
            del self.deadlines[key]

    def __iter__(self):
        with self.condition:
            return iter(tuple(self.deadlines))

    def __len__(self):
        with self.condition:
            return len(self.deadlines)

    def connect(self, resume_key=None, owners=()):
        """/** @param resume_key\t原客户端凭证 @param owners\t业务归属引用 @return 私有客户端凭证 */"""
        with self.condition:
            referenced = set(owners) | set(self.sessions.values())
            for key, deadline in list(self.deadlines.items()):
                if key != resume_key and key not in referenced and deadline + 86400 < self.clock():
                    del self.deadlines[key]
            if resume_key is not None and (not isinstance(resume_key, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", resume_key) is None):
                raise McpBusinessError({"status": "rejected", "code": "CLIENT_KEY_INVALID", "next": "reconnect"})
            if resume_key not in self.deadlines and len(self.deadlines) >= 4096:
                raise McpBusinessError({"status": "rejected", "code": "CLIENT_CAPACITY"})
            key = resume_key or secrets.token_urlsafe(32)
            self.deadlines[key] = self.clock() + 300
            if self.database is not None:
                self.database.execute("INSERT OR REPLACE INTO clients VALUES (?,?)", (self.digest(key), time.time()))
                self.database.execute("DELETE FROM clients WHERE touched < ? AND digest NOT IN (SELECT owner FROM jobs)", (time.time() - 86400,))
                self.database.commit()
            return key

    def touch(self, key):
        """/** @param key\t客户端凭证 @return 续期完成 */"""
        with self.condition:
            if key not in self.deadlines:
                raise McpBusinessError({"status": "rejected", "code": "CLIENT_KEY_INVALID", "next": "reconnect"})
            self.deadlines[key] = self.clock() + 300
            if self.database is not None:
                self.database.execute("UPDATE clients SET touched=? WHERE digest=? AND touched < ?", (time.time(), self.digest(key), time.time() - 60))
                self.database.commit()

    def bind(self, key):
        """/** @param key\t客户端凭证 @return HTTP 会话身份 */"""
        self.touch(key)
        with self.condition:
            session = secrets.token_urlsafe(24)
            self.sessions[session] = key
            return session

    def unbind(self, session):
        """/** @param session\tHTTP 会话身份 @return 释放传输引用 */"""
        with self.condition:
            self.sessions.pop(session, None)

    def resolve(self, session):
        """/** @param session\tHTTP 会话身份 @return 客户端凭证 */"""
        with self.condition:
            return self.sessions.get(session)

    def replay(self, owner, identity, arguments, invoke):
        """/** @param owner\t客户端 @param identity\t稳定请求身份 @param arguments\t请求内容 @param invoke\t首次派发 @return 原请求的唯一结果 */"""
        fingerprint = hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        key = (owner, identity)
        with self.condition:
            for cached, record in list(self.requests.items()):
                if record.get("finished") is not None and self.clock() - record["finished"] > 3600:
                    del self.requests[cached]
            record = self.requests.get(key)
            if record is None and self.database is not None:
                stored = self.database.execute("SELECT fingerprint,outcome,finished FROM requests WHERE owner=? AND identity=? AND finished>=?", (self.digest(owner), identity, time.time() - 3600)).fetchone()
                if stored is not None:
                    record = {"fingerprint": stored[0], "finished": self.clock()}
                    outcome = json.loads(stored[1]) if stored[1] else {"error": {"status": "failed", "code": "GATEWAY_RESTARTED", "next": "inspect_tasks"}}
                    record.update(outcome)
                    self.requests[key] = record
            if record is not None:
                if record["fingerprint"] != fingerprint:
                    raise McpBusinessError({"status": "rejected", "code": "REQUEST_ID_REUSED"})
                while "result" not in record and "error" not in record:
                    self.condition.wait(1)
                if "error" in record:
                    raise McpBusinessError(copy.deepcopy(record["error"]))
                return copy.deepcopy(record["result"])
            if len(self.requests) >= 4096:
                raise McpBusinessError({"status": "rejected", "code": "REQUEST_CAPACITY"})
            record = {"fingerprint": fingerprint}
            self.requests[key] = record
            if self.database is not None:
                self.database.execute("DELETE FROM requests WHERE finished < ?", (time.time() - 3600,))
                if self.database.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= 4096:
                    del self.requests[key]
                    raise McpBusinessError({"status": "rejected", "code": "REQUEST_CAPACITY"})
                self.database.execute("INSERT INTO requests VALUES (?,?,?,?,?)", (self.digest(owner), identity, fingerprint, None, time.time()))
                self.database.commit()
        try:
            result = invoke()
        except BaseException as error:
            with self.condition:
                record["error"] = copy.deepcopy(error.value) if isinstance(error, McpBusinessError) else {"status": "failed", "code": "EXECUTION_UNVERIFIED", "next": "inspect_tasks"}
                if isinstance(error, (ValueError, KeyError, TypeError)):
                    record["error"] = {"status": "rejected", "code": "ARGUMENT_INVALID", "details": str(error), "next": "describe_tool"}
                record["finished"] = self.clock()
                self._store_request(owner, identity, record)
                self.condition.notify_all()
            raise
        with self.condition:
            record.update(result=copy.deepcopy(result), finished=self.clock())
            self._store_request(owner, identity, record)
            self.condition.notify_all()
            return result

    def _store_request(self, owner, identity, record):
        """/** @param owner\t客户端 @param identity\t请求身份 @param record\t唯一结果 @return 已持久化的重放边界 */"""
        if self.database is None:
            return
        outcome = {key: record[key] for key in ("result", "error") if key in record}
        self.database.execute("UPDATE requests SET outcome=?,finished=? WHERE owner=? AND identity=?", (json.dumps(outcome, ensure_ascii=False, separators=(",", ":")), time.time(), self.digest(owner), identity))
        self.database.commit()

    def close(self):
        """/** @return 关闭本登记簿的恢复存储 */"""
        with self.condition:
            if self.database is not None:
                self.database.close()
                self.database = None
