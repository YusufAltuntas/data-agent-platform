"""Bootstrap's LiteLLM step: one LiteLLM team with a budget and one virtual key per team, once."""

import json
from collections.abc import Callable

import httpx
import pytest
import respx
import sqlalchemy as sa

from dap.crypto import decrypt
from dap.db import bootstrap, seed
from dap.db.session import create_sync_engine
from dap.settings import Settings

pytestmark = pytest.mark.integration

BASE_URL = "http://litellm.test:4000"


@pytest.fixture
def dap_settings(settings: Settings, new_database: Callable[[], str]) -> Settings:
    fresh = settings.model_copy(
        update={
            "dap_db_name": new_database(),
            "llm_base_url": BASE_URL,
            "litellm_team_max_budget_usd": 0.5,
        }
    )
    bootstrap.migrate(fresh)
    seed.apply_seed(fresh)
    return fresh


def _team_created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"team_id": f"lt-{json.loads(request.content)['team_alias']}"})


def _key_generated(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"key": f"sk-{json.loads(request.content)['team_id']}"})


def _team_keys(settings: Settings) -> dict[str, tuple[str | None, str | None]]:
    """Team id → (LiteLLM team id, decrypted key)."""
    engine = create_sync_engine(settings)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT id, litellm_team_id, llm_key_enc FROM teams"))
            return {
                team: (litellm_id, None if key is None else decrypt(settings, key))
                for team, litellm_id, key in rows
            }
    finally:
        engine.dispose()


def _execute(settings: Settings, sql: str) -> None:
    engine = create_sync_engine(settings)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(sql))
    finally:
        engine.dispose()


def test_each_team_gets_a_budgeted_team_and_a_key_once(dap_settings: Settings) -> None:
    with respx.mock(base_url=BASE_URL) as llm, httpx.Client() as http:
        teams = llm.post("/team/new").mock(side_effect=_team_created)
        keys = llm.post("/key/generate").mock(side_effect=_key_generated)

        bootstrap.ensure_llm_keys(dap_settings, http)
        bootstrap.ensure_llm_keys(dap_settings, http)

    assert teams.call_count == 2
    assert keys.call_count == 2
    assert sorted(json.loads(c.request.content)["team_alias"] for c in teams.calls) == [
        "hr",
        "sales",
    ]
    assert {json.loads(c.request.content)["max_budget"] for c in teams.calls} == {0.5}
    assert _team_keys(dap_settings) == {
        "hr": ("lt-hr", "sk-lt-hr"),
        "sales": ("lt-sales", "sk-lt-sales"),
    }


def test_a_team_without_a_key_keeps_its_litellm_team(dap_settings: Settings) -> None:
    """A run that stopped between creating the team and its key resumes without a second team."""
    _execute(dap_settings, "UPDATE teams SET litellm_team_id = 'lt-earlier' WHERE id = 'sales'")

    with respx.mock(base_url=BASE_URL) as llm, httpx.Client() as http:
        teams = llm.post("/team/new").mock(side_effect=_team_created)
        llm.post("/key/generate").mock(side_effect=_key_generated)
        bootstrap.ensure_llm_keys(dap_settings, http)

    assert [json.loads(c.request.content)["team_alias"] for c in teams.calls] == ["hr"]
    assert _team_keys(dap_settings)["sales"] == ("lt-earlier", "sk-lt-earlier")
