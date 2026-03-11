# tests/test_e2e.py
"""
End-to-end tests: executive assistant scenario.
Uses no real API calls — semantic_check=False on all tools.
"""
import json
from unittest.mock import MagicMock


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
    assert result.tool_name == "send_email"


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
    sentinel.configure(db_path=str(tmp_path / "test.db"), default_agent_id="test-agent")

    @sentinel.policy.wrap(
        intent="test tool",
        risk_level="low",
        action_type="reversible",
        semantic_check=False,
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
    )
    def another_tool(x: str) -> dict:
        return {"ok": True}

    another_tool(x="bad content")  # should block

    cfg = sentinel._config
    await cfg._ensure_initialized()
    entries = await cfg.store.get_entries(agent_id="test-agent")
    assert len(entries) == 2
    outcomes = {e.outcome for e in entries}
    assert "pass" in outcomes
    assert "block" in outcomes


async def test_e2e_dispatcher_pass_and_block(tmp_path):
    """SentinelToolDispatcher: one tool passes, one is blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.core.models import PolicyDefinition
    from sentinel.integrations.anthropic import SentinelToolDispatcher

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

    # Test passing call
    block = MagicMock()
    block.type = "tool_use"
    block.name = "send_email"
    block.input = {"to": "sarah@company.com", "subject": "Hi", "body": "Meeting confirmed"}
    block.id = "tu_001"
    result = await dispatcher.dispatch(block)
    assert result["type"] == "tool_result"
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
