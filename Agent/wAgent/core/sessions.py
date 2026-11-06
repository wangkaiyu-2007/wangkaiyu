from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


DEFAULT_SESSION_DIR = ".agents/sessions"
SESSION_HEADER_TYPE = "session"
_EVENT_MESSAGE = "message"
_EVENT_SNAPSHOT = "snapshot"
_EVENT_CHECKPOINT = "checkpoint"
_EVENT_TITLE = "title"


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str
    path: Path


class SessionStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        self._directory = (
            Path(directory).expanduser()
            if directory is not None
            else Path(DEFAULT_SESSION_DIR)
        )

    @property
    def directory(self) -> Path:
        return self._directory

    def _ensure_directory(self) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionError(f"无法创建会话目录 {self._directory}：{exc}") from exc

    def create(self, messages: Sequence[dict[str, Any]], title: str = "新会话") -> "SessionLog":
        self._ensure_directory()
        now = datetime.now()
        base_id = now.strftime("%Y%m%d-%H%M%S")
        session_id = base_id
        path = self._directory / f"{session_id}.jsonl"
        suffix = 2
        while path.exists():
            session_id = f"{base_id}-{suffix}"
            path = self._directory / f"{session_id}.jsonl"
            suffix += 1

        log = SessionLog(
            store=self,
            session_id=session_id,
            path=path,
            created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            title=title or "新会话",
        )
        log._append_event(
            {
                "type": SESSION_HEADER_TYPE,
                "id": session_id,
                "created_at": log.created_at,
                "title": log.title,
                "ts": log.created_at,
            }
        )
        log._append_event(
            {
                "type": _EVENT_SNAPSHOT,
                "ts": log.created_at,
                "title": log.title,
                "messages": list(messages),
            }
        )
        log._logged_count = len(messages)
        log._signature = _prefix_signature(messages, len(messages))
        return log

    def open(self, session_id: str) -> tuple["SessionLog", list[dict[str, Any]]]:
        path = self._path_for(session_id)
        messages, meta = self._read_session(path)
        log = SessionLog(
            store=self,
            session_id=session_id,
            path=path,
            created_at=meta.get("created_at") or _timestamp_from_path(path),
            title=meta.get("title") or "新会话",
        )
        log._logged_count = len(messages)
        log._signature = _prefix_signature(messages, len(messages))
        return log, messages

    def list_sessions(self) -> list[SessionInfo]:
        if not self._directory.is_dir():
            return []
        sessions: list[SessionInfo] = []
        for path in self._directory.glob("*.jsonl"):
            if not path.is_file():
                continue
            try:
                messages, meta = self._read_session(path)
                stat = path.stat()
            except (OSError, SessionError):
                continue
            sessions.append(
                SessionInfo(
                    id=meta.get("id") or path.stem,
                    title=meta.get("title") or "新会话",
                    created_at=meta.get("created_at") or _timestamp_from_path(path),
                    updated_at=meta.get("updated_at")
                    or datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    message_count=len(messages),
                    preview=_preview(messages),
                    path=path,
                )
            )
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def _path_for(self, session_id: str) -> Path:
        name = str(session_id).strip()
        if name.lower().endswith(".jsonl"):
            name = name[:-6]
        if not name or any(part in name for part in ("/", "\\", "..")):
            raise SessionError(f"无效的会话编号：{session_id!r}")
        path = self._directory / f"{name}.jsonl"
        try:
            path.resolve().relative_to(self._directory.resolve())
        except (OSError, ValueError) as exc:
            raise SessionError(f"无效的会话编号：{session_id!r}") from exc
        if not path.is_file():
            raise SessionError(f"会话不存在：{name}")
        return path

    @staticmethod
    def _read_session(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        meta: dict[str, Any] = {"id": path.stem}
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("type")
                    if kind == SESSION_HEADER_TYPE:
                        meta["id"] = event.get("id") or meta["id"]
                        meta["created_at"] = event.get("created_at")
                        if event.get("title"):
                            meta["title"] = event["title"]
                        meta["updated_at"] = event.get("ts")
                    elif kind == _EVENT_MESSAGE:
                        message = event.get("message")
                        if isinstance(message, dict):
                            messages.append(message)
                        meta["updated_at"] = event.get("ts") or meta.get("updated_at")
                    elif kind == _EVENT_SNAPSHOT:
                        snapshot = event.get("messages")
                        if isinstance(snapshot, list):
                            messages = [
                                item for item in snapshot if isinstance(item, dict)
                            ]
                        if event.get("title"):
                            meta["title"] = event["title"]
                        meta["updated_at"] = event.get("ts") or meta.get("updated_at")
                    elif kind == _EVENT_TITLE:
                        if event.get("title"):
                            meta["title"] = event["title"]
                        meta["updated_at"] = event.get("ts") or meta.get("updated_at")
                    elif kind == _EVENT_CHECKPOINT:
                        if event.get("title"):
                            meta["title"] = event["title"]
                        meta["updated_at"] = event.get("ts") or meta.get("updated_at")
        except OSError as exc:
            raise SessionError(f"无法读取会话 {path}：{exc}") from exc
        return messages, meta


class SessionLog:
    def __init__(
        self,
        store: SessionStore,
        session_id: str,
        path: Path,
        created_at: str,
        title: str,
    ) -> None:
        self._store = store
        self.id = session_id
        self.path = path
        self.created_at = created_at
        self.title = title
        self._logged_count = 0
        self._signature = ""

    def _append_event(self, event: dict[str, Any]) -> None:
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SessionError(f"写入会话日志失败：{exc}") from exc

    def sync(
        self,
        messages: Sequence[dict[str, Any]],
        title: str | None = None,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if title and title != self.title:
            self.title = title
            self._append_event({"type": _EVENT_TITLE, "ts": now, "title": title})

        prefix_changed = (
            len(messages) >= self._logged_count
            and _prefix_signature(messages, self._logged_count) != self._signature
        )
        if len(messages) < self._logged_count or prefix_changed:
            self._append_event(
                {
                    "type": _EVENT_SNAPSHOT,
                    "ts": now,
                    "title": self.title,
                    "messages": list(messages),
                }
            )
            self._logged_count = len(messages)
            self._signature = _prefix_signature(messages, len(messages))
            return

        for message in messages[self._logged_count :]:
            self._append_event({"type": _EVENT_MESSAGE, "ts": now, "message": message})
        self._logged_count = len(messages)
        self._signature = _prefix_signature(messages, len(messages))

    def save(
        self,
        messages: Sequence[dict[str, Any]],
        title: str | None = None,
        snapshot: bool = False,
    ) -> None:
        self.sync(messages, title)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if snapshot:
            self._append_event(
                {
                    "type": _EVENT_SNAPSHOT,
                    "ts": now,
                    "title": self.title,
                    "messages": list(messages),
                }
            )
            self._logged_count = len(messages)
            self._signature = _prefix_signature(messages, len(messages))
        self._append_event(
            {
                "type": _EVENT_CHECKPOINT,
                "ts": now,
                "title": self.title,
                "message_count": len(messages),
            }
        )


def _prefix_signature(
    messages: Sequence[dict[str, Any]], count: int
) -> str:
    if count <= 0:
        return ""
    payload = json.dumps(
        list(messages[:count]), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "system":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            if content.startswith("[AGENTS.md 项目约定]"):
                continue
            text = " ".join(content.split())
            return text[:60] + ("…" if len(text) > 60 else "")
    return "（空会话）"


def _timestamp_from_path(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""
