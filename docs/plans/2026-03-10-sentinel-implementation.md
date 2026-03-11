# Sentinel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Sentinel — a policy enforcement layer that intercepts AI agent tool calls, evaluates them against declared policies, and logs every invocation.

**Architecture:** Python decorator-based wrapper intercepts tool function calls before execution. A rule-based engine evaluates constraints; a provider-agnostic semantic checker evaluates intent via LLM. Every invocation (pass/block/modify) is written to a SQLite audit store with a FastAPI query API.

**Tech Stack:** Python 3.10+, uv, FastAPI, SQLite (aiosqlite), Pydantic v2, pytest, anthropic SDK (optional semantic check), python-dotenv

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `sentinel/__init__.py`
- Create: `sentinel/core/__init__.py`
- Create: `sentinel/audit/__init__.py`
- Create: `sentinel/integrations/__init__.py`
- Create: `sentinel/api/__init__.py`
- Create: `sentinel/api/routes/__init__.py`
- Create: `tests/__init__.py`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Initialize uv project**

```bash
cd /Users/sidharthsrinivasan/Desktop/Projects/sentinel
uv init --name sentinel --python 3.10
```

**Step 2: Replace pyproject.toml with full dependencies**

```toml
[project]
name = "sentinel"
version = "0.1.0"
description = "Agent Action Policy Engine"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "pydantic>=2.0.0",
    "aiosqlite>=0.20.0",
    "python-dotenv>=1.0.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.40.0"]
langchain = ["langchain>=0.3.0"]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "mypy>=1.10.0",
    "ruff>=0.4.0",
]

[project.scripts]
sentinel = "sentinel.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.mypy]
python_version = "3.10"
strict = true
ignore_missing_imports = true

[tool.ruff]
line-length = 100
```

**Step 3: Install dependencies**

```bash
uv sync --extra dev
uv pip install anthropic  # for semantic check
```

**Step 4: Create directory structure**

```bash
mkdir -p sentinel/core sentinel/audit sentinel/integrations sentinel/api/routes tests
touch sentinel/__init__.py sentinel/core/__init__.py sentinel/audit/__init__.py
touch sentinel/integrations/__init__.py sentinel/api/__init__.py sentinel/api/routes/__init__.py
touch tests/__init__.py
```

**Step 5: Create .env.example**

```
ANTHROPIC_API_KEY=sk-ant-...
SENTINEL_DB_PATH=sentinel_audit.db
SENTINEL_LOG_LEVEL=INFO
```

**Step 6: Create .gitignore**

```
.env
*.db
__pycache__/
.mypy_cache/
.ruff_cache/
dist/
.venv/
```

**Step 7: Commit**

```bash
git init
git add .
git commit -m "chore: scaffold sentinel project with uv"
```

---

## Task 2: Core Pydantic Models

**Files:**
- Create: `sentinel/core/models.py`
- Create: `tests/test_models.py`

**Step 1: Write failing tests**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError


def test_policy_definition_requires_intent():
    from sentinel.core.models import PolicyDefinition
    with pytest.raises(ValidationError):
        PolicyDefinition(risk_level="low", action_type="reversible")


def test_policy_definition_defaults():
    from sentinel.core.models import PolicyDefinition
    p = PolicyDefinition(
        intent="test intent",
        risk_level="low",
        action_type="reversible",
    )
    assert p.semantic_check is True
    assert p.semantic_threshold == 0.8
    assert p.on_block == "return"
    assert p.on_modify == "auto"
    assert p.log_level == "all"
    assert p.constraints == {}


def test_policy_result_fields():
    from sentinel.core.models import PolicyResult
    r = PolicyResult(
        outcome="pass",
        checks_run=["domain_allowlist"],
        checks_failed=[],
    )
    assert r.outcome == "pass"
    assert r.reason is None


def test_policy_violation_fields():
    from sentinel.core.models import PolicyViolation
    v = PolicyViolation(
        tool_name="send_email",
        reason="Blocked keyword found: confidential",
        suggestion="Remove sensitive terms from email body",
        what_happened="blocked_keyword check failed",
    )
    assert v.tool_name == "send_email"
    # Must be JSON serializable
    import json
    json.dumps(v.model_dump())


def test_audit_entry_fields():
    from sentinel.core.models import AuditEntry
    from datetime import datetime, timezone
    entry = AuditEntry(
        agent_id="agent-1",
        tool_name="send_email",
        action_type="irreversible",
        risk_level="high",
        intent="manage communications",
        params={"to": "user@example.com"},
        outcome="pass",
        policy_result={"outcome": "pass", "checks_run": [], "checks_failed": []},
    )
    assert entry.id is not None
    assert isinstance(entry.timestamp, datetime)


def test_audit_summary_fields():
    from sentinel.core.models import AuditSummary
    s = AuditSummary(
        total_calls=10,
        passes=7,
        blocks=3,
        modifies=0,
        top_blocked_tools=[("send_email", 3)],
    )
    assert s.total_calls == 10
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'sentinel.core.models'`

**Step 3: Implement models**

```python
# sentinel/core/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class PolicyDefinition(BaseModel):
    # Required
    intent: str
    risk_level: Literal["low", "medium", "high", "critical"]
    action_type: Literal["reversible", "irreversible", "destructive"]

    # Optional rule-based constraints
    constraints: dict[str, Any] = Field(default_factory=dict)

    # Optional semantic check
    semantic_check: bool = True
    semantic_threshold: float = 0.8

    # Optional behavior config
    on_block: Literal["raise", "return", "log_only"] = "return"
    on_modify: Literal["auto", "ask", "block"] = "auto"
    log_level: Literal["all", "blocks_only", "none"] = "all"

    # Optional escalation (V2)
    escalate_on: list[str] = Field(default_factory=list)


class PolicyResult(BaseModel):
    outcome: Literal["pass", "block", "modify"]
    checks_run: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    reason: str | None = None
    modified_params: dict[str, Any] | None = None


class PolicyViolation(BaseModel):
    tool_name: str
    reason: str
    suggestion: str
    what_happened: str


class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str
    tool_name: str
    action_type: str
    risk_level: str
    intent: str
    params: dict[str, Any]
    outcome: str
    policy_result: dict[str, Any]
    modified_params: dict[str, Any] | None = None
    block_reason: str | None = None
    execution_result: dict[str, Any] | None = None
    task_id: str | None = None


class AgentSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    task_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditSummary(BaseModel):
    total_calls: int
    passes: int
    blocks: int
    modifies: int
    top_blocked_tools: list[tuple[str, int]] = Field(default_factory=list)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_models.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add sentinel/core/models.py tests/test_models.py
git commit -m "feat: add core Pydantic models"
```

---

## Task 3: Rule-Based Engine

**Files:**
- Create: `sentinel/core/rules.py`
- Create: `tests/test_rules.py`

**Step 1: Write failing tests**

```python
# tests/test_rules.py
import pytest
from sentinel.core.rules import RuleEngine


def test_domain_allowlist_pass():
    engine = RuleEngine()
    result = engine.check_domain_allowlist(
        value="user@company.com",
        allowed=["@company.com", "@partner.com"],
    )
    assert result is True


def test_domain_allowlist_block():
    engine = RuleEngine()
    result = engine.check_domain_allowlist(
        value="user@evil.com",
        allowed=["@company.com"],
    )
    assert result is False


def test_keyword_blocklist_pass():
    engine = RuleEngine()
    result = engine.check_keyword_blocklist(
        text="Hello, please find the report attached.",
        blocked=["confidential", "salary"],
    )
    assert result is True


def test_keyword_blocklist_block():
    engine = RuleEngine()
    result = engine.check_keyword_blocklist(
        text="The salary details are confidential.",
        blocked=["confidential", "salary"],
    )
    assert result is False


