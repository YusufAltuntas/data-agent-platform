"""Run ownership (K11): the advisory lock, the retry while another worker holds it, no leaks."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import QueuePool

from dap.agent.llm import LLMResponse, Message
from dap.agent.providers.fake import FakeProvider, default_scenario
from dap.celery_app import create_celery_app
from dap.db.models import RunStatus
from dap.settings import Settings
from dap.worker.lock import lock_key
from dap.worker.runner import WorkerContext
from dap.worker.tasks import LOCK_MAX_RETRIES, LOCK_RETRY_DELAY_S, register_tasks
from tests.integration.conftest import insert_run, load_run

pytestmark = pytest.mark.integration


@pytest.fixture
def context(worker_settings: Settings) -> Iterator[WorkerContext]:
    context = WorkerContext(worker_settings)
    yield context
    context.close()


def _connect(settings: Settings) -> psycopg.Connection[tuple[Any, ...]]:
    url = settings.dap_db_url("psycopg")
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        autocommit=True,
    )


def test_lock_key_is_derived_from_the_run_id() -> None:
    run_id = uuid.uuid4()
    assert lock_key(run_id) == lock_key(uuid.UUID(str(run_id)))
    assert lock_key(run_id) != lock_key(uuid.uuid4())
    assert -(2**63) <= lock_key(run_id) < 2**63  # a Postgres bigint


def test_task_leaves_a_locked_run_alone_and_retries(
    worker_settings: Settings, context: WorkerContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = insert_run(worker_settings)
    task = register_tasks(create_celery_app(worker_settings), context)
    countdowns: list[int | None] = []
    real_retry = task.retry

    def spy_retry(*args: Any, **kwargs: Any) -> Any:
        countdowns.append(kwargs.get("countdown"))
        return real_retry(*args, **kwargs)

    monkeypatch.setattr(task, "retry", spy_retry)

    holder = _connect(worker_settings)  # another worker that owns the run
    try:
        assert holder.execute("SELECT pg_try_advisory_lock(%s)", [lock_key(run_id)]).fetchone() == (
            True,
        )

        # Eagerly applied, each retry runs at once: the first try plus every allowed retry fail.
        result = task.apply(args=(str(run_id),))

        assert result.failed()
        assert isinstance(result.result, task.MaxRetriesExceededError)
        assert countdowns == [LOCK_RETRY_DELAY_S] * (LOCK_MAX_RETRIES + 1)
        assert (LOCK_RETRY_DELAY_S, LOCK_MAX_RETRIES) == (30, 10)
        run, events = load_run(worker_settings, run_id)
        assert (run.status, run.attempts, run.started_at, events) == (
            RunStatus.QUEUED,
            0,
            None,
            [],
        )
    finally:
        holder.close()  # the holder's session ends, Postgres drops its lock

    result = task.apply(args=(str(run_id),))

    assert result.successful()
    run, events = load_run(worker_settings, run_id)
    assert (run.status, run.attempts) == (RunStatus.SUCCEEDED, 1)
    assert {e.attempt for e in events} == {1}


def _lock_holders(settings: Settings) -> list[int]:
    """Backend pids holding an advisory lock in the dap database."""
    with _connect(settings) as conn:
        rows = conn.execute(
            "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
        ).fetchall()
    return [int(row[0]) for row in rows]


def test_lock_lives_on_its_own_connection_and_does_not_leak(worker_settings: Settings) -> None:
    holders_during_run: list[list[int]] = []
    first, *rest = default_scenario()

    def look_at_locks(messages: list[Message]) -> LLMResponse:
        holders_during_run.append(_lock_holders(worker_settings))
        return first if isinstance(first, LLMResponse) else first(messages)

    context = WorkerContext(
        worker_settings, provider_factory=lambda s, t: FakeProvider([look_at_locks, *rest])
    )
    try:
        task = register_tasks(create_celery_app(worker_settings), context)
        run_id = insert_run(worker_settings)

        assert task.apply(args=(str(run_id),)).successful()

        assert load_run(worker_settings, run_id)[0].status == RunStatus.SUCCEEDED
        [[lock_pid]] = holders_during_run  # exactly one lock while the run was executing
        # The pooled connection the run used for its writes is still open, and holds nothing.
        pool = context.engine.pool
        assert isinstance(pool, QueuePool) and pool.checkedin() == 1
        with context.engine.connect() as conn:
            pooled_pid = conn.scalar(sa.select(sa.func.pg_backend_pid()))
        assert pooled_pid != lock_pid
        assert _lock_holders(worker_settings) == []
    finally:
        context.close()
