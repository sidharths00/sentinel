# tests/test_real_usage.py
"""
Tests that mirror what a real user following the README would actually do.
Covers gaps not in the existing suite: async tools, field_patterns,
max_duration_hours, multiple violations, domain blocklist via wrapper,
and the basic.py demo scenario end-to-end.
"""
import pytest

from sentinel.core.models import PolicyViolation


# ---------------------------------------------------------------------------
# Async tool wrapping — common in Claude agent code
# ---------------------------------------------------------------------------

async def test_async_tool_pass(tmp_path):
    """Async tools wrapped with @policy.wrap execute and return normally on PASS."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails on behalf of the user",
        constraints={"blocked_keywords": ["password"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    async def send_email_async(to: str, subject: str, body: str) -> dict:
        return {"status": "sent", "to": to}

    result = await send_email_async(
        to="alice@company.com", subject="Hello", body="Meeting confirmed."
    )
    assert result == {"status": "sent", "to": "alice@company.com"}


async def test_async_tool_block(tmp_path):
    """Async tools wrapped with @policy.wrap return PolicyViolation on BLOCK."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    called = []

    @sentinel.policy.wrap(
        intent="send emails on behalf of the user",
        constraints={"blocked_keywords": ["password"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    async def send_email_async(to: str, subject: str, body: str) -> dict:
        called.append(True)
        return {"status": "sent"}

    result = await send_email_async(
        to="alice@company.com", subject="Creds", body="Here is the password: hunter2"
    )
    assert isinstance(result, PolicyViolation)
    assert result.tool_name == "send_email_async"
    assert len(called) == 0  # function body was NOT executed


# ---------------------------------------------------------------------------
# field_patterns (regex) constraint through the wrapper
# ---------------------------------------------------------------------------

def test_field_patterns_pass(tmp_path):
    """field_patterns allows values matching the regex."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="delete only temp build artifacts",
        constraints={"field_patterns": {"path": r"^/tmp/build/"}},
        risk_level="critical",
        action_type="destructive",
        semantic_check=False,
    )
    def delete_files(path: str) -> dict:
        return {"deleted": path}

    result = delete_files(path="/tmp/build/output.o")
    assert result == {"deleted": "/tmp/build/output.o"}


def test_field_patterns_block(tmp_path):
    """field_patterns blocks values that don't match the regex."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="delete only temp build artifacts",
        constraints={"field_patterns": {"path": r"^/tmp/build/"}},
        risk_level="critical",
        action_type="destructive",
        semantic_check=False,
    )
    def delete_files(path: str) -> dict:
        return {"deleted": path}

    result = delete_files(path="/home/user/important_file.py")
    assert isinstance(result, PolicyViolation)


# ---------------------------------------------------------------------------
# max_duration_hours through the wrapper
# ---------------------------------------------------------------------------

def test_max_duration_hours_pass(tmp_path):
    """Events within the duration limit pass."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="schedule calendar events",
        constraints={"max_duration_hours": 4},
        risk_level="medium",
        action_type="reversible",
        semantic_check=False,
    )
    def create_event(title: str, start: str, end: str) -> dict:
        return {"status": "created"}

    result = create_event(
        title="Team sync",
        start="2026-03-11T14:00:00",
        end="2026-03-11T15:00:00",  # 1 hour
    )
    assert result == {"status": "created"}


def test_max_duration_hours_block(tmp_path):
    """Events exceeding the duration limit are blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="schedule calendar events",
        constraints={"max_duration_hours": 4},
        risk_level="medium",
        action_type="reversible",
        semantic_check=False,
    )
    def create_event(title: str, start: str, end: str) -> dict:
        return {"status": "created"}

    result = create_event(
        title="All-day workshop",
        start="2026-03-11T09:00:00",
        end="2026-03-11T18:00:00",  # 9 hours — exceeds limit
    )
    assert isinstance(result, PolicyViolation)


# ---------------------------------------------------------------------------
# blocked_recipient_domains through the wrapper
# ---------------------------------------------------------------------------

def test_blocked_recipient_domain_pass(tmp_path):
    """Sending to a non-blocked domain passes."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_recipient_domains": ["@competitor.com"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="alice@company.com", body="Hi!")
    assert result == {"status": "sent"}


def test_blocked_recipient_domain_block(tmp_path):
    """Sending to a blocked domain is blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_recipient_domains": ["@competitor.com"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="sales@competitor.com", body="Hi!")
    assert isinstance(result, PolicyViolation)


# ---------------------------------------------------------------------------
# Multiple constraints — any violation blocks
# ---------------------------------------------------------------------------

def test_multiple_constraints_both_violated(tmp_path):
    """When multiple constraints are violated, the call is still blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={
            "blocked_keywords": ["password"],
            "allowed_recipient_domains": ["@company.com"],
        },
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    # Violates both: external domain AND blocked keyword
    result = send_email(to="attacker@evil.com", body="Here is the password: hunter2")
    assert isinstance(result, PolicyViolation)


def test_multiple_constraints_one_violated(tmp_path):
    """When only one of multiple constraints is violated, the call is still blocked."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={
            "blocked_keywords": ["password"],
            "allowed_recipient_domains": ["@company.com"],
        },
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    # Clean body but wrong domain
    result = send_email(to="attacker@evil.com", body="Meeting confirmed.")
    assert isinstance(result, PolicyViolation)


