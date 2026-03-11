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
    from datetime import datetime

    from sentinel.core.models import AuditEntry
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
