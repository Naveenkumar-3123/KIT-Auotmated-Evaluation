"""Standalone EvalAI worker process (Milestone 15, specs #56-#57, #64-#66).

Run on each evaluation PC:
    python -m answer_eval.jobs.worker_main \
        --coordinator http://<control-plane>:8300 \
        --database "$DATABASE_URL" [--worker-id worker-03]

Startup:
  1. Registers with the coordinator (hardware + model profile) and receives
     a one-time bearer token (persisted locally for restarts).
  2. Builds the LOCAL InferenceProvider (llama-server/Ollama) and LangGraph.
  3. Loops: claim durable job -> run pipeline with heartbeats -> save result.

The coordinator stays the only public surface; Postgres/Redis/llama-server are
reached over LAN/Tailscale (#57).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

TOKEN_FILE = Path.home() / ".evalai" / "worker-token.json"


def _hardware() -> dict:
    info: dict = {"cpu": os.cpu_count() and f"{os.cpu_count()} cores", "ram_gb": None, "gpu": None, "vram_gb": None}
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        from answer_eval.hardware.detector import detect_hardware

        hw = detect_hardware()
        gpus = getattr(hw, "gpus", None) or []
        if gpus:
            first = gpus[0]
            info["gpu"] = getattr(first, "name", None)
            vram = getattr(first, "vram_gb", None)
            info["vram_gb"] = float(vram) if vram else None
    except Exception:  # noqa: BLE001 - GPU detection is best-effort
        pass
    return info


def _register(coordinator: str, worker_id: str | None) -> tuple[str, str]:
    """Register and persist the token so restarts keep the same identity."""
    payload = {
        "worker_id": worker_id,
        "hostname": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME"),
        "hardware": _hardware(),
        "model_profile": os.getenv("EVALAI_MODEL_PROFILE"),
        "capabilities": ["vision", "ocr", "evaluation"],
    }
    response = httpx.post(f"{coordinator}/api/workers/register", json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    worker_id = data["worker"]["worker_id"]
    token = data["token"]
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(f"{worker_id}\n{coordinator}\n{token}", encoding="utf-8")
    print(f"[worker] registered as {worker_id}")
    return worker_id, token


def _heartbeat_loop(coordinator: str, worker_id: str, token: str, stop: threading.Event) -> None:
    headers = {"Authorization": f"Bearer {worker_id}:{token}"}

    def beat() -> None:
        with contextlib.suppress(Exception):
            httpx.post(
                f"{coordinator}/api/workers/heartbeat",
                json={"stage": "idle"},
                headers=headers,
                timeout=10,
            )

    while not stop.is_set():
        beat()
        stop.wait(15)


def main() -> int:
    # Load .env so the worker works with zero environment setup on a single PC.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001 - .env is optional
        pass

    parser = argparse.ArgumentParser(description="EvalAI evaluation worker")
    parser.add_argument("--coordinator", required=True, help="Control-plane base URL")
    parser.add_argument("--database", default=os.getenv("DATABASE_URL"), help="Postgres DSN for the durable job store")
    parser.add_argument("--redis", default=os.getenv("REDIS_URL"))
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--lease-seconds", type=float, default=300.0)
    args = parser.parse_args()

    if not args.database:
        print("[worker] --database or DATABASE_URL is required", file=sys.stderr)
        return 2

    worker_id, token = _register(args.coordinator, args.worker_id)

    from answer_eval.jobs import EvaluationWorker, PostgresJobStore
    from answer_eval.jobs.queue import create_queue

    store = PostgresJobStore(args.database)

    def graph_factory():
        import asyncio

        from answer_eval.inference.factory import create_inference_provider
        from answer_eval.models.registry import get_model_registry
        from answer_eval.workflow.graph import build_evaluation_graph

        settings_provider = None  # registry reads config itself
        profile = get_model_registry().get_active_profile(settings_provider)
        provider = create_inference_provider(profile)
        # initialize() is a coroutine; graph_factory runs in a plain worker
        # thread (no running event loop), so asyncio.run is safe here.
        asyncio.run(
            provider.initialize(model=profile, config=settings_provider, hardware=None)  # type: ignore[arg-type]
        )
        return build_evaluation_graph(provider)

    queue = create_queue(args.redis)
    stop = threading.Event()

    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(args.coordinator, worker_id, token, stop), daemon=True
    )
    heartbeat_thread.start()

    worker = EvaluationWorker(
        store=store,
        queue=queue,
        graph_factory=graph_factory,
        worker_id=worker_id,
        lease_seconds=args.lease_seconds,
        poll_interval_s=1.0,
    )
    try:
        worker.run_forever()
    finally:
        stop.set()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

