from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool, ToolResult
from .cli import CliTools
from .filesystem import FileSystemTools
from .registry import ToolRegistry
from .search import SearchTools
from .skills import SkillTools
from .web import WebTools

if TYPE_CHECKING:
    from ..config import SearchConfig
    from ..skills import SkillCatalog


def create_default_registry(
    search_config: "SearchConfig | None" = None,
    skill_catalog: "SkillCatalog | None" = None,
) -> ToolRegistry:
    if skill_catalog is None:
        from ..skills import SkillCatalog

        skill_catalog = SkillCatalog.discover()
    return ToolRegistry(
        (
            *FileSystemTools().tools(),
            *WebTools().tools(),
            *SearchTools(search_config).tools(),
            *CliTools().tools(),
            *SkillTools(skill_catalog).tools(),
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
    "SkillTools",
    "create_default_registry",
]
