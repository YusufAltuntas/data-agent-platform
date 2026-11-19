"""The current user, their teams and roles."""

import sqlalchemy as sa
from fastapi import APIRouter

from dap.api.deps import SessionDep, UserDep
from dap.api.schemas import Me, TeamRole
from dap.db.models import Team

router = APIRouter()


@router.get("/me")
async def me(user: UserDep, session: SessionDep) -> Me:
    teams = await session.scalars(sa.select(Team).where(Team.id.in_(user.roles)).order_by(Team.id))
    return Me(
        email=user.email,
        platform_admin=user.platform_admin,
        teams=[TeamRole(id=t.id, name=t.name, role=user.roles[t.id]) for t in teams],
    )
