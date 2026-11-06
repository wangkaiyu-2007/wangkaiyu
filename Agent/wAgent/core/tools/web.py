from __future__ import annotations

import os
import shutil
import subprocess
from urllib.parse import urlparse

from ..config import ToolConfig
from .base import Tool


DEFAULT_TIMEOUT = 20
MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_MARKDOWN_CHARS = 60000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 wAgent/1.0"
)


class WebTools:
    def __init__(self, config: ToolConfig | None = None) -> None:
        config = config or ToolConfig()
        self._timeout = config.web_timeout
        self._connect_timeout = config.web_connect_timeout
        self._max_html_bytes = config.web_max_html_bytes
        self._max_markdown_chars = config.web_max_markdown_chars

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="fetchWeb",
                description=(
                    "使用 curl 下载指定网页，并用 trafilatura 提取正文并转换为 Markdown。"
                    "会保留正文中的标题、段落、列表、表格和链接，去除导航、广告、页脚等无关内容。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要读取的网页 URL，必须是 http:// 或 https:// 地址",
                        }
                    },
                    "required": ["url"],
                },
                handler=self.fetch_web,
            ),
        )

    def fetch_web(self, url: str) -> str:
        target = self._validate_url(url)
        curl = self._find_curl()
        html = self._download(curl, target)
        markdown = self._extract_markdown(html, target)
        return self._format_result(target, markdown)

    @staticmethod
    def _validate_url(url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("URL 不能为空")
        target = url.strip()
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        if not parsed.netloc:
            raise ValueError(f"URL 缺少有效的域名：{target}")
        return target

    @staticmethod
    def _find_curl() -> str:
        configured = os.environ.get("WAGENT_CURL")
        candidates = [configured] if configured else []
        candidates.extend(("curl", "curl.exe"))
        for candidate in candidates:
            if not candidate:
                continue
            path = shutil.which(candidate)
            if path:
                return path
        raise ValueError(
            "未找到 curl 程序，请先安装 curl，或通过环境变量 WAGENT_CURL 指定 curl 可执行文件路径"
        )

    def _download(self, curl: str, url: str) -> bytes:
        command = [
            curl,
            "--silent",
            "--show-error",
            "--fail",
            "--location",
            "--compressed",
            "--max-time",
            f"{self._timeout:g}",
            "--connect-timeout",
            f"{self._connect_timeout:g}",
            "--max-filesize",
            str(self._max_html_bytes),
            "--proto",
            "=http,https",
            "--proto-redir",
            "=http,https",
            "--user-agent",
            USER_AGENT,
            "--header",
            "Accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "--header",
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
            url,
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._timeout + 5,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise ValueError(f"无法启动 curl：{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"网页访问超时（超过 {self._timeout:g} 秒）") from exc
        except OSError as exc:
            raise ValueError(f"调用 curl 失败：{exc}") from exc

        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0:
            raise ValueError(self._describe_curl_error(completed.returncode, stderr))

        html = completed.stdout
        if not html.strip():
            raise ValueError("网页返回内容为空")
        if len(html) > self._max_html_bytes:
            raise ValueError(
                f"网页内容过大（超过 {self._max_html_bytes / (1024 * 1024):.1f} MB）"
            )
        return html

    @staticmethod
    def _describe_curl_error(returncode: int, stderr: str) -> str:
        messages = {
            6: "无法解析域名",
            7: "无法连接到服务器",
            22: "网页返回 HTTP 错误状态码",
            28: "网页访问超时",
            35: "TLS/SSL 握手失败",
            47: "重定向次数过多",
            52: "服务器没有返回任何内容",
            56: "接收网页数据失败",
            60: "HTTPS 证书校验失败",
            63: "网页内容超过大小限制",
        }
        detail = messages.get(returncode, "网页访问失败")
        suffix = f"：{stderr}" if stderr else ""
        return f"{detail}（curl 返回码 {returncode}）{suffix}"

    def _extract_markdown(self, html: bytes, url: str) -> str:
        try:
            import trafilatura
        except ImportError as exc:
            raise ValueError(
                "缺少 trafilatura 依赖，请先执行：pip install -r requirements.txt"
            ) from exc

        try:
            markdown = trafilatura.extract(
                html,
                url=url,
                output_format="markdown",
                include_comments=False,
                include_tables=True,
                include_links=True,
                include_formatting=True,
                include_images=False,
                favor_precision=True,
                deduplicate=True,
            )
        except Exception as exc:
            raise ValueError(f"HTML 解析失败：{exc}") from exc

        if not markdown or not markdown.strip():
            raise ValueError("无法从网页中提取正文，页面可能为空、需要登录或由脚本动态渲染")

        content = markdown.strip()
        if len(content) > self._max_markdown_chars:
            content = (
                content[: self._max_markdown_chars]
                + f"\n\n[正文过长，已截断，仅保留前 {self._max_markdown_chars} 个字符]"
            )
        return content

    @staticmethod
    def _format_result(url: str, markdown: str) -> str:
        return (
            f"原始 URL：{url}\n"
            f"--- 正文开始 ---\n{markdown}\n--- 正文结束 ---"
        )
