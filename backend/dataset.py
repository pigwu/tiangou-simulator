from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


SESSION_GAP_SECONDS = 6 * 60 * 60


def validate_roles(messages: list[dict], dog_speaker: str, receiver_speaker: str) -> None:
    speakers = {str(item.get("sender", "")).strip() for item in messages}
    if not dog_speaker or not receiver_speaker or dog_speaker == receiver_speaker:
        raise ValueError("舔狗与被舔者必须是两个不同的说话人")
    if dog_speaker not in speakers or receiver_speaker not in speakers:
        raise ValueError("选择的说话人不存在于导入记录中")


def _normalized_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def _parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) in {10, 13}:
        try:
            return datetime.fromtimestamp(int(raw) / (1000 if len(raw) == 13 else 1))
        except (OSError, OverflowError, ValueError):
            return None
    normalized = raw.replace("年", "-").replace("月", "-").replace("日", " ").replace("T", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized).rstrip("Z")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    return None


def _clean_messages(messages: Iterable[dict], allowed: set[str]) -> tuple[list[dict], int]:
    cleaned: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    duplicates = 0
    for item in messages:
        sender = str(item.get("sender", "")).strip()
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        timestamp = str(item.get("timestamp", "") or "").strip()
        if sender not in allowed or not content:
            continue
        fingerprint = (sender, _normalized_text(content), timestamp)
        adjacent_duplicate = bool(
            cleaned
            and cleaned[-1]["sender"] == sender
            and _normalized_text(cleaned[-1]["content"]) == fingerprint[1]
            and (not timestamp or cleaned[-1]["timestamp"] == timestamp)
        )
        if fingerprint in seen or adjacent_duplicate:
            duplicates += 1
            continue
        seen.add(fingerprint)
        cleaned.append({"sender": sender, "content": content, "timestamp": timestamp})
    return cleaned, duplicates


def group_sessions(
    messages: Iterable[dict], allowed: set[str], gap_seconds: int = SESSION_GAP_SECONDS,
) -> tuple[list[list[dict]], int]:
    cleaned, duplicates = _clean_messages(messages, allowed)
    sessions: list[list[dict]] = []
    previous_time: datetime | None = None
    for message in cleaned:
        current_time = _parse_timestamp(message.get("timestamp"))
        new_session = not sessions
        if sessions and previous_time and current_time:
            try:
                delta = (current_time - previous_time).total_seconds()
                new_session = delta < 0 or delta > gap_seconds
            except TypeError:
                # Mixed timezone-aware and naive exports cannot be compared reliably.
                new_session = True
        if new_session:
            sessions.append([])
        sessions[-1].append(message)
        if current_time:
            previous_time = current_time
    return sessions, duplicates


def group_turns(messages: Iterable[dict], allowed: set[str]) -> list[dict[str, str]]:
    """Backward-compatible turn grouping for callers that do not need session metadata."""
    sessions, _ = group_sessions(messages, allowed)
    turns: list[dict[str, str]] = []
    for session in sessions:
        for item in session:
            sender = item["sender"]
            if turns and turns[-1]["sender"] == sender:
                turns[-1]["content"] += "\n" + item["content"]
            else:
                turns.append({"sender": sender, "content": item["content"]})
    return turns


def _session_turns(session: list[dict]) -> list[dict]:
    turns: list[dict] = []
    for item in session:
        if turns and turns[-1]["sender"] == item["sender"]:
            turns[-1]["content"] += "\n" + item["content"]
            turns[-1]["end_time"] = item.get("timestamp", "")
        else:
            turns.append({
                "sender": item["sender"],
                "content": item["content"],
                "start_time": item.get("timestamp", ""),
                "end_time": item.get("timestamp", ""),
            })
    return turns


