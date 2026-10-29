from __future__ import annotations

import os
from typing import Callable

from .config import AgentConfig
from .events import (
    AgentError,
    AgentEvent,
    AssistantCompleted,
    ContentDelta,
    RoundStarted,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
)
from .llm import LLMError, OpenAIChatClient
from .tools import ToolRegistry, create_default_registry


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
    "14. 使用 searchWeb 后，应基于搜索摘要归纳，并保留关键来源的标题或 URL，便于用户核对。"
)

EventSink = Callable[[AgentEvent], None]


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        registry: ToolRegistry | None = None,
        client: OpenAIChatClient | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._config = config
        self._registry = registry or create_default_registry(config.search)
        self._client = client or OpenAIChatClient(config.llm)
        self._system_prompt = system_prompt or self._build_system_prompt()
        self._history: list[dict] = [{"role": "system", "content": self._system_prompt}]
        self._requests = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def history(self) -> tuple[dict, ...]:
        return tuple(self._history)

    def _build_system_prompt(self) -> str:
        return f"{SYSTEM_PROMPT}\n当前工作目录：{os.getcwd()}"

    def clear(self) -> None:
        self._history = [{"role": "system", "content": self._system_prompt}]

    def close(self) -> None:
        self._client.close()

    def chat(self, user_input: str, emit: EventSink | None = None) -> None:
        text = user_input.strip()
        if not text:
            return
        sink: EventSink = emit or (lambda event: None)
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
            self._prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self._completion_tokens += int(usage.get("completion_tokens") or 0)
            self._total_tokens += int(usage.get("total_tokens") or 0)
            emit(
                UsageUpdated(
                    requests=self._requests,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                    total_tokens=self._total_tokens,
                )
            )

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
