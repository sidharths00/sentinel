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
