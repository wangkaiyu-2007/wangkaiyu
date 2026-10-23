from __future__ import annotations

import argparse
from pathlib import Path
import sys


def _bootstrap_package_path() -> None:
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_bootstrap_package_path()

from wAgent import __version__
from wAgent.core.agent import Agent
from wAgent.core.config import ConfigError, load_config


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
    app = WAgentApp(agent)
    try:
        app.run()
    finally:
        agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
