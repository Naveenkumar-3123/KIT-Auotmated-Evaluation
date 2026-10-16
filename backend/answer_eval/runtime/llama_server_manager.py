"""Process manager for standalone llama-server instance."""

import asyncio
import contextlib
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from answer_eval.core.errors import ModelStartupError
from answer_eval.core.logging import get_logger
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.models.profiles import ModelProfile
from answer_eval.runtime.planner import RuntimePlanner
from answer_eval.runtime.profiles import RuntimeConfig

logger = get_logger("runtime.llama_server")


class LlamaServerManager:
    """Manages the standalone llama-server process lifecycle."""

    def __init__(
        self,
        server_binary_path: str = "llama-server",
        workspace_root: Path | None = None,
    ) -> None:
        self.workspace_root = workspace_root or Path(os.getcwd())
        self.server_binary_path = self._resolve_binary(server_binary_path)
        self._process: subprocess.Popen | None = None
        self._current_config: RuntimeConfig | None = None
        self._current_model: ModelProfile | None = None
        self._is_running = False

    @staticmethod
    def _resolve_binary(specified_path: str) -> str:
        """Resolve full path to llama-server binary if available on system."""
        if specified_path != "llama-server" and Path(specified_path).exists():
            return specified_path

        found = shutil.which(specified_path) or shutil.which(f"{specified_path}.exe")
        if found:
            return found

        # Known installation paths (e.g. Ollama bundled llama-server on Windows)
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local_app_data) / "Programs" / "Ollama" / "lib" / "ollama" / "llama-server.exe",
            Path("C:/Program Files/Ollama/lib/ollama/llama-server.exe"),
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return str(c)

        return specified_path

    @property
    def is_running(self) -> bool:
        """Check if server process is currently running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def build_command_args(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
    ) -> list[str]:
        """Build safe argument array for llama-server subprocess execution."""
        ckpt_path, mmproj_path = model.resolve_paths(self.workspace_root)

        args = [
            self.server_binary_path,
            "-m",
            str(ckpt_path),
            "-c",
            str(config.n_ctx),
            "-t",
            str(config.n_threads),
            "-b",
            str(config.n_batch),
            "-ub",
            str(config.n_ubatch),
            "--host",
            config.host,
            "--port",
            str(config.port),
        ]

        # GPU offload
        if config.n_gpu_layers != 0:
            args.extend(["-ngl", str(config.n_gpu_layers)])

        # Multimodal Projector for Vision
        if mmproj_path and model.supports_vision:
            args.extend(["--mmproj", str(mmproj_path)])

        # KV cache precision
        if config.kv_cache_dtype in ("f16", "q8_0", "q4_0"):
            args.extend(["--cache-type-k", config.kv_cache_dtype, "--cache-type-v", config.kv_cache_dtype])

        return args

    async def wait_until_ready(
        self,
        host: str,
        port: int,
        timeout_seconds: float = 60.0,
        interval: float = 1.0,
    ) -> bool:
        """Poll the server /health endpoint until it returns 200 OK."""
        health_url = f"http://{host}:{port}/health"
        deadline = time.time() + timeout_seconds

        async with httpx.AsyncClient(timeout=3.0) as client:
            while time.time() < deadline:
                if not self.is_running:
                    logger.error("llama-server process exited unexpectedly during startup")
                    return False
                try:
                    resp = await client.get(health_url)
                    if resp.status_code == 200:
                        logger.info("llama-server is healthy and ready", url=health_url)
                        return True
                except Exception:
                    pass
                await asyncio.sleep(interval)

        return False

    async def start(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
        timeout_seconds: float = 90.0,
    ) -> None:
        """Start the standalone llama-server process."""
        if self.is_running:
            logger.info("llama-server is already running; stopping previous instance first")
            self.stop()

        cmd = self.build_command_args(model, config)
        logger.info(
            "Launching standalone llama-server",
            host=config.host,
            port=config.port,
            model_id=model.model_id,
            n_gpu_layers=config.n_gpu_layers,
            n_ctx=config.n_ctx,
            cmd_preview=" ".join(cmd[:6]) + " ...",
        )

        # Check if binary exists or is on PATH
        resolved_bin = shutil.which(self.server_binary_path) or self.server_binary_path
        if not Path(resolved_bin).exists() and not shutil.which(self.server_binary_path):
            raise ModelStartupError(
                f"llama-server executable '{self.server_binary_path}' not found on system PATH.",
                details={"binary_path": self.server_binary_path},
            )

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._current_config = config
            self._current_model = model
        except Exception as e:
            raise ModelStartupError(
                f"Failed to spawn llama-server process: {e}",
                details={"command": cmd, "error": str(e)},
            ) from e

        # Wait for health check
        is_ready = await self.wait_until_ready(config.host, config.port, timeout_seconds=timeout_seconds)
        if not is_ready:
            stderr_snippet = ""
            if self._process and self._process.stderr:
                with contextlib.suppress(Exception):
                    stderr_snippet = self._process.stderr.read(1024)
            self.stop()
            raise ModelStartupError(
                f"llama-server failed to respond healthy within {timeout_seconds}s.",
                details={"stderr": stderr_snippet, "config": config.model_dump()},
            )

        self._is_running = True

    def stop(self) -> None:
        """Gracefully terminate the llama-server process."""
        if self._process is not None:
            logger.info("Stopping llama-server process")
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2.0)
            except Exception as e:
                logger.warning("Error stopping llama-server process", error=str(e))
            finally:
                self._process = None
                self._is_running = False

    async def restart_with_degraded_config(
        self,
        hardware: HardwareProfile,
        model: ModelProfile,
        planner: RuntimePlanner,
        current_fallback: int,
    ) -> RuntimeConfig:
        """Handle OOM/failure by stopping, planning degraded config, and restarting."""
        logger.warn(
            "Initiating llama-server restart with degraded configuration",
            current_fallback=current_fallback,
        )
        self.stop()

        new_fallback = current_fallback + 1
        new_config = planner.plan_candidate(
            hardware=hardware,
            model=model,
            settings=planner.workspace_root / "config" / "settings.yaml",  # type: ignore
            fallback_level=new_fallback,
            use_cached_known_good=False,
        )

        await self.start(model, new_config)
        return new_config