def test_keyword_blocklist_case_insensitive():
    engine = RuleEngine()
    result = engine.check_keyword_blocklist(
        text="CONFIDENTIAL document",
        blocked=["confidential"],
    )
    assert result is False


def test_numeric_bounds_pass():
    engine = RuleEngine()
    assert engine.check_numeric_bounds(value=5, min_val=1, max_val=10) is True


def test_numeric_bounds_fail_max():
    engine = RuleEngine()
    assert engine.check_numeric_bounds(value=11, min_val=1, max_val=10) is False


def test_numeric_bounds_fail_min():
    engine = RuleEngine()
    assert engine.check_numeric_bounds(value=0, min_val=1, max_val=10) is False


def test_count_limit_pass():
    engine = RuleEngine()
    assert engine.check_count_limit(items=["a", "b", "c"], max_count=5) is True


def test_count_limit_fail():
    engine = RuleEngine()
    assert engine.check_count_limit(items=["a"] * 6, max_count=5) is False


def test_regex_match_pass():
    engine = RuleEngine()
    assert engine.check_regex(value="abc123", pattern=r"^[a-z0-9]+$") is True


def test_regex_match_fail():
    engine = RuleEngine()
    assert engine.check_regex(value="abc 123", pattern=r"^[a-z0-9]+$") is False


def test_domain_blocklist():
    engine = RuleEngine()
    assert engine.check_domain_blocklist(
        value="user@evil.com",
        blocked=["@evil.com"],
    ) is False
    assert engine.check_domain_blocklist(
        value="user@good.com",
        blocked=["@evil.com"],
    ) is True


def test_evaluate_constraints_pass():
    from sentinel.core.models import PolicyDefinition
    engine = RuleEngine()
    policy = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        constraints={
            "blocked_keywords": ["confidential"],
            "max_recipients": 5,
        },
    )
    params = {"to": "user@company.com", "subject": "Hello", "body": "Hi there"}
    result = engine.evaluate(policy, params)
    assert result.outcome == "pass"
    assert len(result.checks_failed) == 0


def test_evaluate_constraints_block_keyword():
    from sentinel.core.models import PolicyDefinition
    engine = RuleEngine()
    policy = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        constraints={"blocked_keywords": ["confidential"]},
    )
    params = {"to": "user@company.com", "subject": "Confidential info", "body": "secret"}
    result = engine.evaluate(policy, params)
    assert result.outcome == "block"
    assert any("keyword" in c for c in result.checks_failed)


def test_evaluate_domain_allowlist_block():
    from sentinel.core.models import PolicyDefinition
    engine = RuleEngine()
    policy = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        constraints={
            "allowed_recipient_domains": ["@company.com"],
        },
    )
    params = {"to": "hacker@evil.com", "subject": "Hi", "body": "test"}
    result = engine.evaluate(policy, params)
    assert result.outcome == "block"


def test_evaluate_max_recipients_block():
    from sentinel.core.models import PolicyDefinition
    engine = RuleEngine()
    policy = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        constraints={"max_recipients": 3},
    )
    # Pass a list of recipients
    params = {"to": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}
    result = engine.evaluate(policy, params)
    assert result.outcome == "block"
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_rules.py -v
```
Expected: `ModuleNotFoundError`

**Step 3: Implement rules**

```python
# sentinel/core/rules.py
from __future__ import annotations

import re
from typing import Any

from sentinel.core.models import PolicyDefinition, PolicyResult


class RuleEngine:
    """Evaluates rule-based constraints against proposed tool parameters."""

    def check_domain_allowlist(self, value: str, allowed: list[str]) -> bool:
        """Return True if value ends with any allowed domain suffix."""
        return any(value.lower().endswith(d.lower()) for d in allowed)

    def check_domain_blocklist(self, value: str, blocked: list[str]) -> bool:
        """Return True (allowed) if value does NOT end with any blocked domain."""
        return not any(value.lower().endswith(d.lower()) for d in blocked)

    def check_keyword_blocklist(self, text: str, blocked: list[str]) -> bool:
        """Return True (allowed) if text contains none of the blocked keywords."""
        text_lower = text.lower()
        return not any(kw.lower() in text_lower for kw in blocked)

    def check_numeric_bounds(
        self,
        value: float | int,
        min_val: float | int | None = None,
        max_val: float | int | None = None,
    ) -> bool:
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        return True

    def check_count_limit(self, items: list[Any], max_count: int) -> bool:
        return len(items) <= max_count

    def check_regex(self, value: str, pattern: str) -> bool:
        return bool(re.match(pattern, value))

    def _scan_strings(self, params: dict[str, Any]) -> list[str]:
        """Recursively collect all string values from params."""
        strings: list[str] = []
        for v in params.values():
            if isinstance(v, str):
                strings.append(v)
            elif isinstance(v, list):
                strings.extend(i for i in v if isinstance(i, str))
        return strings

    def _collect_emails(self, params: dict[str, Any]) -> list[str]:
        """Collect values that look like emails or are in email-like fields."""
        emails: list[str] = []
        email_keys = {"to", "cc", "bcc", "recipient", "recipients", "email"}
        for k, v in params.items():
            if k.lower() in email_keys:
                if isinstance(v, str):
                    emails.append(v)
                elif isinstance(v, list):
                    emails.extend(i for i in v if isinstance(i, str))
        return emails

    def evaluate(self, policy: PolicyDefinition, params: dict[str, Any]) -> PolicyResult:
        """Run all applicable rule checks. Return first block or pass."""
        constraints = policy.constraints
        checks_run: list[str] = []
        checks_failed: list[str] = []

        all_strings = self._scan_strings(params)
        email_values = self._collect_emails(params)

        # --- blocked_keywords ---
        if "blocked_keywords" in constraints:
            checks_run.append("keyword_blocklist")
            keywords = constraints["blocked_keywords"]
            for s in all_strings:
                if not self.check_keyword_blocklist(s, keywords):
                    checks_failed.append("keyword_blocklist")
                    break

        # --- allowed_recipient_domains ---
        if "allowed_recipient_domains" in constraints and email_values:
            checks_run.append("domain_allowlist")
            allowed = constraints["allowed_recipient_domains"]
            for email in email_values:
                if not self.check_domain_allowlist(email, allowed):
                    checks_failed.append("domain_allowlist")
                    break

        # --- blocked_recipient_domains ---
        if "blocked_recipient_domains" in constraints and email_values:
            checks_run.append("domain_blocklist")
            blocked_domains = constraints["blocked_recipient_domains"]
            for email in email_values:
                if not self.check_domain_blocklist(email, blocked_domains):
                    checks_failed.append("domain_blocklist")
                    break

        # --- max_recipients ---
        if "max_recipients" in constraints:
            checks_run.append("max_recipients")
            max_r = constraints["max_recipients"]
            # Check list fields
            for k, v in params.items():
                if isinstance(v, list) and k.lower() in {"to", "cc", "bcc", "recipients", "attendees"}:
                    if not self.check_count_limit(v, max_r):
                        checks_failed.append("max_recipients")
                        break
            # Check comma-separated string
            for k, v in params.items():
                if isinstance(v, str) and k.lower() in {"to", "cc", "bcc"}:
                    parts = [p.strip() for p in v.split(",") if p.strip()]
                    if len(parts) > max_r:
                        checks_failed.append("max_recipients")

        # --- max_duration_hours (numeric) ---
        if "max_duration_hours" in constraints and "end" in params and "start" in params:
            checks_run.append("max_duration_hours")
            # Simple string-based check: parse ISO datetimes if possible
            try:
                from datetime import datetime
                start = datetime.fromisoformat(params["start"])
                end = datetime.fromisoformat(params["end"])
                hours = (end - start).total_seconds() / 3600
                if hours > constraints["max_duration_hours"]:
                    checks_failed.append("max_duration_hours")
            except Exception:
                pass  # Skip if unparseable

        # --- allowed_calendars ---
        if "allowed_calendars" in constraints and "calendar" in params:
            checks_run.append("allowed_calendars")
            if params["calendar"] not in constraints["allowed_calendars"]:
                checks_failed.append("allowed_calendars")

        # --- regex constraints ---
        if "field_patterns" in constraints:
            for field, pattern in constraints["field_patterns"].items():
                if field in params and isinstance(params[field], str):
                    checks_run.append(f"regex:{field}")
                    if not self.check_regex(params[field], pattern):
                        checks_failed.append(f"regex:{field}")

        if checks_failed:
            return PolicyResult(
                outcome="block",
                checks_run=checks_run,
                checks_failed=checks_failed,
                reason=f"Failed checks: {', '.join(checks_failed)}",
            )

        return PolicyResult(
            outcome="pass",
            checks_run=checks_run,
            checks_failed=[],
        )
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_rules.py -v
```
Expected: All tests PASS

**Step 5: Commit**

```bash
git add sentinel/core/rules.py tests/test_rules.py
git commit -m "feat: implement rule-based policy engine"
```

---

## Task 4: Audit Store (SQLite)

**Files:**
- Create: `sentinel/audit/store.py`
- Create: `tests/test_audit_store.py`

**Step 1: Write failing tests**

```python
# tests/test_audit_store.py
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta


