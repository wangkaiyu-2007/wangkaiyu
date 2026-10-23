from __future__ import annotations

import os
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Input,
    OptionList,
    ProgressBar,
    RichLog,
    Static,
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
        yield Input(
            placeholder="输入问题后按 Enter；输入 / 查看命令",
            id="prompt",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", RichLog)
        self._status = self.query_one("#status", Static)
        self._input = self.query_one("#prompt", Input)
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
        self._status.update(Text(self._default_status, style="dim"))
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
            Text(
                "可以让我：查看目录、读取或编辑纯文本、创建/删除文件与目录、重命名等。",
                style="dim",
            )
        )
        self._log.write(
            Text(
                "相对路径以当前工作目录为准；删除和重命名属于破坏性操作，请明确说明。",
                style="dim",
            )
        )
        self._log.write(Text("输入 / 可查看命令列表，输入 /help 或按 F1 查看完整帮助。", style="dim"))
        self._log.write(Text(""))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt":
            self._update_command_palette(event.value)

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
        text = (value or "").strip()
        if not text.startswith("/") or " " in text:
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
            prompt.append(description, style="dim")
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
            self._input.value = command
            self._input.cursor_position = len(command)

    def _execute_command(self, command: str) -> None:
        self._hide_command_palette()
        self._input.value = ""
        if command == "/help":
            self.action_help()
        elif command == "/clear":
            self.action_clear()
            self._input.focus()
        elif command in ("/quit", "/exit"):
            self.exit()
        else:
            self._status.update(Text(f"未知命令：{command}", style="yellow"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        palette_command = self._selected_command() if self._palette_visible else None
        event.input.value = ""
        if not text:
            self._hide_command_palette()
            return

        if palette_command:
            self._execute_command(palette_command)
            return
        if text in COMMAND_NAMES:
            self._execute_command(text)
            return
        if self._busy:
            self._status.update(Text("请等待当前回复完成", style="yellow"))
            return

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
        self._status.update(Text(f"侧边栏已{state}", style="dim"))

    def action_clear(self) -> None:
        if self._busy:
            self._status.update(Text("当前任务进行中，暂时无法清空上下文", style="yellow"))
            return
        self._hide_command_palette()
        self._agent.clear()
        self._assistant_buffer = ""
        self._assistant_line_started = False
        self._task_state = "就绪"
        self._current_round = 0
        self._current_tool = "-"
        self._turn_tool_count = 0
        self._turn_elapsed = 0.0
        self._round_progress.update(progress=0)
        self._render_task()
        self._log.clear()
        self._write_welcome()
        self._write_line("上下文已清空", style="dim")
        self._status.update(Text(self._default_status, style="dim"))

    def _start_turn(self, text: str) -> None:
        self._hide_command_palette()
        self._busy = True
        self._assistant_buffer = ""
        self._assistant_line_started = False
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
        self._status.update(Text("思考中...", style="yellow"))
        user_line = Text("\n")
        user_line.append("你  ", style="bold cyan")
        user_line.append(text)
        self._log.write(user_line)
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
            tool_line = Text("\n")
            tool_line.append("[工具] ", style="bold yellow")
            tool_line.append(event.name, style="bold cyan")
            self._log.write(tool_line)
            self._write_prefixed("  参数：", event.arguments, style="dim")
            return

        if isinstance(event, ToolFinished):
            self._current_tool = event.name if event.ok else f"{event.name}（失败）"
            self._task_state = "等待模型继续"
            self._render_task()
            style = "dim" if event.ok else "bold red"
            self._write_prefixed("  结果：", event.content, style=style)
            self._status.update(Text("工具执行完成，继续思考...", style="yellow"))
            return

        if isinstance(event, AgentError):
            self._turn_had_error = True
            self._flush_assistant()
            self._assistant_line_started = False
            self._task_state = "出错"
            self._current_tool = "-"
            self._render_task()
            self._log.write(Text(f"\n错误：{event.message}", style="bold red"))

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
        self._status.update(Text(self._default_status, style="dim"))

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
            text.append(f"{label}：", style="dim")
            text.append(str(value))
        return text

    def _drain_assistant_lines(self) -> None:
        while "\n" in self._assistant_buffer:
            line, self._assistant_buffer = self._assistant_buffer.split("\n", 1)
            self._write_assistant_line(line)

    def _flush_assistant(self) -> None:
        if self._assistant_buffer:
            self._write_assistant_line(self._assistant_buffer)
            self._assistant_buffer = ""

    def _write_assistant_line(self, line: str) -> None:
        text = Text()
        if not self._assistant_line_started:
            text.append("助手  ", style="bold green")
            self._assistant_line_started = True
        else:
            text.append("      ")
        text.append(line)
        self._log.write(text)

    def _write_prefixed(self, prefix: str, content: str, style: str = "dim") -> None:
        lines = str(content).splitlines() or [""]
        for index, line in enumerate(lines):
            text = Text()
            text.append(prefix if index == 0 else " " * len(prefix), style="bold")
            text.append(line, style=style)
            self._log.write(text)

    def _write_line(self, text: str, style: str = "") -> None:
        self._log.write(Text(text, style=style))
