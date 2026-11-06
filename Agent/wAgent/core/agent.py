from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .config import AgentConfig
from .context import (
    COMPACT_SUMMARY_MIN_TOKENS,
    COMPACTION_PROMPT,
    DEFAULT_CONTEXT_WINDOW,
    ContextError,
    ContextUsage,
    archive_messages,
    build_archive_note,
    clamp_text_to_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    make_usage,
    render_history_for_summary,
    render_transcript,
)
from .events import (
    AgentError,
    AgentEvent,
    AssistantCompleted,
    CompactionFailed,
    ContentDelta,
    ContextArchived,
    ContextCompacted,
    ContextUsageUpdated,
    RoundStarted,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
)
from .llm import LLMError, OpenAIChatClient
from .mcp import MCPClientManager, load_mcp_config
from .skills import SkillCatalog
from .tools import ContextTools, SkillTools, ToolRegistry, create_default_registry


SYSTEM_PROMPT = (
    "你是一个具备完整上下文记忆、并支持本地文件与网页读取工具调用的对话助手，严格遵守以下规则：\n"
    "1. 基于全部历史上下文理解用户当前输入，禁止脱离对话语境单独作答；\n"
    "2. 用户在历史中已经提供过的信息，不得重复询问；\n"
    "3. 当用户使用指代性表述时，准确对应历史内容，保持话题连贯；\n"
    "4. 涉及本地文件或目录的操作，必须调用对应的工具完成，禁止自行编造结果；\n"
    "5. 用户提供网页 URL 或要求读取网页正文时，必须调用 fetchWeb；需要实时信息、新闻或最新资料时，优先调用 searchWeb；禁止编造搜索结果或网页内容；\n"
    "6. 需要执行本地命令行程序时，必须调用 runCli，并根据返回的标准输出、标准错误和退出码判断结果，禁止编造执行输出；\n"
    "7. 读取或编辑文件内容时，只支持纯文本格式文件；遇到二进制文件应如实告知用户；\n"
    "8. 删除目录、删除文件、重命名属于破坏性操作，执行前先确认用户意图明确；\n"
    "9. 用户给出的相对路径，一律相对于当前工作目录解析；\n"
    "10. 拿到工具返回结果后，用自然流畅的语言向用户转述；\n"
    "11. 回复保持简洁，除非用户要求更多细节；\n"
    "12. 回复使用规范的 Markdown：标题用 ###，要点用 - 列表，代码或命令用 ``` 代码块；\n"
    "13. 先给结论，再给必要说明；不要输出大量空行、重复内容或无意义的客套话；\n"
    "14. 使用 searchWeb 后，应基于搜索摘要归纳，并保留关键来源的标题或 URL，便于用户核对；\n"
    "15. 描述以 [MCP:服务器名] 开头的工具来自外部 MCP Server，调用时严格按工具的 JSON Schema 传参，并把执行结果如实转述给用户；\n"
    "16. 当上下文压缩摘要缺少某些历史细节时，调用 recallContext 工具检索 .agents/context 中的原始归档，不要凭空猜测。"
)

