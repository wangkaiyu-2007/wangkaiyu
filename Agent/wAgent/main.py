from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def _bootstrap_package_path() -> None:
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_bootstrap_package_path()

from wAgent import __version__
from wAgent.core.agent import Agent
from wAgent.core.config import ConfigError, create_default_config, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wAgent",
        description="wAgent：基于 Textual 的本地文件智能助手",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="指定 config.ini 路径；默认自动查找",
    )
    parser.add_argument("--version", action="version", version=f"wAgent {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cwd_config = Path.cwd() / "config.ini"
    if (
        args.config is None
        and not os.environ.get("WAGENT_CONFIG")
        and not cwd_config.is_file()
    ):
        try:
            created = create_default_config(cwd_config)
        except ConfigError as exc:
            print(f"配置错误：{exc}", file=sys.stderr)
            return 2
        try:
            from wAgent.tui.setup import show_config_notice
        except ImportError:
            print("请修改配置文件中的 base_url、api_key 和 model 后重新启动 wAgent。")
            return 3
        show_config_notice(created)
        return 3

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    try:
        from wAgent.tui.app import WAgentApp
    except ImportError as exc:
        print(
            f"TUI 依赖加载失败：{exc}\n请先执行：pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    agent = Agent(config)
    for warning in agent.mcp.warnings:
        print(f"MCP：{warning}", file=sys.stderr)

    app = WAgentApp(agent)
    try:
        app.run()
    finally:
        agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
