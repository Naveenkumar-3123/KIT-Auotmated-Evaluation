"""Hardware module exports."""

from answer_eval.hardware.detector import detect_cpu, detect_gpus, detect_hardware
from answer_eval.hardware.profiles import CPUInfo, GPUInfo, HardwareProfile

__all__ = [
    "CPUInfo",
    "GPUInfo",
    "HardwareProfile",
    "detect_cpu",
    "detect_gpus",
    "detect_hardware",
]
