# tests/test_semantic.py
from unittest.mock import AsyncMock, MagicMock


async def test_semantic_result_consistent():
    from sentinel.core.semantic import SemanticResult
    r = SemanticResult(consistent=True, confidence=0.95, reason="Matches intent")
    assert r.consistent is True


async def test_anthropic_checker_parses_response():
    """Mock the Anthropic API call and verify parsing."""
    from sentinel.core.semantic import AnthropicSemanticChecker

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [
        MagicMock(text='{"consistent": true, "confidence": 0.92, "reason": "Matches"}')
    ]
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
    off_intent_json = (
        '{"consistent": false, "confidence": 0.95,'
        ' "reason": "Unrelated to declared intent"}'
    )
    mock_message.content = [MagicMock(text=off_intent_json)]
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
