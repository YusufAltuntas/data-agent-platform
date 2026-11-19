"""The run task (K10, K11, design §8): an end-to-end run through a solo Celery worker, then each
outcome of a run with the task applied in-process and a scripted FakeProvider.
"""

import importlib
import io
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import redis
import sqlalchemy as sa
import structlog
from billiard.exceptions import SoftTimeLimitExceeded
from celery import Celery
from celery.contrib.testing.worker import start_worker
from celery.exceptions import Retry
from celery.signals import celeryd_init, worker_process_shutdown, worker_shutdown
from kombu.connection import Connection
from sqlalchemy.pool import NullPool

from dap import events
from dap.agent.llm import BudgetExceededError, LLMResponse, Message
from dap.agent.providers.fake import FakeProvider, Step, default_scenario
from dap.celery_app import RUN_TASK, create_celery_app
from dap.crypto import encrypt
from dap.db.models import Run, RunEvent, RunStatus, Team
from dap.db.session import create_sync_engine
from dap.observability import metrics
from dap.observability.logging import configure_logging
from dap.observability.metrics import WORKER_REGISTRY
from dap.observability.tracing import Tracer, create_tracer
from dap.settings import Settings, get_settings
from dap.worker import runner
from dap.worker.runner import WorkerContext, build_provider
from dap.worker.tasks import LOCK_MAX_RETRIES, LOCK_RETRY_DELAY_S, register_tasks
from tests.fake_tracer import FakeTracer
from tests.integration.conftest import insert_run, load_run

pytestmark = pytest.mark.integration

CELERY_QUEUE = "celery"  # Celery's default queue
FINISH_TIMEOUT_S = 30.0


def _raise(error: BaseException) -> Step:
    def step(messages: list[Message]) -> LLMResponse:
        raise error

    return step


class Runs:
    """Applies the run task in-process with a scripted provider (a new one per run)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: list[FakeProvider] = []
        self._contexts: list[WorkerContext] = []

    def apply(
        self, run_id: uuid.UUID, steps: list[Step] | None = None, tracer: Tracer | None = None
    ) -> None:
        def provider(settings: Settings, team: Team) -> FakeProvider:
            self.providers.append(FakeProvider(steps))
            return self.providers[-1]

        context = WorkerContext(
            self.settings,
            provider_factory=provider,
            tracer_factory=(lambda _: tracer) if tracer else create_tracer,
        )
        self._contexts.append(context)
        result = register_tasks(create_celery_app(self.settings), context).apply(
            args=(str(run_id),)
        )
        assert result.successful(), result.result

    def close(self) -> None:
        for context in self._contexts:
            context.close()


@pytest.fixture
def runs(worker_settings: Settings) -> Iterator[Runs]:
    runs = Runs(worker_settings)
    yield runs
    runs.close()


def _worker_metric(name: str, **labels: str) -> float:
    """A worker sample; tests compare it before and after, as other tests add to it."""
    return WORKER_REGISTRY.get_sample_value(name, labels) or 0.0


def _types(run_events: list[RunEvent]) -> list[str]:
    return [e.type for e in run_events]


def _insert_events(settings: Settings, run_id: uuid.UUID, attempt: int, count: int) -> None:
    """Events of an earlier attempt that died midway."""
    engine = create_sync_engine(settings)
    try:
        with engine.begin() as conn:
            for seq in range(1, count + 1):
                conn.execute(
                    sa.insert(RunEvent).values(
                        run_id=run_id,
                        seq=seq,
                        attempt=attempt,
                        type="status" if seq == 1 else "llm_call",
                        payload={"status": "running"} if seq == 1 else {},
                    )
                )
    finally:
        engine.dispose()


def _purge_queue(settings: Settings) -> None:
    with Connection(settings.rabbitmq_url()) as conn:
        channel: Any = conn.default_channel  # the stubs only know the generic channel
        channel.queue_declare(CELERY_QUEUE, durable=True, auto_delete=False)  # as Celery does
        channel.queue_purge(CELERY_QUEUE)


def _wait_until_finished(settings: Settings, run_id: uuid.UUID) -> Run:
    deadline = time.monotonic() + FINISH_TIMEOUT_S
    while time.monotonic() < deadline:
        run, _ = load_run(settings, run_id)
        if run.status in events.TERMINAL_STATUSES:
            return run
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish in {FINISH_TIMEOUT_S} s")


def test_end_to_end_through_a_solo_worker(worker_settings: Settings) -> None:
    """The API's message, a real worker, the default fake scenario and the datasets database."""
    run_id = insert_run(worker_settings)
    _purge_queue(worker_settings)
    app = create_celery_app(worker_settings)
    context = WorkerContext(worker_settings)  # LLM_PROVIDER defaults to fake
    register_tasks(app, context)
    try:
        with start_worker(app, pool="solo", perform_ping_check=False):
            app.send_task(RUN_TASK, args=(str(run_id),))
            run = _wait_until_finished(worker_settings, run_id)
    finally:
        context.close()
        app.close()

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.attempts) == (RunStatus.SUCCEEDED, None, 1)
    assert run.answer is not None
    assert run.answer["columns"] == ["row_count"]
    assert run.answer["rows"] == [[500]]  # the first table, customers
    assert run.answer["sql"] == "SELECT COUNT(*) AS row_count FROM customers"
    assert (run.model, run.prompt_tokens, run.completion_tokens) == ("default", 300, 60)
    assert run.cost_usd == 0
    assert run.started_at is not None and run.finished_at is not None
    assert run.started_at <= run.finished_at

    assert [e.seq for e in run_events] == list(range(1, len(run_events) + 1))
    assert {e.attempt for e in run_events} == {1}
    assert _types(run_events) == [
        "status",
        *["llm_call", "tool_call", "tool_result"] * 3,
        "answer",
        "status",
    ]
    assert run_events[0].payload["status"] == "running"
    assert run_events[-1].payload["status"] == "succeeded"
    assert run_events[-2].payload == run.answer