@pytest.fixture
async def store(tmp_path):
    from sentinel.audit.store import AuditStore
    db_path = str(tmp_path / "test.db")
    store = AuditStore(db_path=db_path)
    await store.initialize()
    yield store
    await store.close()


def make_entry(**kwargs):
    from sentinel.core.models import AuditEntry
    defaults = dict(
        agent_id="agent-1",
        tool_name="send_email",
        action_type="irreversible",
        risk_level="high",
        intent="send emails",
        params={"to": "user@co.com"},
        outcome="pass",
        policy_result={"outcome": "pass", "checks_run": [], "checks_failed": []},
    )
    defaults.update(kwargs)
    return AuditEntry(**defaults)


async def test_write_and_retrieve(store):
    entry = make_entry()
    await store.write(entry)
    entries = await store.get_entries(agent_id="agent-1", limit=10)
    assert len(entries) == 1
    assert entries[0].id == entry.id
    assert entries[0].tool_name == "send_email"


async def test_get_blocks_only(store):
    await store.write(make_entry(outcome="pass"))
    await store.write(make_entry(outcome="block"))
    blocks = await store.get_blocks(agent_id="agent-1")
    assert len(blocks) == 1
    assert blocks[0].outcome == "block"


async def test_get_by_task(store):
    e1 = make_entry(task_id="task-abc")
    e2 = make_entry(task_id="task-xyz")
    await store.write(e1)
    await store.write(e2)
    results = await store.get_by_task(task_id="task-abc")
    assert len(results) == 1
    assert results[0].task_id == "task-abc"


async def test_get_summary(store):
    await store.write(make_entry(outcome="pass"))
    await store.write(make_entry(outcome="pass"))
    await store.write(make_entry(outcome="block", tool_name="send_email"))
    summary = await store.get_summary(agent_id="agent-1")
    assert summary.total_calls == 3
    assert summary.passes == 2
    assert summary.blocks == 1
    assert summary.top_blocked_tools[0][0] == "send_email"


async def test_get_entries_since(store):
    past = make_entry()
    # Override timestamp to be old
    from sentinel.core.models import AuditEntry
    import uuid
    old_entry = AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        agent_id="agent-1",
        tool_name="old_tool",
        action_type="reversible",
        risk_level="low",
        intent="test",
        params={},
        outcome="pass",
        policy_result={},
    )
    recent = make_entry(tool_name="recent_tool")
    await store.write(old_entry)
    await store.write(recent)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    entries = await store.get_entries(agent_id="agent-1", since=since)
    assert len(entries) == 1
    assert entries[0].tool_name == "recent_tool"
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_audit_store.py -v
```
Expected: `ModuleNotFoundError`

**Step 3: Implement AuditStore**

```python
# sentinel/audit/store.py
from __future__ import annotations

import json
from datetime import datetime, timezone
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
        assert self._conn, "Store not initialized"
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
        assert self._conn
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
        assert self._conn
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
        assert self._conn
        async with self._conn.execute(
            "SELECT * FROM audit_entries WHERE task_id = ? ORDER BY timestamp DESC",
            (task_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def get_summary(
        self, agent_id: str | None = None, since: datetime | None = None
    ) -> AuditSummary:
        assert self._conn
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

        async with self._conn.execute(
            f"SELECT tool_name, COUNT(*) as cnt FROM audit_entries "
            f"{where} {'AND' if where else 'WHERE'} outcome='block' "
            f"GROUP BY tool_name ORDER BY cnt DESC LIMIT 10",
            args,
        ) as cur:
            block_rows = await cur.fetchall()

        return AuditSummary(
            total_calls=row["total"] or 0,
            passes=row["passes"] or 0,
            blocks=row["blocks"] or 0,
            modifies=row["modifies"] or 0,
            top_blocked_tools=[(r["tool_name"], r["cnt"]) for r in block_rows],
        )
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_audit_store.py -v
```
Expected: All tests PASS

**Step 5: Commit**

```bash
git add sentinel/audit/store.py tests/test_audit_store.py
git commit -m "feat: implement SQLite audit store"
```

---

## Task 5: AuditLogger

**Files:**
- Create: `sentinel/audit/logger.py`
- Create: `tests/test_audit_logger.py`

**Step 1: Write failing tests**

```python
# tests/test_audit_logger.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from sentinel.core.models import AuditEntry, PolicyResult


@pytest.fixture
def mock_store():
    store = AsyncMock()
    return store


@pytest.fixture
def logger(mock_store):
    from sentinel.audit.logger import AuditLogger
    return AuditLogger(store=mock_store)


async def test_log_pass(logger, mock_store):
    result = PolicyResult(outcome="pass", checks_run=["keyword_blocklist"], checks_failed=[])
    entry = await logger.log(
        agent_id="agent-1",
        tool_name="send_email",
        action_type="irreversible",
        risk_level="high",
        intent="send emails",
        params={"to": "user@co.com"},
        policy_result=result,
        execution_result={"status": "sent"},
    )
    mock_store.write.assert_awaited_once()
    assert entry.outcome == "pass"
    assert entry.execution_result == {"status": "sent"}


async def test_log_block(logger, mock_store):
    result = PolicyResult(
        outcome="block",
        checks_run=["keyword_blocklist"],
        checks_failed=["keyword_blocklist"],
        reason="Blocked keyword: confidential",
    )
    entry = await logger.log(
        agent_id="agent-1",
        tool_name="send_email",
        action_type="irreversible",
        risk_level="high",
        intent="send emails",
        params={"to": "user@co.com", "body": "confidential info"},
        policy_result=result,
    )
    assert entry.outcome == "block"
    assert entry.block_reason == "Blocked keyword: confidential"


async def test_log_skipped_for_none_level(mock_store):
    from sentinel.audit.logger import AuditLogger
    from sentinel.core.models import PolicyDefinition
    logger = AuditLogger(store=mock_store)
    result = PolicyResult(outcome="pass", checks_run=[], checks_failed=[])
    # log_level="none" should not write
    await logger.log(
        agent_id="agent-1",
        tool_name="tool",
        action_type="reversible",
        risk_level="low",
        intent="test",
        params={},
        policy_result=result,
        log_level="none",
    )
    mock_store.write.assert_not_awaited()
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_audit_logger.py -v
```

**Step 3: Implement AuditLogger**

```python
# sentinel/audit/logger.py
from __future__ import annotations

from typing import Any, Literal

from sentinel.audit.store import AuditStore
from sentinel.core.models import AuditEntry, PolicyResult


class AuditLogger:
    def __init__(self, store: AuditStore) -> None:
        self.store = store

    async def log(
        self,
        *,
        agent_id: str,
        tool_name: str,
        action_type: str,
        risk_level: str,
        intent: str,
        params: dict[str, Any],
        policy_result: PolicyResult,
        execution_result: dict[str, Any] | None = None,
        modified_params: dict[str, Any] | None = None,
        task_id: str | None = None,
        log_level: Literal["all", "blocks_only", "none"] = "all",
    ) -> AuditEntry:
        entry = AuditEntry(
            agent_id=agent_id,
            tool_name=tool_name,
            action_type=action_type,
            risk_level=risk_level,
            intent=intent,
            params=params,
            outcome=policy_result.outcome,
            policy_result=policy_result.model_dump(),
            execution_result=execution_result,
            modified_params=modified_params,
            block_reason=policy_result.reason if policy_result.outcome == "block" else None,
            task_id=task_id,
        )

        should_write = (
            log_level == "all"
            or (log_level == "blocks_only" and policy_result.outcome == "block")
        )
        if should_write:
            await self.store.write(entry)

        return entry
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_audit_logger.py -v
```
Expected: All tests PASS

**Step 5: Commit**

```bash
git add sentinel/audit/logger.py tests/test_audit_logger.py
git commit -m "feat: implement audit logger"
```

---

## Task 6: Policy Wrapper (`@policy.wrap`)

**Files:**
- Create: `sentinel/core/wrapper.py`
- Create: `sentinel/core/engine.py`
- Create: `sentinel/config.py`
- Modify: `sentinel/__init__.py`
- Create: `tests/test_wrapper.py`

**Step 1: Write failing tests**

```python
# tests/test_wrapper.py
import pytest
from unittest.mock import AsyncMock, patch


def test_wrap_pass_executes_function(tmp_path):
    """A passing policy allows the function to execute."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails on behalf of the executive",
        constraints={"blocked_keywords": ["confidential"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="user@company.com", subject="Hello", body="Meeting confirmed")
    assert result == {"status": "sent"}


def test_wrap_block_returns_violation(tmp_path):
    """A blocked action returns a PolicyViolation, does not execute the function."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    called = []

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_keywords": ["confidential"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        called.append(True)
        return {"status": "sent"}

    result = send_email(to="user@co.com", subject="Hi", body="This is confidential info")
    from sentinel.core.models import PolicyViolation
    assert isinstance(result, PolicyViolation)
    assert "keyword" in result.what_happened.lower() or "keyword" in result.reason.lower()
    assert len(called) == 0  # function was NOT called


def test_wrap_block_raises_when_configured(tmp_path):
    """on_block='raise' raises an exception instead of returning."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_keywords": ["confidential"]},
        risk_level="high",
        action_type="irreversible",
        on_block="raise",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {}

    with pytest.raises(Exception):
        send_email(to="user@co.com", subject="Hi", body="confidential")


def test_wrap_log_only_executes_despite_violation(tmp_path):
    """on_block='log_only' allows execution even with a violation."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_keywords": ["confidential"]},
        risk_level="high",
        action_type="irreversible",
        on_block="log_only",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="user@co.com", subject="Hi", body="confidential info")
    assert result == {"status": "sent"}


