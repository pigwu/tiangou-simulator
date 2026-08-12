from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable


def validate_roles(messages: list[dict], dog_speaker: str, receiver_speaker: str) -> None:
    speakers = {str(item.get("sender", "")).strip() for item in messages}
    if not dog_speaker or not receiver_speaker or dog_speaker == receiver_speaker:
        raise ValueError("舔狗与被舔者必须是两个不同的说话人")
    if dog_speaker not in speakers or receiver_speaker not in speakers:
        raise ValueError("选择的说话人不存在于导入记录中")


def group_turns(messages: Iterable[dict], allowed: set[str]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for item in messages:
        sender = str(item.get("sender", "")).strip()
        content = str(item.get("content", "")).strip()
        if sender not in allowed or not content:
            continue
        if turns and turns[-1]["sender"] == sender:
            turns[-1]["content"] += "\n" + content
        else:
            turns.append({"sender": sender, "content": content})
    return turns


def build_examples(messages: list[dict], dog_speaker: str, receiver_speaker: str, model_role: str) -> list[dict]:
    validate_roles(messages, dog_speaker, receiver_speaker)
    target = dog_speaker if model_role == "dog" else receiver_speaker
    other = receiver_speaker if model_role == "dog" else dog_speaker
    turns = group_turns(messages, {target, other})
    examples: list[dict] = []
    history: list[dict[str, str]] = []
    for turn in turns:
        role = "assistant" if turn["sender"] == target else "user"
        mapped = {"role": role, "content": turn["content"]}
        if role == "assistant" and history and history[-1]["role"] == "user":
            examples.append({
                "messages": [
                    {"role": "system", "content": f"你扮演聊天中的{('舔狗' if model_role == 'dog' else '被舔者')}“{target}”。模仿表达风格，不编造现实经历。"},
                    *history[-6:], mapped,
                ],
                "metadata": {"target_speaker": target, "target_role": model_role},
            })
        history.append(mapped)
    return examples


def build_narrative_memory(narrative: str, narrator_role: str, dog_name: str, receiver_name: str) -> dict:
    narrator = dog_name if narrator_role == "dog" else receiver_name
    other = receiver_name if narrator_role == "dog" else dog_name
    return {
        "kind": "narrative",
        "narrator_role": narrator_role,
        "content": narrative.strip(),
        "context": f"这是一段由{narrator}自述的关系经历；另一方是{other}。它只提供背景事实和关系动态，不代表任何逐字原话。",
    }


def keywords(text: str) -> set[str]:
    chunks = set(re.findall(r"[\u4e00-\u9fff]{1,4}|[A-Za-z0-9_]+", text.lower()))
    return {chunk for chunk in chunks if chunk.strip()}


def retrieve_memories(query: str, examples: list[dict], limit: int = 5, narrative: dict | None = None) -> list[str]:
    wanted = keywords(query)
    scored: list[tuple[float, str]] = []
    for example in examples:
        dialog = example.get("messages", [])
        user_text = " ".join(item["content"] for item in dialog if item.get("role") == "user")
        assistant = next((item["content"] for item in reversed(dialog) if item.get("role") == "assistant"), "")
        overlap = len(wanted & keywords(user_text))
        score = overlap * 3 + (1 / (1 + abs(len(query) - len(user_text))))
        scored.append((score, f"对方：{user_text[-240:]}\n目标角色：{assistant}"))
    memories = [text for _, text in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]
    if narrative and narrative.get("content"):
        memories.insert(0, f"关系背景（自述，不是逐字对话）：{narrative.get('content', '')[:1600]}")
    return memories[:limit]


def style_profile(messages: list[dict], target: str) -> dict:
    texts = [str(item.get("content", "")) for item in messages if item.get("sender") == target]
    if not texts:
        return {"message_count": 0, "average_length": 0, "common_phrases": []}
    phrases = Counter(fragment for text in texts for fragment in re.findall(r"[\u4e00-\u9fff]{2,5}", text))
    return {
        "message_count": len(texts),
        "average_length": round(sum(map(len, texts)) / len(texts), 1),
        "common_phrases": [item for item, _ in phrases.most_common(12)],
    }


def save_dataset(examples: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
