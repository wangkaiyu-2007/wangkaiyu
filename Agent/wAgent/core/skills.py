from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - 允许在未安装 PyYAML 时使用简易解析
    yaml = None


SKILL_FILE_NAME = "SKILL.md"
SKILLS_RELATIVE_DIR = Path(".agents") / "skills"


class SkillError(ValueError):
    """Skill 发现或加载失败。"""


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    directory: Path
    skill_file: Path

    @property
    def path(self) -> Path:
        return self.skill_file


class SkillCatalog:
    """在项目根目录的 .agents/skills 下发现 Skill，仅保留名称与描述。"""

    def __init__(
        self,
        project_root: Path,
        skills_root: Path,
        skills: Iterable[Skill] = (),
        warnings: Iterable[str] = (),
    ) -> None:
        self._project_root = project_root
        self._skills_root = skills_root
        self._skills = tuple(skills)
        self._by_name = {skill.name: skill for skill in self._skills}
        self._warnings = tuple(warnings)

    @classmethod
    def discover(cls, project_root: str | Path | None = None) -> "SkillCatalog":
        root = Path(project_root).expanduser() if project_root is not None else Path.cwd()
        root = root.resolve()
        skills_root = root / SKILLS_RELATIVE_DIR

        skills: dict[str, Skill] = {}
        warnings: list[str] = []

        if skills_root.is_dir():
            for entry in sorted(skills_root.iterdir(), key=lambda item: item.name.lower()):
                if not entry.is_dir():
                    continue
                skill_file = entry / SKILL_FILE_NAME
                if not skill_file.is_file():
                    continue
                try:
                    meta = _read_frontmatter(skill_file)
                except (OSError, SkillError) as exc:
                    warnings.append(f"跳过 {entry.name}：{exc}")
                    continue

                name = str(meta.get("name") or "").strip()
                description = str(meta.get("description") or "").strip()
                if not name or not description:
                    warnings.append(
                        f"跳过 {entry.name}：{SKILL_FILE_NAME} 缺少必需的 name 或 description"
                    )
                    continue
                if name in skills:
                    warnings.append(f"跳过 {entry.name}：Skill 名称重复：{name}")
                    continue

                skills[name] = Skill(
                    name=name,
                    description=_one_line(description),
                    directory=entry.resolve(),
                    skill_file=skill_file.resolve(),
                )

        return cls(root, skills_root, skills.values(), warnings)

    def refresh(self) -> None:
        fresh = self.discover(self._project_root)
        self._skills = fresh._skills
        self._by_name = fresh._by_name
        self._warnings = fresh._warnings

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def skills_root(self) -> Path:
        return self._skills_root

    @property
    def skills(self) -> tuple[Skill, ...]:
        return self._skills

    @property
    def warnings(self) -> tuple[str, ...]:
        return self._warnings

    def get(self, name: str) -> Skill:
        skill = self._by_name.get(str(name).strip())
        if skill is None:
            available = "、".join(self._by_name) or "（无）"
            raise SkillError(f"未找到 Skill：{name}。当前可用 Skill：{available}")
        return skill

    def prompt(self) -> str:
        if not self._skills:
            return ""
        lines = ["You have access to the following skills:"]
        lines.extend(f"- '{skill.name}': {skill.description}" for skill in self._skills)
        lines.append(
            "Use the 'loadSkill' tool to load the full instructions of a skill when needed. "
            "You can also load additional files referenced by a skill by passing the optional "
            "'filename' parameter."
        )
        return "\n".join(lines)


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def _read_frontmatter(path: Path) -> dict:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open("r", encoding=encoding) as handle:
                return _parse_frontmatter(handle)
        except UnicodeDecodeError:
            continue
    return {}


def _parse_frontmatter(handle) -> dict:
    first = handle.readline()
    if first.lstrip("\ufeff").strip() != "---":
        return {}

    lines: list[str] = []
    closed = False
    for line in handle:
        if line.strip() in ("---", "..."):
            closed = True
            break
        lines.append(line)
    if not closed:
        return {}

    text = "".join(lines)
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SkillError(f"{SKILL_FILE_NAME} Frontmatter 格式错误：{exc}") from exc
        return data if isinstance(data, dict) else {}
    return _simple_yaml(text)


def _simple_yaml(text: str) -> dict:
    data: dict[str, str] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1].isspace():
            if current_key:
                data[current_key] = f"{data[current_key]} {raw.strip()}".strip()
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key] = value
        current_key = key
    return data
