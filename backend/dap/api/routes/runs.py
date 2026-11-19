"""Runs: create (rate limit, budget pre-check, queue), list, detail, cancel and the SSE stream."""

import asyncio
import base64
import binascii
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.sse import format_sse_event
from sqlalchemy.ext.asyncio import AsyncSession

from dap import events
from dap.api.deps import Resources, ResourcesDep, SessionDep, UserDep, authorize_team
from dap.api.routes.budget import team_spend
from dap.api.schemas import RunCreated, RunDetail, RunIn, RunPage, RunSummary
from dap.authz import Action, User
from dap.celery_app import RUN_TASK
from dap.db.models import Run, RunEvent, RunStatus
from dap.observability.metrics import RUNS_CREATED

RUNS_PER_MINUTE = 5
RATE_LIMIT_WINDOW_S = 60
CANCEL_FLAG_TTL_S = 24 * 3600
SUBSCRIBE_TIMEOUT_S = 5.0
# With no live event for this long the stream re-reads the database, in case a publish was lost.
IDLE_CATCH_UP_S = 15.0

router = APIRouter()

_RUN_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")


@router.post("/teams/{team}/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    team: str, body: RunIn, user: UserDep, session: SessionDep, resources: ResourcesDep
) -> RunCreated:
    await authorize_team(session, user, team, Action.START_RUN, body.dataset)
    await _check_rate_limit(resources, user)
    spend = await team_spend(session, resources, team)
    if spend is not None and spend.exceeded:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {"code": "budget_exceeded", "message": "The team's LLM budget is used up"},
        )
    run = Run(
        team_id=team,
        dataset_id=body.dataset,
        created_by=user.email,
        question=body.question,
        status=RunStatus.QUEUED,
    )
    session.add(run)
    await session.commit()
    try:
        # Publishing talks to RabbitMQ synchronously; keep it off the event loop.
        await asyncio.to_thread(resources.celery.send_task, RUN_TASK, args=[str(run.id)])
    except Exception:  # any broker failure: no worker will ever pick this run up
        run.status = RunStatus.FAILED
        run.error = "enqueue_failed"
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The run could not be queued"
        ) from None
    RUNS_CREATED.labels(team=team).inc()
    return RunCreated(run_id=run.id)


@router.get("/teams/{team}/runs")
async def list_runs(
    team: str,
    user: UserDep,
    session: SessionDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunPage:
    """Newest first. Keyset pagination on (`created_at`, `id`), so pages never overlap."""
    await authorize_team(session, user, team, Action.VIEW_TEAM)
    query = sa.select(Run).where(Run.team_id == team)
    if cursor is not None:
        created_at, run_id = _decode_cursor(cursor)
        query = query.where(sa.tuple_(Run.created_at, Run.id) < (created_at, run_id))
    rows = list(
        await session.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1))
    )
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit else None
    return RunPage(items=[RunSummary.model_validate(r) for r in page], next_cursor=next_cursor)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, user: UserDep, session: SessionDep) -> RunDetail:
    run = await _authorized_run(session, user, run_id, Action.VIEW_TEAM)
    return RunDetail.model_validate(run)


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID, user: UserDep, session: SessionDep, resources: ResourcesDep
) -> RunCreated:
    """Set the cancel flag; the worker checks it between steps and records `cancelled`."""
    await _authorized_run(session, user, run_id, Action.CANCEL_RUN)
    await resources.redis.set(events.cancel_key(run_id), "1", ex=CANCEL_FLAG_TTL_S)
    return RunCreated(run_id=run_id)


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    user: UserDep,
    session: SessionDep,
    resources: ResourcesDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> StreamingResponse:
    await _authorized_run(session, user, run_id, Action.VIEW_TEAM)
    await session.close()  # the stream can stay open for minutes; do not hold a connection
    return StreamingResponse(
        _event_stream(resources, run_id, after=last_event_id or 0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def _event_stream(
    resources: Resources, run_id: uuid.UUID, after: int
) -> AsyncIterator[bytes]:
    """K12: subscribe first, then replay from the database, then forward live events.

    `after` is the last `seq` sent; anything at or below it (replayed, or seen by the client
    before reconnecting) is skipped, so an event that is both stored and published is sent once.
    """
    pubsub = resources.redis.pubsub()
    try:
        await pubsub.subscribe(events.channel(run_id))
        confirmation = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
        if confirmation is None or confirmation["type"] != "subscribe":
            raise RuntimeError(f"Redis did not confirm the subscription for run {run_id}")

        run_finished, stored = await _replay(resources, run_id, after)
        while True:
            for event in stored:
                if event.seq <= after:
                    continue
                yield format_sse_event(data_str=event.to_wire(), id=str(event.seq))
                after = event.seq
                if event.is_terminal:
                    return
            if run_finished:
                return
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=IDLE_CATCH_UP_S
            )
            live = None if message is None else events.Event.from_wire(message["data"])
            if live is None or live.seq > after + 1:
                # Idle, or a publish was lost: fill in from the database, in order.
                run_finished, stored = await _replay(resources, run_id, after)
            else:
                stored = [live]
    finally:
        await pubsub.aclose()  # type: ignore[no-untyped-call]


async def _replay(
    resources: Resources, run_id: uuid.UUID, after: int
) -> tuple[bool, list[events.Event]]:
    """Whether the run has finished, and its stored events after `seq` `after`.

    The status is read before the events: the worker commits a final status together with its
    status event, so a finished run's events are all visible to the second read.
    """
    async with resources.sessions() as session:
        run_status = await session.scalar(sa.select(Run.status).where(Run.id == run_id))
        rows = await session.scalars(
            sa.select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.seq > after)
            .order_by(RunEvent.seq)
        )
        stored = [events.Event.from_row(row) for row in rows]
    return run_status in events.TERMINAL_STATUSES, stored


async def _authorized_run(
    session: AsyncSession, user: User, run_id: uuid.UUID, action: Action
) -> Run:
    """Load the run and check `action` on its team; a run the user may not see is missing."""
    run = await session.get(Run, run_id)
    if run is None:
        raise _RUN_NOT_FOUND
    try:
        await authorize_team(session, user, run.team_id, action, run)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise _RUN_NOT_FOUND from None
        raise
    return run


async def _check_rate_limit(resources: Resources, user: User) -> None:
    """At most RUNS_PER_MINUTE run creations per user in a window opened by the first one."""
    key = f"dap:ratelimit:runs:{user.email}"
    async with resources.redis.pipeline(transaction=True) as pipe:
        pipe.set(key, 0, ex=RATE_LIMIT_WINDOW_S, nx=True)
        pipe.incr(key)
        _, count = await pipe.execute()
    if count > RUNS_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many runs, try again later")


def _encode_cursor(run: Run) -> str:
    raw = json.dumps([run.created_at.isoformat(), str(run.id)])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, run_id = json.loads(base64.urlsafe_b64decode(cursor))
        return datetime.fromisoformat(created_at), uuid.UUID(run_id)
    except (binascii.Error, ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from None
