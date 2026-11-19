"""Team datasets, members (team admin) and dataset grants (platform admin)."""

from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Path, Response, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dap.api.deps import SessionDep, UserDep, authorize_team
from dap.api.schemas import DatasetOut, MemberIn, MemberOut
from dap.authz import Action
from dap.db.models import AuditLog, Dataset, DatasetGrant, Membership

router = APIRouter(prefix="/teams/{team}")

Email = Annotated[str, Path(pattern=r"^[^@\s/]+@[^@\s/]+$", max_length=320)]


@router.get("/datasets")
async def list_datasets(team: str, user: UserDep, session: SessionDep) -> list[DatasetOut]:
    ref = await authorize_team(session, user, team, Action.VIEW_TEAM)
    datasets = await session.scalars(
        sa.select(Dataset).where(Dataset.id.in_(ref.dataset_ids)).order_by(Dataset.id)
    )
    return [DatasetOut(id=d.id, name=d.name, description=d.description) for d in datasets]


@router.put("/members/{email}")
async def put_member(
    team: str, email: Email, body: MemberIn, user: UserDep, session: SessionDep
) -> MemberOut:
    await authorize_team(session, user, team, Action.MANAGE_MEMBERS)
    email = email.lower()
    previous = await _role_of(session, team, email)
    stmt = insert(Membership).values(team_id=team, email=email, role=body.role)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Membership.team_id, Membership.email], set_={"role": body.role}
        )
    )
    details = {"role": body.role, "previous_role": previous}
    _audit(session, user.email, "member.set", f"{team}/{email}", details)
    await session.commit()
    return MemberOut(team=team, email=email, role=body.role)


@router.delete("/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(team: str, email: Email, user: UserDep, session: SessionDep) -> Response:
    await authorize_team(session, user, team, Action.MANAGE_MEMBERS)
    email = email.lower()
    previous = await _role_of(session, team, email)
    if previous is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    await session.execute(
        sa.delete(Membership).where(Membership.team_id == team, Membership.email == email)
    )
    _audit(session, user.email, "member.remove", f"{team}/{email}", {"previous_role": previous})
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/datasets/{dataset}")
async def put_grant(team: str, dataset: str, user: UserDep, session: SessionDep) -> DatasetOut:
    await authorize_team(session, user, team, Action.MANAGE_GRANTS)
    found = await session.get(Dataset, dataset)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    await session.execute(
        insert(DatasetGrant).values(team_id=team, dataset_id=dataset).on_conflict_do_nothing()
    )
    _audit(session, user.email, "grant.add", f"{team}/{dataset}")
    await session.commit()
    return DatasetOut(id=found.id, name=found.name, description=found.description)


@router.delete("/datasets/{dataset}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_grant(team: str, dataset: str, user: UserDep, session: SessionDep) -> Response:
    ref = await authorize_team(session, user, team, Action.MANAGE_GRANTS)
    if dataset not in ref.dataset_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    await session.execute(
        sa.delete(DatasetGrant).where(
            DatasetGrant.team_id == team, DatasetGrant.dataset_id == dataset
        )
    )
    _audit(session, user.email, "grant.remove", f"{team}/{dataset}")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _role_of(session: AsyncSession, team: str, email: str) -> str | None:
    return await session.scalar(
        sa.select(Membership.role).where(Membership.team_id == team, Membership.email == email)
    )


def _audit(
    session: AsyncSession,
    actor: str,
    action: str,
    target: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an admin action in the same transaction as the change."""
    session.add(AuditLog(actor=actor, action=action, target=target, details=details))
