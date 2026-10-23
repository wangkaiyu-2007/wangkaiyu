from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str
    ok: bool = True


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    handler: Callable[..., str] = field(repr=False)
    parameters: dict[str, Any] = field(default_factory=dict)

    def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            content = self.handler(**arguments)
        except TypeError as exc:
            return ToolResult(f"工具参数错误：{exc}", ok=False)
        except (OSError, ValueError) as exc:
            return ToolResult(f"操作失败：{exc}", ok=False)
        except Exception as exc:
            return ToolResult(f"工具执行异常：{exc}", ok=False)
        return ToolResult(str(content), ok=True)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
