"""Run endpoints: create (authz, rate limit, budget, queue), list, detail, cancel, budget."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import redis
import respx
import sqlalchemy as sa
from celery import Celery
from kombu.connection import Connection
from kombu.exceptions import OperationalError
from prometheus_client import REGISTRY

from dap import events
from dap.celery_app import RUN_TASK
from dap.db.session import create_sync_engine
from dap.settings import Settings
from tests.integration.conftest import Auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ALICE, BOB, CAROL, ADMIN = (
    "alice@example.com",
    "bob@example.com",
    "carol@example.com",
    "admin@example.com",
)
CELERY_QUEUE = "celery"  # Celery's default queue
NEW_RUN = {"dataset": "sales", "question": "How many orders were placed in 2025?"}


@pytest.fixture(autouse=True)
def clean_redis(api_settings: Settings) -> Iterator[redis.Redis]:
    """Rate-limit counters and the budget cache must not leak between tests."""
    client = redis.Redis.from_url(api_settings.redis_url())
    client.flushdb()
    yield client
    client.close()


def _runs_created(team: str) -> float:
    """`dap_runs_created_total` for the team; tests compare it before and after."""
    return REGISTRY.get_sample_value("dap_runs_created_total", {"team": team}) or 0.0


def _execute(settings: Settings, query: str, **params: Any) -> list[tuple[Any, ...]]:
    engine = create_sync_engine(settings)
    try:
        with engine.begin() as conn:
            result = conn.execute(sa.text(query), params)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        engine.dispose()


def _insert_runs(settings: Settings, count: int, created_by: str = ALICE) -> list[str]:
    """Runs inserted in one transaction: they share `created_at`, so the cursor needs the id."""
    ids = [str(uuid.uuid4()) for _ in range(count)]
    engine = create_sync_engine(settings)
    try:
        with engine.begin() as conn:
            for run_id in ids:
                conn.execute(
                    sa.text(
                        "INSERT INTO runs (id, team_id, dataset_id, created_by, question, status)"
                        " VALUES (:id, 'sales', 'sales', :by, 'q', 'queued')"
                    ),
                    {"id": run_id, "by": created_by},
                )
    finally:
        engine.dispose()
    return ids


def _add_member(settings: Settings, team: str, email: str, role: str) -> None:
    _execute(
        settings,
        "INSERT INTO memberships (team_id, email, role) VALUES (:t, :e, :r)",
        t=team,
        e=email,
        r=role,
    )


def _set_litellm_team(settings: Settings, team: str, litellm_team_id: str) -> None:
    _execute(
        settings, "UPDATE teams SET litellm_team_id = :l WHERE id = :t", l=litellm_team_id, t=team
    )


def _run_count(settings: Settings) -> int:
    return int(_execute(settings, "SELECT count(*) FROM runs")[0][0])


def _purge_queue(settings: Settings) -> None:
    with Connection(settings.rabbitmq_url()) as conn:
        channel: Any = conn.default_channel  # the stubs only know the generic channel
        channel.queue_declare(CELERY_QUEUE, durable=True, auto_delete=False)  # as Celery does
        channel.queue_purge(CELERY_QUEUE)


def _queued_messages(settings: Settings) -> list[Any]:
    with Connection(settings.rabbitmq_url()) as conn:
        channel: Any = conn.default_channel  # the stubs only know the generic channel
        messages = []
        while (message := channel.basic_get(CELERY_QUEUE, no_ack=True)) is not None:
            messages.append(message)
        return messages


def _team_info(spend: float, max_budget: float | None) -> dict[str, Any]:
    return {"team_id": "lt-sales", "team_info": {"spend": spend, "max_budget": max_budget}}


# --- create ---------------------------------------------------------------------------------


async def test_alice_starts_a_run_and_it_is_queued(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    _purge_queue(api_settings)
    created = _runs_created("sales")

    response = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))

    assert response.status_code == 202
    assert _runs_created("sales") == created + 1
    run_id = response.json()["run_id"]
    assert _execute(
        api_settings, "SELECT team_id, dataset_id, created_by, status, attempts FROM runs"
    ) == [("sales", "sales", ALICE, "queued", 0)]
    messages = _queued_messages(api_settings)
    assert len(messages) == 1
    assert messages[0].headers["task"] == RUN_TASK
    args, kwargs, _ = json.loads(messages[0].body)  # Celery message protocol 2
    assert (args, kwargs) == ([run_id], {})


async def test_run_that_cannot_be_queued_is_marked_failed(
    client: httpx.AsyncClient,
    auth: Auth,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broker_down(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(Celery, "send_task", broker_down)
    created = _runs_created("sales")

    response = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))

    assert response.status_code == 503
    assert _runs_created("sales") == created  # never queued, so not created
    assert _execute(api_settings, "SELECT status, error, finished_at IS NOT NULL FROM runs") == [
        ("failed", "enqueue_failed", True)
    ]


@pytest.mark.parametrize(
    ("email", "team", "dataset", "code"),
    [
        pytest.param(BOB, "sales", "sales", 403, id="viewer"),
        pytest.param(ALICE, "sales", "hr", 403, id="dataset-not-granted"),
        pytest.param(ALICE, "hr", "hr", 404, id="other-team"),
        pytest.param(ALICE, "nope", "sales", 404, id="missing-team"),
    ],
)
async def test_unauthorized_run_requests_are_rejected(
    client: httpx.AsyncClient,
    auth: Auth,
    api_settings: Settings,
    email: str,
    team: str,
    dataset: str,
    code: int,
) -> None:
    response = await client.post(
        f"/api/teams/{team}/runs", json={**NEW_RUN, "dataset": dataset}, headers=auth(email)
    )
    assert response.status_code == code
    assert _run_count(api_settings) == 0


async def test_sixth_run_within_a_minute_is_rate_limited(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    created = _runs_created("sales")
    codes = [
        (await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))).status_code
        for _ in range(6)
    ]
    assert codes == [202] * 5 + [429]
    assert _run_count(api_settings) == 5
    assert _runs_created("sales") == created + 5


async def test_run_is_rejected_with_402_when_the_budget_is_used_up(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    _set_litellm_team(api_settings, "sales", "lt-sales")
    with respx.mock(base_url=api_settings.llm_base_url) as llm:
        route = llm.get("/team/info", params={"team_id": "lt-sales"}).respond(
            json=_team_info(spend=10.0, max_budget=10.0)
        )
        first = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))
        second = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))

    assert first.status_code == second.status_code == 402
    assert first.json()["detail"]["code"] == "budget_exceeded"
    assert _run_count(api_settings) == 0
    assert route.call_count == 1  # the second request is answered from the Redis cache
    master_key = api_settings.litellm_master_key.get_secret_value()
    assert route.calls.last.request.headers["authorization"] == f"Bearer {master_key}"


async def test_run_is_accepted_under_the_budget(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    _set_litellm_team(api_settings, "sales", "lt-sales")
    with respx.mock(base_url=api_settings.llm_base_url) as llm:
        llm.get("/team/info").respond(json=_team_info(spend=2.5, max_budget=10.0))
        response = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))
    assert response.status_code == 202


async def test_budget_check_is_skipped_without_a_litellm_team(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    with respx.mock(base_url="http://never.test", assert_all_called=False) as llm:
        response = await client.post("/api/teams/sales/runs", json=NEW_RUN, headers=auth(ALICE))
    assert response.status_code == 202
    assert llm.calls.call_count == 0


# --- list and detail ------------------------------------------------------------------------


async def test_pagination_returns_every_run_once(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    created = _insert_runs(api_settings, 7)
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        page = await client.get("/api/teams/sales/runs", params=params, headers=auth(BOB))
        assert page.status_code == 200
        body = page.json()
        seen += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 7
    assert set(seen) == set(created)


async def test_non_member_cannot_list_runs(client: httpx.AsyncClient, auth: Auth) -> None:
    response = await client.get("/api/teams/sales/runs", headers=auth(CAROL))
    assert response.status_code == 404


async def test_invalid_cursor_is_rejected(client: httpx.AsyncClient, auth: Auth) -> None:
    response = await client.get(
        "/api/teams/sales/runs", params={"cursor": "garbage"}, headers=auth(ALICE)
    )
    assert response.status_code == 400


async def test_run_detail_has_attempts_cost_and_trace(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    [run_id] = _insert_runs(api_settings, 1)
    _execute(
        api_settings,
        "UPDATE runs SET attempts = 2, cost_usd = 0.0123, prompt_tokens = 100,"
        " completion_tokens = 20, trace_id = 'trace-1' WHERE id = :id",
        id=run_id,
    )
    response = await client.get(f"/api/runs/{run_id}", headers=auth(BOB))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run_id
    assert body["status"] == "queued"
    assert body["attempts"] == 2
    assert body["cost_usd"] == pytest.approx(0.0123)
    assert (body["prompt_tokens"], body["completion_tokens"]) == (100, 20)
    assert body["trace_id"] == "trace-1"
    assert body["answer"] is None and body["error"] is None


async def test_run_of_another_team_looks_missing(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    [run_id] = _insert_runs(api_settings, 1)
    hidden = await client.get(f"/api/runs/{run_id}", headers=auth(CAROL))
    missing = await client.get(f"/api/runs/{uuid.uuid4()}", headers=auth(CAROL))
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


# --- cancel ---------------------------------------------------------------------------------


async def test_analyst_cancels_only_own_runs_and_team_admin_any(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings, clean_redis: redis.Redis
) -> None:
    _add_member(api_settings, "sales", "erin@example.com", "analyst")
    _add_member(api_settings, "sales", "dave@example.com", "admin")
    [run_id] = _insert_runs(api_settings, 1, created_by=ALICE)
    url = f"/api/runs/{run_id}/cancel"

    assert (await client.post(url, headers=auth("erin@example.com"))).status_code == 403
    assert (await client.post(url, headers=auth(BOB))).status_code == 403
    assert (await client.post(url, headers=auth(CAROL))).status_code == 404
    assert clean_redis.exists(events.cancel_key(uuid.UUID(run_id))) == 0

    assert (await client.post(url, headers=auth("dave@example.com"))).status_code == 202
    assert clean_redis.exists(events.cancel_key(uuid.UUID(run_id))) == 1
    assert _execute(api_settings, "SELECT status FROM runs") == [("queued",)]


async def test_analyst_cancels_own_run(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings, clean_redis: redis.Redis
) -> None:
    [run_id] = _insert_runs(api_settings, 1, created_by=ALICE)
    response = await client.post(f"/api/runs/{run_id}/cancel", headers=auth(ALICE))
    assert response.status_code == 202
    assert clean_redis.exists(events.cancel_key(uuid.UUID(run_id))) == 1


# --- budget ---------------------------------------------------------------------------------


async def test_team_admin_sees_spend_limit_and_per_run_costs(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    _set_litellm_team(api_settings, "sales", "lt-sales")
    [run_id] = _insert_runs(api_settings, 1)
    _execute(api_settings, "UPDATE runs SET cost_usd = 0.5 WHERE id = :id", id=run_id)

    with respx.mock(base_url=api_settings.llm_base_url) as llm:
        llm.get("/team/info").respond(json=_team_info(spend=1.25, max_budget=10.0))
        response = await client.get(
            "/api/teams/sales/budget", headers=auth(ADMIN, platform_admin=True)
        )

    assert response.status_code == 200
    body = response.json()
    assert (body["spend_usd"], body["max_budget_usd"]) == (1.25, 10.0)
    assert [(r["id"], r["cost_usd"]) for r in body["runs"]] == [(run_id, 0.5)]


async def test_budget_without_litellm_team_has_no_spend(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    response = await client.get("/api/teams/hr/budget", headers=auth(CAROL))
    assert response.status_code == 200
    assert response.json() == {
        "team": "hr",
        "spend_usd": None,
        "max_budget_usd": None,
        "runs": [],
    }


async def test_analyst_cannot_see_the_budget(client: httpx.AsyncClient, auth: Auth) -> None:
    assert (await client.get("/api/teams/sales/budget", headers=auth(ALICE))).status_code == 403
