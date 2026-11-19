"""The run task (K11): take ownership of the run with its advisory lock, then execute it.

A task that cannot get the lock does not touch the run or its events; another worker owns it,
so this one retries later and, if the run has finished by then, does nothing. Only `queued` and
`running` runs are executed; `running` means an earlier attempt died, so the run restarts from
scratch as the next attempt.
"""

import logging
import uuid

from celery import Celery, Task
from sqlalchemy.orm import Session

from dap.celery_app import RUN_TASK
from dap.db.models import Run, RunStatus
from dap.observability.logging import run_context
from dap.observability.tracing import trace_id_for
from dap.worker.lock import run_lock
from dap.worker.runner import WorkerContext, execute_run, fail_run

LOCK_RETRY_DELAY_S = 30
LOCK_MAX_RETRIES = 10
MAX_ATTEMPTS = 3
RUNNABLE_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})

logger = logging.getLogger(__name__)


def register_tasks(app: Celery, context: WorkerContext) -> Task[[str], None]:
    """Register the run task on `app`; it uses `context` for every resource."""

    @app.task(
        name=RUN_TASK,
        bind=True,
        max_retries=LOCK_MAX_RETRIES,
        default_retry_delay=LOCK_RETRY_DELAY_S,
        # Only on this app: a shared task would be added to every Celery app in the process
        # (the API's included), each copy bound to the first context registered.
        shared=False,
    )
    def run_task(self: Task[[str], None], run_id: str) -> None:
        owned_run = uuid.UUID(run_id)
        # Every log line of the task carries the run's ids as fields (design §9); the trace id
        # follows from the run id, so it is known before the run is even loaded.
        trace_id = trace_id_for(owned_run) if context.tracer.enabled else None
        with run_context(owned_run, trace_id):
            try:
                with run_lock(context.lock_engine, owned_run) as owned:
                    if owned:
                        _take_run(context, owned_run)
            except Exception as exc:
                # Nothing could be recorded (database or Redis down). Acking would leave the run
                # unfinished forever; the retry finds it `running` and counts it as an attempt.
                logger.exception("run %s could not be recorded; retrying", owned_run)
                raise self.retry(exc=exc, countdown=LOCK_RETRY_DELAY_S) from exc
            if not owned:
                raise self.retry(countdown=LOCK_RETRY_DELAY_S)

    return run_task


def _take_run(context: WorkerContext, run_id: uuid.UUID) -> None:
    """With the lock held: start the next attempt of a runnable run."""
    with Session(context.engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            logger.warning("run %s does not exist", run_id)
            return
        if run.status not in RUNNABLE_STATUSES:
            return
        if run.attempts >= MAX_ATTEMPTS:
            fail_run(
                context,
                session,
                run,
                "too_many_attempts",
                f"The run was started {run.attempts} times without finishing.",
            )
            return
        run.attempts += 1
        execute_run(context, session, run)
