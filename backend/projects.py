from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LEGACY_ID = "legacy"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_project_id(project_id: str) -> str:
    value = str(project_id or LEGACY_ID).strip().lower()
    if value != LEGACY_ID and not PROJECT_ID_PATTERN.fullmatch(value):
        raise ValueError("无效的本地项目 ID")
    return value


def project_dir(data_root: Path, project_id: str, require_exists: bool = False) -> Path:
    project_id = validate_project_id(project_id)
    root = data_root.resolve()
    if project_id == LEGACY_ID:
        result = root
    else:
        projects_root = (root / "projects").resolve()
        result = (projects_root / project_id).resolve()
        try:
            result.relative_to(projects_root)
        except ValueError as exc:
            raise ValueError("项目目录越过了本地项目边界") from exc
    if require_exists and not result.is_dir():
        raise FileNotFoundError("本地项目不存在")
    return result


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def directory_size(path: Path, include_projects: bool = True) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        if not include_projects and "projects" in item.relative_to(path).parts:
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def _project_summary(data_root: Path, project_id: str, path: Path) -> dict:
    managed = project_id != LEGACY_ID
    manifest = read_json(path / "project.json") if managed else {}
    source = read_json(path / "source.json")
    profiles = [read_json(path / f"{role}-profile.json") for role in ("dog", "receiver")]
    profiles = [profile for profile in profiles if profile]
    updated_candidates = [manifest.get("updated_at"), source.get("updated_at")]
    try:
        updated_candidates.append(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    except OSError:
        pass
    return {
        "id": project_id,
        "name": manifest.get("name") or ("原有项目" if not managed else project_id),
        "managed": managed,
        "created_at": manifest.get("created_at"),
        "updated_at": next((value for value in updated_candidates if value), None),
        "dog_name": source.get("dog_name") or next((profile.get("dog_name") for profile in profiles if profile.get("dog_name")), "舔狗"),
        "receiver_name": source.get("receiver_name") or next((profile.get("receiver_name") for profile in profiles if profile.get("receiver_name")), "被舔者"),
        "message_count": len(source.get("messages", [])),
        "narrative_chars": len(str(source.get("narrative", ""))),
        "roles_ready": [role for role in ("dog", "receiver") if (path / f"{role}-profile.json").is_file()],
        "size_bytes": directory_size(path, include_projects=managed),
    }


def list_projects(data_root: Path) -> list[dict]:
    root = data_root.resolve()
    projects: list[dict] = []
    legacy_markers = ("profile.json", "dog-profile.json", "receiver-profile.json", "source.json", "dataset.jsonl")
    if any((root / marker).exists() for marker in legacy_markers):
        projects.append(_project_summary(root, LEGACY_ID, root))
    projects_root = root / "projects"
    if projects_root.is_dir():
        for path in sorted((item for item in projects_root.iterdir() if item.is_dir()), key=lambda item: item.name):
            if PROJECT_ID_PATTERN.fullmatch(path.name) and (path / "project.json").is_file():
                projects.append(_project_summary(root, path.name, path))
    return sorted(projects, key=lambda item: item.get("updated_at") or "", reverse=True)


def create_project(data_root: Path, name: str) -> dict:
    clean_name = re.sub(r"\s+", " ", name).strip()
    if not clean_name or len(clean_name) > 60:
        raise ValueError("项目名需要 1–60 个字符")
    project_id = uuid.uuid4().hex[:12]
    path = project_dir(data_root, project_id)
    path.mkdir(parents=True, exist_ok=False)
    timestamp = now_iso()
    write_json(path / "project.json", {"id": project_id, "name": clean_name, "created_at": timestamp, "updated_at": timestamp})
    return _project_summary(data_root, project_id, path)


def touch_project(data_root: Path, project_id: str, **updates: object) -> None:
    if project_id == LEGACY_ID:
        return
    path = project_dir(data_root, project_id, require_exists=True)
    manifest = read_json(path / "project.json")
    manifest.update(updates)
    manifest["updated_at"] = now_iso()
    write_json(path / "project.json", manifest)


def project_detail(data_root: Path, project_id: str) -> dict:
    path = project_dir(data_root, project_id, require_exists=True)
    summary = _project_summary(data_root, validate_project_id(project_id), path)
    source = read_json(path / "source.json")
    return {**summary, "source": source}


def delete_project(data_root: Path, project_id: str, acknowledgement: str) -> dict:
    project_id = validate_project_id(project_id)
    if project_id == LEGACY_ID:
        raise ValueError("原有项目为兼容数据，不能通过项目管理器递归删除")
    path = project_dir(data_root, project_id, require_exists=True)
    manifest = read_json(path / "project.json")
    name = str(manifest.get("name", ""))
    if acknowledgement.strip() != name:
        raise ValueError("请输入完整项目名确认删除")
    projects_root = (data_root.resolve() / "projects").resolve()
    path.resolve().relative_to(projects_root)
    shutil.rmtree(path)
    return {"deleted": True, "id": project_id, "name": name, "recoverable": False}


def create_export(data_root: Path, project_id: str, include_adapters: bool = False) -> tuple[Path, str]:
    project_id = validate_project_id(project_id)
    path = project_dir(data_root, project_id, require_exists=True)
    summary = _project_summary(data_root, project_id, path)
    file_handle, temporary_name = tempfile.mkstemp(prefix=f"tiangou-{project_id}-", suffix=".zip")
    os.close(file_handle)
    output = Path(temporary_name)
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("tiangou-project/export-manifest.json", json.dumps({
                "format": "tiangou-project-v1",
                "exported_at": now_iso(),
                "project": summary,
                "includes_adapters": include_adapters,
            }, ensure_ascii=False, indent=2))
            for item in path.rglob("*"):
                if not item.is_file():
                    continue
                relative = item.relative_to(path)
                if project_id == LEGACY_ID and relative.parts and relative.parts[0] == "projects":
                    continue
                if not include_adapters and relative.parts and relative.parts[0] == "adapters":
                    continue
                archive.write(item, Path("tiangou-project") / relative)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", summary["name"]).strip("-") or project_id
    return output, f"舔狗模拟器-{safe_name}.zip"
