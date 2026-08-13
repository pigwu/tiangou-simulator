from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from .dataset import (
    build_narrative_memory,
    prepare_dataset,
    retrieve_memories,
    retrieve_memory_items,
    save_dataset,
    style_profile,
)
from .parsers import parse_upload
from .models import MODELS, catalog, estimate, system_profile
from .training_jobs import TrainingJobManager, diagnose_training
from .projects import (
    LEGACY_ID,
    create_export,
    create_project,
    delete_project,
    list_projects,
    now_iso,
    project_detail,
    project_dir,
    read_json,
    touch_project,
    validate_project_id,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TIANGOU_DATA_DIR", ROOT / "local_data"))
DATASET_FILE = DATA_DIR / "dataset.jsonl"
PROFILE_FILE = DATA_DIR / "profile.json"
TRAINING_CONFIG_FILE = DATA_DIR / "training-config.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def data_dir_for(project_id: str = LEGACY_ID, require_exists: bool = False) -> Path:
    return project_dir(DATA_DIR, project_id, require_exists=require_exists)


def role_artifacts(model_role: str, project_id: str = LEGACY_ID) -> tuple[Path, Path, Path, Path]:
    directory = data_dir_for(project_id)
    return (
        directory / f"{model_role}-dataset.jsonl",
        directory / f"{model_role}-profile.json",
        directory / f"{model_role}-training-config.json",
        directory / f"Modelfile.{model_role}",
    )


def role_split_artifacts(model_role: str, project_id: str = LEGACY_ID) -> tuple[Path, Path]:
    directory = data_dir_for(project_id)
    return directory / f"{model_role}-validation.jsonl", directory / f"{model_role}-test.jsonl"

app = FastAPI(title="舔狗模拟器本地 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


async def ollama_models() -> list[str]:
    """Read the local Ollama catalog without inheriting Windows proxy settings."""
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        response = await client.get(f"{OLLAMA_URL}/api/tags")
        response.raise_for_status()
        return [str(item.get("name", "")) for item in response.json().get("models", []) if item.get("name")]


def ollama_http_error(exc: httpx.HTTPStatusError, model: str) -> str:
    try:
        error = str(exc.response.json().get("error", "")).strip()
    except (json.JSONDecodeError, AttributeError, ValueError):
        error = exc.response.text.strip()
    if exc.response.status_code == 404 or "not found" in error.lower():
        return f"本地没有模型 {model}。请运行：ollama pull {model}，或在 UI 中选择已安装的模型。"
    safe_error = error[:300] if error else "Ollama 没有提供错误详情"
    return f"Ollama 返回 HTTP {exc.response.status_code}：{safe_error}"


class DatasetRequest(BaseModel):
    project_id: str = LEGACY_ID
    messages: list[dict]
    dog_speaker: str
    receiver_speaker: str
    dog_name: str = "舔狗"
    receiver_name: str = "被舔者"
    model_role: str = Field(pattern="^(dog|receiver)$")
    narrative: str = Field(default="", max_length=200_000)
    narrator_role: str = Field(default="dog", pattern="^(dog|receiver)$")
    method: str = Field(default="memory", pattern="^(memory|lora|hybrid)$")
    model_id: str = "qwen25-3b"
    epochs: float = Field(default=2.0, ge=0.1, le=20)
    lora_model_tag: str = Field(default="tiangou-role:latest", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    project_id: str = LEGACY_ID
    message: str = Field(min_length=1, max_length=4000)
    model: str = "qwen2.5:3b"
    model_role: str = Field(pattern="^(dog|receiver)$")
    player_role: str = Field(pattern="^(dog|receiver)$")
    dog_speaker: str
    receiver_speaker: str
    dog_name: str = "舔狗"
    receiver_name: str = "被舔者"
    ignored_count: int = Field(default=0, ge=0, le=100)
    max_ignored: int = Field(default=3, ge=1, le=100)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)
    method: str = Field(default="memory", pattern="^(memory|lora|hybrid)$")


class EstimateRequest(BaseModel):
    model_id: str = "qwen25-3b"
    method: str = Field(default="memory", pattern="^(memory|lora|hybrid)$")
    message_count: int = Field(default=0, ge=0, le=10_000_000)
    narrative_chars: int = Field(default=0, ge=0, le=1_000_000)
    epochs: float = Field(default=2.0, ge=0.1, le=20)


class TrainingStatusRequest(BaseModel):
    project_id: str = LEGACY_ID
    model_tag: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")
    model_role: str | None = Field(default=None, pattern="^(dog|receiver)$")


class EvaluationRequest(BaseModel):
    project_id: str = LEGACY_ID
    base_model: str = "qwen2.5:3b"
    role_model: str = Field(default="tiangou-role:latest", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")
    model_role: str = Field(pattern="^(dog|receiver)$")
    player_role: str = Field(pattern="^(dog|receiver)$")
    dog_speaker: str
    receiver_speaker: str
    dog_name: str = "舔狗"
    receiver_name: str = "被舔者"
    limit: int = Field(default=3, ge=1, le=5)


class TrainingJobRequest(BaseModel):
    project_id: str = LEGACY_ID
    model_role: str = Field(pattern="^(dog|receiver)$")
    resume: bool = False
    acknowledgement: str = Field(max_length=30)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ProjectDeleteRequest(BaseModel):
    acknowledgement: str = Field(min_length=1, max_length=60)


_training_managers: dict[str, TrainingJobManager] = {}


def training_manager(project_id: str = LEGACY_ID) -> TrainingJobManager:
    directory = data_dir_for(project_id)
    key = str(directory.resolve())
    if key not in _training_managers:
        _training_managers[key] = TrainingJobManager(ROOT, directory)
    return _training_managers[key]


def training_context(model_role: str, project_id: str = LEGACY_ID) -> tuple[dict, object, dict]:
    config_file = role_artifacts(model_role, project_id)[2]
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "请先在 UI 生成对应角色的 LoRA 或混合模式配置") from exc
    model_spec = next((item for item in MODELS if item.hf_id == config.get("base_model_huggingface")), None)
    if model_spec is None:
        raise HTTPException(422, "训练配置中的基础模型不在当前适配目录中，请重新生成配置")
    hardware = system_profile()
    return config, model_spec, hardware


@app.get("/api/health")
async def health() -> dict:
    models: list[str] = []
    try:
        models = await ollama_models()
    except httpx.HTTPError:
        pass
    return {"ok": True, "ollama": bool(models), "models": models, "platform": platform.system(), "data_dir": str(DATA_DIR)}


@app.get("/api/system")
async def system() -> dict:
    profile = system_profile()
    installed_models: list[str] = []
    try:
        installed_models = await ollama_models()
    except httpx.HTTPError:
        pass
    return {"hardware": profile, "models": catalog(profile), "installed_models": installed_models}


@app.get("/api/projects")
async def projects() -> dict:
    return {"projects": list_projects(DATA_DIR)}


@app.post("/api/projects")
async def new_project(request: ProjectCreateRequest) -> dict:
    try:
        return create_project(DATA_DIR, request.name)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    try:
        return project_detail(DATA_DIR, project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str, request: ProjectDeleteRequest) -> dict:
    try:
        for role in ("dog", "receiver"):
            if training_manager(project_id).status(role, include_log=False).get("status") == "running":
                raise ValueError("项目仍有训练任务运行，请先停止训练")
        result = delete_project(DATA_DIR, project_id, request.acknowledgement)
        _training_managers.pop(str(data_dir_for(project_id).resolve()), None)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}/export")
async def export_project(project_id: str, include_adapters: bool = False) -> FileResponse:
    try:
        output, filename = create_export(DATA_DIR, project_id, include_adapters=include_adapters)
        return FileResponse(
            output, media_type="application/zip", filename=filename,
            background=BackgroundTask(lambda: output.unlink(missing_ok=True)),
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/estimate")
async def training_estimate(request: EstimateRequest) -> dict:
    return estimate(request.model_id, request.method, request.message_count, request.narrative_chars, request.epochs)


@app.get("/api/training-diagnostics/{model_role}")
async def training_diagnostics(model_role: str, project_id: str = LEGACY_ID) -> dict:
    if model_role not in {"dog", "receiver"}:
        raise HTTPException(422, "无效的模型角色")
    config, model_spec, hardware = training_context(model_role, project_id)
    directory = data_dir_for(project_id, require_exists=True)
    result = diagnose_training(directory, model_role, config, model_spec, hardware)
    result["job"] = training_manager(project_id).status(model_role)
    return result


@app.post("/api/training-jobs")
async def start_training_job(request: TrainingJobRequest) -> dict:
    if request.acknowledgement.strip() != "确认本地训练":
        raise HTTPException(422, "请完整输入“确认本地训练”后再启动")
    config, model_spec, hardware = training_context(request.model_role, request.project_id)
    directory = data_dir_for(request.project_id, require_exists=True)
    diagnostics = diagnose_training(directory, request.model_role, config, model_spec, hardware)
    if diagnostics["completed"]:
        raise HTTPException(409, "当前数据和基础模型已有匹配的训练凭证，无需重复训练")
    if diagnostics["blockers"]:
        raise HTTPException(409, "训练前检查未通过：" + "；".join(diagnostics["blockers"]))
    checkpoint = Path(diagnostics["checkpoint"]) if request.resume and diagnostics.get("checkpoint") else None
    if request.resume and checkpoint is None:
        raise HTTPException(409, "没有找到可恢复的 checkpoint")
    command = [
        sys.executable, "-m", "backend.train_lora",
        "--dataset", str(diagnostics["dataset"]),
        "--model", model_spec.hf_id,
        "--output", str(diagnostics["output"]),
        "--epochs", str(config.get("epochs", 2)),
    ]
    if diagnostics["validation"]:
        command.extend(["--validation", str(diagnostics["validation"])])
    if checkpoint:
        command.extend(["--resume-from", str(checkpoint)])
    try:
        dataset_sha256 = hashlib.sha256(Path(diagnostics["dataset"]).read_bytes()).hexdigest()
        return training_manager(request.project_id).start(
            request.model_role, command, request.resume, model_spec.name, Path(diagnostics["output"]),
            dataset_sha256, model_spec.hf_id,
        )
    except (OSError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/training-jobs/{model_role}")
async def training_job_status(model_role: str, project_id: str = LEGACY_ID) -> dict:
    if model_role not in {"dog", "receiver"}:
        raise HTTPException(422, "无效的模型角色")
    return training_manager(project_id).status(model_role)


@app.post("/api/training-jobs/{model_role}/cancel")
async def cancel_training_job(model_role: str, project_id: str = LEGACY_ID) -> dict:
    if model_role not in {"dog", "receiver"}:
        raise HTTPException(422, "无效的模型角色")
    try:
        return training_manager(project_id).cancel(model_role)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/training-status")
async def training_status(request: TrainingStatusRequest) -> dict:
    config: dict = {}
    try:
        directory = data_dir_for(request.project_id, require_exists=True)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    config_file = role_artifacts(request.model_role, request.project_id)[2] if request.model_role else directory / "training-config.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fallback_config = directory / "training-config.json"
        if request.model_role and fallback_config.exists():
            try:
                config = json.loads(fallback_config.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    adapter_value = config.get("adapter_output")
    adapter_dir = Path(adapter_value) if adapter_value else None
    weight_ready = bool(adapter_dir and (
        (adapter_dir / "adapter_model.safetensors").exists()
        or (adapter_dir / "adapter_model.bin").exists()
    ))
    receipt: dict = {}
    if adapter_dir:
        try:
            receipt = json.loads((adapter_dir / "training-result.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    receipt_ready = bool(receipt)
    dataset_value = config.get("dataset")
    dataset_path = Path(dataset_value) if dataset_value else None
    dataset_matches = False
    if dataset_path and dataset_path.exists() and receipt.get("dataset_sha256"):
        dataset_matches = hashlib.sha256(dataset_path.read_bytes()).hexdigest() == receipt["dataset_sha256"]
    base_model_matches = bool(receipt_ready and receipt.get("base_model") == config.get("base_model_huggingface"))
    installed: list[str] = []
    try:
        installed = await ollama_models()
    except httpx.HTTPError:
        pass
    tag_matches = config.get("ollama_model_tag") == request.model_tag
    role_matches = request.model_role is None or config.get("model_role") == request.model_role
    registered = request.model_tag in installed
    ready = bool(tag_matches and role_matches and weight_ready and receipt_ready and dataset_matches and base_model_matches and registered)
    missing: list[str] = []
    if not tag_matches:
        missing.append("当前训练配置中的角色标签与输入不一致")
    if not role_matches:
        missing.append("当前训练配置中的角色方向与本轮模型角色不一致")
    if not weight_ready:
        missing.append("LoRA 适配器权重")
    if not receipt_ready:
        missing.append("本地训练凭证 training-result.json")
    elif not dataset_matches:
        missing.append("与当前数据集匹配的训练凭证")
    if receipt_ready and not base_model_matches:
        missing.append("与当前基础模型匹配的训练凭证")
    if not registered:
        missing.append(f"Ollama 角色标签 {request.model_tag}")
    return {
        "ready": ready,
        "registered": registered,
        "weight_ready": weight_ready,
        "receipt_ready": receipt_ready,
        "dataset_matches": dataset_matches,
        "base_model_matches": base_model_matches,
        "role_matches": role_matches,
        "missing": missing,
        "receipt": {
            "completed_at": receipt.get("completed_at"),
            "example_count": receipt.get("example_count"),
            "epochs": receipt.get("epochs"),
            "train_loss": receipt.get("train_loss"),
            "runtime_seconds": receipt.get("runtime_seconds"),
            "best_eval_loss": receipt.get("best_eval_loss"),
        } if receipt_ready else None,
    }


@app.post("/api/import")
async def import_chat(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 50 MB")
    try:
        messages = parse_upload(file.filename or "chat.txt", data)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    speakers = [name for name in dict.fromkeys(item["sender"] for item in messages)]
    return {"messages": messages, "speakers": speakers, "count": len(messages)}


@app.post("/api/dataset")
async def dataset(request: DatasetRequest) -> dict:
    try:
        directory = data_dir_for(request.project_id, require_exists=True)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    if training_manager(request.project_id).status(request.model_role, include_log=False).get("status") == "running":
        raise HTTPException(409, "该角色正在训练，不能覆盖训练数据；请先等待完成或在 UI 中取消任务")
    examples: list[dict] = []
    prepared: dict = {"train": [], "validation": [], "test": [], "report": {}}
    if request.messages:
        try:
            prepared = prepare_dataset(request.messages, request.dog_speaker, request.receiver_speaker, request.model_role)
            examples = prepared["train"]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    narrative = build_narrative_memory(request.narrative, request.narrator_role, request.dog_name, request.receiver_name) if request.narrative.strip() else None
    if not examples and not narrative:
        raise HTTPException(422, "请提供能形成问答轮次的聊天记录，或至少 30 字的经历自述")
    if request.method in {"lora", "hybrid"} and not examples:
        raise HTTPException(422, "LoRA 与混合模式需要双方逐轮聊天记录；单篇经历自述只能用于聊天记忆。")
    target = request.dog_name if request.model_role == "dog" else request.receiver_name
    model_spec = next((item for item in MODELS if item.id == request.model_id), MODELS[1])
    dataset_file, profile_file, training_config_file, modelfile = role_artifacts(request.model_role, request.project_id)
    validation_file, test_file = role_split_artifacts(request.model_role, request.project_id)
    adapter_dir = directory / "adapters" / f"{request.model_role}-lora"
    directory.mkdir(parents=True, exist_ok=True)
    if examples:
        save_dataset(examples, dataset_file)
    elif dataset_file.exists():
        dataset_file.unlink()
    for split_examples, split_file in ((prepared["validation"], validation_file), (prepared["test"], test_file)):
        if split_examples:
            save_dataset(split_examples, split_file)
        elif split_file.exists():
            split_file.unlink()
    profile = {
        "dog_speaker": request.dog_speaker,
        "receiver_speaker": request.receiver_speaker,
        "model_role": request.model_role,
        "dog_name": request.dog_name,
        "receiver_name": request.receiver_name,
        "examples": prepared["all"] if request.messages else [],
        "train_examples": examples,
        "validation_examples": prepared["validation"],
        "test_examples": prepared["test"],
        "data_report": prepared["report"],
        "narrative": narrative,
        "style": style_profile(request.messages, request.dog_speaker if request.model_role == "dog" else request.receiver_speaker),
    }
    profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    source_file = directory / "source.json"
    source = read_json(source_file)
    source.update({
        "input_mode": "story" if request.narrative.strip() and not request.messages else "records",
        "messages": request.messages,
        "narrative": request.narrative,
        "narrator_role": request.narrator_role,
        "dog_speaker": request.dog_speaker,
        "receiver_speaker": request.receiver_speaker,
        "dog_name": request.dog_name,
        "receiver_name": request.receiver_name,
        "updated_at": now_iso(),
    })
    write_json(source_file, source)
    touch_project(DATA_DIR, request.project_id, dog_name=request.dog_name, receiver_name=request.receiver_name)
    training_config = {
        "method": request.method,
        "model_role": request.model_role,
        "target": target,
        "base_model_id": model_spec.id,
        "base_model_huggingface": model_spec.hf_id,
        "base_model_ollama": model_spec.ollama_tag,
        "dataset": str(dataset_file) if examples else None,
        "validation_dataset": str(validation_file) if prepared["validation"] else None,
        "test_dataset": str(test_file) if prepared["test"] else None,
        "has_narrative": bool(narrative),
        "epochs": request.epochs,
        "adapter_output": str(adapter_dir) if request.method != "memory" else None,
        "ollama_adapter_direct_supported": model_spec.ollama_adapter_supported if request.method != "memory" else None,
        "ollama_model_tag": request.lora_model_tag if request.method != "memory" else None,
        "train_command": (
            f'python -m backend.train_lora --dataset "{dataset_file.as_posix()}" '
            + (f'--validation "{validation_file.as_posix()}" ' if prepared["validation"] else "")
            + f'--model {model_spec.hf_id} --output "{adapter_dir.as_posix()}" --epochs {request.epochs:g}'
        ) if request.method != "memory" else None,
        "register_command": f'ollama create {request.lora_model_tag} -f "{modelfile.as_posix()}"' if request.method != "memory" and model_spec.ollama_adapter_supported else None,
        "warning": (
            "此文件只描述训练输入；生成它不会下载模型，也不会启动训练。"
            if request.method == "memory" or model_spec.ollama_adapter_supported else
            "Ollama 当前官方 Safetensors ADAPTER 列表未包含此架构；训练后不能假定可直接 ollama create。请先合并/转换并注册为 Ollama 标签，或选择标注为支持直载的模型。"
        ),
    }
    if request.method != "memory" and model_spec.ollama_adapter_supported:
        modelfile.write_text(
            f'FROM {model_spec.ollama_tag}\nADAPTER "{adapter_dir.resolve().as_posix()}"\nPARAMETER temperature 0.78\nPARAMETER top_p 0.9\n',
            encoding="utf-8",
        )
    elif modelfile.exists():
        modelfile.unlink()
    training_config_file.write_text(json.dumps(training_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "example_count": len(examples),
        "data_report": prepared["report"],
        "target": target,
        "dataset": str(dataset_file) if examples else None,
        "training_config": str(training_config_file),
        "modelfile": str(modelfile) if request.method != "memory" and model_spec.ollama_adapter_supported else None,
        "train_command": training_config["train_command"],
        "register_command": training_config["register_command"],
        "adapter_direct_supported": training_config["ollama_adapter_direct_supported"],
        "warning": training_config["warning"],
    }


def role_prompt(request: ChatRequest, memories: list[str]) -> str:
    model_name = request.dog_name if request.model_role == "dog" else request.receiver_name
    role = "舔狗" if request.model_role == "dog" else "被舔者"
    pressure = min(1.0, request.ignored_count / max(request.max_ignored, 1))
    recent_replies = [turn.content for turn in request.history if turn.role == "assistant"][-4:]
    if recent_replies:
        memories = [
            "本轮刚才已经说过这些话，不要原句复读，也不要只做同义改写：\n- " + "\n- ".join(recent_replies),
            *memories,
        ]
    state = (
        f"对方已连续忽略你 {request.ignored_count} 次。焦虑强度 {pressure:.0%}，可以更在意但禁止威胁、辱骂、道德绑架或连续轰炸。"
        if request.model_role == "dog" else
        "你可以冷淡、简短或延迟，但不要羞辱、操纵或故意伤害对方。"
    )
    memory_text = "\n\n".join(memories) if memories else "没有注入历史片段。"
    mode_rule = {
        "memory": "表达风格来自下方聊天记忆片段；模仿其长度、用词、标点和克制程度，但不要照抄。",
        "lora": "表达风格由当前已加载的 LoRA 角色模型提供；不要假装记得未提供的具体事实。",
        "hybrid": "表达风格优先由当前已加载的 LoRA 角色模型提供；下方聊天记忆只补充关系事实和相似情境，不要照抄原句。",
    }[request.method]
    memory_heading = (
        "以下片段仅用于补充关系事实和相似情境，其中‘目标角色’的回复才是正确一方的标签："
        if request.method in {"memory", "hybrid"} else
        "本模式不注入聊天记忆；风格必须来自已加载的 LoRA 角色模型："
    )
    return f"""你正在进行虚构的私聊角色模拟。你扮演{role}“{model_name}”，输出且只输出一条自然的中文聊天消息。
{mode_rule}
不声称自己是真实人物，不编造线下事实。
{state}
{memory_heading}
{memory_text}
"""


def memories_for_method(method: str, query: str, examples: list[dict], narrative: dict | None) -> list[str]:
    if method not in {"memory", "hybrid"}:
        return []
    return retrieve_memories(query, examples, narrative=narrative)


def _normalized_similarity(left: str, right: str) -> float:
    clean = lambda value: re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()
    return SequenceMatcher(None, clean(left), clean(right)).ratio()


def _style_score(reply: str, expected: str) -> float:
    if not reply or not expected:
        return 0.0
    length_score = min(len(reply), len(expected)) / max(len(reply), len(expected))
    reply_marks = Counter(character for character in reply if character in "！？?!…~哈嗯啊哦")
    expected_marks = Counter(character for character in expected if character in "！？?!…~哈嗯啊哦")
    mark_total = sum((reply_marks | expected_marks).values())
    mark_score = sum((reply_marks & expected_marks).values()) / mark_total if mark_total else 1.0
    return length_score * 0.7 + mark_score * 0.3


async def _call_ollama(client: httpx.AsyncClient, model: str, system_prompt: str, message: str) -> tuple[str, int]:
    started = time.perf_counter()
    response = await client.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}],
        "options": {"temperature": 0.2, "top_p": 0.85, "num_predict": 120, "seed": 42},
    })
    response.raise_for_status()
    reply = response.json().get("message", {}).get("content", "").strip()
    if not reply:
        raise ValueError(f"模型 {model} 没有返回内容")
    return reply, round((time.perf_counter() - started) * 1000)


@app.post("/api/evaluate")
async def evaluate(request: EvaluationRequest) -> dict:
    """Run a small, reproducible local comparison on complete held-out sessions."""
    profile_path = role_artifacts(request.model_role, request.project_id)[1]
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "请先重新生成角色数据，才能建立评测集") from exc
    test_examples = profile.get("test_examples", [])
    if not test_examples:
        raise HTTPException(422, "当前记录没有独立测试集。请导入带日期时间、覆盖至少 3 段独立会话的聊天后重新生成。")
    samples = test_examples[:request.limit]
    status = await training_status(TrainingStatusRequest(project_id=request.project_id, model_tag=request.role_model, model_role=request.model_role))
    modes = [
        ("base", "基础模型", request.base_model),
        ("memory", "聊天记忆", request.base_model),
    ]
    skipped: list[dict] = []
    if status["ready"]:
        modes.extend((("lora", "LoRA", request.role_model), ("hybrid", "混合模式", request.role_model)))
    else:
        skipped.extend({"method": method, "reason": "角色模型尚未就绪"} for method in ("lora", "hybrid"))

    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            for sample_index, example in enumerate(samples):
                dialog = example.get("messages", [])
                query = next((item.get("content", "") for item in reversed(dialog) if item.get("role") == "user"), "")
                expected = next((item.get("content", "") for item in reversed(dialog) if item.get("role") == "assistant"), "")
                if not query or not expected:
                    continue
                for method, label, model_tag in modes:
                    if method == "base":
                        prompt = "你正在进行虚构的中文私聊角色模拟。只回复一条自然消息，不解释规则，不声称自己是真实人物。"
                        memory_items: list[dict] = []
                    else:
                        memory_items = retrieve_memory_items(
                            query, profile.get("train_examples", []), narrative=profile.get("narrative"),
                        ) if method in {"memory", "hybrid"} else []
                        prompt_request = ChatRequest(
                            message=query,
                            model=model_tag,
                            method=method,
                            model_role=request.model_role,
                            player_role=request.player_role,
                            dog_speaker=request.dog_speaker,
                            receiver_speaker=request.receiver_speaker,
                            dog_name=request.dog_name,
                            receiver_name=request.receiver_name,
                        )
                        prompt = role_prompt(prompt_request, [item["content"] for item in memory_items])
                    reply, latency_ms = await _call_ollama(client, model_tag, prompt, query)
                    rows.append({
                        "sample": sample_index + 1,
                        "method": method,
                        "label": label,
                        "query": query,
                        "expected": expected,
                        "reply": reply,
                        "similarity": round(_normalized_similarity(reply, expected), 3),
                        "style_score": round(_style_score(reply, expected), 3),
                        "verbatim_risk": _normalized_similarity(reply, expected) >= 0.92,
                        "latency_ms": latency_ms,
                        "memory_count": len(memory_items),
                    })
    except httpx.HTTPStatusError as exc:
        raise HTTPException(503, ollama_http_error(exc, request.base_model)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "本地评测未能连接 Ollama") from exc
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc

    summary: list[dict] = []
    for method, label, _ in modes:
        mode_rows = [row for row in rows if row["method"] == method]
        if not mode_rows:
            continue
        replies = [re.sub(r"[\W_]+", "", row["reply"], flags=re.UNICODE).lower() for row in mode_rows]
        duplicate_rate = 1 - len(set(replies)) / len(replies) if replies else 0
        summary.append({
            "method": method,
            "label": label,
            "samples": len(mode_rows),
            "similarity": round(sum(row["similarity"] for row in mode_rows) / len(mode_rows), 3),
            "style_score": round(sum(row["style_score"] for row in mode_rows) / len(mode_rows), 3),
            "verbatim_rate": round(sum(row["verbatim_risk"] for row in mode_rows) / len(mode_rows), 3),
            "duplicate_rate": round(duplicate_rate, 3),
            "average_latency_ms": round(sum(row["latency_ms"] for row in mode_rows) / len(mode_rows)),
        })
    report = {"sample_count": len(samples), "summary": summary, "rows": rows, "skipped": skipped}
    evaluation_file = data_dir_for(request.project_id, require_exists=True) / f"{request.model_role}-evaluation.json"
    evaluation_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    if request.method in {"lora", "hybrid"}:
        status = await training_status(TrainingStatusRequest(project_id=request.project_id, model_tag=request.model, model_role=request.model_role))
        if not status["ready"]:
            raise HTTPException(409, "LoRA 角色模型尚未就绪：缺少" + "、".join(status["missing"]))
    examples: list[dict] = []
    narrative: dict | None = None
    try:
        directory = data_dir_for(request.project_id, require_exists=True)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    role_profile = role_artifacts(request.model_role, request.project_id)[1]
    fallback_profile = directory / "profile.json"
    profile_path = role_profile if role_profile.exists() else fallback_profile
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            if profile.get("model_role") == request.model_role:
                # New profiles keep held-out conversations separate. Older profiles fall back to examples.
                examples = profile.get("train_examples", profile.get("examples", []))
                narrative = profile.get("narrative")
        except (json.JSONDecodeError, OSError):
            pass
    memory_items = retrieve_memory_items(request.message, examples, narrative=narrative) if request.method in {"memory", "hybrid"} else []
    memories = [item["content"] for item in memory_items]
    conversation = [{"role": turn.role, "content": turn.content} for turn in request.history[-16:]]
    payload = {
        "model": request.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": role_prompt(request, memories)},
            *conversation,
            {"role": "user", "content": request.message},
        ],
        "options": {"temperature": 0.78, "top_p": 0.9, "num_predict": 120},
    }
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            reply = response.json().get("message", {}).get("content", "").strip()
            normalized = lambda text: re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()
            recent = {
                normalized(turn.content)
                for turn in request.history[-8:]
                if turn.role == "assistant"
            }
            if reply and normalized(reply) in recent:
                retry_payload = {
                    **payload,
                    "messages": [
                        {
                            **payload["messages"][0],
                            "content": payload["messages"][0]["content"] + "\n上一版回复与本轮旧回复完全重复。换一个新的信息点重新回复。",
                        },
                        *payload["messages"][1:],
                    ],
                    "options": {**payload["options"], "temperature": 0.95},
                }
                retry = await client.post(f"{OLLAMA_URL}/api/chat", json=retry_payload)
                retry.raise_for_status()
                alternative = retry.json().get("message", {}).get("content", "").strip()
                if alternative:
                    reply = alternative
    except httpx.HTTPStatusError as exc:
        raise HTTPException(503, ollama_http_error(exc, request.model)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "未连接 Ollama。请先安装并启动 Ollama。") from exc
    if not reply:
        raise HTTPException(503, "模型没有返回内容")
    return {
        "reply": reply,
        "memory_count": len(memories),
        "memory_evidence": [
            {
                "kind": item["kind"], "source_id": item["source_id"], "source_time": item["source_time"],
                "score": round(item["score"], 3), "reason": item["reason"], "preview": item["content"][:220],
            }
            for item in memory_items
        ],
        "method": request.method,
        "model": request.model,
    }
