"""Hardware profile data structures."""

from pydantic import BaseModel, Field


class GPUInfo(BaseModel):
    """Detailed GPU hardware information."""

    index: int = Field(default=0, description="GPU device index")
    name: str = Field(description="GPU model name (e.g. NVIDIA GeForce RTX 3060)")
    vram_total_gb: float = Field(description="Total VRAM in Gigabytes")
    vram_free_gb: float = Field(description="Available/Free VRAM in Gigabytes")
    vram_used_gb: float = Field(description="Used VRAM in Gigabytes")
    cuda_driver_version: str | None = Field(default=None, description="CUDA driver version")
    cuda_runtime_version: str | None = Field(default=None, description="CUDA runtime version")
    compute_capability: str | None = Field(default=None, description="CUDA compute capability (e.g. 8.6)")


class CPUInfo(BaseModel):
    """Detailed CPU hardware information."""

    model: str = Field(description="CPU model description")
    physical_cores: int = Field(description="Number of physical CPU cores")
    logical_cores: int = Field(description="Number of logical/hyperthreaded CPU cores")
    max_frequency_mhz: float | None = Field(default=None, description="Max CPU frequency in MHz")


class HardwareProfile(BaseModel):
    """Complete snapshot of the host machine hardware."""

    gpu: GPUInfo | None = Field(default=None, description="Primary GPU if available")
    all_gpus: list[GPUInfo] = Field(default_factory=list, description="All detected GPUs")
    has_nvidia_gpu: bool = Field(default=False, description="Whether an NVIDIA GPU is present")
    cpu: CPUInfo = Field(description="CPU hardware information")
    system_ram_total_gb: float = Field(description="Total system RAM in GB")
    system_ram_available_gb: float = Field(description="Available system RAM in GB")
    storage_total_gb: float | None = Field(default=None, description="Total storage on primary disk in GB")
    storage_free_gb: float | None = Field(default=None, description="Free storage on primary disk in GB")
    os_info: str = Field(description="Operating system description")
    python_version: str = Field(description="Python runtime version")
