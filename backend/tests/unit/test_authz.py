"""Every cell of design §6's permission matrix, including the ones that need a resource."""

import pytest

from dap.authz import Action, TeamRef, User, can
from dap.db.models import Role, Run

ME = "me@example.com"
OTHER = "other@example.com"
TEAM = TeamRef(id="sales", dataset_ids=frozenset({"sales"}))
OWN_RUN = Run(created_by=ME)
OTHERS_RUN = Run(created_by=OTHER)

PRINCIPALS = {
    "viewer": User(email=ME, roles={"sales": Role.VIEWER}),
    "analyst": User(email=ME, roles={"sales": Role.ANALYST}),
    "admin": User(email=ME, roles={"sales": Role.ADMIN}),
    "platform-admin": User(email=ME, roles={}, platform_admin=True),
}

# (action, resource, label) -> allowed for viewer, analyst, team admin, platform-admin
MATRIX: list[tuple[Action, str | Run | None, str, tuple[bool, bool, bool, bool]]] = [
    (Action.VIEW_TEAM, None, "view-team-runs", (True, True, True, True)),
    (Action.START_RUN, "sales", "start-run-granted-dataset", (False, True, True, True)),
    (Action.START_RUN, "hr", "start-run-ungranted-dataset", (False, False, False, False)),
    (Action.START_RUN, None, "start-run-without-dataset", (False, False, False, False)),
    (Action.CANCEL_RUN, OWN_RUN, "cancel-own-run", (False, True, True, True)),
    (Action.CANCEL_RUN, OTHERS_RUN, "cancel-others-run", (False, False, True, True)),
    (Action.VIEW_BUDGET, None, "view-budget", (False, False, True, True)),
    (Action.MANAGE_MEMBERS, None, "manage-members", (False, False, True, True)),
    (Action.MANAGE_GRANTS, None, "manage-dataset-grants", (False, False, False, True)),
]

CASES = [
    pytest.param(principal, action, resource, allowed[i], id=f"{label}-{principal}")
    for action, resource, label, allowed in MATRIX
    for i, principal in enumerate(PRINCIPALS)
]


@pytest.mark.parametrize(("principal", "action", "resource", "expected"), CASES)
def test_matrix(principal: str, action: Action, resource: str | Run | None, expected: bool) -> None:
    assert can(PRINCIPALS[principal], action, TEAM, resource) is expected


@pytest.mark.parametrize("action", list(Action))
def test_non_member_can_do_nothing(action: Action) -> None:
    member_elsewhere = User(email=ME, roles={"hr": Role.ADMIN})
    resources: dict[Action, str | Run] = {Action.START_RUN: "sales", Action.CANCEL_RUN: OWN_RUN}
    resource = resources.get(action)
    assert can(member_elsewhere, action, TEAM, resource) is False


def test_team_role_does_not_carry_over_to_another_team() -> None:
    hr = TeamRef(id="hr", dataset_ids=frozenset({"hr"}))
    sales_admin = PRINCIPALS["admin"]
    assert can(sales_admin, Action.MANAGE_MEMBERS, TEAM) is True
    assert can(sales_admin, Action.MANAGE_MEMBERS, hr) is False
