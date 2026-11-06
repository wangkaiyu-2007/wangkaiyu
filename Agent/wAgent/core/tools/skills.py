from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import ToolConfig
from ..skills import SKILL_FILE_NAME, Skill, SkillCatalog, SkillError
from .base import Tool
from .filesystem import detect_encoding

try:
    import yaml
except ImportError:  # pragma: no cover - 允许在未安装 PyYAML 时使用简易解析
    yaml = None


MAX_SKILL_FILE_BYTES = 1024 * 1024
MAX_SKILL_NAME_LENGTH = 64
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_SEPARATORS = ("---", "...")


class SkillTools:
    def __init__(
        self, catalog: SkillCatalog, config: ToolConfig | None = None
    ) -> None:
        self._catalog = catalog
        config = config or ToolConfig()
        self._max_file_bytes = config.skill_max_file_bytes
        self._max_name_length = config.skill_max_name_length

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="loadSkill",
                description=(
                    "按需加载 Agent Skill 的完整说明或附件文件。"
                    "只提供 name 时返回该 Skill 的 SKILL.md 全文；"
                    "同时提供 filename 时读取 Skill 目录内的指定附件文件，不会重复加载 SKILL.md。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill 的名称，必须与系统提示中列出的名称一致",
                        },
                        "filename": {
                            "type": "string",
                            "description": (
                                "可选：要加载的 Skill 附件文件路径或名称。"
                                "支持相对 Skill 目录、相对项目根目录以及绝对路径，"
                                "但必须位于该 Skill 目录内部。"
                            ),
                        },
                    },
                    "required": ["name"],
                },
                handler=self.load_skill,
            ),
            Tool(
                name="createSkill",
                description=(
                    "根据用户的自然语言要求创建新的 Agent Skill：在当前项目 .agents/skills/ 下"
                    "创建与 name 对应的英文子目录，并在其中生成符合规范的 SKILL.md。"
                    "name 为 Skill 名称，会自动规范为小写字母、数字和连字符组成的格式；"
                    "skillContext 为要写入 SKILL.md 的完整内容，可以自带 YAML Frontmatter，"
                    "未提供时会自动补充 name 与 description。"
                    "若目标 Skill 已存在则不会覆盖。"
                    "如需额外创建 references/、scripts/ 等目录或辅助文件，请继续调用 fileOps 工具。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill 名称，例如 pdf-processing（将规范为小写字母、数字和连字符）",
                        },
                        "skillContext": {
                            "type": "string",
                            "description": (
                                "要写入 SKILL.md 的完整内容，可包含 YAML Frontmatter 与正文；"
                                "若未包含 Frontmatter，工具会自动生成 name 和 description"
                            ),
                        },
                    },
                    "required": ["name", "skillContext"],
                },
                handler=self.create_skill,
            ),
        )

    def create_skill(self, name: str, skillContext: str) -> str:
        slug = normalize_skill_name(name, self._max_name_length)

        if not isinstance(skillContext, str) or not skillContext.strip():
            raise SkillError("skillContext 不能为空，请提供要写入 SKILL.md 的完整内容")

        existing = self._find_existing(slug)
        if existing is not None:
            raise SkillError(
                f"Skill 已存在，未做任何修改：{slug}（目录：{existing}）。"
                "如需更新请先删除或重命名原有 Skill 目录"
            )

        metadata, body = _split_frontmatter(skillContext.lstrip("\ufeff"))
        description = str(metadata.get("description") or "").strip()
        if not description:
            description = _derive_description(body)
        if not description:
            raise SkillError(
                "无法确定 Skill 的 description：请在 Frontmatter 中提供 description，"
                "或在正文中补充一句说明"
            )

        target_dir = self._catalog.skills_root / slug
        target_file = target_dir / SKILL_FILE_NAME
        if target_dir.exists() or target_file.exists():
            raise SkillError(
                f"Skill 已存在，未做任何修改：{slug}（目录：{target_dir}）。"
                "如需更新请先删除或重命名原有 Skill 目录"
            )

        content = _compose_skill_document(slug, description, metadata, body)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8", newline="")

        self._refresh_catalog()

        return (
            f"已创建 Skill：{slug}\n"
            f"目录：{target_dir}\n"
            f"文件：{target_file}\n"
            f"名称：{slug}\n"
            f"描述：{' '.join(description.split())}\n"
            "提示：如需补充 references/、scripts/ 等目录或文件，请继续调用 fileOps 工具。"
        )

    def _find_existing(self, slug: str) -> Path | None:
        target_dir = self._catalog.skills_root / slug
        if target_dir.exists():
            return target_dir
        for skill in self._catalog.skills:
            if skill.name == slug:
                return skill.directory
        return None

    def _refresh_catalog(self) -> None:
        refresh = getattr(self._catalog, "refresh", None)
        if callable(refresh):
            refresh()

    def load_skill(self, name: str, filename: str = "") -> str:
        skill = self._catalog.get(name)
        if filename is None or (isinstance(filename, str) and not filename.strip()):
            target = skill.skill_file
        elif isinstance(filename, str):
            target = self._resolve_attachment(skill, filename)
        else:
            raise SkillError("filename 必须是字符串")
        content = self._read_text(target)
        return (
            f"Skill：{skill.name}\n"
            f"文件：{target}\n"
            f"--- 内容开始 ---\n{content}\n--- 内容结束 ---"
        )

    def _resolve_attachment(self, skill: Skill, filename: str) -> Path:
        raw = filename.strip()
        if not raw:
            raise SkillError("filename 不能为空")

        skill_dir = skill.directory.resolve()
        raw_path = Path(os.path.expanduser(raw))

        candidates: list[Path] = []
        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            candidates.append(skill_dir / raw_path)
            candidates.append(self._catalog.project_root / raw_path)

        seen: set[str] = set()
        outside: list[Path] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            if not resolved.is_file():
                continue
            if _is_within(resolved, skill_dir):
                return resolved
            outside.append(resolved)

        if "/" not in raw.replace("\\", "/"):
            matches = self._search_by_name(skill_dir, raw_path.name)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                relative = "\n".join(
                    f"- {path.relative_to(skill_dir).as_posix()}" for path in matches
                )
                raise SkillError(
                    f"在 Skill '{skill.name}' 中找到多个同名文件 {raw_path.name}，"
                    f"请使用 filename 指定其中一个：\n{relative}"
                )

        if outside:
            raise SkillError(
                f"出于安全考虑，只允许读取 Skill '{skill.name}' 目录内的文件：{skill_dir}"
            )
        raise SkillError(f"在 Skill '{skill.name}' 中找不到文件：{raw}")

    @staticmethod
    def _search_by_name(skill_dir: Path, name: str) -> list[Path]:
        matches: list[Path] = []
        seen: set[str] = set()
        target = name.lower()
        for path in skill_dir.rglob("*"):
            try:
                if not path.is_file():
                    continue
                if path.name.lower() != target:
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if not _is_within(resolved, skill_dir):
                continue
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            matches.append(resolved)
        matches.sort(key=lambda item: item.relative_to(skill_dir).as_posix().lower())
        return matches

    def _read_text(self, path: Path) -> str:
        size = path.stat().st_size
        if size > self._max_file_bytes:
            raise SkillError(
                f"文件过大（{size} 字节），超过 {self._max_file_bytes} 字节限制：{path}"
            )
        raw = path.read_bytes()
        encoding = detect_encoding(raw)
        if encoding is None:
            raise SkillError(f"不是纯文本文件，无法读取：{path}")
        return raw.decode(encoding)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def normalize_skill_name(name: str, max_length: int = MAX_SKILL_NAME_LENGTH) -> str:
    if not isinstance(name, str) or not name.strip():
        raise SkillError("Skill 名称不能为空")
    raw = name.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not slug:
        raise SkillError(
            f"Skill 名称必须包含英文字母或数字，并使用小写字母、数字和连字符，例如 pdf-processing：{raw}"
        )
    if len(slug) > max_length:
        raise SkillError(
            f"Skill 名称过长（{len(slug)} 个字符），最多 {max_length} 个字符：{slug}"
        )
    if not SKILL_NAME_PATTERN.match(slug):
        raise SkillError(f"Skill 名称格式无效，只能使用小写字母、数字和连字符：{slug}")
    return slug


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() in _FRONTMATTER_SEPARATORS:
            return _parse_yaml("".join(lines[1:index])), "".join(lines[index + 1 :])
    raise SkillError(
        f"{SKILL_FILE_NAME} 的 YAML Frontmatter 未正确闭合，缺少结束的 ---"
    )


