from __future__ import annotations

import os
import re
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Footer,
    Header,
    OptionList,
    ProgressBar,
    RichLog,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from wAgent.core.agent import Agent
from wAgent.core.events import (
    AgentError,
    AgentEvent,
    AssistantCompleted,
    ContentDelta,
    RoundStarted,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
)
from wAgent.tui.help import HelpScreen


COMMAND_ITEMS = (
    ("/help", "打开使用帮助（F1）"),
    ("/clear", "清空对话上下文（Ctrl+L）"),
    ("/quit", "退出程序（Ctrl+Q）"),
    ("/exit", "退出程序"),
)
COMMAND_NAMES = {name for name, _ in COMMAND_ITEMS}

LABEL_WIDTH = 6
USER_LABEL = "你" + " " * (LABEL_WIDTH - 2)
ASSISTANT_LABEL = "助手" + " " * (LABEL_WIDTH - 4)
CONTINUATION = " " * LABEL_WIDTH

INLINE_TOKEN = re.compile(
    r"(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]\n]+\]\([^)\n]+\))"
)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
MAX_TABLE_CELL_WIDTH = 30


class PromptArea(TextArea):
    """多行输入框：Enter 发送，Shift+Enter / Ctrl+J 换行。"""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("shift+enter", "ctrl+j", "alt+enter"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            self.scroll_cursor_visible()
            return

        if event.key in ("enter", "ctrl+enter"):
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self.text))
            return

        if getattr(self.app, "_palette_visible", False) and event.key in (
            "up",
            "down",
            "tab",
            "escape",
        ):
            return

        await super()._on_key(event)


