from __future__ import annotations

import locale
import shutil
import subprocess

from ..config import ToolConfig
from .base import Tool


DEFAULT_TIMEOUT = 30
MAX_OUTPUT_CHARS = 8000


class CliTools:
    def __init__(self, config: ToolConfig | None = None) -> None:
        config = config or ToolConfig()
        self._timeout = config.cli_timeout
        self._max_output_chars = config.cli_max_output_chars

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="runCli",
                description=(
                    "在本地受控教学环境中执行任意已安装的命令行程序。"
                    "command 为程序名称或可执行文件路径，args 为参数列表；"
                    "命令通过参数列表直接启动，不经过 Shell 解析。"
                    "返回标准输出、标准错误和退出码，超时或输出过长时会明确标注。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的程序名称或可执行文件路径，例如 python、git、curl",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "传给程序的参数列表，按顺序逐个传入，例如 [\"--version\"]",
                        },
                    },
                    "required": ["command"],
                },
                handler=self.run_cli,
            ),
        )

    def run_cli(self, command: str, args: list[str] | None = None) -> str:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command 不能为空")
        if args is None:
            args = []
        if not isinstance(args, (list, tuple)):
            raise ValueError("args 必须是字符串列表")
        if any(not isinstance(arg, str) for arg in args):
            raise ValueError("args 中的每一项都必须是字符串")

        program = shutil.which(command.strip())
        if program is None:
            raise ValueError(f"未找到可执行程序：{command.strip()}")

        argv = [program, *args]
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise ValueError(f"无法启动程序：{command.strip()}（{exc}）") from exc
        except subprocess.TimeoutExpired as exc:
            return self._format_result(
                argv,
                stdout=self._decode(exc.stdout),
                stderr=self._decode(exc.stderr),
                exit_code=None,
                timed_out=True,
            )
        except OSError as exc:
            raise ValueError(f"调用程序失败：{exc}") from exc

        return self._format_result(
            argv,
            stdout=self._decode(completed.stdout),
            stderr=self._decode(completed.stderr),
            exit_code=completed.returncode,
            timed_out=False,
        )

    @staticmethod
    def _decode(data: bytes | str | None) -> str:
        if data is None:
            return ""
        if isinstance(data, str):
            return data
        encodings = ("utf-8", locale.getpreferredencoding(False), "gbk")
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return data.decode("utf-8", errors="replace")

    def _truncate(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text) <= self._max_output_chars:
            return text
        omitted = len(text) - self._max_output_chars
        return (
            text[: self._max_output_chars]
            + f"\n[输出过长，已截断：仅保留前 {self._max_output_chars} 个字符，"
            f"其余 {omitted} 个字符已省略]"
        )

    def _format_result(
        self,
        argv: list[str],
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
    ) -> str:
        stdout = self._truncate(stdout).strip()
        stderr = self._truncate(stderr).strip()
        if timed_out:
            status = f"超时（超过 {self._timeout:g} 秒，进程已终止）"
            exit_text = "无（超时终止）"
        else:
            status = "完成"
            exit_text = str(exit_code)

        return (
            f"命令：{subprocess.list2cmdline(argv)}\n"
            f"执行状态：{status}\n"
            f"退出码：{exit_text}\n"
            f"--- 标准输出 ---\n{stdout or '(空)'}\n"
            f"--- 标准错误 ---\n{stderr or '(空)'}"
        )
