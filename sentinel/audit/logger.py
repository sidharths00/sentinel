# sentinel/audit/logger.py
from __future__ import annotations

from typing import Any, Literal

from sentinel.audit.store import AuditStore
from sentinel.core.models import AuditEntry, PolicyResult


class AuditLogger:
    def __init__(self, store: AuditStore) -> None:
        self.store = store

    async def log(
        self,
        *,
        agent_id: str,
        tool_name: str,
        action_type: str,
        risk_level: str,
        intent: str,
        params: dict[str, Any],
        policy_result: PolicyResult,
        execution_result: dict[str, Any] | None = None,
        modified_params: dict[str, Any] | None = None,
        task_id: str | None = None,
        log_level: Literal["all", "blocks_only", "none"] = "all",
    ) -> AuditEntry:
        entry = AuditEntry(
            agent_id=agent_id,
            tool_name=tool_name,
            action_type=action_type,
            risk_level=risk_level,
            intent=intent,
            params=params,
            outcome=policy_result.outcome,
            policy_result=policy_result.model_dump(),
            execution_result=execution_result,
            modified_params=modified_params,
            block_reason=policy_result.reason if policy_result.outcome == "block" else None,
            task_id=task_id,
        )

        should_write = (
            log_level == "all"
            or (log_level == "blocks_only" and policy_result.outcome == "block")
        )
        if should_write:
            await self.store.write(entry)

        return entry
