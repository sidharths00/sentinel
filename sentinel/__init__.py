# sentinel/__init__.py
from __future__ import annotations

from sentinel.config import SentinelConfig
from sentinel.core.wrapper import policy

_config = SentinelConfig()


def configure(
    *,
    semantic_checker: object = None,
    db_path: str | None = None,
    default_agent_id: str = "default",
) -> None:
    global _config
    _config = SentinelConfig(
        semantic_checker=semantic_checker,  # type: ignore[arg-type]
        db_path=db_path,
        default_agent_id=default_agent_id,
    )


__all__ = ["policy", "configure", "SentinelConfig"]
