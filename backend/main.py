from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .dataset import build_examples, build_narrative_memory, retrieve_memories, save_dataset, style_profile
from .parsers import parse_upload
from .models import catalog, estimate, system_profile


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TIANGOU_DATA_DIR", ROOT / "local_data"))
DATASET_FILE = DATA_DIR / "dataset.jsonl"
PROFILE_FILE = DATA_DIR / "profile.json"
TRAINING_CONFIG_FILE = DATA_DIR / "training-config.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

app = FastAPI(title="舔狗模拟器本地 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class DatasetRequest(BaseModel):
    messages: list[dict]
    dog_speaker: str
    receiver_speaker: str
    dog_name: str = "舔狗"
    receiver_name: str = "被舔者"
    model_role: str = Field(pattern="^(dog|receiver)$")
    narrative: str = Field(default="", max_length=200_000)
    narrator_role: str = Field(default="dog", pattern="^(dog|receiver)$")


class ChatRequest(BaseModel):
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


class EstimateRequest(BaseModel):
    model_id: str = "qwen25-3b"
    method: str = Field(default="memory", pattern="^(memory|lora)$")
    message_count: int = Field(default=0, ge=0, le=10_000_000)
    narrative_chars: int = Field(default=0, ge=0, le=1_000_000)
    epochs: float = Field(default=2.0, ge=0.1, le=20)


@app.get("/api/health")
async def health() -> dict:
    ollama = False
    try:
        async with httpx.AsyncClient(timeout=1.2) as client:
            ollama = (await client.get(f"{OLLAMA_URL}/api/tags")).is_success
    except httpx.HTTPError:
        pass
    return {"ok": True, "ollama": ollama, "platform": platform.system(), "data_dir": str(DATA_DIR)}


@app.get("/api/system")
async def system() -> dict:
    profile = system_profile()
    return {"hardware": profile, "models": catalog(profile)}


@app.post("/api/estimate")
async def training_estimate(request: EstimateRequest) -> dict:
    return estimate(request.model_id, request.method, request.message_count, request.narrative_chars, request.epochs)


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
    examples: list[dict] = []
    if request.messages:
        try:
            examples = build_examples(request.messages, request.dog_speaker, request.receiver_speaker, request.model_role)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    narrative = build_narrative_memory(request.narrative, request.narrator_role, request.dog_name, request.receiver_name) if request.narrative.strip() else None
    if not examples and not narrative:
        raise HTTPException(422, "请提供能形成问答轮次的聊天记录，或至少 30 字的经历自述")
    target = request.dog_name if request.model_role == "dog" else request.receiver_name
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if examples:
        save_dataset(examples, DATASET_FILE)
    elif DATASET_FILE.exists():
        DATASET_FILE.unlink()
    profile = {
        "dog_speaker": request.dog_speaker,
        "receiver_speaker": request.receiver_speaker,
        "model_role": request.model_role,
        "dog_name": request.dog_name,
        "receiver_name": request.receiver_name,
        "examples": examples,
        "narrative": narrative,
        "style": style_profile(request.messages, request.dog_speaker if request.model_role == "dog" else request.receiver_speaker),
    }
    PROFILE_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    training_config = {
        "model_role": request.model_role,
        "target": target,
        "dataset": str(DATASET_FILE) if examples else None,
        "has_narrative": bool(narrative),
        "warning": "此文件只描述训练输入；生成它不会下载模型，也不会启动训练。",
    }
    TRAINING_CONFIG_FILE.write_text(json.dumps(training_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "example_count": len(examples), "target": target, "dataset": str(DATASET_FILE) if examples else None, "training_config": str(TRAINING_CONFIG_FILE)}


def role_prompt(request: ChatRequest, memories: list[str]) -> str:
    model_name = request.dog_name if request.model_role == "dog" else request.receiver_name
    role = "舔狗" if request.model_role == "dog" else "被舔者"
    pressure = min(1.0, request.ignored_count / max(request.max_ignored, 1))
    state = (
        f"对方已连续忽略你 {request.ignored_count} 次。焦虑强度 {pressure:.0%}，可以更在意但禁止威胁、辱骂、道德绑架或连续轰炸。"
        if request.model_role == "dog" else
        "你可以冷淡、简短或延迟，但不要羞辱、操纵或故意伤害对方。"
    )
    memory_text = "\n\n".join(memories) if memories else "没有可用的相似历史片段。"
    return f"""你正在进行虚构的私聊角色模拟。你扮演{role}“{model_name}”，输出且只输出一条自然的中文聊天消息。
模仿参考记录的长度、用词、标点和克制程度，不照抄，不声称自己是真实人物，不编造线下事实。
{state}
以下片段仅用于学习语气，其中“目标角色”的回复才是你要模仿的标签：
{memory_text}
"""


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    examples: list[dict] = []
    narrative: dict | None = None
    if PROFILE_FILE.exists():
        try:
            profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            if profile.get("model_role") == request.model_role:
                examples = profile.get("examples", [])
                narrative = profile.get("narrative")
        except (json.JSONDecodeError, OSError):
            pass
    memories = retrieve_memories(request.message, examples, narrative=narrative)
    payload = {
        "model": request.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": role_prompt(request, memories)},
            {"role": "user", "content": request.message},
        ],
        "options": {"temperature": 0.78, "top_p": 0.9, "num_predict": 120},
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            reply = response.json().get("message", {}).get("content", "").strip()
    except httpx.HTTPStatusError as exc:
        detail = "本地模型不存在，请先运行：ollama pull " + request.model if exc.response.status_code == 404 else "Ollama 调用失败"
        raise HTTPException(503, detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "未连接 Ollama。请先安装并启动 Ollama。") from exc
    if not reply:
        raise HTTPException(503, "模型没有返回内容")
    return {"reply": reply, "memory_count": len(memories)}
