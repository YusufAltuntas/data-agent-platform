"""Run tracing (K5, K6): off without keys, one trace per run and one span per tool call."""

import uuid
from typing import Any

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from dap.observability import tracing
from dap.observability.tracing import (
    LangfuseTracer,
    NoopTracer,
    RunTrace,
    Span,
    create_tracer,
)
from dap.settings import Settings
from tests.fake_tracer import FakeSpan, FakeTracer

RUN_ID = uuid.UUID("0f6c2a8e-6d1b-4a57-9a43-1c2d3e4f5a6b")


def _settings(**langfuse: Any) -> Settings:
    return Settings(
        postgres_password=SecretStr("x"),
        ds_sales_ro_password=SecretStr("x"),
        ds_hr_ro_password=SecretStr("x"),
        dap_fernet_key=SecretStr("x"),
        rabbitmq_password=SecretStr("x"),
        litellm_master_key=SecretStr("x"),
        **langfuse,
    )


def _tool_events(step: int, call_id: str, name: str, *, ok: bool = True) -> list[Any]:
    return [
        ("tool_call", {"step": step, "id": call_id, "name": name, "arguments": "{}"}),
        ("tool_result", {"step": step, "id": call_id, "name": name, "ok": ok, "data": {"n": 1}}),
    ]


class RaisingTracer(FakeTracer):
    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        raise ConnectionError("Langfuse is down")


class ChildRaisingSpan(FakeSpan):
    """A root span whose children cannot be started: `start_child` raises `error`."""

    def __init__(self, error: BaseException) -> None:
        super().__init__("f" * 16, "run", None, RUN_ID.hex)
        self._error = error

    def start_child(self, name: str, input: Any) -> Span:
        raise self._error


class ChildRaisingTracer(FakeTracer):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        self.traces.append(ChildRaisingSpan(self._error))
        return self.traces[-1]


@pytest.mark.parametrize(
    "langfuse",
    [
        pytest.param({}, id="no-keys"),
        pytest.param({"langfuse_public_key": "pk-lf-1"}, id="public-key-only"),
        pytest.param(
            {"langfuse_public_key": "", "langfuse_secret_key": SecretStr("")}, id="empty-keys"
        ),
    ],
)
def test_without_keys_no_langfuse_client_is_created(
    monkeypatch: pytest.MonkeyPatch, langfuse: dict[str, Any]
) -> None:
    def no_client(**kwargs: Any) -> Langfuse:
        raise AssertionError("the Langfuse client must not be created")

    monkeypatch.setattr(tracing, "Langfuse", no_client)

    tracer = create_tracer(_settings(**langfuse))

    assert isinstance(tracer, NoopTracer)
    assert tracer.enabled is False


