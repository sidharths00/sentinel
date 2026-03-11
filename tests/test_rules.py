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
