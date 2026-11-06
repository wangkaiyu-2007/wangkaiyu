from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .config import LLMConfig


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class ChatResult:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None


class OpenAIChatClient:
    def __init__(self, config: LLMConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def close(self) -> None:
        self._session.close()

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_content: Callable[[str], None] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools is not None:
            payload["tools"] = tools
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        try:
            response = self._session.post(
                self._config.chat_url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                stream=True,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"请求失败：{exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:1000]
            response.close()
            raise LLMError(f"接口返回 HTTP {response.status_code}：{detail}")

        parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage: dict[str, int] | None = None

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8", errors="replace")
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except ValueError:
                    continue

                chunk_usage = payload.get("usage")
                if chunk_usage:
                    usage = chunk_usage

                try:
                    delta = payload["choices"][0]["delta"]
                except (KeyError, IndexError):
                    continue

                content = delta.get("content")
                if content:
                    parts.append(content)
                    if on_content is not None:
                        on_content(content)

                self._merge_tool_calls(tool_calls, delta.get("tool_calls") or [])
        except requests.RequestException as exc:
            raise LLMError(f"读取流式响应失败：{exc}") from exc
        finally:
            response.close()

        return ChatResult(content="".join(parts), tool_calls=tool_calls, usage=usage)

    @staticmethod
    def _merge_tool_calls(tool_calls: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
        for chunk in chunks:
            index = chunk.get("index", 0)
            while len(tool_calls) <= index:
                tool_calls.append(
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
            current = tool_calls[index]
            if chunk.get("id"):
                current["id"] = chunk["id"]
            function = chunk.get("function") or {}
            if function.get("name"):
                current["function"]["name"] += function["name"]
            if function.get("arguments"):
                current["function"]["arguments"] += function["arguments"]
