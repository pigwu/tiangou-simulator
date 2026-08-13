from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRAINING_PACKAGES = ("torch", "transformers", "datasets", "peft", "trl", "accelerate")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def latest_checkpoint(output: Path) -> Path | None:
    checkpoints: list[tuple[int, Path]] = []
    if output.exists():
        for path in output.glob("checkpoint-*"):
            if path.is_dir():
                try:
                    checkpoints.append((int(path.name.rsplit("-", 1)[1]), path))
                except (IndexError, ValueError):
                    continue
    return max(checkpoints, default=(0, None), key=lambda item: item[0])[1]


def torch_capabilities() -> dict:
    code = (
        "import json, torch; "
        "print(json.dumps({'cuda': bool(torch.cuda.is_available()), "
        "'mps': bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available()), "
        "'torch': torch.__version__}))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=20, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
        return {}


def diagnose_training(data_dir: Path, model_role: str, config: dict, model_spec: Any, hardware: dict) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    expected_dataset = (data_dir / f"{model_role}-dataset.jsonl").resolve()
    expected_validation = (data_dir / f"{model_role}-validation.jsonl").resolve()
    expected_output = (data_dir / "adapters" / f"{model_role}-lora").resolve()
    dataset = Path(str(config.get("dataset") or "")).resolve() if config.get("dataset") else None
    validation = Path(str(config.get("validation_dataset") or "")).resolve() if config.get("validation_dataset") else None
    output = Path(str(config.get("adapter_output") or "")).resolve() if config.get("adapter_output") else None

    if config.get("model_role") != model_role:
        blockers.append("角色配置方向不匹配，请重新生成训练配置")
    if config.get("method") not in {"lora", "hybrid"}:
        blockers.append("当前配置不是 LoRA 或混合模式")
    if config.get("base_model_huggingface") != getattr(model_spec, "hf_id", None):
        blockers.append("基础模型不在内置适配目录中或与配置不一致")
    if dataset != expected_dataset or not dataset or not dataset.is_file():
        blockers.append("角色训练集不存在或路径不安全，请重新生成")
    if validation and (validation != expected_validation or not validation.is_file()):
        blockers.append("验证集路径不安全或文件不存在，请重新生成")
    if output != expected_output or not output or not _inside(output, data_dir / "adapters"):
        blockers.append("适配器输出路径不安全，请重新生成")

    required_packages = list(TRAINING_PACKAGES)
    if hardware.get("cuda") and hardware.get("system") != "Darwin":
        required_packages.append("bitsandbytes")
    missing_packages = [package for package in required_packages if importlib.util.find_spec(package) is None]
    if missing_packages:
        blockers.append("缺少训练依赖：" + "、".join(missing_packages))
    capabilities = torch_capabilities() if "torch" not in missing_packages else {}
    if not hardware.get("cuda") and not hardware.get("mps"):
        blockers.append("没有检测到 NVIDIA CUDA 或 Apple Silicon MPS；请使用聊天记忆模式")
    elif hardware.get("cuda") and capabilities and not capabilities.get("cuda"):
        blockers.append("当前 Python 的 PyTorch 没有识别 CUDA；请检查 CUDA 版 PyTorch、驱动或改用 WSL2")
    elif hardware.get("mps") and capabilities and not capabilities.get("mps"):
        blockers.append("当前 Python 的 PyTorch 没有识别 Apple Silicon MPS")
    required_vram = float(getattr(model_spec, "min_lora_vram_gb", 0) or 0)
    available_vram = float(hardware.get("vram_gb", 0) or 0)
    if hardware.get("cuda") and available_vram + 0.1 < required_vram:
        blockers.append(f"检测到约 {available_vram:g} GB 显存，所选模型建议至少 {required_vram:g} GB")
    required_disk = round(float(getattr(model_spec, "full_disk_gb", 0) or 0) * 1.35 + 2.0, 1)
    free_disk = float(hardware.get("free_disk_gb", 0) or 0)
    if free_disk and free_disk < required_disk:
        blockers.append(f"剩余磁盘约 {free_disk:g} GB，训练与 checkpoint 预计至少需要 {required_disk:g} GB")
    if hardware.get("system") == "Windows" and hardware.get("cuda"):
        warnings.append("Windows 原生 bitsandbytes 兼容性取决于版本；失败时建议在 WSL2 中训练")
    if validation is None:
        warnings.append("没有独立验证集，将无法早停或选择最佳 checkpoint")

    checkpoint = latest_checkpoint(expected_output)
    receipt = _read_json(expected_output / "training-result.json")
    dataset_sha256 = hashlib.sha256(expected_dataset.read_bytes()).hexdigest() if expected_dataset.is_file() else ""
    receipt_matches = bool(
        receipt
        and receipt.get("dataset_sha256") == dataset_sha256
        and receipt.get("base_model") == config.get("base_model_huggingface")
    )
    if receipt_matches:
        warnings.append("该角色已有完整训练凭证；无需重复训练，除非先生成了新的数据集")
    elif receipt:
        warnings.append("发现旧训练凭证，但它与当前数据或基础模型不匹配；允许重新训练")
    previous_job = _read_json(data_dir / "training-jobs" / f"{model_role}.json")
    checkpoint_matches = bool(
        checkpoint
        and previous_job.get("dataset_sha256") == dataset_sha256
        and previous_job.get("base_model") == config.get("base_model_huggingface")
    )
    if checkpoint and not checkpoint_matches and not receipt_matches:
        warnings.append("发现 checkpoint，但它无法证明与当前数据和基础模型匹配；UI 不会从它恢复")
    return {
        "ready": not blockers and not receipt_matches,
        "blockers": blockers,
        "warnings": warnings,
        "missing_packages": missing_packages,
        "dataset": str(dataset) if dataset else None,
        "validation": str(validation) if validation else None,
        "output": str(expected_output),
        "checkpoint": str(checkpoint) if checkpoint_matches else None,
        "can_resume": bool(checkpoint_matches and not receipt_matches),
        "completed": receipt_matches,
        "required_disk_gb": required_disk,
        "free_disk_gb": free_disk,
        "required_vram_gb": required_vram,
        "available_vram_gb": available_vram,
        "python": sys.executable,
        "torch": capabilities,
    }


class TrainingJobManager:
    def __init__(self, root: Path, data_dir: Path):
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.jobs_dir = self.data_dir / "training-jobs"
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def _state_file(self, role: str) -> Path:
        return self.jobs_dir / f"{role}.json"

    def _log_file(self, role: str) -> Path:
        return self.jobs_dir / f"{role}.log"

    def _progress_file(self, role: str) -> Path:
        return self.jobs_dir / f"{role}-progress.json"

    def _load(self, role: str) -> dict:
        return _read_json(self._state_file(role))

    def _save(self, role: str, state: dict) -> dict:
        _atomic_json(self._state_file(role), state)
        return state

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _active_other_role(self, role: str) -> str | None:
        for candidate in ("dog", "receiver"):
            if candidate == role:
                continue
            state = self.status(candidate, include_log=False)
            if state.get("status") == "running":
                return candidate
        return None

    def start(
        self, role: str, command: list[str], resume: bool, model: str, output: Path,
        dataset_sha256: str, base_model: str,
    ) -> dict:
        with self._lock:
            current = self.status(role, include_log=False)
            if current.get("status") == "running":
                raise RuntimeError("该角色已有训练任务正在运行")
            other = self._active_other_role(role)
            if other:
                raise RuntimeError("另一角色的训练任务正在运行；为避免显存冲突，同一时间只允许一个任务")
            self.jobs_dir.mkdir(parents=True, exist_ok=True)
            progress_file = self._progress_file(role)
            if progress_file.exists():
                progress_file.unlink()
            command = [*command, "--progress-file", str(progress_file)]
            log_path = self._log_file(role)
            with log_path.open("a", encoding="utf-8") as log_handle:
                log_handle.write(f"\n[{_now()}] {'恢复' if resume else '启动'}本地训练：{model}\n")
                log_handle.flush()
                creationflags = 0
                start_new_session = os.name != "nt"
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
                process = subprocess.Popen(
                    command,
                    cwd=self.root,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    creationflags=creationflags,
                    start_new_session=start_new_session,
                )
            self._processes[role] = process
            state = {
                "status": "running",
                "role": role,
                "pid": process.pid,
                "model": model,
                "base_model": base_model,
                "dataset_sha256": dataset_sha256,
                "output": str(output),
                "resume": resume,
                "started_at": _now(),
                "updated_at": _now(),
                "exit_code": None,
                "message": "训练进程已启动",
            }
            return self._with_details(role, self._save(role, state), include_log=True)

    def status(self, role: str, include_log: bool = True) -> dict:
        state = self._load(role)
        if not state:
            return {"status": "idle", "role": role, "progress": {}, "log_tail": []}
        if state.get("status") == "running":
            process = self._processes.get(role)
            exit_code = process.poll() if process else None
            alive = exit_code is None and (process is not None or self._pid_exists(int(state.get("pid") or 0)))
            if not alive:
                receipt = _read_json(Path(str(state.get("output") or "")) / "training-result.json")
                state.update({
                    "status": "completed" if receipt else "failed",
                    "exit_code": exit_code,
                    "finished_at": _now(),
                    "updated_at": _now(),
                    "message": "训练完成并生成凭证" if receipt else "训练已中断；可查看日志并从 checkpoint 恢复",
                })
                self._save(role, state)
                self._processes.pop(role, None)
        return self._with_details(role, state, include_log=include_log)

    def _with_details(self, role: str, state: dict, include_log: bool) -> dict:
        result = dict(state)
        result["progress"] = _read_json(self._progress_file(role))
        result["log_tail"] = self._tail(self._log_file(role), 35) if include_log else []
        return result

    @staticmethod
    def _tail(path: Path, limit: int) -> list[str]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-limit:]
        except OSError:
            return []

    def cancel(self, role: str) -> dict:
        with self._lock:
            state = self._load(role)
            if state.get("status") != "running":
                raise RuntimeError("当前没有可取消的训练任务")
            pid = int(state.get("pid") or 0)
            if pid <= 0:
                raise RuntimeError("训练任务没有有效进程号")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process = self._processes.pop(role, None)
            if process:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            state.update({
                "status": "cancelled", "exit_code": None, "finished_at": _now(), "updated_at": _now(),
                "message": "训练已由用户取消；已有 checkpoint 会保留，可稍后恢复",
            })
            return self._with_details(role, self._save(role, state), include_log=True)
