"""Hardware detection module without PyTorch dependency."""

import csv
import io
import platform
import shutil
import subprocess

import psutil

from answer_eval.core.logging import get_logger
from answer_eval.hardware.profiles import CPUInfo, GPUInfo, HardwareProfile

logger = get_logger("hardware.detector")


def _detect_gpus_via_pynvml() -> tuple[list[GPUInfo], str | None]:
    """Attempt GPU detection using pynvml / nvidia-ml-py."""
    gpus: list[GPUInfo] = []
    driver_version: str | None = None
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        driver_version = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver_version, bytes):
            driver_version = driver_version.decode("utf-8")

        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)

            # Compute capability if available
            compute_cap = None
            try:
                major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                compute_cap = f"{major}.{minor}"
            except Exception:
                pass

            gpus.append(
                GPUInfo(
                    index=i,
                    name=name,
                    vram_total_gb=round(mem_info.total / (1024**3), 2),
                    vram_free_gb=round(mem_info.free / (1024**3), 2),
                    vram_used_gb=round(mem_info.used / (1024**3), 2),
                    cuda_driver_version=driver_version,
                    compute_capability=compute_cap,
                )
            )
        pynvml.nvmlShutdown()
    except Exception as e:
        logger.debug("pynvml detection not available or failed", error=str(e))
    return gpus, driver_version


def _detect_gpus_via_nvidia_smi() -> list[GPUInfo]:
    """Fallback GPU detection using nvidia-smi CLI command."""
    gpus: list[GPUInfo] = []
    nvidia_smi_path = shutil.which("nvidia-smi")
    if not nvidia_smi_path:
        return gpus

    try:
        cmd = [
            nvidia_smi_path,
            "--query-gpu=index,name,memory.total,memory.free,memory.used,driver_version",
            "--format=csv,noheader,nounits",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            reader = csv.reader(io.StringIO(result.stdout.strip()))
            for row in reader:
                if len(row) >= 6:
                    idx = int(row[0].strip())
                    name = row[1].strip()
                    total_mb = float(row[2].strip())
                    free_mb = float(row[3].strip())
                    used_mb = float(row[4].strip())
                    driver = row[5].strip()
                    gpus.append(
                        GPUInfo(
                            index=idx,
                            name=name,
                            vram_total_gb=round(total_mb / 1024.0, 2),
                            vram_free_gb=round(free_mb / 1024.0, 2),
                            vram_used_gb=round(used_mb / 1024.0, 2),
                            cuda_driver_version=driver,
                        )
                    )
    except Exception as e:
        logger.debug("nvidia-smi query failed", error=str(e))

    return gpus


def detect_gpus() -> list[GPUInfo]:
    """Detect all GPUs without requiring PyTorch."""
    # 1. Try pynvml first
    gpus, _ = _detect_gpus_via_pynvml()
    if gpus:
        return gpus

    # 2. Fall back to nvidia-smi CLI
    gpus = _detect_gpus_via_nvidia_smi()
    return gpus


def detect_cpu() -> CPUInfo:
    """Detect CPU information."""
    model = platform.processor() or "Unknown CPU"

    # On Windows, try WMIC/registry for more friendly CPU brand string
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if val:
                model = str(val).strip()
            winreg.CloseKey(key)
        except Exception:
            pass

    physical_cores = psutil.cpu_count(logical=False) or 1
    logical_cores = psutil.cpu_count(logical=True) or physical_cores

    max_freq = None
    freq = psutil.cpu_freq()
    if freq and freq.max > 0:
        max_freq = round(freq.max, 1)

    return CPUInfo(
        model=model,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        max_frequency_mhz=max_freq,
    )


def detect_hardware() -> HardwareProfile:
    """Detect all system hardware components and return immutable HardwareProfile."""
    logger.info("Detecting system hardware")

    # CPU
    cpu = detect_cpu()

    # RAM
    vmem = psutil.virtual_memory()
    total_ram_gb = round(vmem.total / (1024**3), 2)
    available_ram_gb = round(vmem.available / (1024**3), 2)

    # Disk / Storage
    storage_total_gb = None
    storage_free_gb = None
    try:
        disk = psutil.disk_usage("/")
        storage_total_gb = round(disk.total / (1024**3), 2)
        storage_free_gb = round(disk.free / (1024**3), 2)
    except Exception:
        pass

    # OS Info
    os_info = f"{platform.system()} {platform.release()} ({platform.architecture()[0]})"
    python_version = platform.python_version()

    # GPUs
    gpus = detect_gpus()
    primary_gpu = gpus[0] if gpus else None
    has_nvidia = len(gpus) > 0

    profile = HardwareProfile(
        gpu=primary_gpu,
        all_gpus=gpus,
        has_nvidia_gpu=has_nvidia,
        cpu=cpu,
        system_ram_total_gb=total_ram_gb,
        system_ram_available_gb=available_ram_gb,
        storage_total_gb=storage_total_gb,
        storage_free_gb=storage_free_gb,
        os_info=os_info,
        python_version=python_version,
    )

    logger.info(
        "Hardware detection complete",
        has_gpu=has_nvidia,
        gpu_name=primary_gpu.name if primary_gpu else "None",
        vram_total_gb=primary_gpu.vram_total_gb if primary_gpu else 0.0,
        cpu=cpu.model,
        cores=f"{cpu.physical_cores}C/{cpu.logical_cores}T",
        ram_gb=total_ram_gb,
    )

    return profile
