from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    family: str
    params_b: float
    ollama_tag: str
    hf_id: str
    quant_disk_gb: float
    full_disk_gb: float
    runtime_ram_gb: float
    min_lora_vram_gb: float
    chinese: str
    note: str
    ollama_adapter_supported: bool


MODELS = (
    ModelSpec("qwen25-15b", "Qwen2.5 1.5B", "Qwen", 1.5, "qwen2.5:1.5b", "Qwen/Qwen2.5-1.5B-Instruct", 1.0, 3.2, 3.0, 6.0, "优秀", "低配电脑和快速试跑", False),
    ModelSpec("qwen25-3b", "Qwen2.5 3B", "Qwen", 3.0, "qwen2.5:3b", "Qwen/Qwen2.5-3B-Instruct", 2.0, 6.2, 5.0, 8.0, "优秀", "默认推荐，质量与速度均衡", False),
    ModelSpec("qwen25-7b", "Qwen2.5 7B", "Qwen", 7.0, "qwen2.5:7b", "Qwen/Qwen2.5-7B-Instruct", 4.7, 15.0, 9.0, 12.0, "优秀", "语气和长上下文更稳定", False),
    ModelSpec("qwen3-8b", "Qwen3 8B", "Qwen", 8.0, "qwen3:8b", "Qwen/Qwen3-8B", 5.2, 16.5, 10.0, 16.0, "优秀", "推理能力更强，可关闭思考输出", False),
    ModelSpec("gemma3-4b", "Gemma 3 4B", "Gemma", 4.0, "gemma3:4b", "google/gemma-3-4b-it", 3.3, 8.5, 6.0, 10.0, "良好", "多语言能力和效率均衡", False),
    ModelSpec("llama32-3b", "Llama 3.2 3B", "Llama", 3.0, "llama3.2:3b", "meta-llama/Llama-3.2-3B-Instruct", 2.0, 6.5, 5.0, 8.0, "一般", "英文经历较多时可选", False),
    ModelSpec("mistral7b-v03", "Mistral 7B Instruct v0.3", "Mistral", 7.0, "mistral:7b-instruct-v0.3-q4_K_M", "mistralai/Mistral-7B-Instruct-v0.3", 4.4, 14.5, 9.0, 12.0, "一般", "Ollama 官方列出的 Safetensors LoRA 直载架构", True),
)


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4, check=False, creationflags=0x08000000 if os.name == "nt" else 0)
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def system_profile() -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine()
    total_ram = 0.0
    if system == "Windows":
        output = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        try:
            total_ram = int(output.splitlines()[-1]) / 1024**3
        except (ValueError, IndexError):
            pass
    elif system == "Darwin":
        output = _run(["sysctl", "-n", "hw.memsize"])
        try:
            total_ram = int(output) / 1024**3
        except ValueError:
            pass
    else:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_ram = pages * page_size / 1024**3
        except (ValueError, OSError, AttributeError):
            pass

    gpu_name = ""
    vram_gb = 0.0
    if shutil.which("nvidia-smi"):
        output = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if output:
            parts = output.splitlines()[0].rsplit(",", 1)
            gpu_name = parts[0].strip()
            try:
                vram_gb = float(parts[1].strip()) / 1024
            except (ValueError, IndexError):
                pass
    elif system == "Darwin" and machine in {"arm64", "aarch64"}:
        gpu_name = "Apple Silicon（统一内存）"
        vram_gb = total_ram

    free_disk = shutil.disk_usage(os.getcwd()).free / 1024**3
    return {
        "system": system,
        "machine": machine,
        "ram_gb": round(total_ram, 1),
        "gpu_name": gpu_name or "未检测到独立显卡",
        "vram_gb": round(vram_gb, 1),
        "free_disk_gb": round(free_disk, 1),
        "cuda": bool(shutil.which("nvidia-smi")),
        "mps": system == "Darwin" and machine in {"arm64", "aarch64"},
        "ollama_installed": bool(shutil.which("ollama")),
        "python": platform.python_version(),
    }


def catalog(profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    hardware = profile or system_profile()
    result: list[dict[str, Any]] = []
    for spec in MODELS:
        item = asdict(spec)
        memory_ok = hardware["ram_gb"] <= 0 or hardware["ram_gb"] >= spec.runtime_ram_gb + 3
        disk_ok = hardware["free_disk_gb"] >= spec.quant_disk_gb + 2
        lora_ok = hardware["vram_gb"] >= spec.min_lora_vram_gb
        item.update({
            "memory_compatible": memory_ok,
            "disk_compatible": disk_ok,
            "lora_compatible": lora_ok,
            "recommended": spec.id == ("qwen25-7b" if hardware["vram_gb"] >= 14 and hardware["ram_gb"] >= 24 else "qwen25-3b" if hardware["ram_gb"] >= 12 else "qwen25-15b"),
            "ollama_url": f"https://ollama.com/library/{spec.ollama_tag.split(':')[0]}",
            "huggingface_url": f"https://huggingface.co/{spec.hf_id}",
            "ollama_command": f"ollama pull {spec.ollama_tag}",
            "lora_command": f"python -m backend.train_lora --model {spec.hf_id}",
        })
        result.append(item)
    return result


def estimate(model_id: str, method: str, message_count: int, narrative_chars: int, epochs: float = 2.0, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    hardware = profile or system_profile()
    spec = next((item for item in MODELS if item.id == model_id), MODELS[1])
    effective_messages = max(message_count, narrative_chars // 45, 1)
    if method == "memory":
        seconds = max(5, effective_messages * 0.006)
        return {
            "min_minutes": max(1, round(seconds / 60)),
            "max_minutes": max(1, round(seconds * 2.4 / 60)),
            "disk_gb": round(min(1.5, effective_messages * 0.00008 + 0.02), 2),
            "peak_memory_gb": 1.0,
            "confidence": "高",
            "compatible": hardware["free_disk_gb"] > 1,
            "basis": f"约 {effective_messages} 条等效文本；仅整理与索引，不训练模型权重",
        }
    tokens = max(2_000, effective_messages * 45)
    device_factor = 1.0
    if hardware["vram_gb"] >= 24:
        device_factor = 0.55
    elif hardware["vram_gb"] >= 16:
        device_factor = 0.9
    elif hardware["vram_gb"] >= 12:
        device_factor = 1.5
    elif hardware["vram_gb"] >= 8:
        device_factor = 2.8
    else:
        device_factor = 8.0
    # 粗略按常见单卡 QLoRA 吞吐校准；给出宽区间而非伪精确的完成时间。
    minutes = max(8.0, tokens / 1000 * spec.params_b * epochs * 0.035 * device_factor)
    compatible = hardware["vram_gb"] >= spec.min_lora_vram_gb
    result = {
        "min_minutes": round(minutes * 0.7),
        "max_minutes": round(minutes * 1.7),
        "disk_gb": round(spec.full_disk_gb * 1.35 + 1.0, 1),
        "peak_memory_gb": round(spec.min_lora_vram_gb, 1),
        "confidence": "中（实际受消息长度、驱动和批大小影响）",
        "compatible": compatible,
        "basis": f"约 {tokens:,} tokens · {epochs:g} 轮 · {hardware['gpu_name']}",
    }
    if method == "hybrid":
        result["disk_gb"] = round(result["disk_gb"] + min(1.5, effective_messages * 0.00008 + 0.02), 1)
        result["basis"] += " · LoRA 风格训练 + 聊天记忆索引"
    return result