def test_with_keys_the_langfuse_client_gets_them(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(tracing, "Langfuse", lambda **kwargs: created.append(kwargs))

    tracer = create_tracer(
        _settings(
            langfuse_public_key="pk-lf-1",
            langfuse_secret_key=SecretStr("sk-lf-1"),
            langfuse_host="https://langfuse.example",
        )
    )

    assert isinstance(tracer, LangfuseTracer)
    assert created == [
        {"public_key": "pk-lf-1", "secret_key": "sk-lf-1", "host": "https://langfuse.example"}
    ]


def test_a_client_that_cannot_start_switches_tracing_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_client(**kwargs: Any) -> Langfuse:
        raise ValueError("bad host")

    monkeypatch.setattr(tracing, "Langfuse", broken_client)

    tracer = create_tracer(
        _settings(langfuse_public_key="pk-lf-1", langfuse_secret_key=SecretStr("sk-lf-1"))
    )

    assert isinstance(tracer, NoopTracer)
    assert "tracing is off" in caplog.text


def test_a_disabled_tracer_leaves_the_run_untraced() -> None:
    trace = RunTrace(NoopTracer(), RUN_ID, "How many customers?")
    for event in _tool_events(1, "call_1", "list_tables"):
        trace.on_event(*event)
    trace.end({"status": "succeeded", "error": None})

    assert trace.trace_id is None
    assert trace.litellm_metadata() is None


def test_one_trace_per_run_and_one_span_per_tool_call() -> None:
    tracer = FakeTracer()

    trace = RunTrace(tracer, RUN_ID, "How many customers?")
    events = [
        ("llm_call", {"step": 1}),
        *_tool_events(1, "call_1", "list_tables"),
        ("llm_call", {"step": 2}),
        *_tool_events(2, "call_1", "run_sql", ok=False),  # the same call id in a later step
        *_tool_events(2, "call_2", "final_answer"),
        ("answer", {"answer": "42"}),
    ]
    for event in events:
        trace.on_event(*event)
    trace.end({"status": "succeeded", "error": None})

    [root] = tracer.traces
    assert root.trace_id == trace.trace_id == RUN_ID.hex
    assert (root.name, root.input) == ("run", {"question": "How many customers?"})
    assert (root.ended, root.error, root.output) == (
        True,
        False,
        {"status": "succeeded", "error": None},
    )
    assert [(s.name, s.ended, s.error) for s in root.children] == [
        ("list_tables", True, False),
        ("run_sql", True, True),
        ("final_answer", True, False),
    ]
    assert root.children[0].output == {"n": 1}
    assert tracer.flushes == 1


def test_litellm_metadata_points_at_the_trace_and_its_root_span() -> None:
    trace = RunTrace(FakeTracer(), RUN_ID, "q")

    assert trace.litellm_metadata() == {
        "existing_trace_id": RUN_ID.hex,
        "parent_observation_id": "f" * 16,
    }


def test_spans_left_open_by_a_failure_are_ended_as_errors() -> None:
    tracer = FakeTracer()
    trace = RunTrace(tracer, RUN_ID, "q")
    trace.on_event("tool_call", {"step": 1, "id": "c", "name": "run_sql", "arguments": "{}"})

    trace.end(None)  # the run failed before a final status could be recorded

    [root] = tracer.traces
    assert [(s.ended, s.error) for s in [root, *root.children]] == [(True, True), (True, True)]


def test_a_tracer_failure_never_reaches_the_run(caplog: pytest.LogCaptureFixture) -> None:
    trace = RunTrace(RaisingTracer(), RUN_ID, "q")
    trace.on_event("tool_call", {"step": 1, "id": "c", "name": "run_sql", "arguments": "{}"})
    trace.end({"status": "succeeded", "error": None})

    assert trace.trace_id is None
    assert trace.litellm_metadata() is None
    assert "could not start the trace" in caplog.text


def test_a_span_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    tracer = FakeTracer()
    trace = RunTrace(tracer, RUN_ID, "q")
    trace.on_event("tool_call", {"step": 1})  # no tool name: starting the span fails

    trace.end({"status": "succeeded", "error": None})

    assert "could not trace the tool_call event" in caplog.text
    assert tracer.traces[0].ended


def test_the_soft_time_limit_is_not_swallowed_as_a_tracing_failure() -> None:
    """The limit can fire inside a span call; the run must still end as `timeout`."""
    trace = RunTrace(ChildRaisingTracer(SoftTimeLimitExceeded()), RUN_ID, "q")

    with pytest.raises(SoftTimeLimitExceeded):
        trace.on_event("tool_call", {"step": 1, "id": "c", "name": "run_sql", "arguments": "{}"})


def test_an_ordinary_span_error_is_still_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    trace = RunTrace(ChildRaisingTracer(ConnectionError("Langfuse is down")), RUN_ID, "q")

    trace.on_event("tool_call", {"step": 1, "id": "c", "name": "run_sql", "arguments": "{}"})

    assert "could not trace the tool_call event" in caplog.text


def test_langfuse_tracer_builds_the_trace_with_the_sdk() -> None:
    """The real SDK, exporting to memory instead of Langfuse: ids and nesting are as expected."""
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=f"pk-lf-test-{uuid.uuid4().hex}",  # the SDK keeps one client per key
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        span_exporter=exporter,
    )
    try:
        trace = RunTrace(LangfuseTracer(client), RUN_ID, "q")
        for event in _tool_events(1, "call_1", "list_tables"):
            trace.on_event(*event)
        metadata = trace.litellm_metadata()
        trace.end({"status": "succeeded", "error": None})
    finally:
        client.shutdown()

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"run", "list_tables"}
    root, tool = spans["run"], spans["list_tables"]
    assert {f"{s.context.trace_id:032x}" for s in (root, tool)} == {RUN_ID.hex}
    assert tool.parent is not None
    assert tool.parent.span_id == root.context.span_id
    assert metadata == {
        "existing_trace_id": RUN_ID.hex,
        "parent_observation_id": f"{root.context.span_id:016x}",
    }
