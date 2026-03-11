# sentinel/api/routes/audit.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(prefix="/audit", tags=["audit"])


def get_store() -> Any:
    import sentinel
    return sentinel._config.store


@router.get("/entries")
async def get_entries(
    agent_id: str | None = Query(None),
    limit: int = Query(100, le=1000),
    since: datetime | None = Query(None),
) -> list[dict[str, Any]]:
    store = get_store()
    entries = await store.get_entries(agent_id=agent_id, limit=limit, since=since)
    return [e.model_dump(mode="json") for e in entries]


@router.get("/blocks")
async def get_blocks(
    agent_id: str | None = Query(None),
    since: datetime | None = Query(None),
) -> list[dict[str, Any]]:
    store = get_store()
    entries = await store.get_blocks(agent_id=agent_id, since=since)
    return [e.model_dump(mode="json") for e in entries]


@router.get("/summary")
async def get_summary(
    agent_id: str | None = Query(None),
    since: datetime | None = Query(None),
) -> dict[str, Any]:
    store = get_store()
    summary = await store.get_summary(agent_id=agent_id, since=since)
    return summary.model_dump()
