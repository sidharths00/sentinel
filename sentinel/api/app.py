# sentinel/api/app.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from sentinel.api.routes import audit, policies


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    yield
    # Graceful shutdown: close the audit store connection
    import sentinel as _sentinel

    cfg = _sentinel._config
    if cfg._initialized and cfg._store is not None:
        await cfg._store.close()


def create_app(config: Any | None = None) -> FastAPI:
    app = FastAPI(title="Sentinel Audit API", version="0.1.0", lifespan=lifespan)
    app.include_router(audit.router)
    app.include_router(policies.router)
    return app


app = create_app()