def prepare_dataset(messages: list[dict], dog_speaker: str, receiver_speaker: str, model_role: str) -> dict:
    """Build role-correct examples, remove repeats, then hold out complete recent sessions."""
    validate_roles(messages, dog_speaker, receiver_speaker)
    target = dog_speaker if model_role == "dog" else receiver_speaker
    other = receiver_speaker if model_role == "dog" else dog_speaker
    sessions, duplicate_messages = group_sessions(messages, {target, other})
    examples: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    duplicate_examples = 0
    for session_index, session in enumerate(sessions):
        history: list[dict[str, str]] = []
        for turn_index, turn in enumerate(_session_turns(session)):
            role = "assistant" if turn["sender"] == target else "user"
            mapped = {"role": role, "content": turn["content"]}
            if role == "assistant" and history and history[-1]["role"] == "user":
                pair = (_normalized_text(history[-1]["content"]), _normalized_text(turn["content"]))
                if pair in seen_pairs:
                    duplicate_examples += 1
                else:
                    seen_pairs.add(pair)
                    examples.append({
                        "messages": [
                            {"role": "system", "content": f"你扮演聊天中的{('舔狗' if model_role == 'dog' else '被舔者')}“{target}”。模仿表达风格，不编造现实经历。"},
                            *history[-6:], mapped,
                        ],
                        "metadata": {
                            "target_speaker": target,
                            "target_role": model_role,
                            "session_id": f"session-{session_index + 1:04d}",
                            "turn_index": turn_index,
                            "source_time": turn.get("start_time", ""),
                        },
                    })
            history.append(mapped)

    groups: list[list[dict]] = []
    for example in examples:
        session_id = example["metadata"]["session_id"]
        if not groups or groups[-1][0]["metadata"]["session_id"] != session_id:
            groups.append([])
        groups[-1].append(example)

    train_groups = list(groups)
    validation_groups: list[list[dict]] = []
    test_groups: list[list[dict]] = []
    if len(groups) >= 3 and len(examples) >= 12:
        target_size = max(1, round(len(examples) * 0.1))
        while len(train_groups) > 2 and sum(map(len, test_groups)) < target_size:
            test_groups.insert(0, train_groups.pop())
        while len(train_groups) > 1 and sum(map(len, validation_groups)) < target_size:
            validation_groups.insert(0, train_groups.pop())
    elif len(groups) == 2 and len(examples) >= 12:
        test_groups.append(train_groups.pop())

    flatten = lambda values: [item for group in values for item in group]
    train = flatten(train_groups)
    validation = flatten(validation_groups)
    test = flatten(test_groups)
    total = max(len(examples), 1)
    warnings: list[str] = []
    timestamp_count = sum(bool(str(item.get("timestamp", "")).strip()) for item in messages)
    if timestamp_count < len(messages) * 0.5:
        warnings.append("多数消息没有可用时间，无法可靠识别跨天会话")
    if not test:
        warnings.append("独立会话不足，暂未生成测试集；请导入包含日期时间的更多聊天")
    if validation and len(validation) / total > 0.3 or test and len(test) / total > 0.3:
        warnings.append("最近单个会话较长，留出集占比较高；这是避免相邻消息泄漏的结果")
    report = {
        "source_messages": len(messages),
        "usable_messages": sum(len(session) for session in sessions),
        "duplicate_messages_removed": duplicate_messages,
        "duplicate_examples_removed": duplicate_examples,
        "session_count": len(groups),
        "example_count": len(examples),
        "train_count": len(train),
        "validation_count": len(validation),
        "test_count": len(test),
        "split_strategy": "按时间排序的完整会话留出" if test else "仅训练集（独立会话不足）",
        "warnings": warnings,
    }
    return {"all": examples, "train": train, "validation": validation, "test": test, "report": report}


def build_examples(messages: list[dict], dog_speaker: str, receiver_speaker: str, model_role: str) -> list[dict]:
    return prepare_dataset(messages, dog_speaker, receiver_speaker, model_role)["all"]


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
    return set(_terms(text))


def _terms(text: str) -> list[str]:
    lowered = text.lower()
    terms = re.findall(r"[a-z0-9_]+", lowered)
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(chunk) == 1:
            terms.append(chunk)
        else:
            terms.extend(chunk[index:index + size] for size in (2, 3) for index in range(len(chunk) - size + 1))
    return terms


def _cosine(query: Counter, document: Counter, idf: dict[str, float]) -> float:
    common = set(query) & set(document)
    numerator = sum(query[term] * document[term] * idf.get(term, 1.0) ** 2 for term in common)
    query_norm = math.sqrt(sum((count * idf.get(term, 1.0)) ** 2 for term, count in query.items()))
    document_norm = math.sqrt(sum((count * idf.get(term, 1.0)) ** 2 for term, count in document.items()))
    return numerator / (query_norm * document_norm) if query_norm and document_norm else 0.0


def _narrative_chunks(content: str, size: int = 420) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？!?])|\n+", content) if piece.strip()]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > size:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


