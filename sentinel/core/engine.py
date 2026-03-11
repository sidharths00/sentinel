# sentinel/core/engine.py
from __future__ import annotations

from typing import Any

from sentinel.core.models import PolicyDefinition, PolicyResult
from sentinel.core.rules import RuleEngine


class PolicyEngine:
    def __init__(self) -> None:
        self.rules = RuleEngine()

    async def evaluate(
        self,
        policy: PolicyDefinition,
        tool_name: str,
        params: dict[str, Any],
        semantic_checker: Any | None = None,
    ) -> PolicyResult:
        # Phase 1: Rule-based checks
        result = self.rules.evaluate(policy, params)
        if result.outcome == "block":
            return result

        # Phase 2: Semantic check (if enabled and checker available)
        if policy.semantic_check and semantic_checker is not None:
            try:
                sem = await semantic_checker(tool_name, params, policy.intent)
                if not sem.consistent and sem.confidence >= policy.semantic_threshold:
                    return PolicyResult(
                        outcome="block",
                        checks_run=result.checks_run + ["semantic_intent"],
                        checks_failed=["semantic_intent"],
                        reason=f"Semantic check failed: {sem.reason}",
                    )
                result.checks_run.append("semantic_intent")
            except Exception:
                # Degrade gracefully — rules already passed
                pass

        return result
