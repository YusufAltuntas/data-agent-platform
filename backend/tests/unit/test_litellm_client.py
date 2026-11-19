"""Team and key creation against a mocked LiteLLM proxy (respx); no network calls."""

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from pydantic import SecretStr

from dap import litellm_client
from dap.settings import Settings

BASE_URL = "http://litellm.test:4000"
MASTER_KEY = "sk-master"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        postgres_password=SecretStr("x"),
        ds_sales_ro_password=SecretStr("x"),
        ds_hr_ro_password=SecretStr("x"),
        dap_fernet_key=SecretStr("x"),
        rabbitmq_password=SecretStr("x"),
        litellm_master_key=SecretStr(MASTER_KEY),
        llm_base_url=BASE_URL,
    )


@pytest.fixture
def router() -> Iterator[respx.Router]:
    with respx.mock(base_url=BASE_URL) as mock:
        yield mock


def test_create_team_sends_alias_and_budget(router: respx.Router, settings: Settings) -> None:
    route = router.post("/team/new").respond(200, json={"team_id": "t-123", "team_alias": "sales"})

    with httpx.Client() as http:
        team_id = litellm_client.create_team(http, settings, "sales", max_budget_usd=1.0)

    assert team_id == "t-123"
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {MASTER_KEY}"
    assert json.loads(request.content) == {"team_alias": "sales", "max_budget": 1.0}


def test_generate_key_returns_the_virtual_key(router: respx.Router, settings: Settings) -> None:
    route = router.post("/key/generate").respond(200, json={"key": "sk-team", "team_id": "t-123"})

    with httpx.Client() as http:
        key = litellm_client.generate_key(http, settings, "t-123", key_alias="dap-sales")

    assert key == "sk-team"
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {MASTER_KEY}"
    assert json.loads(request.content) == {"team_id": "t-123", "key_alias": "dap-sales"}


def test_proxy_errors_are_raised(router: respx.Router, settings: Settings) -> None:
    router.post("/team/new").respond(401, json={"error": {"message": "unauthorized"}})

    with httpx.Client() as http, pytest.raises(httpx.HTTPStatusError):
        litellm_client.create_team(http, settings, "sales", max_budget_usd=1.0)
