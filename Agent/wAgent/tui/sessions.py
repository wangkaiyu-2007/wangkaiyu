from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from wAgent.core.sessions import SessionInfo


class SessionListScreen(ModalScreen[SessionInfo | None]):
    CSS = """
    SessionListScreen {
        align: center middle;
    }

    #session-dialog {
        width: 84%;
        max-width: 110;
        height: 78%;
        padding: 1 2;
        border: thick $accent 70%;
        background: $surface;
    }

    #session-title {
        height: 1;
        color: $accent;
        text-style: bold;
    }

    #session-hint {
        height: 1;
        margin-bottom: 1;
        color: $text 55%;
    }

    #session-options {
        height: 1fr;
        border: round $accent 30%;
        background: $panel;
    }

    #session-options > .option-list--option-highlighted {
        background: $boost;
        color: $accent;
    }

    #session-actions {
        height: 3;
        align-horizontal: right;
        padding-top: 1;
    }

    #session-close {
        background: $surface-lighten-1;
        color: $text;
        border: tall $accent;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "取消"),
    ]

    def __init__(self, sessions: list[SessionInfo]) -> None:
        super().__init__()
        self._sessions = sessions
        self._index = {session.id: session for session in sessions}

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Static(f"历史会话（{len(self._sessions)}）", id="session-title")
            yield Static(
                "Up/Down 选择 · Enter 恢复 · Esc 取消",
                id="session-hint",
            )
            yield OptionList(id="session-options", markup=False)
            with Vertical(id="session-actions"):
                yield Button("取消 (Esc)", id="session-close")

    def on_mount(self) -> None:
        options = self.query_one("#session-options", OptionList)
        for session in self._sessions:
            line = Text()
            line.append(session.id, style="bold #e8a87c")
            line.append("  ")
            line.append(session.title)
            line.append(f"  · {session.updated_at} · {session.message_count} 条")
            options.add_option(Option(line, id=session.id))
        if self._sessions:
            options.highlighted = 0
            options.focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id:
            self.dismiss(self._index.get(str(event.option.id)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "session-close":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
