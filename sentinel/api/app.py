# sentinel/api/app.py
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from sentinel.api.routes import audit, policies


def create_app(config: Any | None = None) -> FastAPI:
    app = FastAPI(title="Sentinel Audit API", version="0.1.0")
    app.include_router(audit.router)
    app.include_router(policies.router)
    return app


app = create_app()
