from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import ToolConfig
from ..context import list_archive_files
from .base import Tool


MAX_MATCHES = 8
MAX_SNIPPET_CHARS = 420
MAX_RESULT_CHARS = 6000
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class ContextTools:
    def __init__(
        self,
        config: ToolConfig | None = None,
        directory: str | None = None,
    ) -> None:
        config = config or ToolConfig()
        self._max_matches = config.context_search_max_matches
        self._max_snippet_chars = config.context_search_max_snippet_chars
        self._max_result_chars = config.context_search_max_result_chars
        self._directory = directory

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="recallContext",
                description=(
                    "检索此前被压缩归档的原始上下文。id 可选，用于指定归档编号；"
                    "text 必填，是要查找的关键词或文本。未提供 id 时会搜索所有归档。"
                    "返回匹配片段、归档编号和消息位置。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "可选的上下文归档编号，例如 20261022-153000",
                        },
                        "text": {
                            "type": "string",
                            "description": "要检索的关键词或文本内容",
                        },
                    },
                    "required": ["text"],
                },
                handler=self.recall_context,
            ),
        )

    def recall_context(self, text: str, id: str = "") -> str:
        keyword = self._prepare_keyword(text)
        archive_id = self._prepare_id(id)

        if archive_id:
            path = self._archive_path(archive_id)
            if path is None:
                available = self._available_ids()
                hint = f"可用归档：{available}" if available else "当前没有历史归档。"
                return f"未找到指定归档：{archive_id}。{hint}"
            files = [path]
        else:
            files = list_archive_files(self._directory)
            if not files:
                return "当前没有历史上下文归档，暂时无法检索。"

        matches: list[tuple[int, str, int, str, str]] = []
        for path in files:
            current_id = path.stem
            for line_number, message in self._iter_messages(path):
                count, content, snippet = self._match_message(message, keyword)
                if count <= 0:
                    continue
                matches.append((count, current_id, line_number, content, snippet))

        if not matches:
            scope = f"归档 {archive_id}" if archive_id else "历史归档"
            return f"在{scope}中未找到包含“{keyword}”的内容。"

        matches.sort(key=lambda item: (-item[0], item[1], item[2]), reverse=False)
        selected = matches[: self._max_matches]

        lines = [
            f"检索关键词：{keyword}",
            f"命中片段：{len(matches)} 处（显示前 {len(selected)} 处）",
            "",
        ]
        for index, (count, current_id, line_number, content, snippet) in enumerate(
            selected, start=1
        ):
            lines.append(
                f"[{index}] 归档 {current_id} · 第 {line_number} 条消息 · 匹配 {count} 次"
            )
            lines.append(f"角色：{content}")
            lines.append(snippet)
            lines.append("")

        result = "\n".join(lines).strip()
        if len(result) > self._max_result_chars:
            result = result[: self._max_result_chars] + "\n\n[检索结果过长，已截断]"
        return result

    @staticmethod
    def _prepare_keyword(text: Any) -> str:
        if not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        keyword = text.strip()
        if not keyword:
            raise ValueError("text 不能为空")
        return keyword

    @staticmethod
    def _prepare_id(raw: Any) -> str:
        if raw is None:
            return ""
        value = str(raw).strip()
        if not value:
            return ""
        if value.lower().endswith(".jsonl"):
            value = value[:-6]
        if not _ID_PATTERN.fullmatch(value) or value in (".", ".."):
            raise ValueError("id 只能包含字母、数字、点、下划线或连字符")
        return value

    def _archive_path(self, archive_id: str) -> Path | None:
        import os

        directory = (
            Path(self._directory)
            if self._directory
            else Path(os.getcwd()) / ".agents" / "context"
        )
        path = directory / f"{archive_id}.jsonl"
        try:
            resolved = path.resolve()
            root = directory.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    def _available_ids(self) -> str:
        files = list_archive_files(self._directory)
        return "、".join(path.stem for path in files[:20])

    @staticmethod
    def _iter_messages(path: Path):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(message, dict):
                        yield line_number, message
        except OSError:
            return

    def _match_message(
        self, message: dict[str, Any], keyword: str
    ) -> tuple[int, str, str]:
        role = str(message.get("role", "unknown"))
        content = message.get("content")
        content_text = content if isinstance(content, str) else ""
        tool_calls = message.get("tool_calls")
        tool_text = (
            json.dumps(tool_calls, ensure_ascii=False) if tool_calls else ""
        )
        tool_call_id = str(message.get("tool_call_id") or "")

        searchable = "\n".join(
            part for part in (content_text, tool_text, tool_call_id) if part
        )
        count = searchable.casefold().count(keyword.casefold())
        if count <= 0:
            return 0, role, ""

        source = content_text or tool_text or tool_call_id
        return count, role, self._snippet(source, keyword)

    def _snippet(self, text: str, keyword: str) -> str:
        lowered = text.casefold()
        position = lowered.find(keyword.casefold())
        if position < 0:
            position = 0
        half = self._max_snippet_chars // 2
        start = max(0, position - half)
        end = min(len(text), start + self._max_snippet_chars)
        snippet = text[start:end]
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        return "片段：" + snippet
