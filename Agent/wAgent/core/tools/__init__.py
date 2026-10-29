from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool, ToolResult
from .cli import CliTools
from .filesystem import FileSystemTools
from .registry import ToolRegistry
from .search import SearchTools
from .web import WebTools

if TYPE_CHECKING:
    from ..config import SearchConfig


def create_default_registry(search_config: "SearchConfig | None" = None) -> ToolRegistry:
    return ToolRegistry(
        (
            *FileSystemTools().tools(),
            *WebTools().tools(),
            *SearchTools(search_config).tools(),
            *CliTools().tools(),
        )
    )


__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "FileSystemTools",
    "WebTools",
    "SearchTools",
    "CliTools",
    "create_default_registry",
]