def test_a_run_records_its_metrics(worker_settings: Settings, runs: Runs) -> None:
    """Design §9: the final status and duration, tokens and cost of each LLM call, tool calls."""
    samples = [
        ("dap_runs_finished_total", {"status": "succeeded"}),
        ("dap_run_duration_seconds_count", {}),
        ("dap_llm_tokens_total", {"model": "default", "direction": "prompt"}),
        ("dap_llm_tokens_total", {"model": "default", "direction": "completion"}),
        ("dap_tool_calls_total", {"tool": "list_tables", "outcome": "ok"}),
        ("dap_tool_calls_total", {"tool": "run_sql", "outcome": "ok"}),
        ("dap_tool_calls_total", {"tool": "final_answer", "outcome": "ok"}),
    ]
    before = [_worker_metric(name, **labels) for name, labels in samples]

    runs.apply(insert_run(worker_settings))

    after = [_worker_metric(name, **labels) for name, labels in samples]
    assert [a - b for a, b in zip(after, before, strict=True)] == [1, 1, 300, 60, 1, 1, 1]


def test_a_traced_run_has_one_trace_with_a_span_per_tool_call(
    worker_settings: Settings, runs: Runs
) -> None:
    run_id = insert_run(worker_settings)
    tracer = FakeTracer()

    runs.apply(run_id, tracer=tracer)

    run, run_events = load_run(worker_settings, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.trace_id == run_id.hex
    [root] = tracer.traces
    assert root.trace_id == run_id.hex
    tool_calls = [e.payload["name"] for e in run_events if e.type == "tool_call"]
    assert tool_calls == ["list_tables", "run_sql", "final_answer"]
    assert [s.name for s in root.children] == tool_calls
    assert all(s.ended and not s.error for s in [root, *root.children])
    assert root.output == {"status": "succeeded", "error": None}
    assert tracer.flushes == 1
    # LiteLLM writes its generations into the same trace, under the run's span (K6).
    expected = {"existing_trace_id": run_id.hex, "parent_observation_id": root.id}
    assert runs.providers[0].metadata_seen == [expected] * 3


def test_without_langfuse_keys_the_run_is_not_traced(worker_settings: Settings, runs: Runs) -> None:
    run_id = insert_run(worker_settings)

    runs.apply(run_id)  # the test settings have no Langfuse keys

    run, _ = load_run(worker_settings, run_id)
    assert (run.status, run.trace_id) == (RunStatus.SUCCEEDED, None)
    assert runs.providers[0].metadata_seen == [None] * 3


@pytest.fixture
def json_logs() -> Iterator[io.StringIO]:
    """Logging configured as in the worker, into a buffer; restored afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    stream = io.StringIO()
    configure_logging(stream=stream)
    yield stream
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()


def test_worker_log_lines_are_json_with_run_id_and_trace_id(
    worker_settings: Settings, runs: Runs, json_logs: io.StringIO
) -> None:
    run_id = insert_run(worker_settings)
    first, *_ = default_scenario()

    runs.apply(run_id, [first, _raise(RuntimeError("bug"))], tracer=FakeTracer())

    lines = [json.loads(line) for line in json_logs.getvalue().splitlines()]
    [failure] = [line for line in lines if line["logger"] == "dap.worker.runner"]
    assert (failure["run_id"], failure["trace_id"]) == (str(run_id), run_id.hex)
    assert "RuntimeError: bug" in failure["exception"]


def test_a_run_left_running_restarts_as_the_next_attempt(
    worker_settings: Settings, runs: Runs
) -> None:
    run_id = insert_run(worker_settings, status=RunStatus.RUNNING, attempts=1)
    _insert_events(worker_settings, run_id, attempt=1, count=3)

    runs.apply(run_id)

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.attempts) == (RunStatus.SUCCEEDED, 2)
    assert [e.seq for e in run_events] == list(range(1, len(run_events) + 1))
    assert [e.attempt for e in run_events[:3]] == [1, 1, 1]
    new = run_events[3:]
    assert {e.attempt for e in new} == {2}
    assert (new[0].type, new[0].payload["status"]) == ("status", "running")
    assert new[-1].payload["status"] == "succeeded"
    # The attempt started from scratch: the model saw only the system and user messages first.
    assert [m["role"] for m in runs.providers[0].messages_seen[0]] == ["system", "user"]


def test_a_run_past_its_attempts_fails_without_executing(
    worker_settings: Settings, runs: Runs
) -> None:
    run_id = insert_run(worker_settings, status=RunStatus.RUNNING, attempts=3)

    runs.apply(run_id)

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.attempts) == (RunStatus.FAILED, "too_many_attempts", 3)
    assert run.finished_at is not None
    assert runs.providers == []  # no provider was even built
    assert _types(run_events) == ["error", "status"]
    assert run_events[0].payload["code"] == "too_many_attempts"
    assert run_events[1].payload == {"status": "failed", "error": "too_many_attempts"}


def test_cancel_flag_cancels_the_run(worker_settings: Settings, runs: Runs) -> None:
    run_id = insert_run(worker_settings)
    redis_client = redis.Redis.from_url(worker_settings.redis_url())
    first, *rest = default_scenario()

    def ask_to_cancel(messages: list[Message]) -> LLMResponse:
        redis_client.set(events.cancel_key(run_id), "1", ex=60)  # as POST /cancel does
        return first if isinstance(first, LLMResponse) else first(messages)

    try:
        runs.apply(run_id, [ask_to_cancel, *rest])
    finally:
        redis_client.close()

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.answer) == (RunStatus.CANCELLED, "cancelled", None)
    assert len(runs.providers[0].messages_seen) == 1  # checked before the second step
    assert run_events[-1].payload == {"status": "cancelled", "error": "cancelled"}


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        pytest.param(
            BudgetExceededError("Budget has been exceeded"),
            RunStatus.BUDGET_EXCEEDED,
            "budget_exceeded",
            id="budget",
        ),
        pytest.param(SoftTimeLimitExceeded(), RunStatus.FAILED, "timeout", id="soft-time-limit"),
        pytest.param(RuntimeError("bug"), RunStatus.FAILED, "internal_error", id="unexpected"),
    ],
)
def test_failures_end_the_run(
    worker_settings: Settings, runs: Runs, error: Exception, status: RunStatus, code: str
) -> None:
    run_id = insert_run(worker_settings)
    first, *_ = default_scenario()
    finished = _worker_metric("dap_runs_finished_total", status=status)

    # The first step succeeds, so the failure happens mid-run, after events were written.
    runs.apply(run_id, [first, _raise(error)])

    assert _worker_metric("dap_runs_finished_total", status=status) == finished + 1

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.answer) == (status, code, None)
    assert run.finished_at is not None
    assert _types(run_events)[-2:] == ["error", "status"]
    assert run_events[-2].payload["code"] == code
    assert run_events[-1].payload == {"status": status, "error": code}
    assert [e.seq for e in run_events] == list(range(1, len(run_events) + 1))


@pytest.mark.parametrize(
    "status",
    [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BUDGET_EXCEEDED],
)
def test_a_finished_run_is_left_untouched(
    worker_settings: Settings, runs: Runs, status: RunStatus
) -> None:
    run_id = insert_run(worker_settings, status=status)

    runs.apply(run_id)

    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.attempts, run.started_at, run_events) == (status, 0, None, [])
    assert runs.providers == []


def test_an_unknown_run_is_ignored(runs: Runs) -> None:
    runs.apply(uuid.uuid4())

    assert runs.providers == []


def test_build_provider_follows_the_settings(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    team = Team(id="sales", name="Sales", llm_key_enc=encrypt(settings, "sk-team-key"))
    fake = build_provider(settings.model_copy(update={"fake_step_delay_s": 2.5}), team)
    assert isinstance(fake, FakeProvider)
    assert fake._step_delay_s == 2.5

    created: list[tuple[Any, ...]] = []
    sentinel: Any = object()

    def openai_provider(base_url: str, api_key: str, *, timeout_s: float) -> Any:
        created.append((base_url, api_key, timeout_s))
        return sentinel

    monkeypatch.setattr(runner, "OpenAICompatibleProvider", openai_provider)
    real = settings.model_copy(
        update={"llm_provider": "openai_compatible", "llm_base_url": "http://litellm:4000"}
    )
    assert build_provider(real, team) is sentinel
    # 3 attempts of 30 s fit in the 120 s soft time limit.
    assert created == [("http://litellm:4000", "sk-team-key", 30.0)]


def test_worker_app_module_is_importable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`celery -A dap.worker.app worker` builds the app from the environment, connecting nothing."""
    for name in ("postgres_password", "ds_sales_ro_password", "ds_hr_ro_password"):
        monkeypatch.setenv(name.upper(), "x")
    monkeypatch.setenv("DAP_FERNET_KEY", settings.dap_fernet_key.get_secret_value())
    monkeypatch.setenv("RABBITMQ_PASSWORD", "x")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "x")
    get_settings.cache_clear()
    monkeypatch.delitem(sys.modules, "dap.worker.app", raising=False)
    served: list[int] = []
    dead: list[int] = []
    slept: list[float] = []
    monkeypatch.setattr(metrics, "start_worker_metrics_server", served.append)
    monkeypatch.setattr(metrics, "mark_process_dead", dead.append)
    monkeypatch.setattr(time, "sleep", slept.append)
    try:
        module = importlib.import_module("dap.worker.app")
        app: Celery = module.app
        assert RUN_TASK in app.tasks
        assert served == []  # importing serves nothing
        # `celery worker` sends these in its parent process (the second when a child exits).
        worker_shutdown.send(sender=None)
        assert slept == []  # no endpoint, nothing to wait for
        celeryd_init.send(sender="worker@test", instance=None, conf=app.conf, options={})
        worker_process_shutdown.send(sender="worker@test", pid=4242, exitcode=0)
        worker_shutdown.send(sender=None)
        assert (served, dead, slept) == ([9200], [4242], [module.LAST_SCRAPE_WAIT_S])
    finally:
        # Even after a failed assertion: a connected receiver would add 20 s to later tests.
        imported = sys.modules.pop("dap.worker.app", None)
        if imported is not None:
            worker_shutdown.disconnect(imported._wait_for_last_scrape)
        get_settings.cache_clear()


