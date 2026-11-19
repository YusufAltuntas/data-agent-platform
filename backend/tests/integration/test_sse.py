"""The event writer and the SSE stream (K12): subscribe, replay, live; no loss, no repeats."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, cast

import httpx
import pytest
import redis
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dap import events
from dap.api.routes import runs as runs_routes
from dap.db.session import create_sync_engine
from dap.events import EventType
from dap.settings import Settings
from tests.integration.conftest import Auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ALICE, CAROL = "alice@example.com", "carol@example.com"
# Far below the stream's idle catch-up (patched to IDLE_CATCH_UP_S below), so an event can only
# arrive in time through the K12 order or live forwarding, never through the catch-up re-read.
STREAM_TIMEOUT_S = 5.0
IDLE_CATCH_UP_S = 60.0

WriteEvent = Callable[..., events.Event]


@pytest.fixture(autouse=True)
def no_idle_catch_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_routes, "IDLE_CATCH_UP_S", IDLE_CATCH_UP_S)


class _DroppedPublish:
    """A Redis stand-in whose publishes are lost."""

    def publish(self, channel: str, message: str) -> int:
        return 0


class _CommitCheckingRedis:
    """Records, at publish time, whether the event's row is visible to another connection."""

    def __init__(self, real: redis.Redis, settings: Settings) -> None:
        self.real = real
        self.settings = settings
        self.visible_at_publish: list[bool] = []

    def publish(self, channel: str, message: str) -> int:
        engine = create_sync_engine(self.settings)
        try:
            with engine.connect() as conn:
                found = conn.scalar(
                    sa.text("SELECT count(*) FROM run_events WHERE seq = :seq"),
                    {"seq": json.loads(message)["seq"]},
                )
        finally:
            engine.dispose()
        self.visible_at_publish.append(found == 1)
        return int(self.real.publish(channel, message))


@pytest.fixture
def sync_redis(api_settings: Settings) -> Iterator[redis.Redis]:
    client = redis.Redis.from_url(api_settings.redis_url())
    yield client
    client.close()


@pytest.fixture
def run_id(api_settings: Settings) -> uuid.UUID:
    new_id = uuid.uuid4()
    engine = create_sync_engine(api_settings)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO runs (id, team_id, dataset_id, created_by, question, status)"
                    " VALUES (:id, 'sales', 'sales', :by, 'q', 'queued')"
                ),
                {"id": new_id, "by": ALICE},
            )
    finally:
        engine.dispose()
    return new_id


@pytest.fixture
def write(
    api_settings: Settings, sync_redis: redis.Redis, run_id: uuid.UUID
) -> Iterator[WriteEvent]:
    """The worker's part: the synchronous writer, one session per event."""
    engine = create_sync_engine(api_settings)

    def write_event(
        type: EventType = EventType.LLM_CALL,
        payload: dict[str, Any] | None = None,
        attempt: int = 1,
        via: Any = None,
    ) -> events.Event:
        """`via` replaces the Redis client the event is published with."""
        publisher = cast(redis.Redis, via or sync_redis)
        with Session(engine) as session:
            return events.write_event(
                session, publisher, run_id, attempt=attempt, type=type, payload=payload or {}
            )

    yield write_event
    engine.dispose()


def _finish(write: WriteEvent, status: str = "succeeded") -> events.Event:
    return write(EventType.STATUS, {"status": status})


def _parse(body: str) -> list[tuple[int, dict[str, Any]]]:
    """(SSE id, data) of each event in a text/event-stream body."""
    parsed = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "data" in fields:
            parsed.append((int(fields["id"]), json.loads(fields["data"])))
    return parsed


async def _stream(
    client: httpx.AsyncClient, run_id: uuid.UUID, headers: dict[str, str]
) -> list[tuple[int, dict[str, Any]]]:
    async with asyncio.timeout(STREAM_TIMEOUT_S):
        response = await client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse(response.text)


async def _wait_for_subscriber(client: redis.Redis, run_id: uuid.UUID) -> None:
    async with asyncio.timeout(STREAM_TIMEOUT_S):
        while client.pubsub_numsub(events.channel(run_id))[0][1] < 1:
            await asyncio.sleep(0.02)


# --- writer ---------------------------------------------------------------------------------


def test_writer_numbers_events_stores_them_and_publishes_after_commit(
    write: WriteEvent, sync_redis: redis.Redis, run_id: uuid.UUID, api_settings: Settings
) -> None:
    pubsub = sync_redis.pubsub(ignore_subscribe_messages=True)  # type: ignore[no-untyped-call]
    pubsub.subscribe(events.channel(run_id))
    pubsub.get_message(timeout=5)  # the subscribe confirmation

    first = write(EventType.STATUS, {"status": "running"})
    second = write(EventType.TOOL_CALL, {"tool": "list_tables"}, attempt=2)

    assert (first.seq, second.seq) == (1, 2)
    published = [pubsub.get_message(timeout=5) for _ in range(2)]
    assert [m["data"].decode() for m in published if m] == [first.to_wire(), second.to_wire()]
    assert json.loads(second.to_wire()) == {
        "seq": 2,
        "attempt": 2,
        "type": "tool_call",
        "payload": {"tool": "list_tables"},
        "created_at": second.created_at.isoformat(),
    }
    engine = create_sync_engine(api_settings)
    try:
        with engine.connect() as conn:
            stored = conn.execute(sa.text("SELECT seq, attempt, type FROM run_events")).all()
    finally:
        engine.dispose()
    assert [tuple(r) for r in stored] == [(1, 1, "status"), (2, 2, "tool_call")]
    pubsub.close()


