"""Executes one owned run: builds the provider and tools, runs the agent loop, records the outcome.

Every event goes through `events.write_event` with the run's current attempt number; a final
status is committed together with its `status` event (design §8 error table, K11, K12).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from functools import cached_property
from typing import Any

import redis
import sqlalchemy as sa
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from dap.agent.executor import DatasetExecutor, connect
from dap.agent.llm import LLMProvider
from dap.agent.loop import AgentResult, run_agent
from dap.agent.providers.fake import FakeProvider
from dap.agent.providers.openai_compat import OpenAICompatibleProvider
from dap.agent.tools import RedisSchemaCache, Tools
from dap.crypto import decrypt
from dap.db.datasets import get_dataset
from dap.db.models import Run, RunStatus, Team
from dap.db.session import create_sync_engine
from dap.events import EventType, cancel_key, write_event
from dap.observability import metrics
from dap.observability.tracing import RunTrace, Tracer, create_tracer
from dap.settings import Settings
from dap.worker.lock import create_lock_engine

# Three attempts per step (design §8) must fit in the 120 s soft time limit (K10); with the
# adapter's default 60 s a dead provider would surface as `timeout`, not `llm_unavailable`.
LLM_TIMEOUT_S = 30.0

logger = logging.getLogger(__name__)

type ProviderFactory = Callable[[Settings, Team], LLMProvider]
type TracerFactory = Callable[[Settings], Tracer]


def build_provider(settings: Settings, team: Team) -> LLMProvider:
    """A new provider for every run: the fake one, or LiteLLM with the team's own key (K3)."""
    if settings.llm_provider == "fake":
        return FakeProvider(step_delay_s=settings.fake_step_delay_s)
    if team.llm_key_enc is None:
        raise RuntimeError(f"team {team.id} has no LLM key")
    return OpenAICompatibleProvider(
        settings.llm_base_url, decrypt(settings, team.llm_key_enc), timeout_s=LLM_TIMEOUT_S
    )


class WorkerContext:
    """Long-lived resources of one worker process, created on first use, not at import time."""

    def __init__(
        self,
        settings: Settings,
        provider_factory: ProviderFactory = build_provider,
        tracer_factory: TracerFactory = create_tracer,
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory
        self.tracer_factory = tracer_factory

    @cached_property
    def engine(self) -> sa.Engine:
        """The dap database, for the run and its events."""
        return create_sync_engine(self.settings, pool_pre_ping=True)

    @cached_property
    def lock_engine(self) -> sa.Engine:
        return create_lock_engine(self.settings)

    @cached_property
    def redis(self) -> redis.Redis:
        return redis.Redis.from_url(self.settings.redis_url())

    @cached_property
    def tracer(self) -> Tracer:
        """Langfuse, or a tracer that does nothing without keys (K5); one per worker process."""
        return self.tracer_factory(self.settings)

    def close(self) -> None:
        """Release whatever was created."""
        created = vars(self)
        if "engine" in created:
            self.engine.dispose()
        if "lock_engine" in created:
            self.lock_engine.dispose()
        if "redis" in created:
            self.redis.close()


def execute_run(context: WorkerContext, session: Session, run: Run) -> None:
    """Run the agent for `run`, whose `attempts` the caller has already counted.

    Ends with the run in a final status, whatever happens inside the loop: an unexpected error
    fails the run instead of letting the message be redelivered forever. Only a failure to
    record anything at all (database or Redis down) escapes to the task, which retries.

    The run is traced: one trace, one span per tool call.
    """
    trace = RunTrace(context.tracer, run.id, run.question)
    if trace.trace_id is not None:
        run.trace_id = trace.trace_id  # committed with the `running` status
    outcome: dict[str, Any] | None = None
    try:
        outcome = _execute_run(context, session, run, trace)
    finally:
        trace.end(outcome)


def _execute_run(
    context: WorkerContext, session: Session, run: Run, trace: RunTrace
) -> dict[str, Any]:
    """The run's final status and error, for the trace."""
    run_id, attempt = run.id, run.attempts
    try:
        run.status = RunStatus.RUNNING
        run.started_at = run.started_at or _now()
        write_event(
            session,
            context.redis,
            run_id,
            attempt=attempt,
            type=EventType.STATUS,
            payload={"status": RunStatus.RUNNING, "attempt": attempt},
        )
        result = _run_agent(context, session, run, attempt, trace)
    except SoftTimeLimitExceeded:
        session.rollback()
        fail_run(context, session, run, "timeout", "The run exceeded its time limit.")
        return {"status": RunStatus.FAILED, "error": "timeout"}
    except Exception:
        logger.exception("run %s failed with an unexpected error", run_id)
        session.rollback()
        fail_run(context, session, run, "internal_error", "The run failed with an internal error.")
        return {"status": RunStatus.FAILED, "error": "internal_error"}
    # Outside the handler: a publish failing after this commit must not turn the final status
    # into `failed`; the event is stored, so SSE replays it from the database.
    _record_result(context, session, run, result)
    return {"status": result.status, "error": result.error}


def fail_run(context: WorkerContext, session: Session, run: Run, code: str, message: str) -> None:
    """End the run as `failed`: an `error` event, then the final status with its event."""
    attempt, started_at = run.attempts, run.started_at
    write_event(
        session,
        context.redis,
        run.id,
        attempt=attempt,
        type=EventType.ERROR,
        payload={"code": code, "message": message},
    )
    run.status = RunStatus.FAILED
    run.error = code
    run.finished_at = finished_at = _now()
    write_event(
        session,
        context.redis,
        run.id,
        attempt=attempt,
        type=EventType.STATUS,
        payload={"status": RunStatus.FAILED, "error": code},
    )
    metrics.record_run_finished(RunStatus.FAILED, started_at, finished_at)


def _run_agent(
    context: WorkerContext, session: Session, run: Run, attempt: int, trace: RunTrace
) -> AgentResult:
    run_id, team = run.id, run.team_id
    spec = get_dataset(run.dataset_id)
    provider = context.provider_factory(context.settings, session.get_one(Team, run.team_id))

    def on_event(event_type: str, payload: dict[str, Any]) -> None:
        trace.on_event(event_type, payload)
        write_event(
            session,
            context.redis,
            run_id,
            attempt=attempt,
            type=EventType(event_type),
            payload=payload,
        )
        metrics.record_event(team, event_type, payload)

    # The dataset is queried as its own read-only role (K9).
    with connect(context.settings, spec) as conn:
        return run_agent(
            provider=provider,
            tools=Tools(DatasetExecutor(conn, spec.id), RedisSchemaCache(context.redis), spec),
            model=context.settings.llm_model,
            question=run.question,
            on_event=on_event,
            should_cancel=lambda: bool(context.redis.exists(cancel_key(run_id))),
            metadata=trace.litellm_metadata(),
        )


def _record_result(context: WorkerContext, session: Session, run: Run, result: AgentResult) -> None:
    started_at = run.started_at
    run.status = result.status
    run.error = result.error
    run.answer = result.answer
    run.model = result.model
    run.prompt_tokens = result.prompt_tokens
    run.completion_tokens = result.completion_tokens
    run.cost_usd = Decimal(str(result.cost_usd))
    run.finished_at = finished_at = _now()
    write_event(
        session,
        context.redis,
        run.id,
        attempt=run.attempts,
        type=EventType.STATUS,
        payload={"status": result.status, "error": result.error},
    )
    metrics.record_run_finished(result.status, started_at, finished_at)


def _now() -> datetime:
    return datetime.now(UTC)
