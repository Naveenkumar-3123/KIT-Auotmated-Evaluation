"""API configuration loaded purely from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv


def _env_list(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class ApiSettings:
    """Runtime settings for the EvalAI control-plane API."""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    database_url: str = ""
    allowed_origins: tuple[str, ...] = ()
    host: str = "127.0.0.1"
    port: int = 8300
    worker_token: str = ""

    @classmethod
    def from_env(cls) -> ApiSettings:
        # Load .env from the repo/working directory so `uvicorn ... --factory`
        # works without extra tooling. Real environment variables always win.
        load_dotenv(find_dotenv(usecwd=True), override=False)
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", ""),
            # New-style key names (sb_publishable_*/sb_secret_*) take the legacy
            # names' place; both spellings are accepted.
            supabase_anon_key=(
                os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY") or ""
            ),
            supabase_service_role_key=(
                os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY") or ""
            ),
            supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET", ""),
            supabase_jwks_url=os.getenv("SUPABASE_JWKS_URL", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            allowed_origins=_env_list("API_ALLOWED_ORIGINS", "http://localhost:3000"),
            host=os.getenv("API_HOST", "127.0.0.1"),
            port=int(os.getenv("API_PORT", "8300")),
            worker_token=os.getenv("WORKER_TOKEN", ""),
        )
