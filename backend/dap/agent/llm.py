"""The provider-independent LLM interface (design §8, K2).

Messages and tool schemas use the OpenAI chat format, which every adapter speaks or translates.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

type Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON-encoded, exactly as the model produced it


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None  # None when the provider does not report a cost


class LLMError(Exception):
    """The provider failed in a way that ends the run; `code` becomes the run's error."""

    code = "llm_error"


class LLMUnavailableError(LLMError):
    """The provider could not be reached (429, 5xx or timeouts on every attempt)."""

    code = "llm_unavailable"


class BudgetExceededError(LLMError):
    """The team's LLM budget is spent (K4: LiteLLM is the single source of truth)."""

    code = "budget_exceeded"


class LLMProvider(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
