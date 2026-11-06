from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class CompactionPanel(ModalScreen[None]):
    """压缩前后上下文对照面板。"""

    CSS = """
    CompactionPanel {
        align: center middle;
    }

    #compact-dialog {
        width: 94%;
        height: 90%;
        padding: 1 2;
        border: thick $accent 70%;
        background: $surface;
    }

    #compact-title {
        height: 2;
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #compact-columns {
        height: 1fr;
    }

    .compact-column {
        width: 1fr;
        height: 1fr;
        border: round $accent 30%;
        background: $panel;
    }

    #compact-right {
        margin-left: 1;
    }

    .compact-column-title {
        height: 1;
        padding: 0 1;
        color: $accent;
        text-style: bold;
    }

    .compact-scroll {
        height: 1fr;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    .compact-body {
        width: 1fr;
        height: auto;
        color: $text;
    }

    #compact-actions {
        height: 3;
        align-horizontal: right;
        padding: 1 0 0 0;
    }

    #close-compact {
        background: $surface-lighten-1;
        color: $text;
        border: tall $accent;
    }
    """

    BINDINGS = [
        ("escape", "close", "关闭"),
    ]

    def __init__(self, archive_id: str, original_text: str, summary: str) -> None:
        super().__init__()
        self._archive_id = archive_id
        self._original_text = original_text
        self._summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="compact-dialog"):
            yield Static(
                f"上下文压缩结果　·　归档编号 {self._archive_id}",
                id="compact-title",
            )
            with Horizontal(id="compact-columns"):
                with Vertical(classes="compact-column"):
                    yield Static("压缩前原文", classes="compact-column-title")
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(
                            Text(self._original_text or "（空）"),
                            markup=False,
                            classes="compact-body",
                        )
                with Vertical(id="compact-right", classes="compact-column"):
                    yield Static("压缩后结果", classes="compact-column-title")
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(
                            Text(self._summary or "（空）"),
                            markup=False,
                            classes="compact-body",
                        )
            with Horizontal(id="compact-actions"):
                yield Button("关闭 (Esc)", id="close-compact")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-compact":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
