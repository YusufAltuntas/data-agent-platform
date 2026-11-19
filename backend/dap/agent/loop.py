"""The agent loop (design §8): at most `MAX_STEPS` model calls, each followed by its tool calls.

Each step reports events through `on_event` (`llm_call`, `tool_call`, `tool_result`, `answer`,
`error`) with JSON-serialisable payloads; the caller persists and publishes them. Exceptions
raised by the tools themselves (e.g. a dead database connection) propagate to the caller.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from dap.agent.llm import BudgetExceededError, LLMError, LLMProvider, LLMResponse, Message
from dap.agent.tools import TOOL_SCHEMAS, Tools

MAX_STEPS = 8

SYSTEM_PROMPT = (
    "You are a data analyst. Answer the user's question about a PostgreSQL dataset by calling"
    " the tools: list_tables and describe_table to learn the schema, run_sql to run read-only"
    " SELECT queries. When you know the answer, finish by calling final_answer with the final"
    " SELECT statement in sql and a short plain-language answer (a few sentences, no markup) in"
    " answer. If the dataset cannot answer the question (the data is not there, or the request"
    " is not a read), do not invent a query: say so in answer and pass an empty string as sql."
    " Always respond with a tool call."
)
NO_TOOL_CALL_WARNING = (
    "You replied without calling a tool. Continue with the tools and finish by calling"
    " final_answer."
)

type RunStatus = Literal["succeeded", "failed", "cancelled", "budget_exceeded"]
type EventCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class AgentResult:
    status: RunStatus
    error: str | None  # e.g. step_limit, cancelled, budget_exceeded, llm_unavailable
    answer: dict[str, Any] | None  # the final_answer payload when succeeded
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


def run_agent(
    *,
    provider: LLMProvider,
    tools: Tools,
    model: str,
    question: str,
    on_event: EventCallback,
    should_cancel: Callable[[], bool],
    metadata: dict[str, Any] | None = None,
) -> AgentResult:
    messages: list[Message] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    prompt_tokens = completion_tokens = 0
    cost_usd = 0.0

    def finish(
        status: RunStatus, error: str | None = None, answer: dict[str, Any] | None = None
    ) -> AgentResult:
        return AgentResult(status, error, answer, model, prompt_tokens, completion_tokens, cost_usd)

    for step in range(1, MAX_STEPS + 1):
        if should_cancel():
            return finish("cancelled", "cancelled")
        try:
            response = provider.complete(messages, TOOL_SCHEMAS, model, metadata)
        except LLMError as exc:
            on_event("error", {"code": exc.code, "message": str(exc)})
            status: RunStatus = (
                "budget_exceeded" if isinstance(exc, BudgetExceededError) else "failed"
            )
            return finish(status, exc.code)

        prompt_tokens += response.prompt_tokens
        completion_tokens += response.completion_tokens
        cost_usd += response.cost_usd or 0.0
        on_event("llm_call", {"step": step, "model": model, **asdict(response)})
        messages.append(_assistant_message(response))

        if not response.tool_calls:
            messages.append({"role": "user", "content": NO_TOOL_CALL_WARNING})
            continue

        for call in response.tool_calls:
            on_event("tool_call", {"step": step, **asdict(call)})
            result = tools.call(call.name, call.arguments)
            on_event(
                "tool_result",
                {
                    "step": step,
                    "id": call.id,
                    "name": call.name,
                    "ok": result.ok,
                    "data": result.data,
                },
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content()})
            if call.name == "final_answer" and result.ok:
                on_event("answer", result.data)
                return finish("succeeded", answer=result.data)

    on_event("error", {"code": "step_limit", "message": f"No final answer in {MAX_STEPS} steps."})
    return finish("failed", "step_limit")


def _assistant_message(response: LLMResponse) -> Message:
    message: Message = {"role": "assistant", "content": response.text}
    if response.tool_calls:  # the OpenAI API rejects an empty tool_calls list
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ]
    return message