def test_multiple_constraints_all_pass(tmp_path):
    """When all constraints pass, the function executes normally."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={
            "blocked_keywords": ["password"],
            "allowed_recipient_domains": ["@company.com"],
        },
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="alice@company.com", body="Meeting confirmed.")
    assert result == {"status": "sent"}


# ---------------------------------------------------------------------------
# Function body is never called on BLOCK (critical safety guarantee)
# ---------------------------------------------------------------------------

def test_function_body_never_executes_on_block(tmp_path):
    """The wrapped function body NEVER runs when a constraint is violated."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    side_effects = []

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_keywords": ["confidential"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        side_effects.append("EMAIL_SENT")  # this must NOT run
        return {"status": "sent"}

    result = send_email(to="user@co.com", body="This is confidential")
    assert isinstance(result, PolicyViolation)
    assert len(side_effects) == 0, "Function body executed despite policy violation!"


# ---------------------------------------------------------------------------
# PolicyViolation fields are correct (what the README promises)
# ---------------------------------------------------------------------------

def test_policy_violation_has_correct_fields(tmp_path):
    """PolicyViolation returned to callers has tool_name, reason, suggestion, what_happened."""
    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    @sentinel.policy.wrap(
        intent="send emails",
        constraints={"blocked_keywords": ["password"]},
        risk_level="high",
        action_type="irreversible",
        semantic_check=False,
    )
    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    result = send_email(to="user@co.com", body="password: hunter2")
    assert isinstance(result, PolicyViolation)
    assert result.tool_name == "send_email"
    assert isinstance(result.reason, str) and len(result.reason) > 0
    assert isinstance(result.suggestion, str) and len(result.suggestion) > 0
    assert isinstance(result.what_happened, str) and len(result.what_happened) > 0


# ---------------------------------------------------------------------------
# db_path=":memory:" works (used in the README quickstart)
# ---------------------------------------------------------------------------

def test_in_memory_db_works():
    """sentinel.configure(db_path=':memory:') works — used in the quickstart."""
    import sentinel
    sentinel.configure(db_path=":memory:")

    @sentinel.policy.wrap(
        intent="test tool",
        risk_level="low",
        action_type="reversible",
        semantic_check=False,
    )
    def my_tool(x: str) -> dict:
        return {"ok": True, "x": x}

    result = my_tool(x="hello")
    assert result == {"ok": True, "x": "hello"}


# ---------------------------------------------------------------------------
# Dispatcher returns correct structure for Claude tool_use loop
# ---------------------------------------------------------------------------

async def test_dispatcher_blocked_tool_result_structure(tmp_path):
    """Blocked dispatcher result has the exact structure Claude's loop expects."""
    import json
    from unittest.mock import MagicMock

    import sentinel
    sentinel.configure(db_path=str(tmp_path / "test.db"))

    from sentinel.core.models import PolicyDefinition
    from sentinel.integrations.anthropic import SentinelToolDispatcher

    def send_email(to: str, body: str) -> dict:
        return {"status": "sent"}

    dispatcher = SentinelToolDispatcher(
        tools={"send_email": send_email},
        policies={
            "send_email": PolicyDefinition(
                intent="send emails",
                risk_level="high",
                action_type="irreversible",
                constraints={"blocked_keywords": ["confidential"]},
                semantic_check=False,
            )
        },
    )

    block = MagicMock()
    block.type = "tool_use"
    block.name = "send_email"
    block.input = {"to": "x@y.com", "body": "confidential data"}
    block.id = "tu_999"

    result = await dispatcher.dispatch(block)

    # Claude's tool_use loop requires these exact fields
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "tu_999"
    content = json.loads(result["content"])
    assert content["blocked"] is True
    assert "reason" in content
    assert "suggestion" in content
