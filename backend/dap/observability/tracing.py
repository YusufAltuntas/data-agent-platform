"""Langfuse tracing of runs (K5, K6): one trace per run, one span per tool call.

Without Langfuse keys the SDK is never started and the tracer does nothing (K5). The SDK sits
behind the small `Tracer` / `Span` interface so tests can use a fake. A tracing failure never
fails a run: `RunTrace` logs it and carries on. The run's soft time limit is not a tracing
failure: it always reaches the caller, so the run ends as `timeout`.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from billiard.exceptions import SoftTimeLimitExceeded
from langfuse import Langfuse, LangfuseSpan, LangfuseTool

from dap.settings import Settings

# Metadata keys LiteLLM's Langfuse callback reads from the request body (K6, verified against
# LiteLLM 1.110.0). `trace_id` must not be used: LiteLLM would then treat the trace as its own.
LITELLM_TRACE_ID_KEY = "existing_trace_id"
LITELLM_PARENT_OBSERVATION_KEY = "parent_observation_id"

ROOT_SPAN_NAME = "run"

logger = logging.getLogger(__name__)


@contextmanager
def _tracing_errors_logged(message: str, *args: Any) -> Iterator[None]:
    """Log and swallow a tracing failure; let the run's soft time limit through."""
    try:
        yield
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception(message, *args)


class Span(Protocol):
    @property
    def id(self) -> str:
        """The observation id (16 hex characters)."""
        ...

    def start_child(self, name: str, input: Any) -> "Span": ...

    def end(self, output: Any, *, error: bool = False) -> None: ...


class Tracer(Protocol):
    enabled: bool

    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        """The root span of a new trace with the given id (32 lowercase hex characters)."""
        ...

    def flush(self) -> None: ...


class NoopTracer:
    """Tracing switched off: nothing is started, nothing is sent."""

    enabled = False

    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        raise RuntimeError("tracing is disabled")

    def flush(self) -> None:
        pass


class LangfuseTracer:
    enabled = True

    def __init__(self, client: Langfuse) -> None:
        self._client = client

    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        return _LangfuseSpan(
            self._client.start_observation(
                trace_context={"trace_id": trace_id}, name=name, as_type="span", input=input
            )
        )

    def flush(self) -> None:
        self._client.flush()


class _LangfuseSpan:
    def __init__(self, observation: LangfuseSpan | LangfuseTool) -> None:
        self._observation = observation

    @property
    def id(self) -> str:
        return self._observation.id

    def start_child(self, name: str, input: Any) -> Span:
        return _LangfuseSpan(
            self._observation.start_observation(name=name, as_type="tool", input=input)
        )

    def end(self, output: Any, *, error: bool = False) -> None:
        self._observation.update(output=output, level="ERROR" if error else None)
        self._observation.end()


def create_tracer(settings: Settings) -> Tracer:
    """The Langfuse tracer when both keys are set; otherwise one that does nothing (K5)."""
    public_key, secret_key = settings.langfuse_public_key, settings.langfuse_secret_key
    if not public_key or not secret_key or not secret_key.get_secret_value():
        return NoopTracer()
    with _tracing_errors_logged("could not start Langfuse; tracing is off"):
        return LangfuseTracer(
            Langfuse(
                public_key=public_key,
                secret_key=secret_key.get_secret_value(),
                host=settings.langfuse_host or None,  # the SDK's default is Langfuse Cloud
            )
        )
    return NoopTracer()


def trace_id_for(run_id: uuid.UUID) -> str:
    """The run's trace id: its UUID as 32 hex characters, so it needs no lookup."""
    return run_id.hex


class RunTrace:
    """The trace of one run. Feed it the agent loop's events; end it once.

    It raises nothing but the run's soft time limit.
    """

    def __init__(self, tracer: Tracer, run_id: uuid.UUID, question: str) -> None:
        self._tracer = tracer
        self._root: Span | None = None
        self._tool_spans: dict[tuple[Any, Any], Span] = {}
        if tracer.enabled:
            with _tracing_errors_logged("could not start the trace"):
                self._root = tracer.start_trace(
                    trace_id_for(run_id), ROOT_SPAN_NAME, {"question": question}
                )
        self.trace_id = trace_id_for(run_id) if self._root is not None else None

    def litellm_metadata(self) -> dict[str, Any] | None:
        """What the provider sends to LiteLLM so its generations land in this trace (K6)."""
        if self._root is None:
            return None
        return {LITELLM_TRACE_ID_KEY: self.trace_id, LITELLM_PARENT_OBSERVATION_KEY: self._root.id}

    def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """A `tool_call` starts a span, its `tool_result` ends it; other events are ignored."""
        if self._root is None:
            return
        with _tracing_errors_logged("could not trace the %s event", event_type):
            key = (payload.get("step"), payload.get("id"))
            if event_type == "tool_call":
                self._tool_spans[key] = self._root.start_child(
                    payload["name"], payload.get("arguments")
                )
            elif event_type == "tool_result" and key in self._tool_spans:
                self._tool_spans.pop(key).end(payload.get("data"), error=not payload.get("ok"))

    def end(self, output: dict[str, Any] | None) -> None:
        """End the open spans and the trace, then flush: the process may be killed afterwards."""
        if self._root is None:
            return
        with _tracing_errors_logged("could not end the trace"):
            for span in self._tool_spans.values():  # a tool that raised never reported a result
                span.end(None, error=True)
            self._tool_spans.clear()
            failed = output is None or output.get("status") == "failed"
            self._root.end(output, error=failed)
            self._tracer.flush()
