# tests/test_audit_store.py
import uuid
from datetime import datetime, timedelta, timezone

import pytest


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
    from sentinel.core.models import AuditEntry
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
