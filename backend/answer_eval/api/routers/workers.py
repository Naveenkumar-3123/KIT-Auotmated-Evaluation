"""Worker fleet coordinator endpoints (Milestone 15, specs #56-#60/#64).

Workers register once (receive a one-time bearer token) and then heartbeat.
The Computers page (#16/M60) reads the fleet view. Only the coordinator is
public; workers reach Postgres/Redis over LAN/Tailscale (#57).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from answer_eval.api.deps import CurrentTeacher, require_database
from answer_eval.db.repositories import workers as workers_repo

router = APIRouter(tags=["workers"])
_bearer = HTTPBearer(auto_error=False)


class HardwareIn(BaseModel):
    cpu: str | None = None
    ram_gb: float | None = None
    gpu: str | None = None
    vram_gb: float | None = None


class RegisterIn(BaseModel):
    worker_id: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=120)
    hardware: HardwareIn = Field(default_factory=HardwareIn)
    model_profile: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatIn(BaseModel):
    stage: str | None = None
    current_job_id: str | None = None
    progress: float | None = Field(default=None, ge=0, le=100)
    ram_used_gb: float | None = None
    vram_used_gb: float | None = None


async def _verified_worker(request: Request) -> str:
    """Bearer-token worker auth (#64): hash must match the registered node."""
    database = require_database(request)
    credentials: HTTPAuthorizationCredentials | None = await _bearer(request)
    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing worker token")
    token_parts = credentials.credentials.split(":", 1)
    if len(token_parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed worker credentials")
    worker_id, token = token_parts
    if not await workers_repo.verify_worker_token(database.pool, worker_id, token):
        raise HTTPException(status_code=403, detail="Invalid worker credentials")
    return worker_id


@router.post("/workers/register")
async def register(body: RegisterIn, request: Request) -> dict:
    database = require_database(request)
    result = await workers_repo.register_worker(
        database.pool,
        worker_id=body.worker_id,
        hostname=body.hostname,
        hardware=body.hardware.model_dump(),
        model_profile=body.model_profile,
        capabilities=body.capabilities,
    )
    worker = result["worker"]
    return {
        "worker": {
            "worker_id": worker["worker_id"],
            "hostname": worker["hostname"],
            "model_profile": worker["model_profile"],
            "capabilities": list(worker["capabilities"]),
        },
        "token": result["token"],
    }


@router.post("/workers/heartbeat")
async def heartbeat(body: HeartbeatIn, request: Request) -> dict:
    database = require_database(request)
    worker_id = await _verified_worker(request)
    snapshot = await workers_repo.record_heartbeat(
        database.pool,
        worker_id=worker_id,
        stage=body.stage,
        current_job_id=body.current_job_id,
        progress=body.progress,
        ram_used_gb=body.ram_used_gb,
        vram_used_gb=body.vram_used_gb,
    )
    return {"ok": True, "worker": snapshot}


@router.get("/workers")
async def fleet(teacher: CurrentTeacher, request: Request) -> dict:
    database = require_database(request)
    workers = await workers_repo.list_workers(database.pool)
    return {
        "workers": workers,
        "online_count": sum(1 for w in workers if w["online"]),
        "total_count": len(workers),
    }
