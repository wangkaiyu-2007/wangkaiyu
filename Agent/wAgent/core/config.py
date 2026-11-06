from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


@dataclass(frozen=True, slots=True)
class SearchConfig:
    api_key: str
    base_url: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    top_k: int = 8
    timeout: float = 20.0


@dataclass(frozen=True, slots=True)
class ToolConfig:
    fs_max_text_bytes: int = 1024 * 1024
    fs_text_sample_bytes: int = 4096
    cli_timeout: float = 30.0
    cli_max_output_chars: int = 8000
    web_timeout: float = 20.0
    web_connect_timeout: float = 10.0
    web_max_html_bytes: int = 8 * 1024 * 1024
    web_max_markdown_chars: int = 60000
    search_max_query_width: int = 72
    search_max_snippet_chars: int = 700
    search_max_result_chars: int = 16000
    skill_max_file_bytes: int = 1024 * 1024
    skill_max_name_length: int = 64
    mcp_connect_timeout: float = 30.0
    mcp_call_timeout: float = 60.0
    context_search_max_matches: int = 8
    context_search_max_snippet_chars: int = 420
    context_search_max_result_chars: int = 6000


@dataclass(frozen=True, slots=True)
class SessionConfig:
    directory: str = ".agents/sessions"
    auto_save_on_quit: bool = True


@dataclass(frozen=True, slots=True)
class UIConfig:
    refresh_interval: float = 0.5
    sidebar_breakpoint: int = 100


@dataclass(frozen=True, slots=True)
class AgentConfig:
    llm: LLMConfig
    max_tool_rounds: int = 10
    source: Path | None = None
    search: SearchConfig | None = None
    context_window: int | None = None
    compact_max_tokens: int = 8192
    context_warning_ratio: float = 0.60
    compact_summary_tokens: int = 5000
    context_dir: str = ".agents/context"
    agents_md_file: str = "AGENTS.md"
    tools: ToolConfig = field(default_factory=ToolConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _candidate_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[1]
    agent_root = Path(__file__).resolve().parents[2]

    candidates = [
        Path.cwd() / "config.ini",
        project_root / "config.ini",
        project_root / "congfig.ini",
        agent_root / "Practice02" / "config.ini",
    ]

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _section_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
    minimum: int = 1,
) -> int:
    raw = parser.get(section, key, fallback=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"配置项 {section}.{key} 必须是整数，当前值为：{raw!r}"
        ) from exc
    if value < minimum:
        raise ConfigError(f"配置项 {section}.{key} 必须大于等于 {minimum}，当前值为：{value}")
    return value


