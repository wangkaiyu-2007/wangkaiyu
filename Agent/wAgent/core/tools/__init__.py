from __future__ import annotations

from .base import Tool, ToolResult
from .filesystem import FileSystemTools
from .registry import ToolRegistry


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(FileSystemTools().tools())


__all__ = ["Tool", "ToolResult", "ToolRegistry", "FileSystemTools", "create_default_registry"]
