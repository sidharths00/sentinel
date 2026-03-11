# tests/test_audit_logger.py
from unittest.mock import AsyncMock

import pytest

from sentinel.core.models import PolicyResult


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
    logger = AuditLogger(store=mock_store)
    result = PolicyResult(outcome="pass", checks_run=[], checks_failed=[])
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