def _section_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: float,
    minimum: float | None = None,
) -> float:
    raw = parser.get(section, key, fallback=str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(
            f"配置项 {section}.{key} 必须是数字，当前值为：{raw!r}"
        ) from exc
    if minimum is not None and value < minimum:
        raise ConfigError(
            f"配置项 {section}.{key} 必须大于等于 {minimum}，当前值为：{value}"
        )
    return value


def _section_ratio(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: float,
) -> float:
    value = _section_float(parser, section, key, default)
    if not 0 < value <= 1:
        raise ConfigError(
            f"配置项 {section}.{key} 必须在 (0, 1] 范围内，当前值为：{value}"
        )
    return value


def _section_bool(
    parser: configparser.ConfigParser, section: str, key: str, default: bool
) -> bool:
    raw = parser.get(section, key, fallback="true" if default else "false").strip().lower()
    if raw in ("1", "true", "yes", "on", "是", "开"):
        return True
    if raw in ("0", "false", "no", "off", "否", "关"):
        return False
    raise ConfigError(
        f"配置项 {section}.{key} 必须是布尔值（true/false），当前值为：{raw!r}"
    )


def _positive_int(parser: configparser.ConfigParser, key: str, default: int) -> int:
    return _section_int(parser, "agent", key, default)


def _positive_float(parser: configparser.ConfigParser, key: str, default: float) -> float:
    return _section_float(parser, "agent", key, default, minimum=0.000001)


def _context_window(parser: configparser.ConfigParser) -> int | None:
    raw = parser.get("agent", "context_window", fallback="").strip()
    if not raw:
        return None

    multiplier = 1
    original = raw
    lowered = raw.lower()
    if lowered.endswith("k"):
        multiplier = 1024
        raw = raw[:-1]
    elif lowered.endswith("m"):
        multiplier = 1024 * 1024
        raw = raw[:-1]

    try:
        value = int(float(raw) * multiplier)
    except ValueError as exc:
        raise ConfigError(
            f"配置项 agent.context_window 必须是 token 数（可用 128k、1m 等写法），"
            f"当前值为：{original!r}"
        ) from exc
    if value < 1024:
        raise ConfigError(f"配置项 agent.context_window 必须至少为 1024，当前值为：{value}")
    return value


def _search_option(parser: configparser.ConfigParser) -> str:
    for key in (
        "baidu_qianfan_api_key",
        "baidu qianfan api key",
        "baidu_api_key",
        "api_key",
    ):
        if parser.has_option("search", key):
            return parser.get("search", key).strip()
    return ""


def _load_search_config(parser: configparser.ConfigParser) -> SearchConfig | None:
    if not parser.has_section("search"):
        return None

    api_key = _search_option(parser)
    if not api_key or api_key == "your-baidu-qianfan-api-key":
        return SearchConfig(api_key="")

    base_url = parser.get(
        "search",
        "base_url",
        fallback="https://qianfan.baidubce.com/v2/ai_search/web_search",
    ).strip()

    top_k = _section_int(parser, "search", "top_k", 8)
    top_k = max(1, min(50, top_k))
    timeout = _section_float(parser, "search", "timeout", 20.0, minimum=0.000001)

    return SearchConfig(
        api_key=api_key,
        base_url=base_url or "https://qianfan.baidubce.com/v2/ai_search/web_search",
        top_k=top_k,
        timeout=timeout,
    )


def _load_tool_config(parser: configparser.ConfigParser) -> ToolConfig:
    defaults = ToolConfig()
    if not parser.has_section("tools"):
        return defaults
    return ToolConfig(
        fs_max_text_bytes=_section_int(
            parser, "tools", "fs_max_text_bytes", defaults.fs_max_text_bytes
        ),
        fs_text_sample_bytes=_section_int(
            parser, "tools", "fs_text_sample_bytes", defaults.fs_text_sample_bytes
        ),
        cli_timeout=_section_float(
            parser, "tools", "cli_timeout", defaults.cli_timeout, minimum=0.000001
        ),
        cli_max_output_chars=_section_int(
            parser, "tools", "cli_max_output_chars", defaults.cli_max_output_chars
        ),
        web_timeout=_section_float(
            parser, "tools", "web_timeout", defaults.web_timeout, minimum=0.000001
        ),
        web_connect_timeout=_section_float(
            parser, "tools", "web_connect_timeout", defaults.web_connect_timeout, minimum=0.000001
        ),
        web_max_html_bytes=_section_int(
            parser, "tools", "web_max_html_bytes", defaults.web_max_html_bytes
        ),
        web_max_markdown_chars=_section_int(
            parser, "tools", "web_max_markdown_chars", defaults.web_max_markdown_chars
        ),
        search_max_query_width=_section_int(
            parser, "tools", "search_max_query_width", defaults.search_max_query_width
        ),
        search_max_snippet_chars=_section_int(
            parser, "tools", "search_max_snippet_chars", defaults.search_max_snippet_chars
        ),
        search_max_result_chars=_section_int(
            parser, "tools", "search_max_result_chars", defaults.search_max_result_chars
        ),
        skill_max_file_bytes=_section_int(
            parser, "tools", "skill_max_file_bytes", defaults.skill_max_file_bytes
        ),
        skill_max_name_length=_section_int(
            parser, "tools", "skill_max_name_length", defaults.skill_max_name_length
        ),
        mcp_connect_timeout=_section_float(
            parser, "tools", "mcp_connect_timeout", defaults.mcp_connect_timeout, minimum=0.000001
        ),
        mcp_call_timeout=_section_float(
            parser, "tools", "mcp_call_timeout", defaults.mcp_call_timeout, minimum=0.000001
        ),
        context_search_max_matches=_section_int(
            parser, "tools", "context_search_max_matches", defaults.context_search_max_matches
        ),
        context_search_max_snippet_chars=_section_int(
            parser,
            "tools",
            "context_search_max_snippet_chars",
            defaults.context_search_max_snippet_chars,
        ),
        context_search_max_result_chars=_section_int(
            parser,
            "tools",
            "context_search_max_result_chars",
            defaults.context_search_max_result_chars,
        ),
    )


def _load_session_config(parser: configparser.ConfigParser) -> SessionConfig:
    defaults = SessionConfig()
    if not parser.has_section("session"):
        return defaults
    directory = parser.get("session", "directory", fallback=defaults.directory).strip()
    return SessionConfig(
        directory=directory or defaults.directory,
        auto_save_on_quit=_section_bool(
            parser, "session", "auto_save_on_quit", defaults.auto_save_on_quit
        ),
    )


def _load_ui_config(parser: configparser.ConfigParser) -> UIConfig:
    defaults = UIConfig()
    if not parser.has_section("ui"):
        return defaults
    return UIConfig(
        refresh_interval=_section_float(
            parser, "ui", "refresh_interval", defaults.refresh_interval, minimum=0.05
        ),
        sidebar_breakpoint=_section_int(
            parser, "ui", "sidebar_breakpoint", defaults.sidebar_breakpoint
        ),
    )


def load_config(path: str | Path | None = None) -> AgentConfig:
    explicit = Path(path).expanduser() if path is not None else None
    env_path = (
        Path(os.environ["WAGENT_CONFIG"]).expanduser()
        if os.environ.get("WAGENT_CONFIG")
        else None
    )

    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"指定的配置文件不存在：{explicit}")
        selected = explicit
    elif env_path is not None:
        if not env_path.is_file():
            raise ConfigError(f"环境变量 WAGENT_CONFIG 指向的配置文件不存在：{env_path}")
        selected = env_path
    else:
        selected = next((candidate for candidate in _candidate_paths() if candidate.is_file()), None)
        if selected is None:
            searched = "\n".join(f"  - {candidate}" for candidate in _candidate_paths())
            raise ConfigError(f"找不到配置文件，已查找以下位置：\n{searched}")

    parser = configparser.ConfigParser()
    try:
        if not parser.read(selected, encoding="utf-8"):
            raise ConfigError(f"无法读取配置文件：{selected}")
    except configparser.Error as exc:
        raise ConfigError(f"配置文件格式错误：{selected}：{exc}") from exc

    try:
        base_url = parser["openai"]["base_url"].strip()
        api_key = parser["openai"]["api_key"].strip()
        model = parser["openai"]["model"].strip()
    except KeyError as exc:
        raise ConfigError(f"配置文件 {selected} 缺少字段：{exc}") from exc

    if not base_url or not api_key or not model:
        raise ConfigError("配置项 base_url、api_key、model 不能为空")
    if api_key == "your-api-key":
        raise ConfigError("请把配置文件中的 api_key 占位符替换成真实密钥")

    return AgentConfig(
        llm=LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=_positive_float(parser, "request_timeout", 60.0),
        ),
        max_tool_rounds=_positive_int(parser, "max_tool_rounds", 10),
        source=selected,
        search=_load_search_config(parser),
        context_window=_context_window(parser),
        compact_max_tokens=_positive_int(parser, "compact_max_tokens", 8192),
        context_warning_ratio=_section_ratio(
            parser, "agent", "context_warning_ratio", 0.60
        ),
        compact_summary_tokens=_section_int(
            parser, "agent", "compact_summary_tokens", 5000
        ),
        context_dir=parser.get(
            "agent", "context_dir", fallback=".agents/context"
        ).strip()
        or ".agents/context",
        agents_md_file=parser.get(
            "agent", "agents_md_file", fallback="AGENTS.md"
        ).strip()
        or "AGENTS.md",
        tools=_load_tool_config(parser),
        sessions=_load_session_config(parser),
        ui=_load_ui_config(parser),
    )


