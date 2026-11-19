"""`LLMProvider` for any OpenAI-compatible endpoint; in the cluster this is the LiteLLM proxy."""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx
import openai

from dap.agent.llm import (
    BudgetExceededError,
    LLMError,
    LLMResponse,
    LLMUnavailableError,
    Message,
    ToolCall,
)

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
REQUEST_TIMEOUT_S = 60.0
COST_HEADER = "x-litellm-response-cost"
BUDGET_EXCEEDED_TYPE = "budget_exceeded"


def is_budget_exceeded(error: openai.APIStatusError) -> bool:
    """LiteLLM's budget error, recognised by its error type, not its HTTP status (K4)."""
    return error.type == BUDGET_EXCEEDED_TYPE


def _is_retryable(error: openai.APIStatusError) -> bool:
    return error.status_code == 429 or error.status_code >= 500


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = REQUEST_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Retries are ours (budget errors must not be retried), so the SDK's own are off.
        self._client = openai.OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0
        )
        self._sleep = sleep

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self._client.chat.completions.with_raw_response.create(
                    model=model,
                    messages=cast(Any, messages),
                    tools=cast(Any, tools),
                    # LiteLLM reads `metadata` from the request body (e.g. the trace id, K6).
                    extra_body=None if metadata is None else {"metadata": metadata},
                )
                break
            except openai.APIStatusError as exc:
                if is_budget_exceeded(exc):
                    raise BudgetExceededError(exc.message) from exc
                if not _is_retryable(exc):
                    raise LLMError(exc.message) from exc
                error: Exception = exc
            except openai.APIConnectionError as exc:  # includes timeouts
                # The SDK wraps any exception raised while sending (e.g. Celery's soft time limit).
                if isinstance(exc.__cause__, Exception) and not isinstance(
                    exc.__cause__, httpx.HTTPError
                ):
                    raise exc.__cause__ from None
                error = exc
            if attempt == MAX_ATTEMPTS:
                raise LLMUnavailableError(f"{MAX_ATTEMPTS} attempts failed: {error}") from error
            self._sleep(BACKOFF_BASE_S * 2 ** (attempt - 1))

        completion = raw.parse()
        message = completion.choices[0].message
        usage = completion.usage
        return LLMResponse(
            text=message.content,
            tool_calls=[
                ToolCall(call.id, call.function.name, call.function.arguments)
                for call in message.tool_calls or []
                if call.type == "function"
            ],
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            cost_usd=_cost(raw.headers.get(COST_HEADER)),
        )


def _cost(header: str | None) -> float | None:
    try:
        return float(header) if header is not None else None
    except ValueError:
        return None
