"""Request dependencies: app resources, the authenticated user and team authorization."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
import redis.asyncio as aioredis
import sqlalchemy as sa
from celery import Celery
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dap.api.auth import AuthError, TokenVerifier
from dap.authz import Action, OwnedRun, TeamRef, User, can
from dap.db.models import DatasetGrant, Membership, Role, Team
from dap.settings import Settings


@dataclass(frozen=True)
class Resources:
    """Clients that live for the app's lifespan."""

    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: aioredis.Redis
    verifier: TokenVerifier
    http: httpx.AsyncClient  # outgoing calls (LiteLLM)
    celery: Celery  # publishes run tasks


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)


ResourcesDep = Annotated[Resources, Depends(get_resources)]


async def get_session(resources: ResourcesDep) -> AsyncIterator[AsyncSession]:
    async with resources.sessions() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


async def current_user(
    resources: ResourcesDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        identity = await resources.verifier.verify(credentials.credentials)
    except AuthError:
        raise _UNAUTHORIZED from None
    rows = await session.execute(
        sa.select(Membership.team_id, Membership.role).where(Membership.email == identity.email)
    )
    return User(
        email=identity.email,
        roles={team_id: Role(role) for team_id, role in rows},
        platform_admin=identity.platform_admin,
    )


UserDep = Annotated[User, Depends(current_user)]


async def authorize_team(
    session: AsyncSession,
    user: User,
    team_id: str,
    action: Action,
    resource: str | OwnedRun | None = None,
) -> TeamRef:
    """Load the team and check `action` on it.

    A missing team and a team the user may not see are the same 404; a visible team where the
    action is not allowed is 403 (design §6).
    """
    team_exists = await session.scalar(sa.select(sa.exists().where(Team.id == team_id)))
    grants = await session.scalars(
        sa.select(DatasetGrant.dataset_id).where(DatasetGrant.team_id == team_id)
    )
    team = TeamRef(id=team_id, dataset_ids=frozenset(grants))
    if not team_exists or not can(user, Action.VIEW_TEAM, team):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    if not can(user, action, team, resource):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    return team
