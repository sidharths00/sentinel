# sentinel/core/semantic.py
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

SEMANTIC_CHECK_PROMPT = """You are a policy enforcement system.

Declared intent: {intent}
Proposed action: {tool_name}({params})

Is this action consistent with the declared intent?
Answer with JSON only:
{{
  "consistent": true | false,
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation"
}}"""


@dataclass
class SemanticResult:
    consistent: bool
    confidence: float
    reason: str


SemanticCheckerCallable = Callable[
    [str, dict[str, Any], str],
    Coroutine[Any, Any, SemanticResult],
]


class AnthropicSemanticChecker:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self._client: Any = None
        self._api_key = api_key

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    async def check(
        self, tool_name: str, params: dict[str, Any], intent: str
    ) -> SemanticResult:
        prompt = SEMANTIC_CHECK_PROMPT.format(
            intent=intent,
            tool_name=tool_name,
            params=json.dumps(params, default=str),
        )
        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            # Extract JSON — handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            data = json.loads(text)
            return SemanticResult(
                consistent=bool(data["consistent"]),
                confidence=float(data["confidence"]),
                reason=str(data["reason"]),
            )
        except Exception:
            # Fail open: if semantic check errors, allow (rules already passed)
            return SemanticResult(
                consistent=True, confidence=0.0, reason="semantic check unavailable"
            )


class CachedSemanticChecker:
    """Wraps any semantic checker callable with an in-memory cache."""

    def __init__(self, inner: SemanticCheckerCallable) -> None:
        self._inner = inner
        self._cache: dict[str, SemanticResult] = {}

    def _cache_key(self, tool_name: str, params: dict[str, Any], intent: str) -> str:
        payload = json.dumps(
            {"tool": tool_name, "params": params, "intent": intent},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    async def check(self, tool_name: str, params: dict[str, Any], intent: str) -> SemanticResult:
        key = self._cache_key(tool_name, params, intent)
        if key in self._cache:
            return self._cache[key]
        result = await self._inner(tool_name, params, intent)
        self._cache[key] = result
        return result
