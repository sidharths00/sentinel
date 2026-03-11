# sentinel/core/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class PolicyDefinition(BaseModel):
    # Required
    intent: str
    risk_level: Literal["low", "medium", "high", "critical"]
    action_type: Literal["reversible", "irreversible", "destructive"]

    # Optional rule-based constraints
    constraints: dict[str, Any] = Field(default_factory=dict)

    # Optional semantic check
    semantic_check: bool = True
    semantic_threshold: float = 0.8

    # Optional behavior config
    on_block: Literal["raise", "return", "log_only"] = "return"
    on_modify: Literal["auto", "ask", "block"] = "auto"
    log_level: Literal["all", "blocks_only", "none"] = "all"

    # Optional escalation (V2)
    escalate_on: list[str] = Field(default_factory=list)


class PolicyResult(BaseModel):
    outcome: Literal["pass", "block", "modify"]
    checks_run: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    reason: str | None = None
    modified_params: dict[str, Any] | None = None


class PolicyViolation(BaseModel):
    tool_name: str
    reason: str
    suggestion: str
    what_happened: str


class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str
    tool_name: str
    action_type: str
    risk_level: str
    intent: str
    params: dict[str, Any]
    outcome: str
    policy_result: dict[str, Any]
    modified_params: dict[str, Any] | None = None
    block_reason: str | None = None
    execution_result: dict[str, Any] | None = None
    task_id: str | None = None


class AgentSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    task_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditSummary(BaseModel):
    total_calls: int
    passes: int
    blocks: int
    modifies: int
    top_blocked_tools: list[tuple[str, int]] = Field(default_factory=list)
