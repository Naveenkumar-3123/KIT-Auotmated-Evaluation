"""FastAPI application factory for the EvalAI control plane.

Run locally:
    uvicorn answer_eval.api.main:create_app --factory --port 8300
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from answer_eval.api.auth import NativeJWTVerifier, SupabaseJWTVerifier
from answer_eval.api.config import ApiSettings
from answer_eval.api.middleware import (
    RateLimiterMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_error_handlers,
)
from answer_eval.api.routers import analytics as analytics_router
from answer_eval.api.routers import answer_keys as answer_keys_router
from answer_eval.api.routers import assessments as assessments_router
from answer_eval.api.routers import auth as auth_router
from answer_eval.api.routers import console as console_router
from answer_eval.api.routers import health as health_router
from answer_eval.api.routers import policies as policies_router
from answer_eval.api.routers import profiles as profiles_router
from answer_eval.api.routers import reviews as reviews_router
from answer_eval.api.routers import workers as workers_router
from answer_eval.db.pool import Database
from answer_eval.jobs.queue import create_queue
from answer_eval.storage import LocalStorageProvider, StorageProvider

logger = logging.getLogger(__name__)

DEFAULT_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8300",
    "http://127.0.0.1:8300",
)


def create_app(
    settings: ApiSettings | None = None,
    *,
    database: Database | None = None,
    verifier: SupabaseJWTVerifier | None = None,
    storage: StorageProvider | None = None,
    answer_key_parser_factory=None,
) -> FastAPI:
    """Build the app. Dependencies are injectable for tests.

    `answer_key_parser_factory` is a zero-arg callable returning an object
    with `parse(document) -> ParsedAnswerKey` (both the factory call and
    `parse` may be async and will be awaited). Defaults to a lazy factory that
    builds and initializes the configured InferenceProvider on first use.
    """
    settings = settings or ApiSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.database is None:
            db = Database(settings.database_url or "")
            try:
                await db.connect()
                app.state.database = db
            except Exception:  # noqa: BLE001 - boot must not crash without DB
                logger.exception("Database connection failed; /api endpoints will return 503")

        # Milestone 14 — durable job store + queue (Postgres when DB present,
        # SQLite locally; Redis queue when REDIS_URL is set, in-memory otherwise).
        job_store = None
        db_is_sqlite = getattr(app.state.database, "is_sqlite", False)
        if not db_is_sqlite and getattr(app.state, "database", None) is not None and settings.database_url:
            from answer_eval.jobs import EvaluationJobService, PostgresJobStore

            try:
                job_store = PostgresJobStore(settings.database_url)
                app.state.job_store = job_store
                app.state.job_service = EvaluationJobService(
                    job_store, create_queue(os.getenv("REDIS_URL") or None)
                )
                logger.info("Job service ready (durable Postgres store)")
                # Single-PC mode: start an embedded worker thread in the same process.
                _start_embedded_worker(job_store, settings)
            except Exception:  # noqa: BLE001 - jobs degrade to SQLite fallback
                logger.info("PostgresJobStore unavailable; activating embedded SQLite job store")
        if job_store is None:
            from answer_eval.jobs import EvaluationJobService, SQLiteJobStore

            root_data = Path(__file__).resolve().parents[3] / "data"
            job_store_path = str(root_data / "jobs.db") if (root_data / "jobs.db").exists() or root_data.exists() else "data/jobs.db"
            job_store = SQLiteJobStore(job_store_path)
            app.state.job_store = job_store
            app.state.job_service = EvaluationJobService(job_store, create_queue(None))
            logger.info("Job service ready (embedded SQLite job store at %s)", job_store_path)
            _start_embedded_worker(job_store, settings)
        yield
        if job_store is not None and hasattr(job_store, "close"):
            try:
                job_store.close()
            except Exception:  # noqa: BLE001
                logger.exception("Job store close failed")
        db: Database | None = app.state.database
        if db is not None:
            await db.close()
            app.state.database = None

    app = FastAPI(title="EvalAI API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.verifier = verifier or NativeJWTVerifier(
        settings.supabase_url,
        settings.supabase_jwt_secret or os.getenv("JWT_SECRET", "evalai-native-jwt-secret-key-2026"),
        jwks_url=settings.supabase_jwks_url or None,
    )
    if storage is not None:
        app.state.storage = storage
    else:
        storage_root = os.getenv("STORAGE_LOCAL_ROOT", "data/storage")
        storage_path = Path(storage_root)
        if not storage_path.is_absolute():
            root_candidate = Path(__file__).resolve().parents[3] / storage_root
            if root_candidate.exists() or root_candidate.parent.exists():
                storage_root = str(root_candidate)
        Path(storage_root).mkdir(parents=True, exist_ok=True)
        app.state.storage = LocalStorageProvider(storage_root)
    app.state.answer_key_parser_factory = answer_key_parser_factory or _build_default_parser_factory(settings)

    origins = list(settings.allowed_origins) or list(DEFAULT_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    app.include_router(health_router.router, prefix="/api")
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(profiles_router.router, prefix="/api")
    app.include_router(assessments_router.router, prefix="/api")
    app.include_router(answer_keys_router.router, prefix="/api")
    app.include_router(policies_router.router, prefix="/api")
    app.include_router(reviews_router.router, prefix="/api")
    app.include_router(workers_router.router, prefix="/api")
    app.include_router(analytics_router.router, prefix="/api")
    app.include_router(console_router.router, prefix="/api")
    app.include_router(console_router.router)
    return app


def _build_default_parser_factory(settings: ApiSettings):
    """Lazy async factory: constructs the configured InferenceProvider on first
    use so API boot never depends on a running model server. Initialization is
    awaited here (providers expose an async `initialize`); the answer-key parse
    background task awaits this factory on the event loop."""
    cached: dict[str, object] = {}

    async def factory():
        if "agent" not in cached:
            from answer_eval.answerkey.parser import AnswerKeyParserAgent
            from answer_eval.inference.factory import create_inference_provider
            from answer_eval.models.registry import get_model_registry

            # Pass None: the registry reads its own core Settings/config.
            # (ApiSettings has no `active_model_profile`; passing it raised
            # AttributeError inside this factory -> "Parser crashed".)
            profile = get_model_registry().get_active_profile(None)
            provider = create_inference_provider(profile)
            await provider.initialize(
                model=profile,
                config=settings,
                hardware=None,  # type: ignore[arg-type] - remote providers tolerate None
            )
            cached["agent"] = AnswerKeyParserAgent(provider)
        return cached["agent"]

    return factory


def _start_embedded_worker(job_store, settings: ApiSettings) -> threading.Thread | None:
    """Single-PC mode: run an EvaluationWorker thread inside the API process.

    Enabled by `python -m answer_eval.api.main --with-worker` (or env
    EVALAI_EMBEDDED_WORKER=1). One terminal boots the API, the durable job
    store, and a worker that claims jobs from Postgres (Redis optional). This
    makes the whole pipeline run on one computer with no second process.

    Default-on for single-PC mode: without a LOCAL worker, any other machine
    sharing the same DATABASE_URL claims (and permanently fails) this API's
    jobs because the PDF paths only exist here. Set EVALAI_EMBEDDED_WORKER=0
    to opt out on coordinator-only deployments.
    """
    flag = os.getenv("EVALAI_EMBEDDED_WORKER", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return None

    def run() -> None:
        time.sleep(3.0)  # let uvicorn bind the socket before self-registration
        stop: threading.Event | None = None
        try:
            from answer_eval.jobs import EvaluationWorker
            from answer_eval.jobs.queue import create_queue
            from answer_eval.jobs.worker_main import _heartbeat_loop, _register

            host = settings.host if settings.host not in ("", "0.0.0.0") else "127.0.0.1"
            coordinator = f"http://{host}:{settings.port}"
            logger.info("Embedded worker: registering with coordinator", coordinator=coordinator)
            worker_id, token = _register(coordinator, os.getenv("EVALAI_WORKER_ID"))
            stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop, args=(coordinator, worker_id, token, stop), daemon=True
            )
            heartbeat_thread.start()

            queue = create_queue(os.getenv("REDIS_URL") or None)

            def graph_factory():
                import asyncio

                from answer_eval.inference.factory import create_inference_provider
                from answer_eval.models.registry import get_model_registry
                from answer_eval.workflow.graph import build_evaluation_graph

                profile = get_model_registry().get_active_profile(None)
                provider = create_inference_provider(profile)
                asyncio.run(provider.initialize(model=profile, config=None, hardware=None))  # type: ignore[arg-type]
                return build_evaluation_graph(provider)

            worker = EvaluationWorker(
                store=job_store,
                queue=queue,
                graph_factory=graph_factory,
                worker_id=worker_id,
                # Fast local poll: claim this API's own enqueues before any
                # remote worker sharing the job store can grab them.
                poll_interval_s=0.2,
            )
            logger.info("Embedded single-PC worker started", worker_id=worker_id)
            worker.run_forever()
        except Exception:  # noqa: BLE001 - worker must never crash API startup
            logger.exception(
                "Embedded worker failed to start — evaluations will only run when a "
                "standalone worker claims jobs (or restart with EVALAI_EMBEDDED_WORKER=1)"
            )
        finally:
            if stop is not None:
                stop.set()
                logger.info("Embedded worker stopped")

    thread = threading.Thread(target=run, name="embedded-worker", daemon=True)
    thread.start()
    return thread


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    # `python -m answer_eval.api.main --with-worker` boots API + worker together.
    if "--with-worker" in sys.argv:
        os.environ["EVALAI_EMBEDDED_WORKER"] = "1"

    settings = ApiSettings.from_env()
    uvicorn.run(
        "answer_eval.api.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
