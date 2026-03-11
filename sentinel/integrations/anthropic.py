# sentinel/integrations/anthropic.py
from __future__ import annotations

import inspect
import json
from typing import Any, Callable

from sentinel.core.models import PolicyDefinition, PolicyViolation
from sentinel.core.wrapper import policy as sentinel_policy


def _infer_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate a basic JSON schema from function signature type hints."""
    sig = inspect.signature(func)
    type_map: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        ann = param.annotation
        json_type = type_map.get(ann, "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class SentinelToolDispatcher:
    """Dispatches Claude tool_use blocks through Sentinel policy checks."""

    def __init__(
        self,
        tools: dict[str, Callable[..., Any]],
        policies: dict[str, PolicyDefinition] | None = None,
    ) -> None:
        self._tools = tools
        self._policies = policies or {}
        self._wrapped: dict[str, Callable[..., Any]] = {}
        self._wrap_tools()

    def _wrap_tools(self) -> None:
        for name, func in self._tools.items():
            pol = self._policies.get(name)
            if pol:
                wrapped = sentinel_policy.wrap(
                    intent=pol.intent,
                    risk_level=pol.risk_level,
                    action_type=pol.action_type,
                    constraints=pol.constraints,
                    semantic_check=pol.semantic_check,
                    semantic_threshold=pol.semantic_threshold,
                    on_block=pol.on_block,
                    on_modify=pol.on_modify,
                    log_level=pol.log_level,
                )(func)
                self._wrapped[name] = wrapped
            else:
                self._wrapped[name] = func

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for name, func in self._tools.items():
            schemas.append({
                "name": name,
                "description": inspect.getdoc(func) or f"Tool: {name}",
                "input_schema": _infer_schema(func),
            })
        return schemas

    async def dispatch(self, tool_use_block: Any) -> dict[str, Any]:
        name = tool_use_block.name
        params = tool_use_block.input
        tool_use_id = tool_use_block.id

        func = self._wrapped.get(name)
        if func is None:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"error": f"Unknown tool: {name}"}),
                "is_error": True,
            }

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**params)
            else:
                # sync_wrapper from policy.wrap uses ThreadPoolExecutor when loop is running.
                # We need to call it directly in a thread to avoid blocking the event loop.
                import asyncio
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: func(**params))

            if isinstance(result, PolicyViolation):
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps({
                        "blocked": True,
                        "reason": result.reason,
                        "suggestion": result.suggestion,
                        "what_happened": result.what_happened,
                    }),
                    "is_error": False,
                }

            content = json.dumps(result) if isinstance(result, dict) else str(result)
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
        except Exception as e:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"error": str(e)}),
                "is_error": True,
            }

    async def dispatch_all(self, content_blocks: list[Any]) -> list[dict[str, Any]]:
        results = []
        for block in content_blocks:
            if getattr(block, "type", None) == "tool_use":
                result = await self.dispatch(block)
                results.append(result)
        return results
