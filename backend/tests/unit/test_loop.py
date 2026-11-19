"""The agent loop with the FakeProvider and in-memory tool fakes; no database or network."""

import json
from typing import Any

import psycopg
import pytest

from dap.agent.executor import Column, QueryError, QueryResult
from dap.agent.llm import (
    BudgetExceededError,
    LLMResponse,
    LLMUnavailableError,
    Message,
    ToolCall,
)
from dap.agent.loop import MAX_STEPS, NO_TOOL_CALL_WARNING, AgentResult, run_agent
from dap.agent.providers.fake import FakeProvider, Step
from dap.agent.tools import Tools
from dap.db.datasets import get_dataset

GOOD_SQL = "SELECT COUNT(*) FROM orders"


class FakeExecutor:
    """Answers every query with one count row; queries mentioning `nope` fail."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def run(self, query: str, max_rows: int) -> QueryResult:
        if self.error:
            raise self.error
        if "nope" in query:
            raise QueryError('column "nope" does not exist')
        return QueryResult(["count"], [(5000,)], False)

    def list_tables(self) -> list[str]:
        return ["customers", "orders"]

    def describe_table(self, table: str) -> list[Column]:
        return [Column("id", "integer", False)]


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


def _tools(executor: FakeExecutor | None = None) -> Tools:
    return Tools(executor or FakeExecutor(), MemoryCache(), get_dataset("sales"))


def _call(name: str, call_id: str = "c1", **arguments: Any) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=[ToolCall(call_id, name, json.dumps(arguments))],
        prompt_tokens=100,
        completion_tokens=10,
        cost_usd=0.001,
    )


def _text(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], prompt_tokens=100, completion_tokens=10)


def _final(sql: str = GOOD_SQL) -> LLMResponse:
    return _call("final_answer", "c-final", answer="There are 5000 orders.", sql=sql)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        json.dumps(payload)  # every payload must be JSON-serialisable
        self.events.append((event_type, payload))

    @property
    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


def _run(
    steps: list[Step] | None,
    *,
    tools: Tools | None = None,
    cancel_after_checks: int | None = None,
) -> tuple[AgentResult, Recorder, FakeProvider]:
    provider = FakeProvider(steps)
    events = Recorder()
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return cancel_after_checks is not None and checks > cancel_after_checks

    result = run_agent(
        provider=provider,
        tools=tools or _tools(),
        model="default",
        question="How many orders are there?",
        on_event=events,
        should_cancel=should_cancel,
        metadata={"trace_id": "t-1"},
    )
    return result, events, provider


def test_tool_then_final_answer_succeeds() -> None:
    result, events, provider = _run([_call("list_tables"), _final()])

    assert result.status == "succeeded"
    assert result.error is None
    assert result.answer is not None
    assert result.answer["answer"] == "There are 5000 orders."
    assert result.answer["rows"] == [[5000]]
    assert result.model == "default"
    assert (result.prompt_tokens, result.completion_tokens) == (200, 20)
    assert result.cost_usd == pytest.approx(0.002)
    assert events.types == [
        "llm_call",
        "tool_call",
        "tool_result",
        "llm_call",
        "tool_call",
        "tool_result",
        "answer",
    ]
    assert events.events[-1][1] == result.answer
    assert provider.metadata_seen == [{"trace_id": "t-1"}] * 2

    # The model saw the list_tables result before answering.
    second_call = provider.messages_seen[1]
    assert second_call[-1]["role"] == "tool"
    assert json.loads(second_call[-1]["content"]) == {"tables": ["customers", "orders"]}


def test_default_scenario_works_on_any_dataset() -> None:
    sleeps: list[float] = []
    provider = FakeProvider(step_delay_s=0.5, sleep=sleeps.append)

    result = run_agent(
        provider=provider,
        tools=_tools(),
        model="default",
        question="Anything?",
        on_event=Recorder(),
        should_cancel=lambda: False,
    )

    assert result.status == "succeeded"
    assert result.answer is not None
    assert result.answer["sql"] == "SELECT COUNT(*) AS row_count FROM customers"
    assert "5000" in result.answer["answer"]
    assert sleeps == [0.5, 0.5]  # between the three steps, not before the first


def test_no_final_answer_in_eight_steps_fails_with_step_limit() -> None:
    result, events, provider = _run([_call("list_tables")] * (MAX_STEPS + 2))

    assert result.status == "failed"
    assert result.error == "step_limit"
    assert result.answer is None
    assert len(provider.messages_seen) == MAX_STEPS
    assert events.types.count("llm_call") == MAX_STEPS
    event_type, payload = events.events[-1]
    assert (event_type, payload["code"]) == ("error", "step_limit")


def test_text_without_tool_call_is_warned_and_counts_as_a_step() -> None:
    result, events, provider = _run([_text("I think 5000."), _final()])

    assert result.status == "succeeded"
    assert len(provider.messages_seen) == 2
    assert provider.messages_seen[1][-1] == {"role": "user", "content": NO_TOOL_CALL_WARNING}
    assert events.types[:2] == ["llm_call", "llm_call"]


def test_cancel_flag_cancels_at_the_start_of_the_next_step() -> None:
    result, events, provider = _run([_call("list_tables"), _final()], cancel_after_checks=1)

    assert result.status == "cancelled"
    assert result.error == "cancelled"
    assert len(provider.messages_seen) == 1
    assert events.types == ["llm_call", "tool_call", "tool_result"]
    assert (result.prompt_tokens, result.completion_tokens) == (100, 10)


def _raise(error: Exception) -> Step:
    def step(messages: list[Message]) -> LLMResponse:
        raise error

    return step


def test_budget_error_ends_the_run_as_budget_exceeded() -> None:
    result, events, _ = _run([_call("list_tables"), _raise(BudgetExceededError("over budget"))])

    assert result.status == "budget_exceeded"
    assert result.error == "budget_exceeded"
    assert events.events[-1] == ("error", {"code": "budget_exceeded", "message": "over budget"})
    assert result.prompt_tokens == 100


def test_unreachable_provider_fails_the_run() -> None:
    result, events, _ = _run([_raise(LLMUnavailableError("down"))])

    assert result.status == "failed"
    assert result.error == "llm_unavailable"
    assert events.types == ["error"]


def test_sql_error_goes_back_to_the_model_and_the_loop_continues() -> None:
    def fixed_after_error(messages: list[Message]) -> LLMResponse:
        assert "nope" in json.loads(messages[-1]["content"])["error"]
        return _final()

    result, events, _ = _run([_call("run_sql", sql="SELECT nope FROM orders"), fixed_after_error])

    assert result.status == "succeeded"
    tool_result = events.events[2]
    assert tool_result[0] == "tool_result"
    assert tool_result[1]["ok"] is False
    assert "nope" in tool_result[1]["data"]["error"]


def test_failed_final_answer_does_not_end_the_run() -> None:
    result, _, provider = _run([_final("DELETE FROM orders"), _final()])

    assert result.status == "succeeded"
    assert len(provider.messages_seen) == 2


def test_dead_database_connection_propagates() -> None:
    tools = _tools(FakeExecutor(error=psycopg.OperationalError("connection lost")))

    with pytest.raises(psycopg.OperationalError):
        _run([_call("run_sql", sql=GOOD_SQL)], tools=tools)
