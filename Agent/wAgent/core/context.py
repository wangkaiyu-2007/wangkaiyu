from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


CONTEXT_DIR_NAME = ".agents/context"
DEFAULT_CONTEXT_WINDOW = 128 * 1024
CONTEXT_WARNING_RATIO = 0.60
COMPACT_SUMMARY_TOKENS = 5000
COMPACT_SUMMARY_MIN_TOKENS = 500


class ContextError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ContextArchive:
    id: str
    path: Path
    created_at: str


@dataclass(frozen=True, slots=True)
class ContextUsage:
    used_tokens: int
    window_tokens: int
    percent: float
    is_default_window: bool
    warning: bool
    message_count: int
    estimated: bool


COMPACTION_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


def context_directory(base: Path | str | None = None) -> Path:
    root = Path(base) if base is not None else Path.cwd()
    return root / CONTEXT_DIR_NAME


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：ASCII 约 4 字符 1 token，其他字符约 1 字符 1 token。"""
    if not text:
        return 0
    ascii_count = sum(1 for character in text if ord(character) < 128)
    other_count = len(text) - ascii_count
    return max(1, int(math.ceil(ascii_count / 4 + other_count)))


def estimate_message_tokens(message: dict[str, Any]) -> int:
    total = 8
    content = message.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif content is not None:
        total += estimate_tokens(json.dumps(content, ensure_ascii=False))
    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
    tool_call_id = message.get("tool_call_id")
    if tool_call_id:
        total += estimate_tokens(str(tool_call_id))
    name = message.get("name")
    if name:
        total += estimate_tokens(str(name))
    return total


def estimate_messages_tokens(messages: Iterable[dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def make_usage(
    used_tokens: int,
    window_tokens: int,
    message_count: int,
    estimated: bool,
    is_default_window: bool,
    warning_ratio: float = CONTEXT_WARNING_RATIO,
) -> ContextUsage:
    window = window_tokens if window_tokens > 0 else DEFAULT_CONTEXT_WINDOW
    percent = used_tokens / window * 100 if window else 0.0
    return ContextUsage(
        used_tokens=used_tokens,
        window_tokens=window,
        percent=percent,
        is_default_window=is_default_window,
        warning=percent >= warning_ratio * 100,
        message_count=message_count,
        estimated=estimated,
    )


def archive_messages(
    messages: Sequence[dict[str, Any]],
    directory: Path | str | None = None,
) -> ContextArchive:
    """把完整原始上下文写入 .agents/context/<编号>.jsonl。"""
    target_dir = Path(directory) if directory is not None else context_directory()
    now = datetime.now()
    archive_id = now.strftime("%Y%m%d-%H%M%S")
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ContextError(f"无法创建上下文归档目录 {target_dir}：{exc}") from exc

    path = target_dir / f"{archive_id}.jsonl"
    suffix = 2
    base_id = archive_id
    while path.exists():
        archive_id = f"{base_id}-{suffix}"
        path = target_dir / f"{archive_id}.jsonl"
        suffix += 1

    temporary = path.with_suffix(".jsonl.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for message in messages:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.stat().st_size <= 0:
            raise ContextError("写入的归档文件为空")
        os.replace(temporary, path)
    except (OSError, ContextError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, ContextError):
            raise
        raise ContextError(f"保存原始上下文失败：{exc}") from exc

    if not path.is_file() or path.stat().st_size <= 0:
        raise ContextError(f"原始上下文保存失败，归档文件不存在或为空：{path}")

    return ContextArchive(id=archive_id, path=path, created_at=created_at)


def build_archive_note(archive_id: str, created_at: str) -> str:
    return (
        f"此前上下文已于 {created_at} 完成压缩，原始上下文保存在编号为 "
        f"{archive_id} 的归档文件中。如需查找历史信息，请使用 recallContext 工具。"
    )


def render_history_for_summary(messages: Sequence[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role", "unknown"))
        parts = [f"### 消息 {index}（role={role}）"]
        content = message.get("content")
        if isinstance(content, str) and content:
            parts.append(content)
        elif content is not None:
            parts.append(json.dumps(content, ensure_ascii=False))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            parts.append(
                "工具调用：\n"
                + json.dumps(tool_calls, ensure_ascii=False, indent=2)
            )
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            parts.append(f"tool_call_id：{tool_call_id}")
        name = message.get("name")
        if name:
            parts.append(f"name：{name}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def render_transcript(messages: Sequence[dict[str, Any]]) -> str:
    return render_history_for_summary(messages)


def clamp_text_to_tokens(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    current_tokens = estimate_tokens(text)
    cut = max(200, int(len(text) * max_tokens / current_tokens * 0.95))
    while cut > 200 and estimate_tokens(text[:cut]) > max_tokens:
        cut = int(cut * 0.9)
    return text[:cut].rstrip() + "\n\n……（摘要过长，已截断）"


def list_archive_files(directory: Path | str | None = None) -> list[Path]:
    target_dir = Path(directory) if directory is not None else context_directory()
    if not target_dir.is_dir():
        return []
    return sorted(
        (path for path in target_dir.glob("*.jsonl") if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