def _parse_yaml(raw: str) -> dict:
    text = raw.strip()
    if not text:
        return {}
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SkillError(f"{SKILL_FILE_NAME} Frontmatter 格式错误：{exc}") from exc
        return data if isinstance(data, dict) else {}
    from ..skills import _simple_yaml

    return _simple_yaml(text)


def _derive_description(body: str) -> str:
    heading = ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("```", "~~~", "<!--")):
            continue
        line = line.lstrip("> ").strip()
        is_heading = bool(re.match(r"^#{1,6}\s+", line))
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = line.strip("#*_`> ")
        line = " ".join(line.split())
        if not line:
            continue
        if is_heading:
            heading = heading or line
            continue
        return line
    return heading


def _dump_frontmatter(metadata: dict) -> str:
    if yaml is not None:
        return yaml.safe_dump(
            metadata, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
    lines = []
    for key, value in metadata.items():
        escaped = str(value).replace("'", "''")
        lines.append(f"{key}: '{escaped}'")
    return "\n".join(lines) + "\n"


def _compose_skill_document(
    slug: str, description: str, metadata: dict, body: str
) -> str:
    ordered: dict = {
        "name": slug,
        "description": " ".join(description.split()),
    }
    for key, value in metadata.items():
        if key in ordered:
            continue
        ordered[str(key)] = value

    body_text = body.strip("\r\n")
    if not body_text.strip():
        body_text = f"# {slug}\n"

    return f"---\n{_dump_frontmatter(ordered)}---\n\n{body_text}\n"
