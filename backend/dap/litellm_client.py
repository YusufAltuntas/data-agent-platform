"""Admin calls to the LiteLLM proxy (teams, virtual keys, spend), made with the master key.

LiteLLM is the single source of truth for budgets (K4).
"""

import json
from dataclasses import asdict, dataclass

import httpx
import redis.asyncio as aioredis

from dap.settings import Settings

SPEND_CACHE_TTL_S = 60


@dataclass(frozen=True)
class TeamSpend:
    spend_usd: float
    max_budget_usd: float | None  # None: the team has no budget limit

    @property
    def exceeded(self) -> bool:
        return self.max_budget_usd is not None and self.spend_usd >= self.max_budget_usd


def create_team(
    http: httpx.Client, settings: Settings, alias: str, *, max_budget_usd: float
) -> str:
    """Create a LiteLLM team with a budget limit; returns its LiteLLM id."""
    response = http.post(
        f"{settings.llm_base_url}/team/new",
        json={"team_alias": alias, "max_budget": max_budget_usd},
        headers=_admin_headers(settings),
    )
    response.raise_for_status()
    return str(response.json()["team_id"])


def generate_key(
    http: httpx.Client, settings: Settings, litellm_team_id: str, *, key_alias: str
) -> str:
    """Create a virtual key for the team; its spend counts against the team's budget."""
    response = http.post(
        f"{settings.llm_base_url}/key/generate",
        json={"team_id": litellm_team_id, "key_alias": key_alias},
        headers=_admin_headers(settings),
    )
    response.raise_for_status()
    return str(response.json()["key"])


async def fetch_team_spend(
    http: httpx.AsyncClient, settings: Settings, litellm_team_id: str
) -> TeamSpend:
    """Read the team's spend and limit from the proxy's team info endpoint."""
    response = await http.get(
        f"{settings.llm_base_url}/team/info",
        params={"team_id": litellm_team_id},
        headers=_admin_headers(settings),
    )
    response.raise_for_status()
    info = response.json()["team_info"]
    max_budget = info.get("max_budget")
    return TeamSpend(
        spend_usd=float(info.get("spend") or 0.0),
        max_budget_usd=None if max_budget is None else float(max_budget),
    )


async def cached_team_spend(
    redis: aioredis.Redis, http: httpx.AsyncClient, settings: Settings, litellm_team_id: str
) -> TeamSpend:
    """`fetch_team_spend`, cached in Redis for a minute."""
    key = f"dap:litellm:team-spend:{litellm_team_id}"
    cached = await redis.get(key)
    if cached is not None:
        return TeamSpend(**json.loads(cached))
    spend = await fetch_team_spend(http, settings, litellm_team_id)
    await redis.set(key, json.dumps(asdict(spend)), ex=SPEND_CACHE_TTL_S)
    return spend


def _admin_headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.litellm_master_key.get_secret_value()}"}