def test_wrap_allowed_domain_pass(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"allowed_recipient_domains": ["@company.com"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="user@company.com", subject="Hi", body="Hello")
    assert result == {"status": "sent"}


def test_wrap_blocked_domain_block(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"allowed_recipient_domains": ["@company.com"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent"}

    from sentinel.core.models import PolicyViolation
    result = send_email(to="hacker@evil.com", subject="Hi", body="Hello")
    assert isinstance(result, PolicyViolation)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_wrapper.py -v
```

**Step 3: Implement engine.py**

```python
# sentinel/core/engine.py
from __future__ import annotations

from typing import Any

from sentinel.core.models import PolicyDefinition, PolicyResult, PolicyViolation
from sentinel.core.rules import RuleEngine


class PolicyEngine:
    def __init__(self) -> None:
        self.rules = RuleEngine()

    async def evaluate(
        self,
        policy: PolicyDefinition,
        tool_name: str,
        params: dict[str, Any],
        semantic_checker: Any | None = None,
    ) -> PolicyResult:
        # Phase 1: Rule-based checks
        result = self.rules.evaluate(policy, params)
        if result.outcome == "block":
            return result

        # Phase 2: Semantic check (if enabled and checker available)
        if policy.semantic_check and semantic_checker is not None:
            try:
                sem = await semantic_checker(tool_name, params, policy.intent)
                if not sem.consistent and sem.confidence >= policy.semantic_threshold:
                    return PolicyResult(
                        outcome="block",
                        checks_run=result.checks_run + ["semantic_intent"],
                        checks_failed=["semantic_intent"],
                        reason=f"Semantic check failed: {sem.reason}",
                    )
                result.checks_run.append("semantic_intent")
            except Exception:
                # Degrade gracefully — rules already passed
                pass

        return result
```

**Step 4: Implement config.py**

```python
# sentinel/config.py
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Coroutine

from dotenv import load_dotenv

load_dotenv()

SemanticChecker = Callable[
    [str, dict[str, Any], str],
    Coroutine[Any, Any, Any],
]


class SentinelConfig:
    def __init__(
        self,
        *,
        semantic_checker: SemanticChecker | None = None,
        db_path: str | None = None,
        default_agent_id: str = "default",
    ) -> None:
        self.semantic_checker = semantic_checker
        self.db_path = db_path or os.getenv("SENTINEL_DB_PATH", "sentinel_audit.db")
        self.default_agent_id = default_agent_id
        self._store: Any = None
        self._logger: Any = None
        self._engine: Any = None
        self._initialized = False
        self._loop_task: asyncio.Task[None] | None = None

    def _get_default_semantic_checker(self) -> SemanticChecker | None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            from sentinel.core.semantic import AnthropicSemanticChecker
            return AnthropicSemanticChecker(api_key=api_key).check
        except ImportError:
            return None

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        from sentinel.audit.store import AuditStore
        from sentinel.audit.logger import AuditLogger
        from sentinel.core.engine import PolicyEngine

        self._store = AuditStore(db_path=self.db_path)
        await self._store.initialize()
        self._logger = AuditLogger(store=self._store)
        self._engine = PolicyEngine()

        if self.semantic_checker is None:
            self.semantic_checker = self._get_default_semantic_checker()

        self._initialized = True

    @property
    def store(self) -> Any:
        return self._store

    @property
    def logger(self) -> Any:
        return self._logger

    @property
    def engine(self) -> Any:
        return self._engine
```

**Step 5: Implement wrapper.py**

```python
# sentinel/core/wrapper.py
from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable, Literal

from sentinel.core.models import PolicyDefinition, PolicyViolation


class PolicyWrapper:
    """Provides the @policy.wrap decorator."""

    def __init__(self) -> None:
        self._config: Any = None

    def _get_config(self) -> Any:
        from sentinel import _config
        return _config

    def wrap(
        self,
        *,
        intent: str,
        risk_level: Literal["low", "medium", "high", "critical"],
        action_type: Literal["reversible", "irreversible", "destructive"],
        constraints: dict[str, Any] | None = None,
        semantic_check: bool = True,
        semantic_threshold: float = 0.8,
        on_block: Literal["raise", "return", "log_only"] = "return",
        on_modify: Literal["auto", "ask", "block"] = "auto",
        log_level: Literal["all", "blocks_only", "none"] = "all",
        agent_id: str | None = None,
        task_id: str | None = None,
    ) -> Callable[..., Any]:
        policy = PolicyDefinition(
            intent=intent,
            risk_level=risk_level,
            action_type=action_type,
            constraints=constraints or {},
            semantic_check=semantic_check,
            semantic_threshold=semantic_threshold,
            on_block=on_block,
            on_modify=on_modify,
            log_level=log_level,
        )

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = func.__name__

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Bind args to get full params dict
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                params = dict(bound.arguments)

                return asyncio.get_event_loop().run_until_complete(
                    _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level)
                )

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                params = dict(bound.arguments)
                return await _run(tool_name, policy, params, func, args, kwargs, agent_id, task_id, log_level)

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        async def _run(
            tool_name: str,
            policy: PolicyDefinition,
            params: dict[str, Any],
            func: Callable[..., Any],
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
            agent_id: str | None,
            task_id: str | None,
            log_level: str,
        ) -> Any:
            cfg = self._get_config()
            await cfg._ensure_initialized()

            effective_agent_id = agent_id or cfg.default_agent_id

            result = await cfg.engine.evaluate(
                policy, tool_name, params, cfg.semantic_checker
            )

            if result.outcome == "block":
                violation = PolicyViolation(
                    tool_name=tool_name,
                    reason=result.reason or "Policy check failed",
                    suggestion=f"Review constraints for {tool_name}: {result.checks_failed}",
                    what_happened=f"Failed checks: {', '.join(result.checks_failed)}",
                )

                log_outcome = result
                if policy.on_block == "log_only":
                    # Execute anyway, but log as pass_with_warning
                    from sentinel.core.models import PolicyResult
                    log_outcome = PolicyResult(
                        outcome="pass",
                        checks_run=result.checks_run,
                        checks_failed=result.checks_failed,
                        reason="log_only mode: executed despite violation",
                    )
                    if log_level != "none":
                        await cfg.logger.log(
                            agent_id=effective_agent_id,
                            tool_name=tool_name,
                            action_type=policy.action_type,
                            risk_level=policy.risk_level,
                            intent=policy.intent,
                            params=params,
                            policy_result=log_outcome,
                            task_id=task_id,
                            log_level=log_level,
                        )
                    if inspect.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    return func(*args, **kwargs)

                if log_level != "none":
                    await cfg.logger.log(
                        agent_id=effective_agent_id,
                        tool_name=tool_name,
                        action_type=policy.action_type,
                        risk_level=policy.risk_level,
                        intent=policy.intent,
                        params=params,
                        policy_result=result,
                        task_id=task_id,
                        log_level=log_level,
                    )

                if policy.on_block == "raise":
                    raise PermissionError(f"Sentinel blocked {tool_name}: {violation.reason}")
                return violation

            # PASS: execute function
            if inspect.iscoroutinefunction(func):
                execution_result = await func(*args, **kwargs)
            else:
                execution_result = func(*args, **kwargs)

            if log_level != "none":
                await cfg.logger.log(
                    agent_id=effective_agent_id,
                    tool_name=tool_name,
                    action_type=policy.action_type,
                    risk_level=policy.risk_level,
                    intent=policy.intent,
                    params=params,
                    policy_result=result,
                    execution_result=execution_result if isinstance(execution_result, dict) else None,
                    task_id=task_id,
                    log_level=log_level,
                )

            return execution_result

        return decorator


policy = PolicyWrapper()
```

**Step 6: Implement `sentinel/__init__.py`**

```python
# sentinel/__init__.py
from __future__ import annotations

from sentinel.config import SentinelConfig
from sentinel.core.wrapper import policy

_config = SentinelConfig()


def configure(
    *,
    semantic_checker=None,
    db_path: str | None = None,
    default_agent_id: str = "default",
) -> None:
    global _config
    _config = SentinelConfig(
        semantic_checker=semantic_checker,
        db_path=db_path,
        default_agent_id=default_agent_id,
    )


__all__ = ["policy", "configure", "SentinelConfig"]
```

**Step 7: Run tests**

```bash
uv run pytest tests/test_wrapper.py -v
```
Expected: All tests PASS

**Step 8: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: All tests PASS

**Step 9: Commit**

```bash
git add sentinel/ tests/test_wrapper.py
git commit -m "feat: implement @policy.wrap decorator and PolicyEngine"
```

---

## Task 7: Semantic Checker

**Files:**
- Create: `sentinel/core/semantic.py`
- Create: `tests/test_semantic.py`

**Step 1: Write failing tests**

```python
# tests/test_semantic.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_semantic_result_consistent():
    from sentinel.core.semantic import SemanticResult
    r = SemanticResult(consistent=True, confidence=0.95, reason="Matches intent")
    assert r.consistent is True


async def test_anthropic_checker_parses_response():
    """Mock the Anthropic API call and verify parsing."""
    from sentinel.core.semantic import AnthropicSemanticChecker

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"consistent": true, "confidence": 0.92, "reason": "Matches"}')]
    mock_client.messages.create = MagicMock(return_value=mock_message)

    checker = AnthropicSemanticChecker(api_key="test-key")
    checker._client = mock_client

    result = await checker.check(
        tool_name="send_email",
        params={"to": "user@co.com", "body": "Meeting confirmed"},
        intent="manage executive communications",
    )
    assert result.consistent is True
    assert result.confidence == 0.92


async def test_anthropic_checker_handles_off_intent():
    from sentinel.core.semantic import AnthropicSemanticChecker

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"consistent": false, "confidence": 0.95, "reason": "Unrelated to declared intent"}')]
    mock_client.messages.create = MagicMock(return_value=mock_message)

    checker = AnthropicSemanticChecker(api_key="test-key")
    checker._client = mock_client

    result = await checker.check(
        tool_name="delete_files",
        params={"path": "/etc"},
        intent="manage executive communications",
    )
    assert result.consistent is False
    assert result.confidence >= 0.8