DEFAULT_CONFIG_TEMPLATE = """# wAgent 配置文件（首次运行时自动生成）
# 请修改 [openai] 中的 base_url、api_key 和 model，然后重新启动 wAgent。
# 其余配置均有默认值，可按需调整。

[openai]
base_url = https://api.mock.local/v1
api_key = your-api-key
model = mock-model

[agent]
max_tool_rounds = 10
request_timeout = 60
context_window = 128k
compact_max_tokens = 8192
context_warning_ratio = 0.6
compact_summary_tokens = 5000
context_dir = .agents/context
agents_md_file = AGENTS.md

[session]
directory = .agents/sessions
auto_save_on_quit = true

[ui]
refresh_interval = 0.5
sidebar_breakpoint = 100

[search]
baidu_qianfan_api_key = your-baidu-qianfan-api-key
top_k = 8
timeout = 20

[tools]
fs_max_text_bytes = 1048576
fs_text_sample_bytes = 4096
cli_timeout = 30
cli_max_output_chars = 8000
web_timeout = 20
web_connect_timeout = 10
web_max_html_bytes = 8388608
web_max_markdown_chars = 60000
search_max_query_width = 72
search_max_snippet_chars = 700
search_max_result_chars = 16000
skill_max_file_bytes = 1048576
skill_max_name_length = 64
mcp_connect_timeout = 30
mcp_call_timeout = 60
context_search_max_matches = 8
context_search_max_snippet_chars = 420
context_search_max_result_chars = 6000
"""


def create_default_config(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path is not None else Path.cwd() / "config.ini"
    target = target.resolve()
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConfigError(f"无法创建配置文件 {target}：{exc}") from exc
    return target
