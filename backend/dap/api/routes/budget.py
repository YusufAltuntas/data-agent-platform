"""Team budget: spend and limit from LiteLLM (K4), per-run costs from the dap database."""

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from dap.api.deps import Resources, ResourcesDep, SessionDep, UserDep, authorize_team
from dap.api.schemas import Budget, RunCost
from dap.authz import Action
from dap.db.models import Run, Team
from dap.litellm_client import TeamSpend, cached_team_spend

BUDGET_RUNS_LIMIT = 100

router = APIRouter()


@router.get("/teams/{team}/budget")
async def get_budget(
    team: str, user: UserDep, session: SessionDep, resources: ResourcesDep
) -> Budget:
    await authorize_team(session, user, team, Action.VIEW_BUDGET)
    spend = await team_spend(session, resources, team)
    runs = await session.scalars(
        sa.select(Run)
        .where(Run.team_id == team)
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(BUDGET_RUNS_LIMIT)
    )
    return Budget(
        team=team,
        spend_usd=spend.spend_usd if spend else None,
        max_budget_usd=spend.max_budget_usd if spend else None,
        runs=[RunCost.model_validate(run) for run in runs],
    )


async def team_spend(session: AsyncSession, resources: Resources, team: str) -> TeamSpend | None:
    """The team's spend from LiteLLM (cached); None if LiteLLM has no team for it yet."""
    litellm_team_id = await session.scalar(sa.select(Team.litellm_team_id).where(Team.id == team))
    if litellm_team_id is None:
        return None
    try:
        return await cached_team_spend(
            resources.redis, resources.http, resources.settings, litellm_team_id
        )
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LiteLLM is not reachable"
        ) from None