async def test_cache_returns_cached_result():
    from sentinel.core.semantic import CachedSemanticChecker, SemanticResult

    inner = AsyncMock(return_value=SemanticResult(consistent=True, confidence=0.9, reason="ok"))
    checker = CachedSemanticChecker(inner)

    r1 = await checker.check("send_email", {"to": "a@b.com"}, "send emails")
    r2 = await checker.check("send_email", {"to": "a@b.com"}, "send emails")

    assert inner.call_count == 1  # second call was cached
    assert r1.consistent == r2.consistent


async def test_cache_misses_on_different_params():
    from sentinel.core.semantic import CachedSemanticChecker, SemanticResult

    inner = AsyncMock(return_value=SemanticResult(consistent=True, confidence=0.9, reason="ok"))
    checker = CachedSemanticChecker(inner)

    await checker.check("send_email", {"to": "a@b.com"}, "send emails")
    await checker.check("send_email", {"to": "c@d.com"}, "send emails")

    assert inner.call_count == 2


async def test_semantic_checker_fails_gracefully():
    """If LLM returns malformed JSON, return consistent=True (fallback to rules)."""
    from sentinel.core.semantic import AnthropicSemanticChecker

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="I cannot determine this.")]
    mock_client.messages.create = MagicMock(return_value=mock_message)

    checker = AnthropicSemanticChecker(api_key="test-key")
    checker._client = mock_client

    result = await checker.check("send_email", {}, "send emails")
    assert result.consistent is True  # fail open — rules already passed
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_semantic.py -v
```

**Step 3: Implement semantic.py**

```python
# sentinel/core/semantic.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

SEMANTIC_CHECK_PROMPT = """You are a policy enforcement system.

Declared intent: {intent}
Proposed action: {tool_name}({params})

Is this action consistent with the declared intent?
Answer with JSON only:
{{
  "consistent": true | false,
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation"
}}"""


