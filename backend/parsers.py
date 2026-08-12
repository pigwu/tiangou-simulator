from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class Message:
    sender: str
    content: str
    timestamp: str = ""


SYSTEM_PATTERNS = (
    "撤回了一条消息", "拍了拍", "以上是打招呼的内容", "消息已发出，但被对方拒收",
)
LINE_PATTERNS = (
    re.compile(r"^\[(?P<time>[^\]]+)\]\s*(?P<sender>[^:：]{1,50})[:：]\s*(?P<content>.+)$"),
    re.compile(r"^(?P<sender>[^:：\t]{1,50})[:：\t]\s*(?P<content>.+)$"),
)


def _clean(sender: Any, content: Any, timestamp: Any = "") -> Message | None:
    sender = str(sender or "").strip()
    content = re.sub(r"\s+", " ", str(content or "")).strip()
    if not sender or not content or any(marker in content for marker in SYSTEM_PATTERNS):
        return None
    return Message(sender=sender, content=content, timestamp=str(timestamp or "").strip())


def parse_text(text: str) -> list[Message]:
    messages: list[Message] = []
    for raw in text.replace("\ufeff", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for pattern in LINE_PATTERNS:
            match = pattern.match(line)
            if match:
                item = _clean(match.group("sender"), match.group("content"), match.groupdict().get("time", ""))
                if item:
                    messages.append(item)
                break
    return messages


def parse_csv_bytes(data: bytes) -> list[Message]:
    text = decode_bytes(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    aliases = {
        "sender": ("sender", "name", "speaker", "from", "发送人", "昵称", "说话人"),
        "content": ("content", "message", "text", "msg", "内容", "消息", "文本"),
        "timestamp": ("timestamp", "time", "date", "时间", "日期"),
    }
    result: list[Message] = []
    for row in rows:
        normalized = {str(key).strip().lower(): value for key, value in row.items() if key}
        values: dict[str, Any] = {}
        for field, names in aliases.items():
            values[field] = next((normalized.get(name.lower()) for name in names if name.lower() in normalized), "")
        item = _clean(values["sender"], values["content"], values["timestamp"])
        if item:
            result.append(item)
    return result


def parse_json_bytes(data: bytes) -> list[Message]:
    payload = json.loads(decode_bytes(data))
    if isinstance(payload, dict):
        payload = payload.get("messages") or payload.get("data") or payload.get("chat") or []
    if not isinstance(payload, list):
        raise ValueError("JSON 顶层必须是消息数组，或包含 messages/data/chat 数组")
    result: list[Message] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        item = _clean(
            row.get("sender") or row.get("name") or row.get("speaker") or row.get("发送人"),
            row.get("content") or row.get("message") or row.get("text") or row.get("内容"),
            row.get("timestamp") or row.get("time") or row.get("时间"),
        )
        if item:
            result.append(item)
    return result


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("无法识别文本编码，请转换为 UTF-8、UTF-16 或 GB18030")


def parse_upload(filename: str, data: bytes) -> list[dict[str, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        messages = parse_json_bytes(data)
    elif suffix in {".csv", ".tsv"}:
        messages = parse_csv_bytes(data)
    elif suffix == ".txt":
        messages = parse_text(decode_bytes(data))
    else:
        raise ValueError("仅支持 .txt、.csv、.tsv、.json")
    if not messages:
        raise ValueError("没有识别到消息。TXT 推荐格式：[时间] 昵称: 消息内容")
    return [asdict(message) for message in messages]
