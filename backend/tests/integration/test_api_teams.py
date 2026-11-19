"""Team endpoints: datasets, members and grants; 404 vs 403 (design §6) and the audit log."""

from typing import Any

import httpx
import pytest
import sqlalchemy as sa

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


def _rows(settings: Settings, query: str) -> list[tuple[Any, ...]]:
    engine = create_sync_engine(settings)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(sa.text(query))]
    finally:
        engine.dispose()


def _audit(settings: Settings) -> list[tuple[Any, ...]]:
    return _rows(settings, "SELECT actor, action, target, details FROM audit_log ORDER BY id")


async def test_member_lists_the_team_datasets(client: httpx.AsyncClient, auth: Auth) -> None:
    response = await client.get("/api/teams/sales/datasets", headers=auth(BOB))
    assert response.status_code == 200
    assert [d["id"] for d in response.json()] == ["sales"]
    assert set(response.json()[0]) == {"id", "name", "description"}


async def test_non_member_and_missing_team_get_the_same_404(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    other_team = await client.get("/api/teams/hr/datasets", headers=auth(ALICE))
    missing = await client.get("/api/teams/nope/datasets", headers=auth(ALICE))
    assert other_team.status_code == missing.status_code == 404
    assert other_team.json() == missing.json()


async def test_viewer_cannot_add_members(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    response = await client.put(
        "/api/teams/sales/members/dave@example.com", json={"role": "viewer"}, headers=auth(BOB)
    )
    assert response.status_code == 403
    assert _audit(api_settings) == []


async def test_non_member_cannot_manage_members_and_gets_404(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    response = await client.put(
        "/api/teams/hr/members/dave@example.com", json={"role": "viewer"}, headers=auth(ALICE)
    )
    assert response.status_code == 404


async def test_team_admin_adds_changes_and_removes_a_member(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    url = "/api/teams/hr/members/Dave@Example.com"
    added = await client.put(url, json={"role": "viewer"}, headers=auth(CAROL))
    assert added.status_code == 200
    assert added.json() == {"team": "hr", "email": "dave@example.com", "role": "viewer"}

    changed = await client.put(url, json={"role": "analyst"}, headers=auth(CAROL))
    assert changed.status_code == 200
    assert _rows(api_settings, "SELECT role FROM memberships WHERE email = 'dave@example.com'") == [
        ("analyst",)
    ]

    removed = await client.delete(url, headers=auth(CAROL))
    assert removed.status_code == 204
    assert (await client.delete(url, headers=auth(CAROL))).status_code == 404

    target = "hr/dave@example.com"
    assert _audit(api_settings) == [
        (CAROL, "member.set", target, {"role": "viewer", "previous_role": None}),
        (CAROL, "member.set", target, {"role": "analyst", "previous_role": "viewer"}),
        (CAROL, "member.remove", target, {"previous_role": "analyst"}),
    ]


async def test_member_role_must_be_valid(client: httpx.AsyncClient, auth: Auth) -> None:
    response = await client.put(
        "/api/teams/hr/members/dave@example.com", json={"role": "owner"}, headers=auth(CAROL)
    )
    assert response.status_code == 422


async def test_new_member_sees_the_team(client: httpx.AsyncClient, auth: Auth) -> None:
    await client.put(
        "/api/teams/hr/members/dave@example.com", json={"role": "viewer"}, headers=auth(CAROL)
    )
    me = await client.get("/api/me", headers=auth("dave@example.com"))
    assert me.json()["teams"] == [{"id": "hr", "name": "HR", "role": "viewer"}]


async def test_platform_admin_manages_members_without_membership(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    response = await client.put(
        "/api/teams/sales/members/dave@example.com",
        json={"role": "admin"},
        headers=auth(ADMIN, platform_admin=True),
    )
    assert response.status_code == 200


async def test_team_admin_cannot_grant_datasets(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    response = await client.put("/api/teams/hr/datasets/sales", headers=auth(CAROL))
    assert response.status_code == 403
    assert _audit(api_settings) == []


async def test_platform_admin_grants_and_revokes_a_dataset(
    client: httpx.AsyncClient, auth: Auth, api_settings: Settings
) -> None:
    admin = auth(ADMIN, platform_admin=True)
    granted = await client.put("/api/teams/sales/datasets/hr", headers=admin)
    assert granted.status_code == 200
    assert granted.json()["id"] == "hr"

    listed = await client.get("/api/teams/sales/datasets", headers=auth(ALICE))
    assert [d["id"] for d in listed.json()] == ["hr", "sales"]

    revoked = await client.delete("/api/teams/sales/datasets/hr", headers=admin)
    assert revoked.status_code == 204
    assert (await client.delete("/api/teams/sales/datasets/hr", headers=admin)).status_code == 404

    assert _audit(api_settings) == [
        (ADMIN, "grant.add", "sales/hr", None),
        (ADMIN, "grant.remove", "sales/hr", None),
    ]


async def test_grant_of_unknown_dataset_or_team_is_404(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    admin = auth(ADMIN, platform_admin=True)
    assert (await client.put("/api/teams/sales/datasets/nope", headers=admin)).status_code == 404
    assert (await client.put("/api/teams/nope/datasets/sales", headers=admin)).status_code == 404