EventSink = Callable[[AgentEvent], None]
AGENTS_MD_MARKER = "[AGENTS.md 项目约定]"


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        registry: ToolRegistry | None = None,
        client: OpenAIChatClient | None = None,
        system_prompt: str | None = None,
        skill_catalog: SkillCatalog | None = None,
    ) -> None:
        self._config = config
        self._skills = skill_catalog or SkillCatalog.discover(os.getcwd())
        if registry is None:
            self._registry = create_default_registry(
                config.search,
                self._skills,
                config.tools,
                config.context_dir,
            )
        else:
            self._registry = registry
            extra_tools = (
                *SkillTools(self._skills, config.tools).tools(),
                *ContextTools(config.tools, config.context_dir).tools(),
            )
            for tool in extra_tools:
                if tool.name not in registry:
                    registry.register(tool)
        self._mcp = self._setup_mcp()
        self._client = client or OpenAIChatClient(config.llm)
        self._system_prompt = system_prompt or self._build_system_prompt()
        self._history: list[dict] = [{"role": "system", "content": self._system_prompt}]
        self._requests = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._context_paused = False
        self._compacting = False
        self._agents_md_injected = False

    @property
    def context_paused(self) -> bool:
        return self._context_paused

    @property
    def compacting(self) -> bool:
        return self._compacting

    def context_usage(self, used_tokens: int | None = None) -> ContextUsage:
        window = self._config.context_window or DEFAULT_CONTEXT_WINDOW
        if used_tokens is None:
            used_tokens = estimate_messages_tokens(self._history)
            estimated = True
        else:
            estimated = False
        return make_usage(
            used_tokens=used_tokens,
            window_tokens=window,
            message_count=len(self._history),
            estimated=estimated,
            is_default_window=self._config.context_window is None,
            warning_ratio=self._config.context_warning_ratio,
        )

    def _publish_context_usage(
        self, emit: EventSink, used_tokens: int | None = None
    ) -> ContextUsage:
        usage = self.context_usage(used_tokens)
        if usage.warning:
            self._context_paused = True
        emit(
            ContextUsageUpdated(
                used_tokens=usage.used_tokens,
                window_tokens=usage.window_tokens,
                percent=usage.percent,
                is_default_window=usage.is_default_window,
                warning=usage.warning,
                message_count=usage.message_count,
                estimated=usage.estimated,
            )
        )
        return usage

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def skills(self) -> SkillCatalog:
        return self._skills

    @property
    def mcp(self) -> MCPClientManager:
        return self._mcp

    @property
    def mcp_started(self) -> bool:
        return self._mcp_started

    @property
    def history(self) -> tuple[dict, ...]:
        return tuple(self._history)

    def _setup_mcp(self) -> MCPClientManager:
        configs, warnings = load_mcp_config(
            os.getcwd(), default_call_timeout=self._config.tools.mcp_call_timeout
        )
        self._mcp_started = False
        return MCPClientManager(
            configs,
            local_tool_names=self._registry.names,
            warnings=warnings,
            connect_timeout=self._config.tools.mcp_connect_timeout,
        )

    def start_mcp(self) -> None:
        """在后台线程中调用；连接完成后把 MCP 工具注册进注册表。"""
        if self._mcp_started:
            return
        self._mcp_started = True
        if not self._mcp.configs:
            return

        try:
            self._mcp.start()
        except BaseException as exc:
            self._mcp.add_warning(f"MCP 客户端启动失败：{exc}")
            return
        for tool in self._mcp.tools:
            if tool.name in self._registry:
                self._mcp.add_warning(f"MCP 工具名称冲突，已跳过：{tool.name}")
                continue
            self._registry.register(tool)

    def _build_system_prompt(self) -> str:
        prompt = f"{SYSTEM_PROMPT}\n当前工作目录：{os.getcwd()}"
        prompt = prompt.replace(".agents/context", self._config.context_dir)
        skill_prompt = self._skills.prompt()
        if skill_prompt:
            prompt = f"{prompt}\n\n{skill_prompt}"
        return prompt

    def load_agents_md(self) -> Path | None:
        """把项目 AGENTS.md 作为一条消息注入一次，后续轮次直接复用。"""
        if self._agents_md_injected:
            return None
        path = Path.cwd() / self._config.agents_md_file
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise ContextError(f"读取 {path} 失败：{exc}") from exc
        if not content:
            return None
        self._history.append(
            {
                "role": "user",
                "content": (
                    f"{AGENTS_MD_MARKER}\n"
                    "以下是项目 AGENTS.md 的完整内容，请在本次会话后续所有工作中持续遵守。\n\n"
                    f"{content}"
                ),
            }
        )
        self._agents_md_injected = True
        return path

    @staticmethod
    def is_agents_md_message(message: dict) -> bool:
        content = message.get("content")
        return isinstance(content, str) and content.startswith(AGENTS_MD_MARKER)

    def restore_history(self, messages: list[dict]) -> None:
        restored = [dict(message) for message in messages if isinstance(message, dict)]
        if not restored or restored[0].get("role") != "system":
            restored.insert(0, {"role": "system", "content": self._system_prompt})
        else:
            restored[0] = {"role": "system", "content": self._system_prompt}
        self._history = restored
        self._context_paused = False
        self._agents_md_injected = any(
            self.is_agents_md_message(message) for message in self._history
        )
        if not self._agents_md_injected:
            self.load_agents_md()

    def clear(self) -> None:
        self._history = [{"role": "system", "content": self._system_prompt}]
        self._context_paused = False
        self._agents_md_injected = False
        self.load_agents_md()

    def close(self) -> None:
        self._mcp.close()
        self._client.close()

    def chat(self, user_input: str, emit: EventSink | None = None) -> None:
        text = user_input.strip()
        if not text:
            return
        sink: EventSink = emit or (lambda event: None)
        try:
            self.load_agents_md()
        except ContextError as exc:
            sink(AgentError(str(exc)))
            return
        if self._compacting:
            sink(AgentError("正在压缩上下文，暂时无法处理新的任务"))
            return
        if self._context_paused:
            ratio = f"{self._config.context_warning_ratio * 100:g}%"
            sink(
                AgentError(
                    f"上下文使用量已达到 {ratio}，请先执行 /compact 压缩上下文"
                )
            )
            return
        checkpoint = len(self._history)
        self._history.append({"role": "user", "content": text})
        try:
            self._run_turns(sink)
        except LLMError as exc:
            del self._history[checkpoint:]
            sink(AgentError(str(exc)))

    def _run_turns(self, emit: EventSink) -> None:
        for round_number in range(1, self._config.max_tool_rounds + 1):
            emit(RoundStarted(round_number, self._config.max_tool_rounds))
            result = self._client.stream_chat(
                self._history,
                self._registry.schemas(),
                on_content=lambda chunk: emit(ContentDelta(chunk)),
            )

            self._requests += 1
            usage = result.usage or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens
            self._total_tokens += int(usage.get("total_tokens") or 0)
            emit(
                UsageUpdated(
                    requests=self._requests,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                    total_tokens=self._total_tokens,
                )
            )

            if prompt_tokens > 0:
                self._publish_context_usage(emit, prompt_tokens + completion_tokens)
            else:
                self._publish_context_usage(emit)

            if result.content:
                emit(AssistantCompleted(result.content))

            if not result.tool_calls:
                self._history.append({"role": "assistant", "content": result.content or ""})
                return

            self._history.append(
                {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": result.tool_calls,
                }
            )

            for tool_call in result.tool_calls:
                function = tool_call.get("function") or {}
                name = function.get("name", "")
                arguments = function.get("arguments", "") or "{}"
                emit(ToolStarted(name, arguments))
                tool_result = self._registry.execute(name, arguments)
                emit(ToolFinished(name, tool_result.content, tool_result.ok))
                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": tool_result.content,
                    }
                )

        emit(
            AgentError(
                f"已达到最大工具调用轮次（{self._config.max_tool_rounds}），本次任务已中止"
            )
        )

    def compact(self, emit: EventSink | None = None) -> None:
        sink: EventSink = emit or (lambda event: None)
        if self._compacting:
            sink(CompactionFailed("上下文压缩正在进行中，请稍候"))
            return
        if len(self._history) <= 1:
            sink(CompactionFailed("当前没有可以压缩的对话上下文"))
            return

        self._compacting = True
        try:
            try:
                archive = archive_messages(self._history, self._config.context_dir)
            except ContextError as exc:
                sink(CompactionFailed(f"原始上下文保存失败：{exc}"))
                return

            sink(ContextArchived(archive_id=archive.id, path=str(archive.path)))

            try:
                transcript = render_history_for_summary(self._history)
                result = self._client.stream_chat(
                    [
                        {"role": "system", "content": COMPACTION_PROMPT},
                        {"role": "user", "content": transcript},
                    ],
                    tools=None,
                    max_tokens=self._config.compact_max_tokens,
                )
                summary = (result.content or "").strip()
                if not summary:
                    raise ContextError("模型未返回有效的上下文摘要")

                note = build_archive_note(archive.id, archive.created_at)
                summary_budget = max(
                    COMPACT_SUMMARY_MIN_TOKENS,
                    self._config.compact_summary_tokens - estimate_tokens(note),
                )
                summary = clamp_text_to_tokens(summary, summary_budget)
                summary_with_note = f"{summary}\n\n{note}"
                original_text = render_transcript(self._history)

                self._history = [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "assistant",
                        "content": (
                            "以下是此前对话的上下文压缩摘要，供后续工作参考。\n\n"
                            f"{summary_with_note}"
                        ),
                    },
                ]
                self._context_paused = False

                sink(
                    ContextCompacted(
                        archive_id=archive.id,
                        original_text=original_text,
                        summary=summary_with_note,
                        note=note,
                    )
                )
                self._publish_context_usage(
                    sink, estimate_messages_tokens(self._history)
                )
            except (LLMError, ContextError) as exc:
                sink(CompactionFailed(str(exc), archive_id=archive.id))
            except Exception as exc:
                sink(
                    CompactionFailed(
                        f"压缩上下文时发生异常：{exc}", archive_id=archive.id
                    )
                )
        finally:
            self._compacting = False
