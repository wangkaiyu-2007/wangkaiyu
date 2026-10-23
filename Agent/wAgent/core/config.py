from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
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
class AgentConfig:
    llm: LLMConfig
    max_tool_rounds: int = 10
    source: Path | None = None


def _candidate_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[1]
    agent_root = Path(__file__).resolve().parents[2]

    candidates = [
        project_root / "config.ini",
        agent_root / "Practice02" / "config.ini",
        Path.cwd() / "config.ini",
    ]

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _positive_int(parser: configparser.ConfigParser, key: str, default: int) -> int:
    raw = parser.get("agent", key, fallback=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"配置项 agent.{key} 必须是整数，当前值为：{raw!r}") from exc
    if value < 1:
        raise ConfigError(f"配置项 agent.{key} 必须大于 0，当前值为：{value}")
    return value


def _positive_float(parser: configparser.ConfigParser, key: str, default: float) -> float:
    raw = parser.get("agent", key, fallback=str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"配置项 agent.{key} 必须是数字，当前值为：{raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"配置项 agent.{key} 必须大于 0，当前值为：{value}")
    return value


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
    )
