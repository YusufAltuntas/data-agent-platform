"""Authorization (design §6). Every permission decision of the application is made here."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from dap.db.models import Role


class Action(StrEnum):
    VIEW_TEAM = "view_team"  # the team's runs and datasets
    START_RUN = "start_run"  # resource: the dataset id
    CANCEL_RUN = "cancel_run"  # resource: the run
    VIEW_BUDGET = "view_budget"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_GRANTS = "manage_grants"


@dataclass(frozen=True)
class User:
    """The caller: verified e-mail, team roles from the dap database, Keycloak realm role."""

    email: str
    roles: Mapping[str, Role]  # team id -> role
    platform_admin: bool = False


@dataclass(frozen=True)
class TeamRef:
    id: str
    dataset_ids: frozenset[str] = frozenset()  # datasets granted to the team


class OwnedRun(Protocol):
    @property
    def created_by(self) -> str: ...


def can(user: User, action: Action, team: TeamRef, resource: str | OwnedRun | None = None) -> bool:
    role = user.roles.get(team.id)
    if role is None and not user.platform_admin:
        return False  # a non-member sees nothing of the team
    admin = user.platform_admin or role == Role.ADMIN

    match action:
        case Action.VIEW_TEAM:
            return True
        case Action.START_RUN:
            granted = isinstance(resource, str) and resource in team.dataset_ids
            return granted and (admin or role == Role.ANALYST)
        case Action.CANCEL_RUN:
            if admin:
                return True
            if role != Role.ANALYST or resource is None or isinstance(resource, str):
                return False
            return resource.created_by == user.email  # an analyst cancels only own runs
        case Action.VIEW_BUDGET | Action.MANAGE_MEMBERS:
            return admin
        case Action.MANAGE_GRANTS:
            return user.platform_admin
