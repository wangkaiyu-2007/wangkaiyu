from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static


class ConfigNoticeApp(App[None]):
    CSS = """
    Screen {
        background: #141414;
        align: center middle;
    }

    #config-notice {
        width: 78%;
        max-width: 92;
        height: auto;
        padding: 2 3;
        border: thick #e8a87c 70%;
        background: #1c1c1c;
    }

    #config-title {
        height: auto;
        color: #f5cba7;
        text-style: bold;
        padding-bottom: 1;
    }

    #config-message {
        height: auto;
        color: #e8e2dc;
    }

    #config-actions {
        height: 3;
        align-horizontal: right;
        padding-top: 1;
    }

    #config-exit {
        background: #262626;
        color: #e8e2dc;
        border: tall #e8a87c;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "关闭"),
        ("enter", "dismiss", "关闭"),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="config-notice"):
            yield Static("首次运行：请先修改配置文件", id="config-title")
            yield Static(
                "已在当前目录创建配置文件：\n"
                f"{self._path}\n\n"
                "其中的 base_url、api_key 和 model 为 mock 占位值。\n"
                "请修改为真实配置后重新启动 wAgent，程序才能正常工作。",
                id="config-message",
            )
            with Vertical(id="config-actions"):
                yield Button("退出 (Esc)", id="config-exit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-exit":
            self.exit()

    def action_dismiss(self) -> None:
        self.exit()


def _fallback_notice(path: Path, detail: str = "") -> None:
    print(f"已创建配置文件：{path}")
    print("请修改 base_url、api_key 和 model 后重新启动 wAgent。")
    if detail:
        print(f"（无法显示图形对话框：{detail}）")


def show_config_notice(path: Path) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _fallback_notice(path, "当前不是交互式终端")
        return
    try:
        ConfigNoticeApp(path).run()
    except Exception as exc:  # pragma: no cover - 终端不支持 Textual 时的兜底
        _fallback_notice(path, str(exc))
