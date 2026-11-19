"""The OpenAI-compatible adapter against a mocked LiteLLM proxy (respx); no network calls."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from billiard.exceptions import SoftTimeLimitExceeded

from dap.agent.llm import BudgetExceededError, LLMError, LLMUnavailableError
from dap.agent.providers.openai_compat import OpenAICompatibleProvider
from dap.agent.tools import TOOL_SCHEMAS

BASE_URL = "http://litellm.test:4000"
COMPLETIONS_URL = f"{BASE_URL}/chat/completions"
MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "How many orders are there?"}]


def _completion(
    *, content: str | None = None, tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "claude-haiku-5-5",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


def _error(status: int, error_type: str, message: str = "error") -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": message, "type": error_type, "param": None}}
    )


@pytest.fixture
def router() -> Iterator[respx.Router]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def provider(sleeps: list[float]) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(BASE_URL, "sk-team-key", sleep=sleeps.append)


def _complete(provider: OpenAICompatibleProvider, **kwargs: Any) -> Any:
    return provider.complete(MESSAGES, TOOL_SCHEMAS, "default", **kwargs)


def test_reads_tool_calls_tokens_and_cost_header(
    router: respx.Router, provider: OpenAICompatibleProvider
) -> None:
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
    }
    route = router.post(COMPLETIONS_URL).respond(
        200,
        json=_completion(content="Let me check.", tool_calls=[tool_call]),
        headers={"x-litellm-response-cost": "0.00042"},
    )

    response = _complete(provider, metadata={"trace_id": "trace-1", "tags": ["a"]})

    assert response.text == "Let me check."
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("call_1", "run_sql", '{"sql": "SELECT 1"}')
    ]
    assert (response.prompt_tokens, response.completion_tokens) == (120, 30)
    assert response.cost_usd == pytest.approx(0.00042)

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-team-key"
    body = json.loads(request.content)
    assert body["model"] == "default"
    assert body["messages"] == MESSAGES
    assert body["tools"] == TOOL_SCHEMAS
    assert body["metadata"] == {"trace_id": "trace-1", "tags": ["a"]}


def test_text_only_response_without_cost_header(
    router: respx.Router, provider: OpenAICompatibleProvider
) -> None:
    route = router.post(COMPLETIONS_URL).respond(200, json=_completion(content="42"))

    response = _complete(provider)

    assert response.text == "42"
    assert response.tool_calls == []
    assert response.cost_usd is None
    assert "metadata" not in json.loads(route.calls.last.request.content)


def test_retries_after_429_and_succeeds(
    router: respx.Router, provider: OpenAICompatibleProvider, sleeps: list[float]
) -> None:
    route = router.post(COMPLETIONS_URL)
    route.side_effect = [_error(429, "rate_limit"), httpx.Response(200, json=_completion())]

    response = _complete(provider)

    assert response.prompt_tokens == 120
    assert route.call_count == 2
    assert sleeps == [1.0]


def test_three_server_errors_make_the_provider_unavailable(
    router: respx.Router, provider: OpenAICompatibleProvider, sleeps: list[float]
) -> None:
    route = router.post(COMPLETIONS_URL).respond(500, json={"error": {"message": "boom"}})

    with pytest.raises(LLMUnavailableError):
        _complete(provider)

    assert route.call_count == 3
    assert sleeps == [1.0, 2.0]  # exponential backoff between the three attempts


def test_timeouts_are_retried(
    router: respx.Router, provider: OpenAICompatibleProvider, sleeps: list[float]
) -> None:
    route = router.post(COMPLETIONS_URL)
    route.side_effect = [httpx.ReadTimeout("slow"), httpx.Response(200, json=_completion())]

    _complete(provider)

    assert route.call_count == 2


def test_errors_wrapped_by_the_sdk_are_not_retried(
    router: respx.Router, provider: OpenAICompatibleProvider, sleeps: list[float]
) -> None:
    route = router.post(COMPLETIONS_URL).mock(side_effect=SoftTimeLimitExceeded())

    with pytest.raises(SoftTimeLimitExceeded):
        _complete(provider)

    assert route.call_count == 1
    assert sleeps == []


def test_budget_exceeded_is_detected_by_error_type_and_not_retried(
    router: respx.Router, provider: OpenAICompatibleProvider, sleeps: list[float]
) -> None:
    route = router.post(COMPLETIONS_URL).mock(
        return_value=_error(429, "budget_exceeded", "Budget has been exceeded")
    )

    with pytest.raises(BudgetExceededError):
        _complete(provider)

    assert route.call_count == 1
    assert sleeps == []


def test_other_client_errors_are_not_retried(
    router: respx.Router, provider: OpenAICompatibleProvider
) -> None:
    route = router.post(COMPLETIONS_URL).mock(return_value=_error(401, "auth_error"))

    with pytest.raises(LLMError) as raised:
        _complete(provider)

    assert type(raised.value) is LLMError
    assert route.call_count == 1