class WAgentApp(App[None]):
    TITLE = "wAgent"
    SUB_TITLE = "本地文件智能助手"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("f1", "help", "帮助"),
        ("ctrl+b", "toggle_sidebar", "侧边栏"),
        ("ctrl+q", "quit", "退出"),
        ("ctrl+l", "clear", "清空上下文"),
    ]

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        self._busy = False
        self._assistant_buffer = ""
        self._assistant_line_started = False
        self._assistant_in_code = False
        self._assistant_table: list[str] = []
        self._last_kind = "none"
        self._task_state = "就绪"
        self._max_rounds = agent.config.max_tool_rounds
        self._current_round = 0
        self._current_tool = "-"
        self._turn_tool_count = 0
        self._turn_start = 0.0
        self._turn_elapsed = 0.0
        self._turn_had_error = False
        self._usage_requests = 0
        self._usage_prompt_tokens = 0
        self._usage_completion_tokens = 0
        self._usage_total_tokens = 0
        self._palette_visible = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield RichLog(
                id="log",
                wrap=True,
                highlight=False,
                markup=False,
                min_width=20,
                max_lines=None,
                auto_scroll=True,
            )
            with VerticalScroll(id="sidebar"):
                yield Static("wAgent 控制台", id="sidebar-title")

                with Vertical(id="task-panel", classes="panel"):
                    yield Static("任务进度", classes="panel-title")
                    yield ProgressBar(
                        total=self._max_rounds,
                        show_eta=False,
                        show_percentage=False,
                        id="round-progress",
                    )
                    yield Static(id="task-info")

                with Vertical(id="usage-panel", classes="panel"):
                    yield Static("模型使用（会话累计）", classes="panel-title")
                    yield Static(id="usage-info")

                with Vertical(id="runtime-panel", classes="panel"):
                    yield Static("运行环境", classes="panel-title")
                    yield Static(id="runtime-info")

                with Vertical(id="tools-panel", classes="panel"):
                    yield Static(id="tools-title", classes="panel-title")
                    yield Static(id="tools-info")

                yield Static("F1 查看使用帮助", id="sidebar-help")

        yield Static(id="status")
        with Vertical(id="command-palette"):
            yield Static(
                "命令  Up/Down 选择 · Enter 执行 · Tab 补全 · Esc 关闭",
                id="command-palette-title",
            )
            yield OptionList(id="command-options", markup=False)
        yield PromptArea(
            placeholder="输入问题，Enter 发送 · Shift+Enter 换行 · 输入 / 查看命令",
            id="prompt",
            soft_wrap=True,
            show_line_numbers=False,
            highlight_cursor_line=False,
        )
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", RichLog)
        self._status = self.query_one("#status", Static)
        self._input = self.query_one("#prompt", PromptArea)
        self._task_info = self.query_one("#task-info", Static)
        self._usage_info = self.query_one("#usage-info", Static)
        self._runtime_info = self.query_one("#runtime-info", Static)
        self._tools_title = self.query_one("#tools-title", Static)
        self._tools_info = self.query_one("#tools-info", Static)
        self._round_progress = self.query_one("#round-progress", ProgressBar)
        self._palette = self.query_one("#command-palette", Vertical)
        self._command_options = self.query_one("#command-options", OptionList)
        self._palette.display = False

        self._default_status = f"就绪 | 模型：{self._agent.config.llm.model}"
        self._status.update(Text(self._default_status))
        self._render_task()
        self._render_usage()
        self._render_runtime()
        self._render_tools()
        self._write_welcome()
        self._input.focus()
        self.set_interval(0.5, self._tick)

    def _write_welcome(self) -> None:
        self._log.write(Text("wAgent · 本地文件智能助手", style="bold cyan"))
        self._log.write(
            Text("可以让我：查看目录、读取或编辑纯文本、创建/删除文件与目录、重命名等。")
        )
        self._log.write(
            Text("相对路径以当前工作目录为准；删除和重命名属于破坏性操作，请明确说明。")
        )
        self._log.write(
            Text("Enter 发送，Shift+Enter（或 Ctrl+J）换行；输入 / 查看命令，F1 查看帮助。")
        )
        self._log.write(Text(""))
        self._last_kind = "blank"

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area is self._input:
            self._update_command_palette(event.text_area.text)

    def on_key(self, event: events.Key) -> None:
        if not self._palette_visible:
            return
        if event.key == "down":
            self._command_options.action_cursor_down()
            event.stop()
            event.prevent_default()
        elif event.key == "up":
            self._command_options.action_cursor_up()
            event.stop()
            event.prevent_default()
        elif event.key == "tab":
            self._complete_command()
            event.stop()
            event.prevent_default()
        elif event.key == "escape":
            self._hide_command_palette()
            event.stop()
            event.prevent_default()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list is self._command_options and event.option.id:
            self._execute_command(str(event.option.id))
            event.stop()

    def _update_command_palette(self, value: str) -> None:
        raw = value or ""
        text = raw.strip()
        if (
            "\n" in raw
            or "\t" in raw
            or not text.startswith("/")
            or " " in text
        ):
            self._hide_command_palette()
            return

        matches = [
            (name, description)
            for name, description in COMMAND_ITEMS
            if name.startswith(text.lower())
        ]
        if not matches:
            self._hide_command_palette()
            return

        options = []
        for name, description in matches:
            prompt = Text()
            prompt.append(name, style="bold cyan")
            prompt.append("  ")
            prompt.append(description)
            options.append(Option(prompt, id=name))

        self._command_options.clear_options()
        self._command_options.add_options(options)
        self._command_options.highlighted = 0
        self._palette.display = True
        self._palette_visible = True

    def _hide_command_palette(self) -> None:
        self._palette.display = False
        self._palette_visible = False

    def _selected_command(self) -> str | None:
        option = self._command_options.highlighted_option
        return str(option.id) if option is not None and option.id else None

    def _complete_command(self) -> None:
        command = self._selected_command()
        if command:
            self._input.load_text(command)
            self._input.move_cursor((0, len(command)))

    def _clear_input(self) -> None:
        self._input.load_text("")
        self._input.move_cursor((0, 0))
        self._input.focus()

    def _execute_command(self, command: str) -> None:
        self._hide_command_palette()
        self._clear_input()
        if command == "/help":
            self.action_help()
        elif command == "/clear":
            self.action_clear()
            self._input.focus()
        elif command in ("/quit", "/exit"):
            self.exit()
        else:
            self._status.update(Text(f"未知命令：{command}", style="cyan"))

    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        text = event.value.strip()
        palette_command = self._selected_command() if self._palette_visible else None

        if palette_command:
            self._execute_command(palette_command)
            return
        if text in COMMAND_NAMES:
            self._execute_command(text)
            return
        if not text:
            self._hide_command_palette()
            self._clear_input()
            return
        if self._busy:
            self._status.update(Text("请等待当前回复完成", style="cyan"))
            return

        self._clear_input()
        self._start_turn(text)

    def action_help(self) -> None:
        self._hide_command_palette()
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss(None)
            return
        self.push_screen(HelpScreen())

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", VerticalScroll)
        sidebar.display = not sidebar.display
        state = "显示" if sidebar.display else "隐藏"
        self._status.update(Text(f"侧边栏已{state}"))

    def action_clear(self) -> None:
        if self._busy:
            self._status.update(Text("当前任务进行中，暂时无法清空上下文", style="cyan"))
            return
        self._hide_command_palette()
        self._agent.clear()
        self._assistant_buffer = ""
        self._assistant_line_started = False
        self._assistant_in_code = False
        self._assistant_table = []
        self._last_kind = "none"
        self._task_state = "就绪"
        self._current_round = 0
        self._current_tool = "-"
        self._turn_tool_count = 0
        self._turn_elapsed = 0.0
        self._round_progress.update(progress=0)
        self._render_task()
        self._log.clear()
        self._write_welcome()
        self._write_line("上下文已清空")
        self._clear_input()
        self._status.update(Text(self._default_status))

    def _start_turn(self, text: str) -> None:
        self._hide_command_palette()
        self._busy = True
        self._assistant_buffer = ""
        self._assistant_line_started = False
        self._assistant_in_code = False
        self._assistant_table = []
        self._task_state = "思考中"
        self._current_round = 0
        self._current_tool = "-"
        self._turn_tool_count = 0
        self._turn_start = time.monotonic()
        self._turn_elapsed = 0.0
        self._turn_had_error = False
        self._round_progress.update(progress=0)
        self._render_task()
        self._input.disabled = True
        self._status.update(Text("思考中...", style="cyan"))
        self._write_user_message(text)
        self.run_worker(lambda: self._run_agent(text), thread=True, exclusive=True)

    def _run_agent(self, text: str) -> None:
        try:
            self._agent.chat(text, self._emit_from_thread)
        except Exception as exc:
            self.call_from_thread(
                self._handle_event, AgentError(f"未处理的运行时异常：{exc}")
            )
        finally:
            self.call_from_thread(self._finish_turn)

    def _emit_from_thread(self, event: AgentEvent) -> None:
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: AgentEvent) -> None:
        if isinstance(event, ContentDelta):
            self._assistant_buffer += event.text
            self._drain_assistant_lines()
            return

        if isinstance(event, RoundStarted):
            self._current_round = event.round_number
            self._task_state = "等待模型响应"
            self._round_progress.update(progress=event.round_number)
            self._render_task()
            return

        if isinstance(event, UsageUpdated):
            self._usage_requests = event.requests
            self._usage_prompt_tokens = event.prompt_tokens
            self._usage_completion_tokens = event.completion_tokens
            self._usage_total_tokens = event.total_tokens
            self._render_usage()
            return

        if isinstance(event, AssistantCompleted):
            self._flush_assistant()
            self._assistant_line_started = False
            self._task_state = "整理回复"
            self._render_task()
            return

        if isinstance(event, ToolStarted):
            self._flush_assistant()
            self._assistant_line_started = False
            self._current_tool = event.name
            self._turn_tool_count += 1
            self._task_state = "执行工具"
            self._render_task()
            self._separate()
            tool_line = Text()
            tool_line.append("[工具] ", style="bold")
            tool_line.append(event.name, style="bold cyan")
            self._log.write(tool_line)
            self._last_kind = "tool"
            self._write_prefixed("  参数：", event.arguments)
            return

        if isinstance(event, ToolFinished):
            self._current_tool = event.name if event.ok else f"{event.name}（失败）"
            self._task_state = "等待模型继续"
            self._render_task()
            style = "" if event.ok else "bold red"
            self._write_prefixed("  结果：", event.content, style=style)
            self._status.update(Text("工具执行完成，继续思考...", style="cyan"))
            return

        if isinstance(event, AgentError):
            self._turn_had_error = True
            self._flush_assistant()
            self._assistant_line_started = False
            self._task_state = "出错"
            self._current_tool = "-"
            self._render_task()
            self._separate()
            self._write_wrapped(
                "错误：",
                " " * 6,
                Text(event.message),
                prefix_style="bold red",
                body_style="bold red",
            )
            self._last_kind = "error"

    def _finish_turn(self) -> None:
        self._flush_assistant()
        self._assistant_line_started = False
        if self._turn_start:
            self._turn_elapsed = time.monotonic() - self._turn_start
        self._busy = False
        if self._turn_had_error:
            self._task_state = "出错"
        elif self._current_round == 0:
            self._task_state = "就绪"
        else:
            self._task_state = "已完成"
        self._current_tool = "-"
        self._render_task()
        self._input.disabled = False
        self._input.focus()
        self._status.update(Text(self._default_status))

    def _tick(self) -> None:
        if self._busy:
            self._render_task()

    def _render_task(self) -> None:
        if not hasattr(self, "_task_info"):
            return
        if self._busy and self._turn_start:
            elapsed = time.monotonic() - self._turn_start
        else:
            elapsed = self._turn_elapsed
        self._task_info.update(
            self._format_lines(
                [
                    ("状态", self._task_state),
                    ("轮次", f"{self._current_round} / {self._max_rounds}"),
                    ("本回合工具", f"{self._turn_tool_count} 次"),
                    ("当前工具", self._current_tool),
                    ("耗时", f"{elapsed:.1f} 秒"),
                    ("上下文", f"{len(self._agent.history)} 条消息"),
                ]
            )
        )

    def _render_usage(self) -> None:
        if not hasattr(self, "_usage_info"):
            return
        self._usage_info.update(
            self._format_lines(
                [
                    ("请求次数", f"{self._usage_requests} 次"),
                    ("输入 tokens", f"{self._usage_prompt_tokens:,}"),
                    ("输出 tokens", f"{self._usage_completion_tokens:,}"),
                    ("合计 tokens", f"{self._usage_total_tokens:,}"),
                ]
            )
        )

    def _render_runtime(self) -> None:
        if not hasattr(self, "_runtime_info"):
            return
        config = self._agent.config
        source = str(config.source) if config.source else "未知"
        self._runtime_info.update(
            self._format_lines(
                [
                    ("模型", config.llm.model),
                    ("工作目录", os.getcwd()),
                    ("接口", config.llm.base_url),
                    ("配置文件", source),
                    ("请求超时", f"{config.llm.timeout:g} 秒"),
                    ("最大轮次", str(config.max_tool_rounds)),
                ]
            )
        )

    def _render_tools(self) -> None:
        if not hasattr(self, "_tools_info"):
            return
        names = self._agent.registry.names
        self._tools_title.update(f"可用工具（{len(names)}）")
        text = Text()
        for index, name in enumerate(names):
            if index:
                text.append("\n")
            text.append("- ", style="cyan")
            text.append(name)
        self._tools_info.update(text)

    @staticmethod
    def _format_lines(lines: list[tuple[str, str]]) -> Text:
        text = Text()
        for index, (label, value) in enumerate(lines):
            if index:
                text.append("\n")
            text.append(f"{label}：", style="bold")
            text.append(str(value))
        return text

    def _log_content_width(self) -> int:
        try:
            width = self._log.scrollable_content_region.width
        except Exception:
            width = 0
        if width <= 0:
            width = max(20, self._log.size.width - 4)
        return width

    def _separate(self) -> None:
        if self._last_kind in ("none", "blank"):
            return
        self._log.write(Text(""))
        self._last_kind = "blank"

    def _write_wrapped(
        self,
        prefix: str,
        continuation: str,
        body: Text,
        prefix_style: str = "",
        body_style: str = "",
    ) -> None:
        if body_style:
            body.stylize(body_style)
        if not body.plain:
            self._log.write(Text(""))
            return

        available = max(12, self._log_content_width() - Text(prefix).cell_len)
        wrapped = body.wrap(self.app.console, available)
        for index, line in enumerate(wrapped):
            output = Text()
            output.append(prefix if index == 0 else continuation, style=prefix_style)
            output.append_text(line)
            self._log.write(output)

    def _write_user_message(self, text: str) -> None:
        self._separate()
        for index, line in enumerate(text.split("\n")):
            prefix = USER_LABEL if index == 0 else CONTINUATION
            self._write_wrapped(
                prefix,
                CONTINUATION,
                Text(line),
                prefix_style="bold",
            )
        self._last_kind = "user"

    def _drain_assistant_lines(self) -> None:
        while "\n" in self._assistant_buffer:
            line, self._assistant_buffer = self._assistant_buffer.split("\n", 1)
            self._write_assistant_line(line)

    def _flush_assistant(self) -> None:
        if self._assistant_buffer:
            self._write_assistant_line(self._assistant_buffer)
            self._assistant_buffer = ""
        self._flush_assistant_table()

    @staticmethod
    def _is_table_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

    @staticmethod
    def _parse_table_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    def _flush_assistant_table(self) -> None:
        if not self._assistant_table:
            return
        raw_rows = self._assistant_table
        self._assistant_table = []
        rows = [self._parse_table_row(row) for row in raw_rows]
        rows = [row for row in rows if any(row)]
        if not rows:
            return

        separator_index = next(
            (
                index
                for index, row in enumerate(rows)
                if row and all(TABLE_SEPARATOR.match(cell) for cell in row)
            ),
            None,
        )
        has_header = separator_index == 1
        if separator_index is not None:
            del rows[separator_index]

        columns = max(len(row) for row in rows)
        rows = [row + [""] * (columns - len(row)) for row in rows]
        widths = [
            min(MAX_TABLE_CELL_WIDTH, max(Text(row[index]).cell_len for row in rows))
            for index in range(columns)
        ]
        widths = [max(3, width) for width in widths]

        available = max(20, self._log_content_width() - LABEL_WIDTH)
        while sum(widths) + 3 * (columns - 1) > available and max(widths) > 4:
            widest = max(range(columns), key=lambda index: widths[index])
            widths[widest] -= 1

        header = rows[0] if has_header else None
        data_rows = rows[1:] if has_header else rows
        if header is not None:
            self._write_assistant_raw(self._render_table_row(header, widths, "bold cyan"))
            self._write_assistant_raw(self._render_table_separator(widths))
        for row in data_rows:
            self._write_assistant_raw(self._render_table_row(row, widths))

    def _render_table_row(self, cells: list[str], widths: list[int], style: str = "") -> Text:
        line_text = Text()
        for index, width in enumerate(widths):
            if index:
                line_text.append(" │ ")
            cell_text = self._format_inline(cells[index] if index < len(cells) else "")
            cell_text.truncate(width, overflow="ellipsis")
            line_text.append_text(cell_text)
            line_text.append(" " * max(0, width - cell_text.cell_len))
        if style:
            line_text.stylize(style)
        return line_text

    @staticmethod
    def _render_table_separator(widths: list[int]) -> Text:
        line_text = Text()
        for index, width in enumerate(widths):
            if index:
                line_text.append("─┼─")
            line_text.append("─" * width)
        return line_text

    def _write_assistant_raw(self, body: Text) -> None:
        if not body.plain:
            self._log.write(Text(""))
            return
        if not self._assistant_line_started:
            self._separate()
            prefix = ASSISTANT_LABEL
            self._assistant_line_started = True
        else:
            prefix = CONTINUATION
        output = Text()
        output.append(prefix, style="bold")
        output.append_text(body)
        self._log.write(output)
        self._last_kind = "assistant"

    def _format_inline(self, text: str, style: str = "") -> Text:
        result = Text(style=style)
        position = 0
        for match in INLINE_TOKEN.finditer(text):
            if match.start() > position:
                result.append(text[position : match.start()], style=style)
            token = match.group(0)
            if token.startswith("`"):
                result.append(token[1:-1], style="cyan")
            elif token.startswith("**"):
                result.append(token[2:-2], style="bold cyan")
            elif token.startswith("__"):
                result.append(token[2:-2], style="bold cyan")
            else:
                label, _, url = token[1:-1].partition("](")
                result.append(label, style="underline cyan")
                result.append(f"（{url.rstrip(')')}）")
            position = match.end()
        if position < len(text):
            result.append(text[position:], style=style)
        return result

    def _format_assistant_line(self, line: str) -> Text | None:
        stripped = line.rstrip("\r")
        if stripped.strip().startswith("```"):
            self._assistant_in_code = not self._assistant_in_code
            return None

        if self._assistant_in_code:
            return Text(stripped)

        if not stripped.strip():
            return Text("")

        heading = HEADING.match(stripped)
        if heading:
            body = self._format_inline(heading.group(2))
            body.stylize("bold cyan")
            return body

        if RULE.match(stripped):
            return Text("─" * 24)

        bullet = BULLET.match(stripped)
        if bullet:
            line_text = Text()
            line_text.append(bullet.group(1) + "• ", style="cyan")
            line_text.append_text(self._format_inline(bullet.group(2)))
            return line_text

        ordered = ORDERED.match(stripped)
        if ordered:
            line_text = Text()
            line_text.append(ordered.group(1) + ordered.group(2) + " ", style="cyan")
            line_text.append_text(self._format_inline(ordered.group(3)))
            return line_text

        quote = QUOTE.match(stripped)
        if quote:
            return self._format_inline(quote.group(1), style="italic")

        return self._format_inline(stripped)

    def _write_assistant_line(self, line: str) -> None:
        if not self._assistant_in_code and self._is_table_line(line):
            self._assistant_table.append(line)
            return
        if self._assistant_table:
            self._flush_assistant_table()

        body = self._format_assistant_line(line)
        if body is None:
            return
        if not body.plain:
            self._log.write(Text(""))
            return

        if not self._assistant_line_started:
            self._separate()
            prefix = ASSISTANT_LABEL
            self._assistant_line_started = True
        else:
            prefix = CONTINUATION

        self._write_wrapped(
            prefix,
            CONTINUATION,
            body,
            prefix_style="bold",
        )
        self._last_kind = "assistant"

    def _write_prefixed(self, prefix: str, content: str, style: str = "") -> None:
        lines = str(content).splitlines() or [""]
        continuation = " " * Text(prefix).cell_len
        for index, line in enumerate(lines):
            self._write_wrapped(
                prefix if index == 0 else continuation,
                continuation,
                Text(line),
                prefix_style="bold",
                body_style=style,
            )

    def _write_line(self, text: str, style: str = "") -> None:
        self._log.write(Text(text, style=style))
        if text:
            self._last_kind = "notice"
