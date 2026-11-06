from __future__ import annotations

import json
import threading
from typing import Any, Iterable

from .base import Tool, ToolResult


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.RLock()
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        with self._lock:
            if tool.name in self._tools:
                raise ValueError(f"工具已注册：{tool.name}")
            self._tools[tool.name] = tool

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._tools

    @property
    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._tools)

    def tools(self) -> tuple[Tool, ...]:
        with self._lock:
            return tuple(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        with self._lock:
            tools = tuple(self._tools.values())
        return [tool.schema() for tool in tools]

    def execute(self, name: str, arguments_json: str) -> ToolResult:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"未知工具：{name}", ok=False)
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
        except (TypeError, ValueError):
            return ToolResult("工具参数不是合法的 JSON", ok=False)
        if not isinstance(arguments, dict):
            return ToolResult("工具参数必须是 JSON 对象", ok=False)
        return tool.invoke(arguments)
