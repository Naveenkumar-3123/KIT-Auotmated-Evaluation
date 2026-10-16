"""Convenience entrypoint to run the EvalAI backend server."""

import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import uvicorn
from dotenv import load_dotenv

load_dotenv(backend_dir / ".env")

if __name__ == "__main__":
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8300"))
    print(f"Starting EvalAI Backend Server on http://{host}:{port} ...")
    uvicorn.run("answer_eval.api.main:create_app", factory=True, host=host, port=port, reload=False)
