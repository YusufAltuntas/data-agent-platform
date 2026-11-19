"""A scripted `LLMProvider` for tests, CI and `make smoke` (K22); it never calls a model."""

import json
import time
from collections.abc import Callable, Sequence
from typing import Any

from dap.agent.llm import LLMResponse, Message, ToolCall

# A step is a fixed response or a function of the conversation so far (it may also raise).
type Step = LLMResponse | Callable[[list[Message]], LLMResponse]

FAKE_PROMPT_TOKENS = 100
FAKE_COMPLETION_TOKENS = 20


class FakeProvider:
    """Answers the n-th call of a run with the n-th step of its scenario.

    The step index is the number of assistant messages in the conversation, so the provider
    keeps no state between calls. From the second step on it waits `step_delay_s` first.
    """

    def __init__(
        self,
        steps: Sequence[Step] | None = None,
        *,
        step_delay_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._steps = list(steps) if steps is not None else default_scenario()
        self._step_delay_s = step_delay_s
        self._sleep = sleep
        self.messages_seen: list[list[Message]] = []
        self.metadata_seen: list[dict[str, Any] | None] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.messages_seen.append(list(messages))
        self.metadata_seen.append(metadata)
        index = sum(1 for m in messages if m["role"] == "assistant")
        if index >= len(self._steps):
            raise RuntimeError(f"The fake scenario has no step {index + 1}.")
        if index > 0 and self._step_delay_s > 0:
            self._sleep(self._step_delay_s)
        step = self._steps[index]
        return step if isinstance(step, LLMResponse) else step(messages)


def default_scenario() -> list[Step]:
    """`list_tables`, then a row count of the first table with `run_sql`, then `final_answer`.

    It works on any dataset because it only uses what the earlier tool results returned.
    """

    def count_first_table(messages: list[Message]) -> LLMResponse:
        return _call("run_sql", sql=_count_sql(messages))

    def answer(messages: list[Message]) -> LLMResponse:
        count = _tool_results(messages)[-1]["rows"][0][0]  # from the run_sql result
        sql = _count_sql(messages)
        return _call("final_answer", answer=f"The first table has {count} rows.", sql=sql)

    return [_call("list_tables"), count_first_table, answer]


def _count_sql(messages: list[Message]) -> str:
    table = _tool_results(messages)[0]["tables"][0]  # from the list_tables result
    return f"SELECT COUNT(*) AS row_count FROM {table}"


def _tool_results(messages: list[Message]) -> list[Any]:
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


def _call(name: str, **arguments: str) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=[ToolCall(f"fake-{name}", name, json.dumps(arguments))],
        prompt_tokens=FAKE_PROMPT_TOKENS,
        completion_tokens=FAKE_COMPLETION_TOKENS,
    )
