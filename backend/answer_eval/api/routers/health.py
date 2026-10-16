"""Health endpoint (public)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from answer_eval.api.models import HealthOut

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthOut)
@router.get("/health", response_model=HealthOut)
async def healthz(request: Request) -> HealthOut:
    database: object | None = getattr(request.app.state, "database", None)
    connected = bool(database is not None and getattr(database, "connected", False))
    return HealthOut(status="ok", database=connected)
