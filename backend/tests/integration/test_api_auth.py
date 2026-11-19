"""Bearer JWT validation (design §7), `/api/me` and the health endpoints."""

import time
from typing import Any

import httpx
import jwt
import pytest

from dap.api.app import create_app
from dap.settings import Settings
from tests.integration.conftest import Auth, FakeJwks, MakeToken

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_alice_sees_her_team_and_role(client: httpx.AsyncClient, auth: Auth) -> None:
    response = await client.get("/api/me", headers=auth("alice@example.com"))
    assert response.status_code == 200
    assert response.json() == {
        "email": "alice@example.com",
        "platform_admin": False,
        "teams": [{"id": "sales", "name": "Sales", "role": "analyst"}],
    }


async def test_platform_admin_comes_from_the_realm_role(
    client: httpx.AsyncClient, auth: Auth
) -> None:
    response = await client.get("/api/me", headers=auth("admin@example.com", platform_admin=True))
    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com", "platform_admin": True, "teams": []}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"aud": "account"}, id="wrong-aud"),
        pytest.param({"aud": None}, id="no-aud"),
        pytest.param({"email_verified": False}, id="email-not-verified"),
        pytest.param({"email_verified": None}, id="no-email-verified"),
        pytest.param({"exp": int(time.time()) - 60}, id="expired"),
        pytest.param({"iss": "http://evil.test/realms/dap"}, id="wrong-iss"),
        pytest.param({"email": None}, id="no-email"),
    ],
)
async def test_invalid_tokens_get_401(
    client: httpx.AsyncClient, make_token: MakeToken, overrides: dict[str, Any]
) -> None:
    response = await client.get(
        "/api/me", headers=_bearer(make_token("alice@example.com", **overrides))
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="missing"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="garbage"),
        pytest.param({"Authorization": "Basic YWxpY2U6eA=="}, id="not-bearer"),
    ],
)
async def test_missing_or_malformed_credentials_get_401(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 401


async def test_token_signed_by_an_unpublished_key_gets_401(
    client: httpx.AsyncClient, make_token: MakeToken, fake_jwks: FakeJwks
) -> None:
    valid = jwt.decode(make_token("alice@example.com"), options={"verify_signature": False})
    forged = FakeJwks()
    forged.kid = fake_jwks.kid  # same kid and claims, different key
    response = await client.get("/api/me", headers=_bearer(forged.sign(valid)))
    assert response.status_code == 401


async def test_jwks_is_fetched_once_and_cached(
    client: httpx.AsyncClient, auth: Auth, fake_jwks: FakeJwks
) -> None:
    for _ in range(3):
        assert (await client.get("/api/me", headers=auth("alice@example.com"))).status_code == 200
    assert fake_jwks.fetches == 1


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_is_200_when_services_are_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/readyz")
    assert response.status_code == 200
    assert response.json() == {"postgres": "ok", "redis": "ok", "rabbitmq": "ok"}


async def test_readyz_is_503_when_a_service_is_down(
    api_settings: Settings, fake_jwks: FakeJwks
) -> None:
    broken = api_settings.model_copy(update={"redis_host": "127.0.0.1", "redis_port": 1})
    app = create_app(broken, jwks_fetcher=fake_jwks.fetch)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.get("/api/readyz")
    assert response.status_code == 503
    assert response.json() == {"postgres": "ok", "redis": "error", "rabbitmq": "ok"}
