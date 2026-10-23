from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContentDelta:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantCompleted:
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolFinished:
    name: str
    content: str
    ok: bool


@dataclass(frozen=True, slots=True)
class AgentError:
    message: str


@dataclass(frozen=True, slots=True)
class RoundStarted:
    round_number: int
    max_rounds: int


@dataclass(frozen=True, slots=True)
class UsageUpdated:
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


AgentEvent = (
    ContentDelta
    | AssistantCompleted
    | ToolStarted
    | ToolFinished
    | AgentError
    | RoundStarted
    | UsageUpdated
)