@dataclass
class SemanticResult:
    consistent: bool
    confidence: float
    reason: str


SemanticCheckerCallable = Callable[
    [str, dict[str, Any], str],
    Coroutine[Any, Any, SemanticResult],
]


class AnthropicSemanticChecker:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self._client: Any = None
        self._api_key = api_key

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    async def check(
        self, tool_name: str, params: dict[str, Any], intent: str
    ) -> SemanticResult:
        prompt = SEMANTIC_CHECK_PROMPT.format(
            intent=intent,
            tool_name=tool_name,
            params=json.dumps(params, default=str),
        )
        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            # Extract JSON — handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            data = json.loads(text)
            return SemanticResult(
                consistent=bool(data["consistent"]),
                confidence=float(data["confidence"]),
                reason=str(data["reason"]),
            )
        except Exception:
            # Fail open: if semantic check errors, allow (rules already passed)
            return SemanticResult(consistent=True, confidence=0.0, reason="semantic check unavailable")


class CachedSemanticChecker:
    """Wraps any semantic checker callable with an in-memory cache."""

    def __init__(self, inner: SemanticCheckerCallable) -> None:
        self._inner = inner
        self._cache: dict[str, SemanticResult] = {}

    def _cache_key(self, tool_name: str, params: dict[str, Any], intent: str) -> str:
        payload = json.dumps({"tool": tool_name, "params": params, "intent": intent}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    async def check(self, tool_name: str, params: dict[str, Any], intent: str) -> SemanticResult:
        key = self._cache_key(tool_name, params, intent)
        if key in self._cache:
            return self._cache[key]
        result = await self._inner(tool_name, params, intent)
        self._cache[key] = result
        return result
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_semantic.py -v
```
Expected: All PASS

**Step 5: Wire CachedSemanticChecker into config.py**

In `sentinel/config.py`, update `_get_default_semantic_checker`:

```python
def _get_default_semantic_checker(self) -> SemanticChecker | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from sentinel.core.semantic import AnthropicSemanticChecker, CachedSemanticChecker
        checker = AnthropicSemanticChecker(api_key=api_key)
        cached = CachedSemanticChecker(checker.check)
        return cached.check
    except ImportError:
        return None
```

**Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```

**Step 7: Commit**

```bash
git add sentinel/core/semantic.py tests/test_semantic.py sentinel/config.py
git commit -m "feat: implement provider-agnostic semantic checker with caching"
```

---

## Task 8: Anthropic SDK Integration

**Files:**
- Create: `sentinel/integrations/anthropic.py`
- Create: `tests/test_integrations_anthropic.py`

**Step 1: Write failing tests**

```python
# tests/test_integrations_anthropic.py
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_tool_use_block(name: str, input_dict: dict, tool_use_id: str = "tu_123"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    block.id = tool_use_id
    return block


async def test_dispatcher_dispatches_tool(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.integrations.anthropic import SentinelToolDispatcher
    from sentinel.core.models import PolicyDefinition

    def my_tool(x: int) -> dict:
        return {"result": x * 2}

    policy_def = PolicyDefinition(
        intent="compute values",
        risk_level="low",
        action_type="reversible",
        semantic_check=False,
    )

    dispatcher = SentinelToolDispatcher(
        tools={"my_tool": my_tool},
        policies={"my_tool": policy_def},
    )

    block = make_tool_use_block("my_tool", {"x": 5})
    result = await dispatcher.dispatch(block)
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "tu_123"
    assert result["content"] == '{"result": 10}'


async def test_dispatcher_returns_block_result(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.integrations.anthropic import SentinelToolDispatcher
    from sentinel.core.models import PolicyDefinition

    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    policy_def = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        constraints={"blocked_keywords": ["confidential"]},
        semantic_check=False,
    )

    dispatcher = SentinelToolDispatcher(
        tools={"send_email": send_email},
        policies={"send_email": policy_def},
    )

    block = make_tool_use_block("send_email", {"to": "x@y.com", "body": "confidential info"})
    result = await dispatcher.dispatch(block)
    assert result["type"] == "tool_result"
    assert "blocked" in result["content"].lower() or "keyword" in result["content"].lower()


async def test_dispatcher_dispatch_all(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.integrations.anthropic import SentinelToolDispatcher
    from sentinel.core.models import PolicyDefinition

    def tool_a(x: int) -> dict:
        return {"a": x}

    def tool_b(y: str) -> dict:
        return {"b": y}

    policies = {
        "tool_a": PolicyDefinition(intent="compute", risk_level="low", action_type="reversible", semantic_check=False),
        "tool_b": PolicyDefinition(intent="log", risk_level="low", action_type="reversible", semantic_check=False),
    }

    dispatcher = SentinelToolDispatcher(
        tools={"tool_a": tool_a, "tool_b": tool_b},
        policies=policies,
    )

    content = [
        MagicMock(type="text"),
        make_tool_use_block("tool_a", {"x": 1}, "id_1"),
        make_tool_use_block("tool_b", {"y": "hello"}, "id_2"),
    ]
    results = await dispatcher.dispatch_all(content)
    assert len(results) == 2
    tool_use_ids = [r["tool_use_id"] for r in results]
    assert "id_1" in tool_use_ids
    assert "id_2" in tool_use_ids


def test_tool_schemas_generated(tmp_path):
    from sentinel.integrations.anthropic import SentinelToolDispatcher
    from sentinel.core.models import PolicyDefinition
    import inspect

    def send_email(to: str, subject: str, body: str) -> dict:
        """Send an email."""
        return {}

    policy_def = PolicyDefinition(
        intent="send emails",
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )

    dispatcher = SentinelToolDispatcher(
        tools={"send_email": send_email},
        policies={"send_email": policy_def},
    )

    schemas = dispatcher.tool_schemas
    assert len(schemas) == 1
    assert schemas[0]["name"] == "send_email"
    assert "input_schema" in schemas[0]
    assert "to" in schemas[0]["input_schema"]["properties"]
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_integrations_anthropic.py -v
```

**Step 3: Implement anthropic integration**

```python
# sentinel/integrations/anthropic.py
from __future__ import annotations

import inspect
import json
from typing import Any, Callable

from sentinel.core.models import PolicyDefinition, PolicyViolation
from sentinel.core.wrapper import policy as sentinel_policy


def _infer_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate a basic JSON schema from function signature type hints."""
    sig = inspect.signature(func)
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        ann = param.annotation
        json_type = type_map.get(ann, "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class SentinelToolDispatcher:
    """Dispatches Claude tool_use blocks through Sentinel policy checks."""

    def __init__(
        self,
        tools: dict[str, Callable[..., Any]],
        policies: dict[str, PolicyDefinition] | None = None,
    ) -> None:
        self._tools = tools
        self._policies = policies or {}
        self._wrapped: dict[str, Callable[..., Any]] = {}
        self._wrap_tools()

    def _wrap_tools(self) -> None:
        for name, func in self._tools.items():
            pol = self._policies.get(name)
            if pol:
                wrapped = sentinel_policy.wrap(
                    intent=pol.intent,
                    risk_level=pol.risk_level,
                    action_type=pol.action_type,
                    constraints=pol.constraints,
                    semantic_check=pol.semantic_check,
                    semantic_threshold=pol.semantic_threshold,
                    on_block=pol.on_block,
                    on_modify=pol.on_modify,
                    log_level=pol.log_level,
                )(func)
                self._wrapped[name] = wrapped
            else:
                self._wrapped[name] = func

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for name, func in self._tools.items():
            schemas.append({
                "name": name,
                "description": inspect.getdoc(func) or f"Tool: {name}",
                "input_schema": _infer_schema(func),
            })
        return schemas

    async def dispatch(self, tool_use_block: Any) -> dict[str, Any]:
        name = tool_use_block.name
        params = tool_use_block.input
        tool_use_id = tool_use_block.id

        func = self._wrapped.get(name)
        if func is None:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"error": f"Unknown tool: {name}"}),
                "is_error": True,
            }

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**params)
            else:
                result = func(**params)

            if isinstance(result, PolicyViolation):
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps({
                        "blocked": True,
                        "reason": result.reason,
                        "suggestion": result.suggestion,
                        "what_happened": result.what_happened,
                    }),
                    "is_error": False,
                }

            content = json.dumps(result) if isinstance(result, dict) else str(result)
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
        except Exception as e:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"error": str(e)}),
                "is_error": True,
            }

    async def dispatch_all(self, content_blocks: list[Any]) -> list[dict[str, Any]]:
        results = []
        for block in content_blocks:
            if getattr(block, "type", None) == "tool_use":
                result = await self.dispatch(block)
                results.append(result)
        return results
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_integrations_anthropic.py -v
```
Expected: All PASS

**Step 5: Run full suite**

```bash
uv run pytest tests/ -v
```

**Step 6: Commit**

```bash
git add sentinel/integrations/anthropic.py tests/test_integrations_anthropic.py
git commit -m "feat: implement Anthropic SDK integration (SentinelToolDispatcher)"
```

---

## Task 9: FastAPI Audit Log API

**Files:**
- Create: `sentinel/api/app.py`
- Create: `sentinel/api/routes/audit.py`
- Create: `sentinel/api/routes/policies.py`
- Create: `tests/test_api.py`

**Step 1: Write failing tests**

```python
# tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client(tmp_path):
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))
    cfg = sentinel._config
    await cfg._ensure_initialized()

    from sentinel.api.app import create_app
    app = create_app(cfg)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_get_entries_empty(client):
    resp = await client.get("/audit/entries")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_entries_after_write(client, tmp_path):
    import sentinel
    cfg = sentinel._config
    from sentinel.core.models import AuditEntry
    entry = AuditEntry(
        agent_id="agent-1",
        tool_name="send_email",
        action_type="irreversible",
        risk_level="high",
        intent="test",
        params={"to": "a@b.com"},
        outcome="pass",
        policy_result={},
    )
    await cfg.store.write(entry)

    resp = await client.get("/audit/entries?agent_id=agent-1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["tool_name"] == "send_email"


async def test_get_summary(client, tmp_path):
    import sentinel
    cfg = sentinel._config
    from sentinel.core.models import AuditEntry

    for outcome in ["pass", "pass", "block"]:
        entry = AuditEntry(
            agent_id="agent-1",
            tool_name="send_email",
            action_type="irreversible",
            risk_level="high",
            intent="test",
            params={},
            outcome=outcome,
            policy_result={},
        )
        await cfg.store.write(entry)

    resp = await client.get("/audit/summary?agent_id=agent-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 3
    assert data["passes"] == 2
    assert data["blocks"] == 1


async def test_get_blocks(client, tmp_path):
    import sentinel
    cfg = sentinel._config
    from sentinel.core.models import AuditEntry

    for outcome in ["pass", "block"]:
        entry = AuditEntry(
            agent_id="a1",
            tool_name="tool",
            action_type="reversible",
            risk_level="low",
            intent="test",
            params={},
            outcome=outcome,
            policy_result={},
        )
        await cfg.store.write(entry)

    resp = await client.get("/audit/blocks?agent_id=a1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["outcome"] == "block"
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_api.py -v
```

**Step 3: Implement API**

```python
# sentinel/api/routes/audit.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(prefix="/audit", tags=["audit"])


def get_store() -> Any:
    import sentinel
    return sentinel._config.store


@router.get("/entries")
async def get_entries(
    agent_id: str | None = Query(None),
    limit: int = Query(100, le=1000),
    since: datetime | None = Query(None),
) -> list[dict[str, Any]]:
    store = get_store()
    entries = await store.get_entries(agent_id=agent_id, limit=limit, since=since)
    return [e.model_dump(mode="json") for e in entries]


@router.get("/blocks")
async def get_blocks(
    agent_id: str | None = Query(None),
    since: datetime | None = Query(None),
) -> list[dict[str, Any]]:
    store = get_store()
    entries = await store.get_blocks(agent_id=agent_id, since=since)
    return [e.model_dump(mode="json") for e in entries]


@router.get("/summary")
async def get_summary(
    agent_id: str | None = Query(None),
    since: datetime | None = Query(None),
) -> dict[str, Any]:
    store = get_store()
    summary = await store.get_summary(agent_id=agent_id, since=since)
    return summary.model_dump()
```

```python
# sentinel/api/routes/policies.py
from fastapi import APIRouter

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("/")
async def list_policies() -> dict:
    return {"message": "Policy registry not yet implemented"}
```

```python
# sentinel/api/app.py
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from sentinel.api.routes import audit, policies


def create_app(config: Any | None = None) -> FastAPI:
    app = FastAPI(title="Sentinel Audit API", version="0.1.0")
    app.include_router(audit.router)
    app.include_router(policies.router)
    return app


app = create_app()
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_api.py -v
```
Expected: All PASS

**Step 5: Run full suite**

```bash
uv run pytest tests/ -v
```

**Step 6: Commit**

```bash
git add sentinel/api/ tests/test_api.py
git commit -m "feat: implement FastAPI audit log API"
```

---

## Task 10: CLI

**Files:**
- Create: `sentinel/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing test**

```python
# tests/test_cli.py
import pytest
from click.testing import CliRunner


def test_cli_audit_no_entries(tmp_path):
    from sentinel.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--db", str(tmp_path / "test.db")])
    assert result.exit_code == 0
    assert "No entries" in result.output or result.output.strip() == "" or "agent" in result.output.lower()


def test_cli_help():
    from sentinel.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "sentinel" in result.output.lower() or "audit" in result.output.lower()
```

**Step 2: Add click dependency**

```bash
uv add click rich
```

**Step 3: Implement CLI**

```python
# sentinel/cli.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import click


@click.group()
def cli() -> None:
    """Sentinel — Agent Action Policy Engine CLI"""


@cli.command()
@click.option("--agent-id", default=None, help="Filter by agent ID")
@click.option("--since", default="24h", help="Time window: 1h, 24h, 7d (default: 24h)")
@click.option("--outcome", default=None, type=click.Choice(["pass", "block", "modify"]))
@click.option("--limit", default=50, help="Max entries to show")
@click.option("--db", default="sentinel_audit.db", help="Path to SQLite DB")
def audit(agent_id: Optional[str], since: str, outcome: Optional[str], limit: int, db: str) -> None:
    """Display audit log entries."""
    asyncio.run(_audit(agent_id=agent_id, since=since, outcome=outcome, limit=limit, db=db))


def _parse_since(since: str) -> datetime:
    units = {"h": 3600, "d": 86400, "m": 60}
    try:
        unit = since[-1]
        value = int(since[:-1])
        return datetime.now(timezone.utc) - timedelta(seconds=value * units[unit])
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=24)


