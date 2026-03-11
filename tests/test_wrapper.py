# tests/test_wrapper.py
import pytest


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
