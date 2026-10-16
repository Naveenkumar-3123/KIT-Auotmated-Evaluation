"""Unit tests for Runtime Planner, Memory Estimation, and Llama Server Manager."""

from pathlib import Path

from answer_eval.core.config import Settings
from answer_eval.hardware.profiles import CPUInfo, GPUInfo, HardwareProfile
from answer_eval.models.profiles import ModelProfile
from answer_eval.runtime.llama_server_manager import LlamaServerManager
from answer_eval.runtime.memory import (
    KnownGoodRuntimeCache,
    estimate_activation_headroom_gb,
    estimate_kv_cache_gb,
    estimate_model_weights_gb,
)
from answer_eval.runtime.planner import RuntimePlanner
from answer_eval.runtime.profiles import RuntimeConfig


def test_memory_estimations() -> None:
    # 4B model weight heuristic
    m4b = ModelProfile(
        model_id="qwen_4b",
        display_name="4B",
        size_class="4b",
        quantization="Q8_0",
        checkpoint_path="models/nonexistent.gguf",
    )
    ckpt_gb, mmproj_gb = estimate_model_weights_gb(m4b, Path("."))
    assert ckpt_gb > 4.0
    assert mmproj_gb == 0.8

    # KV cache estimation
    kv_8k = estimate_kv_cache_gb(8192, kv_dtype="f16")
    assert 0.1 <= kv_8k <= 1.0

    # Activation headroom
    act_1024 = estimate_activation_headroom_gb(1024 * 1024)
    assert act_1024 >= 1.0


def test_planner_rtx3060_vs_rtx4060(temp_workspace: Path) -> None:
    planner = RuntimePlanner(workspace_root=temp_workspace)
    settings = Settings()

    # Machine 1: RTX 3060 12GB VRAM + 32GB RAM
    hw_3060 = HardwareProfile(
        gpu=GPUInfo(name="NVIDIA GeForce RTX 3060", vram_total_gb=12.0, vram_free_gb=11.0, vram_used_gb=1.0),
        has_nvidia_gpu=True,
        cpu=CPUInfo(model="Ryzen 7 3700X", physical_cores=8, logical_cores=16),
        system_ram_total_gb=32.0,
        system_ram_available_gb=24.0,
        os_info="Windows 11",
        python_version="3.11",
    )

    # Machine 2: RTX 4060 8GB VRAM + 64GB RAM
    hw_4060 = HardwareProfile(
        gpu=GPUInfo(name="NVIDIA GeForce RTX 4060", vram_total_gb=8.0, vram_free_gb=7.0, vram_used_gb=1.0),
        has_nvidia_gpu=True,
        cpu=CPUInfo(model="Core i9-14900KS", physical_cores=24, logical_cores=32),
        system_ram_total_gb=64.0,
        system_ram_available_gb=50.0,
        os_info="Windows 11",
        python_version="3.11",
    )

    # 4B Dev Model on RTX 3060 12GB -> Full GPU (-1)
    m4b = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="4B Q8",
        size_class="4b",
        quantization="Q8_0",
        checkpoint_path="models/4b.gguf",
        runtime_profile_hint="fast_local",
    )
    cfg_3060_4b = planner.plan_candidate(hw_3060, m4b, settings)
    assert cfg_3060_4b.n_gpu_layers == -1  # Full GPU residency
    assert cfg_3060_4b.n_threads == 8

    # Large 30B Model on RTX 4060 8GB -> Hybrid CPU/GPU (partial layers)
    m30b = ModelProfile(
        model_id="qwen_vl_large_local",
        display_name="30B MoE",
        size_class="30b_moe",
        quantization="Q4_K_M",
        checkpoint_path="models/30b.gguf",
        runtime_profile_hint="hybrid_local",
    )
    cfg_4060_30b = planner.plan_candidate(hw_4060, m30b, settings)
    assert cfg_4060_30b.is_hybrid_offload is True
    assert cfg_4060_30b.n_gpu_layers > 0  # Partial offload
    assert cfg_4060_30b.n_gpu_layers != -1


def test_known_good_cache(temp_workspace: Path) -> None:
    cache_path = temp_workspace / ".known_good.json"
    cache = KnownGoodRuntimeCache(cache_path)

    hw = HardwareProfile(
        gpu=GPUInfo(name="RTX 3060", vram_total_gb=12.0, vram_free_gb=11.0, vram_used_gb=1.0),
        has_nvidia_gpu=True,
        cpu=CPUInfo(model="Ryzen", physical_cores=8, logical_cores=16),
        system_ram_total_gb=32.0,
        system_ram_available_gb=24.0,
        os_info="Windows 11",
        python_version="3.11",
    )
    model = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="4B",
        size_class="4b",
        checkpoint_path="models/4b.gguf",
    )
    config = RuntimeConfig(profile_name="fast_local", n_gpu_layers=-1, n_ctx=8192)

    cache.save_known_good(hw, model, config)
    loaded = cache.load_known_good(hw, model)
    assert loaded is not None
    assert loaded["n_gpu_layers"] == -1
    assert loaded["n_ctx"] == 8192


def test_llama_server_manager_command_building() -> None:
    manager = LlamaServerManager(server_binary_path="llama-server")
    model = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="4B Q8",
        size_class="4b",
        checkpoint_path="models/qwen4b.gguf",
        mmproj_path="models/mmproj.gguf",
        supports_vision=True,
    )
    config = RuntimeConfig(
        profile_name="fast_local",
        n_gpu_layers=32,
        n_ctx=8192,
        n_threads=8,
        n_batch=512,
        host="127.0.0.1",
        port=8090,
    )

    args = manager.build_command_args(model, config)
    assert "llama-server" in args[0].lower()
    assert "-m" in args
    assert "-c" in args
    assert "8192" in args
    assert "-ngl" in args
    assert "32" in args
    assert "--mmproj" in args
    assert "--host" in args
    assert "127.0.0.1" in args
