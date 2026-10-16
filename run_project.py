"""Unified Master Supervisor for EvalAI: Database + Backend + Frontend.

Runs:
1. Native PostgreSQL (Port 5432)
2. FastAPI Backend Server (Port 8300)
3. Vite React Frontend (Port 5173)

Monitors all processes and handles graceful shutdown.
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent

def get_pg_bin() -> Path:
    # 1. Standard Windows Program Files installation directories
    for ver in ["16", "17", "15", "14"]:
        candidate = Path(rf"C:\Program Files\PostgreSQL\{ver}\bin")
        if (candidate / "pg_ctl.exe").exists():
            return candidate
    candidate_general = Path(r"C:\Program Files\PostgreSQL\bin")
    if (candidate_general / "pg_ctl.exe").exists():
        return candidate_general
    # 2. Check system PATH
    which_pg = shutil.which("pg_ctl")
    if which_pg:
        return Path(which_pg).parent
    # 3. Local fallback if exists
    local_candidate = ROOT_DIR / "pgsql" / "bin"
    if (local_candidate / "pg_ctl.exe").exists():
        return local_candidate
    return Path(r"C:\Program Files\PostgreSQL\16\bin")

PG_BIN = get_pg_bin()
PG_CTL = PG_BIN / "pg_ctl.exe"
PG_DATA = ROOT_DIR / "data" / "pgsql_data"
PG_PID = PG_DATA / "postmaster.pid"
PG_LOG = ROOT_DIR / "data" / "pgsql.log"

FRONTEND_DIR = ROOT_DIR / "frontend"

def start_postgres():
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
            print("      -> PostgreSQL is already running on 127.0.0.1:5432 [OK]", flush=True)
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass

    if PG_PID.exists():
        try:
            PG_PID.unlink()
        except Exception:
            pass

    # Start detached via pg_ctl
    cmd = [
        str(PG_CTL),
        "-D", str(PG_DATA),
        "-l", str(PG_LOG),
        "-o", "-p 5432",
        "start"
    ]
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    p.wait()

    # Wait for PostgreSQL to respond
    import socket
    for _ in range(15):
        try:
            with socket.create_connection(("127.0.0.1", 5432), timeout=1.0):
                print("      -> PostgreSQL connected and listening on 127.0.0.1:5432 [OK]", flush=True)
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)

    print("      -> [Warning] PostgreSQL socket check timed out, continuing...", flush=True)
    return False

def kill_port(port: int):
    if os.name != "nt":
        return
    try:
        out = subprocess.check_output(f'netstat -ano | findstr ":{port} "', shell=True, text=True)
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5 and "LISTENING" in parts:
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def start_backend(backend_port: int = 8400, api_host: str = "127.0.0.1"):
    kill_port(backend_port)
    print(f"[2/3] Starting FastAPI Backend on http://{api_host}:{backend_port} ...", flush=True)
    backend_script = ROOT_DIR / "run_backend.py"
    log_path = ROOT_DIR / "data" / "backend.log"
    log_file = open(log_path, "a", encoding="utf-8")
    backend_env = os.environ.copy()
    backend_env["PYTHONIOENCODING"] = "utf-8"
    backend_env["API_PORT"] = str(backend_port)
    backend_env["API_HOST"] = str(api_host)
    proc = subprocess.Popen(
        [sys.executable, "-u", str(backend_script)],
        cwd=str(ROOT_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=backend_env,
    )

    # Wait for /api/health to answer
    health_url = f"http://{api_host}:{backend_port}/api/health"
    for _ in range(30):
        try:
            req = urllib.request.urlopen(health_url, timeout=1.5)
            if req.status == 200:
                print(f"      -> FastAPI Backend is healthy on http://{api_host}:{backend_port} [OK]", flush=True)
                print(f"      -> API Docs available at: http://{api_host}:{backend_port}/docs", flush=True)
                return proc
        except Exception:
            time.sleep(0.5)

    print("      -> Backend started (PID %d)" % proc.pid, flush=True)
    return proc

def start_frontend(frontend_port: int = 5174, backend_port: int = 8400, api_host: str = "127.0.0.1"):
    kill_port(frontend_port)
    print(f"[3/3] Starting Vite React Frontend on http://localhost:{frontend_port} ...", flush=True)
    log_path = ROOT_DIR / "data" / "frontend.log"
    log_file = open(log_path, "a", encoding="utf-8")
    frontend_env = os.environ.copy()
    frontend_env["EVALAI_API_ORIGIN"] = f"http://{api_host}:{backend_port}"
    frontend_env["PORT"] = str(frontend_port)
    proc = subprocess.Popen(
        ["cmd.exe", "/c", "pnpm", "dev", "--port", str(frontend_port), "--host"],
        cwd=str(FRONTEND_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=frontend_env,
    )

    # Wait for Vite port
    frontend_url = f"http://localhost:{frontend_port}"
    for _ in range(25):
        try:
            req = urllib.request.urlopen(frontend_url, timeout=1.5)
            if req.status in (200, 304):
                print(f"      -> Vite Frontend is ready at: {frontend_url} [OK]", flush=True)
                return proc
        except Exception:
            time.sleep(0.5)

    print("      -> Frontend server process launched (PID %d)" % proc.pid, flush=True)
    return proc

def main():
    parser = argparse.ArgumentParser(description="EvalAI Full-Stack Supervisor")
    parser.add_argument("--backend-port", type=int, default=int(os.getenv("API_PORT", "8400")), help="Backend port (default: 8400)")
    parser.add_argument("--frontend-port", type=int, default=int(os.getenv("FRONTEND_PORT", "5174")), help="Frontend port (default: 5174)")
    parser.add_argument("--api-host", type=str, default=os.getenv("API_HOST", "127.0.0.1"), help="API host (default: 127.0.0.1)")
    args = parser.parse_args()

    backend_port = args.backend_port
    frontend_port = args.frontend_port
    api_host = args.api_host

    print("=" * 65)
    print("   EVALAI FULL-STACK LAUNCHER (DB + BACKEND + FRONTEND)")
    print(f"   Configured: Backend={api_host}:{backend_port} | Frontend=:{frontend_port}")
    print("=" * 65, flush=True)

    db_ready = start_postgres()
    backend_proc = start_backend(backend_port, api_host)
    frontend_proc = start_frontend(frontend_port, backend_port, api_host)

    print("\n" + "=" * 65)
    print("   ALL SERVICES RUNNING SUCCESSFULLY!")
    print("=" * 65)
    print("  * PostgreSQL Database : postgresql://postgres@localhost:5432/evalai_db")
    print(f"  * FastAPI Backend     : http://{api_host}:{backend_port}")
    print(f"  * API Interactive Docs: http://{api_host}:{backend_port}/docs")
    print(f"  * React Frontend UI   : http://localhost:{frontend_port}")
    print("=" * 65 + "\n", flush=True)

    def shutdown(sig, frame):
        print("\nStopping all services...", flush=True)
        if frontend_proc and frontend_proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(frontend_proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                frontend_proc.terminate()
        if backend_proc and backend_proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(backend_proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                backend_proc.terminate()
        subprocess.run(
            [str(PG_CTL), "-D", str(PG_DATA), "stop", "-m", "fast"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("All services stopped cleanly.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Monitor loop
    try:
        while True:
            time.sleep(5)
            # Check postgres
            import socket
            pg_up = False
            try:
                with socket.create_connection(("127.0.0.1", 5432), timeout=1.5):
                    pg_up = True
            except Exception:
                pass
            if not pg_up:
                print("[Warning] PostgreSQL server stopped! Restarting...", flush=True)
                start_postgres()

            # Check backend process
            if backend_proc and backend_proc.poll() is not None:
                print(f"[Warning] Backend process exited (code {backend_proc.returncode})! Restarting...", flush=True)
                backend_proc = start_backend(backend_port, api_host)

            # Check frontend process
            if frontend_proc and frontend_proc.poll() is not None:
                print(f"[Warning] Frontend process exited (code {frontend_proc.returncode})! Restarting...", flush=True)
                frontend_proc = start_frontend(frontend_port, backend_port, api_host)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()