class FlakyPublish:
    """Wraps the worker's Redis publish; fails the calls whose message matches `fail_on`."""

    def __init__(self, client: redis.Redis, fail_on: Callable[[int, str], bool]) -> None:
        self._publish = client.publish
        self._fail_on = fail_on
        self.calls = 0

    def __call__(self, channel: str, message: str) -> Any:
        self.calls += 1
        if self._fail_on(self.calls, message):
            raise redis.ConnectionError("Redis went away")
        return self._publish(channel, message)


def _advisory_locks(settings: Settings) -> int:
    engine = create_sync_engine(settings, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return int(
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND database"
                        " = (SELECT oid FROM pg_database WHERE datname = current_database())"
                    )
                )
                or 0
            )
    finally:
        engine.dispose()


@pytest.fixture
def context(worker_settings: Settings) -> Iterator[WorkerContext]:
    context = WorkerContext(worker_settings)
    yield context
    context.close()


def test_a_failed_opening_status_write_fails_the_run(
    worker_settings: Settings, context: WorkerContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `running` event commits, then its publish fails: the run must still end."""
    run_id = insert_run(worker_settings)
    monkeypatch.setattr(context.redis, "publish", FlakyPublish(context.redis, lambda n, _: n == 1))

    result = register_tasks(create_celery_app(worker_settings), context).apply(args=(str(run_id),))

    assert result.successful(), result.result
    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.attempts) == (RunStatus.FAILED, "internal_error", 1)
    assert _types(run_events) == ["status", "error", "status"]
    assert run_events[-1].payload == {"status": "failed", "error": "internal_error"}
    assert _advisory_locks(worker_settings) == 0


def test_a_run_that_cannot_be_recorded_is_retried_not_dropped(
    worker_settings: Settings, monkeypatch: pytest.MonkeyPatch, json_logs: io.StringIO
) -> None:
    """With the database unreachable nothing can be recorded; the message must come back."""
    # A database that does not exist fails at once (a closed port can hang on Windows).
    unreachable = worker_settings.model_copy(update={"dap_db_name": "no_such_database"})
    context = WorkerContext(unreachable, tracer_factory=lambda _: FakeTracer())
    task = register_tasks(create_celery_app(unreachable), context)
    retries: list[dict[str, Any]] = []
    run_id = uuid.uuid4()

    def spy_retry(**kwargs: Any) -> Retry:
        retries.append(kwargs)
        return Retry(exc=kwargs.get("exc"), when=kwargs.get("countdown"))

    monkeypatch.setattr(task, "retry", spy_retry)
    try:
        result = task.apply(args=(str(run_id),))
    finally:
        context.close()

    assert result.state == "RETRY"
    [retry] = retries
    assert retry["countdown"] == LOCK_RETRY_DELAY_S
    assert isinstance(retry["exc"], sa.exc.OperationalError)
    assert task.max_retries == LOCK_MAX_RETRIES
    # The line an operator searches for carries the run's ids as fields, not only in the text.
    lines = [json.loads(line) for line in json_logs.getvalue().splitlines()]
    [retrying] = [line for line in lines if line["logger"] == "dap.worker.tasks"]
    assert "could not be recorded; retrying" in retrying["event"]
    assert (retrying["run_id"], retrying["trace_id"]) == (str(run_id), run_id.hex)


def test_a_lost_publish_after_success_keeps_the_run_succeeded(
    worker_settings: Settings, context: WorkerContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_run(worker_settings)
    monkeypatch.setattr(
        context.redis,
        "publish",
        FlakyPublish(context.redis, lambda _, message: '"status": "succeeded"' in message),
    )

    # Eagerly applied, the retry runs at once and finds the run finished: it does nothing.
    result = register_tasks(create_celery_app(worker_settings), context).apply(args=(str(run_id),))

    assert result.successful(), result.result
    run, run_events = load_run(worker_settings, run_id)
    assert (run.status, run.error, run.attempts) == (RunStatus.SUCCEEDED, None, 1)
    assert run_events[-1].payload["status"] == "succeeded"
    assert _advisory_locks(worker_settings) == 0


def test_a_hard_time_limit_requeues_the_message(worker_settings: Settings) -> None:
    """Celery acknowledges a message on a hard time limit unless this is off (K10)."""
    assert create_celery_app(worker_settings).conf.task_acks_on_timeout is False
