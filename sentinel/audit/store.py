# sentinel/audit/store.py
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite

from sentinel.core.models import AuditEntry, AuditSummary

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    intent TEXT NOT NULL,
    params TEXT NOT NULL,
    outcome TEXT NOT NULL,
    policy_result TEXT NOT NULL,
    modified_params TEXT,
    block_reason TEXT,
    execution_result TEXT,
    task_id TEXT
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_agent_id ON audit_entries (agent_id);
CREATE INDEX IF NOT EXISTS idx_task_id ON audit_entries (task_id);
CREATE INDEX IF NOT EXISTS idx_outcome ON audit_entries (outcome);
CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_entries (timestamp);
"""


def _row_to_entry(row: aiosqlite.Row) -> AuditEntry:
    d = dict(row)
    d["params"] = json.loads(d["params"])
    d["policy_result"] = json.loads(d["policy_result"])
    d["modified_params"] = json.loads(d["modified_params"]) if d["modified_params"] else None
    d["execution_result"] = json.loads(d["execution_result"]) if d["execution_result"] else None
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    return AuditEntry(**d)


class AuditStore:
    def __init__(self, db_path: str = "sentinel_audit.db") -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(CREATE_TABLE)
        for stmt in CREATE_INDEXES.strip().split("\n"):
            if stmt.strip():
                await self._conn.execute(stmt)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def write(self, entry: AuditEntry) -> None:
        if self._conn is None:
            raise RuntimeError("AuditStore not initialized — call await store.initialize() first")
        await self._conn.execute(
            """INSERT INTO audit_entries
               (id, timestamp, agent_id, tool_name, action_type, risk_level, intent,
                params, outcome, policy_result, modified_params, block_reason,
                execution_result, task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.timestamp.isoformat(),
                entry.agent_id,
                entry.tool_name,
                entry.action_type,
                entry.risk_level,
                entry.intent,
                json.dumps(entry.params),
                entry.outcome,
                json.dumps(entry.policy_result),
                json.dumps(entry.modified_params) if entry.modified_params else None,
                entry.block_reason,
                json.dumps(entry.execution_result) if entry.execution_result else None,
                entry.task_id,
            ),
        )
        await self._conn.commit()

    async def get_entries(
        self,
        agent_id: str | None = None,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[AuditEntry]:
        if self._conn is None:
            raise RuntimeError("AuditStore not initialized — call await store.initialize() first")
        clauses: list[str] = []
        args: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            args.append(agent_id)
        if since:
            clauses.append("timestamp >= ?")
            args.append(since.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        async with self._conn.execute(
            f"SELECT * FROM audit_entries {where} ORDER BY timestamp DESC LIMIT ?", args
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def get_blocks(
        self,
        agent_id: str | None = None,
        since: datetime | None = None,
    ) -> list[AuditEntry]:
        if self._conn is None:
            raise RuntimeError("AuditStore not initialized — call await store.initialize() first")
        clauses = ["outcome = 'block'"]
        args: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            args.append(agent_id)
        if since:
            clauses.append("timestamp >= ?")
            args.append(since.isoformat())
        where = f"WHERE {' AND '.join(clauses)}"
        async with self._conn.execute(
            f"SELECT * FROM audit_entries {where} ORDER BY timestamp DESC", args
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def get_by_task(self, task_id: str) -> list[AuditEntry]:
        if self._conn is None:
            raise RuntimeError("AuditStore not initialized — call await store.initialize() first")
        async with self._conn.execute(
            "SELECT * FROM audit_entries WHERE task_id = ? ORDER BY timestamp DESC",
            (task_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def get_summary(
        self, agent_id: str | None = None, since: datetime | None = None
    ) -> AuditSummary:
        if self._conn is None:
            raise RuntimeError("AuditStore not initialized — call await store.initialize() first")
        clauses: list[str] = []
        args: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            args.append(agent_id)
        if since:
            clauses.append("timestamp >= ?")
            args.append(since.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        async with self._conn.execute(
            f"SELECT COUNT(*) as total, "
            f"SUM(CASE WHEN outcome='pass' THEN 1 ELSE 0 END) as passes, "
            f"SUM(CASE WHEN outcome='block' THEN 1 ELSE 0 END) as blocks, "
            f"SUM(CASE WHEN outcome='modify' THEN 1 ELSE 0 END) as modifies "
            f"FROM audit_entries {where}",
            args,
        ) as cur:
            row = await cur.fetchone()

        # For the top_blocked_tools query, need to re-apply same WHERE but add outcome filter
        block_clauses = list(clauses) + ["outcome='block'"]
        block_where = f"WHERE {' AND '.join(block_clauses)}" if block_clauses else ""
        async with self._conn.execute(
            f"SELECT tool_name, COUNT(*) as cnt FROM audit_entries "
            f"{block_where} "
            f"GROUP BY tool_name ORDER BY cnt DESC LIMIT 10",
            args,
        ) as cur:
            block_rows = await cur.fetchall()

        total = int(row["total"]) if row is not None and row["total"] is not None else 0
        passes = int(row["passes"]) if row is not None and row["passes"] is not None else 0
        blocks = int(row["blocks"]) if row is not None and row["blocks"] is not None else 0
        modifies = int(row["modifies"]) if row is not None and row["modifies"] is not None else 0

        return AuditSummary(
            total_calls=total,
            passes=passes,
            blocks=blocks,
            modifies=modifies,
            top_blocked_tools=[(r["tool_name"], r["cnt"]) for r in block_rows],
        )
