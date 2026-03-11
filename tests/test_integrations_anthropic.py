# tests/test_integrations_anthropic.py
import pytest
from unittest.mock import MagicMock
import json


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
    assert json.loads(result["content"]) == {"result": 10}


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
    content = json.loads(result["content"])
    assert content.get("blocked") is True


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
