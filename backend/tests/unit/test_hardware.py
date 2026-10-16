"""Unit tests for hardware detection module."""

from answer_eval.hardware.detector import detect_cpu, detect_hardware
from answer_eval.hardware.profiles import CPUInfo, HardwareProfile


def test_detect_cpu() -> None:
    cpu = detect_cpu()
    assert isinstance(cpu, CPUInfo)
    assert cpu.physical_cores >= 1
    assert cpu.logical_cores >= cpu.physical_cores
    assert len(cpu.model) > 0


def test_detect_hardware_completeness() -> None:
    hw = detect_hardware()
    assert isinstance(hw, HardwareProfile)
    assert hw.system_ram_total_gb > 0
    assert hw.system_ram_available_gb > 0
    assert len(hw.os_info) > 0

    if hw.has_nvidia_gpu:
        assert hw.gpu is not None
        assert hw.gpu.vram_total_gb > 0
        assert hw.gpu.vram_free_gb >= 0