async def _audit(
    agent_id: Optional[str],
    since: str,
    outcome: Optional[str],
    limit: int,
    db: str,
) -> None:
    from rich.console import Console
    from rich.table import Table
    from sentinel.audit.store import AuditStore

    store = AuditStore(db_path=db)
    await store.initialize()

    since_dt = _parse_since(since)

    if outcome == "block":
        entries = await store.get_blocks(agent_id=agent_id, since=since_dt)
    else:
        entries = await store.get_entries(agent_id=agent_id, limit=limit, since=since_dt)

    if outcome and outcome != "block":
        entries = [e for e in entries if e.outcome == outcome]

    await store.close()

    console = Console()
    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return

    table = Table(title=f"Sentinel Audit Log ({len(entries)} entries)")
    table.add_column("Time", style="dim")
    table.add_column("Agent")
    table.add_column("Tool")
    table.add_column("Outcome")
    table.add_column("Risk")
    table.add_column("Reason")

    outcome_styles = {"pass": "green", "block": "red", "modify": "yellow"}

    for e in entries:
        ts = e.timestamp.strftime("%m-%d %H:%M:%S")
        style = outcome_styles.get(e.outcome, "white")
        table.add_row(
            ts,
            e.agent_id,
            e.tool_name,
            f"[{style}]{e.outcome}[/{style}]",
            e.risk_level,
            e.block_reason or "",
        )

    console.print(table)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_cli.py -v
