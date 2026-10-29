from __future__ import annotations

import re
from typing import Any

import requests

from ..config import SearchConfig
from .base import Tool


MAX_QUERY_WIDTH = 72
MAX_SNIPPET_CHARS = 700
MAX_RESULT_CHARS = 16000
USER_AGENT = "wAgent/1.0"


class SearchTools:
    def __init__(
        self,
        config: SearchConfig | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="searchWeb",
                description=(
                    "调用百度千帆网络搜索 API 获取互联网实时信息。"
                    "接收搜索关键词或问题，返回搜索摘要、参考来源标题和 URL。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词或问题，建议不超过 72 个字符宽度",
                        }
                    },
                    "required": ["query"],
                },
                handler=self.search_web,
            ),
        )

    def search_web(self, query: str) -> str:
        config = self._config
        if config is None or not config.api_key:
            raise ValueError(
                "缺少百度千帆搜索 API Key，请在配置文件的 [search] 小节中设置 "
                "baidu_qianfan_api_key"
            )

        keyword, truncated = self._prepare_query(query)
        payload = {
            "messages": [{"role": "user", "content": keyword}],
            "search_source": "baidu_search_v2",
            "edition": "standard",
            "resource_type_filter": [{"type": "web", "top_k": config.top_k}],
            "query_policy": {"enable_rewrite": True},
        }
        try:
            response = self._session.post(
                config.base_url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
                json=payload,
                timeout=config.timeout,
            )
        except requests.Timeout as exc:
            raise ValueError(f"搜索请求超时（超过 {config.timeout:g} 秒）") from exc
        except requests.RequestException as exc:
            raise ValueError(f"网络请求失败：{exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            detail = response.text[:500].strip()
            raise ValueError(
                f"搜索 API 返回了无法解析的 JSON（HTTP {response.status_code}）：{detail}"
            ) from exc

        if response.status_code >= 400:
            raise ValueError(self._describe_api_error(response.status_code, data))

        if not isinstance(data, dict):
            raise ValueError("搜索 API 返回了非预期的数据结构")

        code = data.get("code")
        if code not in (None, "", 0, "0"):
            message = data.get("message") or data.get("msg") or "未知错误"
            raise ValueError(f"搜索 API 返回错误（code={code}）：{message}")

        references = data.get("references")
        if references is None and isinstance(data.get("data"), dict):
            references = data["data"].get("references")
        if not isinstance(references, list) or not references:
            return f"未找到与“{keyword}”相关的搜索结果。"

        lines = [f"搜索关键词：{keyword}", f"搜索结果数：{len(references)}"]
        if truncated:
            lines.append("提示：查询内容过长，已按接口限制截取前 72 个字符宽度。")
        lines.append("")

        seen_urls: set[str] = set()
        count = 0
        for reference in references:
            if not isinstance(reference, dict):
                continue
            url = self._clean(reference.get("url"))
            if not url or url in seen_urls:
                continue
            title = self._clean(
                reference.get("title")
                or reference.get("web_anchor")
                or reference.get("website")
                or "无标题"
            )
            date = self._clean(reference.get("date"))
            website = self._clean(reference.get("website"))
            snippet = self._clean(
                reference.get("snippet")
                or reference.get("content")
                or reference.get("web_anchor")
            )
            if len(snippet) > MAX_SNIPPET_CHARS:
                snippet = snippet[:MAX_SNIPPET_CHARS] + "…"

            count += 1
            block = [f"[{count}] {title}", f"URL：{url}"]
            source = " / ".join(part for part in (website, date) if part)
            if source:
                block.append(f"来源：{source}")
            if snippet:
                block.append(f"摘要：{snippet}")
            block.append("")
            lines.extend(block)
            seen_urls.add(url)

        if count == 0:
            return f"未找到与“{keyword}”相关的有效搜索结果。"

        content = "\n".join(lines).strip()
        if len(content) > MAX_RESULT_CHARS:
            content = content[:MAX_RESULT_CHARS] + "\n\n[搜索结果过长，已截断]"
        return content

    @staticmethod
    def _prepare_query(query: str) -> tuple[str, bool]:
        if not isinstance(query, str):
            raise ValueError("搜索关键词必须是字符串")
        text = re.sub(r"\s+", " ", query).strip()
        if not text:
            raise ValueError("搜索关键词不能为空")

        width = 0
        kept: list[str] = []
        for character in text:
            character_width = 2 if ord(character) > 127 else 1
            if width + character_width > MAX_QUERY_WIDTH:
                break
            kept.append(character)
            width += character_width
        return "".join(kept) or text[:1], len(kept) < len(text)

    @staticmethod
    def _clean(value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    @staticmethod
    def _describe_api_error(status_code: int, data: Any) -> str:
        message = ""
        code = ""
        if isinstance(data, dict):
            message = str(data.get("message") or data.get("msg") or "").strip()
            code = str(data.get("code") or data.get("requestId") or "").strip()
        details = "，".join(
            part for part in (f"code={code}" if code else "", message) if part
        )
        suffix = f"：{details}" if details else ""
        return f"搜索 API 返回 HTTP {status_code}{suffix}"
