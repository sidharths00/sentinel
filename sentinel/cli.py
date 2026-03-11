# sentinel/cli.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import click


@click.group()
def cli() -> None:
    """Sentinel — Agent Action Policy Engine CLI"""


@cli.command()
@click.option("--agent-id", default=None, help="Filter by agent ID")
@click.option("--since", default="24h", help="Time window: 1h, 24h, 7d (default: 24h)")
@click.option("--outcome", default=None, type=click.Choice(["pass", "block", "modify"]))
@click.option("--limit", default=50, help="Max entries to show")
@click.option("--db", default="sentinel_audit.db", help="Path to SQLite DB")
def audit(agent_id: str | None, since: str, outcome: str | None, limit: int, db: str) -> None:
    """Display audit log entries."""
    asyncio.run(_audit(agent_id=agent_id, since=since, outcome=outcome, limit=limit, db=db))


def _parse_since(since: str) -> datetime:
    units = {"h": 3600, "d": 86400, "m": 60}
    try:
        unit = since[-1]
        value = int(since[:-1])
        return datetime.now(timezone.utc) - timedelta(seconds=value * units[unit])
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=24)


async def _audit(
    agent_id: str | None,
    since: str,
    outcome: str | None,
    limit: int,
    db: str,
) -> None:
    from rich.console import Console
    from rich.table import Table

    from sentinel.audit.store import AuditStore

    store = AuditStore(db_path=db)
    await store.initialize()

    since_dt = _parse_since(since)

    if outcome == "block":
        entries = await store.get_blocks(agent_id=agent_id, since=since_dt)
    else:
        entries = await store.get_entries(agent_id=agent_id, limit=limit, since=since_dt)

    if outcome and outcome != "block":
        entries = [e for e in entries if e.outcome == outcome]

    await store.close()

    console = Console()
    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return

    table = Table(title=f"Sentinel Audit Log ({len(entries)} entries)")
    table.add_column("Time", style="dim")
    table.add_column("Agent")
    table.add_column("Tool")
    table.add_column("Outcome")
    table.add_column("Risk")
    table.add_column("Reason")

    outcome_styles = {"pass": "green", "block": "red", "modify": "yellow"}

    for e in entries:
        ts = e.timestamp.strftime("%m-%d %H:%M:%S")
        style = outcome_styles.get(e.outcome, "white")
        table.add_row(
            ts,
            e.agent_id,
            e.tool_name,
            f"[{style}]{e.outcome}[/{style}]",
            e.risk_level,
            e.block_reason or "",
        )

    console.print(table)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