def retrieve_memory_items(
    query: str, examples: list[dict], limit: int = 5, narrative: dict | None = None,
) -> list[dict]:
    """Rank local memories with TF-IDF character n-grams, recency and MMR diversity."""
    candidates: list[dict] = []
    for index, example in enumerate(examples):
        dialog = example.get("messages", [])
        user_text = " ".join(item.get("content", "") for item in dialog if item.get("role") == "user")
        assistant = next((item.get("content", "") for item in reversed(dialog) if item.get("role") == "assistant"), "")
        if not user_text or not assistant:
            continue
        metadata = example.get("metadata", {})
        candidates.append({
            "kind": "dialogue",
            "document": user_text,
            "content": f"对方：{user_text[-300:]}\n目标角色：{assistant[:300]}",
            "source_time": metadata.get("source_time", ""),
            "source_id": metadata.get("session_id", f"memory-{index + 1}"),
            "recency": (index + 1) / max(len(examples), 1),
        })
    if narrative and narrative.get("content"):
        for index, chunk in enumerate(_narrative_chunks(str(narrative["content"]))):
            candidates.append({
                "kind": "narrative",
                "document": chunk,
                "content": f"关系背景（自述，不是逐字对话）：{chunk}",
                "source_time": "",
                "source_id": f"narrative-{index + 1}",
                "recency": 0.5,
            })
    if not candidates:
        return []

    query_counter = Counter(_terms(query))
    document_counters = [Counter(_terms(candidate["document"])) for candidate in candidates]
    document_frequency = Counter(term for counter in document_counters for term in counter)
    idf = {term: math.log((len(candidates) + 1) / (frequency + 1)) + 1 for term, frequency in document_frequency.items()}
    normalized_query = _normalized_text(query)
    for candidate, counter in zip(candidates, document_counters):
        semantic = _cosine(query_counter, counter, idf)
        normalized_doc = _normalized_text(candidate["document"])
        sequence = SequenceMatcher(None, normalized_query[:180], normalized_doc[-300:]).ratio() if normalized_query else 0.0
        phrase = 1.0 if normalized_query and normalized_query in normalized_doc else 0.0
        candidate["score"] = semantic * 0.72 + sequence * 0.13 + phrase * 0.08 + candidate["recency"] * 0.07
        reasons = []
        if semantic >= 0.2:
            reasons.append("关键词组相近")
        if phrase:
            reasons.append("包含原问题表达")
        if candidate["recency"] >= 0.8:
            reasons.append("较新的记录")
        if candidate["kind"] == "narrative":
            reasons.append("经历背景")
        candidate["reason"] = "、".join(reasons) or "弱相关参考"

    pool = sorted(candidates, key=lambda item: item["score"], reverse=True)
    selected: list[dict] = []
    while pool and len(selected) < limit:
        best = None
        best_mmr = -1.0
        for candidate in pool:
            redundancy = max(
                (SequenceMatcher(None, _normalized_text(candidate["content"]), _normalized_text(item["content"])).ratio() for item in selected),
                default=0.0,
            )
            mmr = candidate["score"] * 0.82 - redundancy * 0.18
            if mmr > best_mmr:
                best, best_mmr = candidate, mmr
        if best is None:
            break
        pool.remove(best)
        if best["score"] >= 0.035 or (best["kind"] == "narrative" and not selected):
            selected.append(best)
    return [{key: value for key, value in item.items() if key not in {"document", "recency"}} for item in selected]


def retrieve_memories(query: str, examples: list[dict], limit: int = 5, narrative: dict | None = None) -> list[str]:
    return [item["content"] for item in retrieve_memory_items(query, examples, limit=limit, narrative=narrative)]


def style_profile(messages: list[dict], target: str) -> dict:
    texts = [str(item.get("content", "")) for item in messages if item.get("sender") == target]
    if not texts:
        return {"message_count": 0, "average_length": 0, "common_phrases": []}
    phrases = Counter(fragment for text in texts for fragment in re.findall(r"[\u4e00-\u9fff]{2,5}", text))
    return {
        "message_count": len(texts),
        "average_length": round(sum(map(len, texts)) / len(texts), 1),
        "short_reply_ratio": round(sum(len(text) <= 6 for text in texts) / len(texts), 3),
        "question_ratio": round(sum("?" in text or "？" in text for text in texts) / len(texts), 3),
        "emoji_ratio": round(sum(bool(re.search(r"[^\w\s\u4e00-\u9fff，。！？、]", text)) for text in texts) / len(texts), 3),
        "common_phrases": [item for item, _ in phrases.most_common(12)],
    }


def save_dataset(examples: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
