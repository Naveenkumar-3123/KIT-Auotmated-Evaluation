import os
import sys
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

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ANSWER_KEY_BATCH_CONCURRENCY", "1")

root = Path(__file__).resolve().parent
backend_dir = root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv(backend_dir / ".env")
    load_dotenv(root / ".env")

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8300"))
    print(f"Starting EvalAI Backend Server from root on http://{host}:{port} ...")
    uvicorn.run("answer_eval.api.main:create_app", factory=True, host=host, port=port, reload=False)
