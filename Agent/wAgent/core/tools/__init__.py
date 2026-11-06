from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool, ToolResult
from .cli import CliTools
from .context import ContextTools
from .filesystem import FileSystemTools
from .registry import ToolRegistry
from .search import SearchTools
from .skills import SkillTools
from .web import WebTools

if TYPE_CHECKING:
    from ..config import SearchConfig, ToolConfig
    from ..skills import SkillCatalog


def create_default_registry(
    search_config: "SearchConfig | None" = None,
    skill_catalog: "SkillCatalog | None" = None,
    tool_config: "ToolConfig | None" = None,
    context_dir: str | None = None,
) -> ToolRegistry:
    if skill_catalog is None:
        from ..skills import SkillCatalog

        skill_catalog = SkillCatalog.discover()
    return ToolRegistry(
        (
            *FileSystemTools(tool_config).tools(),
            *WebTools(tool_config).tools(),
            *SearchTools(search_config, tool_config).tools(),
            *CliTools(tool_config).tools(),
            *ContextTools(tool_config, context_dir).tools(),
            *SkillTools(skill_catalog, tool_config).tools(),
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
    "ContextTools",
    "SkillTools",
    "create_default_registry",
]