```
Expected: All PASS

**Step 5: Run full suite**

```bash
uv run pytest tests/ -v
```

**Step 6: Commit**

```bash
git add sentinel/cli.py tests/test_cli.py
git commit -m "feat: implement CLI with audit command"
```

---

## Task 11: End-to-End Integration Test (Executive Assistant)

**Files:**
- Create: `tests/test_e2e.py`

**Step 1: Write the integration test**

```python
# tests/test_e2e.py
"""
End-to-end test: executive assistant scenario.
Uses mocked Anthropic client — no real API calls.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock


async def test_e2e_pass_send_email(tmp_path):
    """send_email to allowed domain passes policy."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails on behalf of the executive",
        constraints={
            "blocked_keywords": ["password", "confidential", "wire transfer"],
            "max_recipients": 5,
        },
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent", "message_id": "msg_123"}

    result = send_email(
        to="sarah@company.com",
        subject="Meeting confirmation",
        body="Hi Sarah, confirming our 2pm meeting tomorrow.",
    )
    assert result == {"status": "sent", "message_id": "msg_123"}


async def test_e2e_block_keyword_in_body(tmp_path):
    """send_email with blocked keyword is blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails on behalf of the executive",
        constraints={
            "blocked_keywords": ["password", "confidential", "wire transfer"],
        },
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"status": "sent"}

    from sentinel.core.models import PolicyViolation
    result = send_email(to="user@co.com", subject="Hi", body="Here is the wire transfer details")
    assert isinstance(result, PolicyViolation)
    assert "keyword" in result.what_happened.lower() or "keyword" in result.reason.lower()


async def test_e2e_block_excess_recipients(tmp_path):
    """send_email to too many recipients is blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"max_recipients": 3},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: list, subject: str, body: str) -> dict:
        return {"status": "sent"}

    from sentinel.core.models import PolicyViolation
    result = send_email(
        to=["a@x.com", "b@x.com", "c@x.com", "d@x.com"],
        subject="Hi",
        body="Hello",
    )
    assert isinstance(result, PolicyViolation)


async def test_e2e_create_event_pass(tmp_path):
    """create_event with valid params passes policy."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="schedule calendar events for the executive",
        constraints={
            "max_duration_hours": 4,
            "allowed_calendars": ["primary"],
        },
        risk_level="medium",
        action_type="reversible",
        semantic_check=False,
    )
    def create_event(title: str, start: str, end: str, attendees: list) -> dict:
        return {"status": "created", "event_id": "evt_456"}

    result = create_event(
        title="1hr meeting with Sarah",
        start="2026-03-11T14:00:00",
        end="2026-03-11T15:00:00",
        attendees=["sarah@company.com"],
    )
    assert result == {"status": "created", "event_id": "evt_456"}


async def test_e2e_audit_log_populated(tmp_path):
    """After tool calls, audit log contains correct entries."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="test tool",
        risk_level="low",
        action_type="reversible",
        semantic_check=False,
        agent_id="test-agent",
    )
    def my_tool(x: str) -> dict:
        return {"ok": True}

    my_tool(x="hello")  # should pass

    @sentinel.policy.wrap(
        intent="test tool",
        constraints={"blocked_keywords": ["bad"]},
        risk_level="low",
        action_type="reversible",
        semantic_check=False,
        agent_id="test-agent",
    )
    def another_tool(x: str) -> dict:
        return {"ok": True}

    another_tool(x="bad content")  # should block

    import asyncio
    cfg = sentinel._config
    await cfg._ensure_initialized()
    entries = await cfg.store.get_entries(agent_id="test-agent")
    assert len(entries) == 2
    outcomes = {e.outcome for e in entries}
    assert "pass" in outcomes
    assert "block" in outcomes


async def test_e2e_dispatcher_with_policies(tmp_path):
    """SentinelToolDispatcher dispatches tool_use blocks correctly."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.integrations.anthropic import SentinelToolDispatcher
    from sentinel.core.models import PolicyDefinition

    def send_email(to: str, subject: str, body: str) -> dict:
        """Send an email."""
        return {"status": "sent"}

    def create_event(title: str, start: str, end: str, attendees: list) -> dict:
        """Create a calendar event."""
        return {"status": "created"}

    policies = {
        "send_email": PolicyDefinition(
            intent="send emails on behalf of the executive",
            risk_level="high",
            action_type="irreversible",
            constraints={"blocked_keywords": ["confidential"]},
            semantic_check=False,
        ),
        "create_event": PolicyDefinition(
            intent="schedule calendar events",
            risk_level="medium",
            action_type="reversible",
            semantic_check=False,
        ),
    }

    dispatcher = SentinelToolDispatcher(
        tools={"send_email": send_email, "create_event": create_event},
        policies=policies,
    )

    from unittest.mock import MagicMock

    # Test passing call
    block = MagicMock()
    block.type = "tool_use"
    block.name = "send_email"
    block.input = {"to": "sarah@company.com", "subject": "Hi", "body": "Meeting confirmed"}
    block.id = "tu_001"
    result = await dispatcher.dispatch(block)
    assert result["type"] == "tool_result"
    import json
    content = json.loads(result["content"])
    assert content.get("status") == "sent"

    # Test blocked call
    block2 = MagicMock()
    block2.type = "tool_use"
    block2.name = "send_email"
    block2.input = {"to": "x@y.com", "subject": "Hi", "body": "This is confidential"}
    block2.id = "tu_002"
    result2 = await dispatcher.dispatch(block2)
    content2 = json.loads(result2["content"])
    assert content2.get("blocked") is True
```

**Step 2: Run integration tests**

```bash
uv run pytest tests/test_e2e.py -v
```
Expected: All PASS

**Step 3: Run full suite**

```bash
uv run pytest tests/ -v
```
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add end-to-end executive assistant integration tests"
```

---

## Task 12: README

**Files:**
- Create: `README.md`

**Step 1: Write README**

Content should include:
- What Sentinel is (one paragraph)
- Installation (`uv pip install sentinel` / `uv sync`)
- Quick start — the `@policy.wrap` decorator example with `send_email`
- All three outcomes (pass, block, modify)
- SentinelConfig and semantic check setup (BYO callable, `.env` default)
- SentinelToolDispatcher example for Claude integration
- CLI usage: `sentinel audit --agent-id X --since 24h`
- Policy constraints reference table
- Acceptance criteria coverage note

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with quickstart and usage examples"
```

---

## Task 13: Final Verification

**Step 1: Run full test suite with coverage**

```bash
uv run pytest tests/ -v --tb=short
```
Expected: All tests PASS, 0 failures

**Step 2: Type check**

```bash
uv run mypy sentinel/ --ignore-missing-imports
```
Expected: No errors (or only import-related warnings from optional deps)

**Step 3: Lint**

```bash
uv run ruff check sentinel/ tests/
```
Expected: No errors

**Step 4: Final commit**

```bash
git add .
git commit -m "chore: final verification — all tests pass, mypy clean"
```
