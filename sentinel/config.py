# sentinel/config.py
from __future__ import annotations

import os
from typing import Any, Callable, Coroutine

from dotenv import load_dotenv

load_dotenv()

SemanticChecker = Callable[
    [str, dict[str, Any], str],
    Coroutine[Any, Any, Any],
]


class SentinelConfig:
    def __init__(
        self,
        *,
        semantic_checker: SemanticChecker | None = None,
        db_path: str | None = None,
        default_agent_id: str = "default",
    ) -> None:
        self.semantic_checker = semantic_checker
        self.db_path = db_path or os.getenv("SENTINEL_DB_PATH", "sentinel_audit.db")
        self.default_agent_id = default_agent_id
        self._store: Any = None
        self._logger: Any = None
        self._engine: Any = None
        self._initialized = False

    def _get_default_semantic_checker(self) -> SemanticChecker | None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            from sentinel.core.semantic import AnthropicSemanticChecker, CachedSemanticChecker
            checker = AnthropicSemanticChecker(api_key=api_key)
            cached = CachedSemanticChecker(checker.check)
            return cached.check
        except ImportError:
            return None

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        from sentinel.audit.store import AuditStore
        from sentinel.audit.logger import AuditLogger
        from sentinel.core.engine import PolicyEngine

        self._store = AuditStore(db_path=self.db_path)
        await self._store.initialize()
        self._logger = AuditLogger(store=self._store)
        self._engine = PolicyEngine()

        if self.semantic_checker is None:
            self.semantic_checker = self._get_default_semantic_checker()

        self._initialized = True

    @property
    def store(self) -> Any:
        return self._store

    @property
    def logger(self) -> Any:
        return self._logger

    @property
    def engine(self) -> Any:
        return self._engine