def test_writer_publishes_only_after_the_commit(
    write: WriteEvent, sync_redis: redis.Redis, api_settings: Settings
) -> None:
    checking = _CommitCheckingRedis(sync_redis, api_settings)
    write(via=checking)
    write(via=checking)
    assert checking.visible_at_publish == [True, True]


# --- stream ---------------------------------------------------------------------------------


async def test_events_written_before_connecting_are_replayed(
    client: httpx.AsyncClient, auth: Auth, write: WriteEvent, run_id: uuid.UUID
) -> None:
    written = [write(EventType.STATUS, {"status": "running"}), write(), _finish(write)]

    received = await _stream(client, run_id, auth(ALICE))

    assert [seq for seq, _ in received] == [1, 2, 3]
    assert [data for _, data in received] == [json.loads(e.to_wire()) for e in written]


async def test_stream_of_a_finished_run_closes_after_replay(
    client: httpx.AsyncClient,
    auth: Auth,
    write: WriteEvent,
    run_id: uuid.UUID,
    api_settings: Settings,
) -> None:
    write()
    engine = create_sync_engine(api_settings)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE runs SET status = 'failed' WHERE id = :id"), {"id": run_id}
            )
    finally:
        engine.dispose()

    received = await _stream(client, run_id, auth(ALICE))

    assert [seq for seq, _ in received] == [1]


async def test_events_written_while_connected_are_streamed(
    client: httpx.AsyncClient,
    auth: Auth,
    write: WriteEvent,
    run_id: uuid.UUID,
    sync_redis: redis.Redis,
) -> None:
    write(EventType.STATUS, {"status": "running"})
    stream = asyncio.create_task(_stream(client, run_id, auth(ALICE)))
    await _wait_for_subscriber(sync_redis, run_id)

    for _ in range(3):
        await asyncio.to_thread(write)
    await asyncio.to_thread(_finish, write)

    received = await stream
    assert [seq for seq, _ in received] == [1, 2, 3, 4, 5]
    assert received[-1][1]["payload"] == {"status": "succeeded"}


async def test_writer_racing_subscribe_and_replay_loses_and_repeats_nothing(
    client: httpx.AsyncClient,
    auth: Auth,
    write: WriteEvent,
    run_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event written after subscribing but before the replay read arrives twice (DB and
    Redis); one written after the replay read arrives only live. Each must be sent once."""
    write(EventType.STATUS, {"status": "running"})
    replay: Callable[..., Awaitable[Any]] = runs_routes._replay

    async def racing_replay(*args: Any, **kwargs: Any) -> Any:
        await asyncio.to_thread(write)  # in the database and published
        result = await replay(*args, **kwargs)
        await asyncio.to_thread(write)  # published only after the replay read
        await asyncio.to_thread(_finish, write)
        return result

    monkeypatch.setattr(runs_routes, "_replay", racing_replay)

    received = await _stream(client, run_id, auth(ALICE))

    assert [seq for seq, _ in received] == [1, 2, 3, 4]


async def test_lost_publish_is_filled_in_from_the_database_in_order(
    client: httpx.AsyncClient,
    auth: Auth,
    write: WriteEvent,
    run_id: uuid.UUID,
    sync_redis: redis.Redis,
) -> None:
    write(EventType.STATUS, {"status": "running"})
    stream = asyncio.create_task(_stream(client, run_id, auth(ALICE)))
    await _wait_for_subscriber(sync_redis, run_id)

    await asyncio.to_thread(write, via=_DroppedPublish())  # stored, never published
    await asyncio.to_thread(write)
    await asyncio.to_thread(_finish, write)

    received = await stream
    assert [seq for seq, _ in received] == [1, 2, 3, 4]


async def test_last_event_id_skips_events_already_seen(
    client: httpx.AsyncClient, auth: Auth, write: WriteEvent, run_id: uuid.UUID
) -> None:
    for _ in range(4):
        write()
    _finish(write)

    received = await _stream(client, run_id, {**auth(ALICE), "Last-Event-ID": "3"})

    assert [seq for seq, _ in received] == [4, 5]


async def test_stream_of_another_teams_run_is_404(
    client: httpx.AsyncClient, auth: Auth, run_id: uuid.UUID
) -> None:
    response = await client.get(f"/api/runs/{run_id}/events", headers=auth(CAROL))
    assert response.status_code == 404
