"""Request and response bodies of the API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dap.db.models import Role, RunStatus


class TeamRole(BaseModel):
    id: str
    name: str
    role: Role


class Me(BaseModel):
    email: str
    platform_admin: bool
    teams: list[TeamRole]


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str


class MemberIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    team: str
    email: str
    role: Role


class RunIn(BaseModel):
    dataset: str
    question: str = Field(min_length=1, max_length=2000)


class RunCreated(BaseModel):
    run_id: uuid.UUID


class RunSummary(BaseModel):
    """A run in the team's list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: str
    dataset_id: str
    created_by: str
    question: str
    status: RunStatus
    attempts: int
    cost_usd: float | None
    created_at: datetime
    finished_at: datetime | None


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None  # pass as `cursor` for the next page; None on the last page


class RunDetail(RunSummary):
    answer: dict[str, Any] | None
    error: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    trace_id: str | None
    started_at: datetime | None


class RunCost(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: str
    status: RunStatus
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: datetime


class Budget(BaseModel):
    """Spend and limit come from LiteLLM (K4); None when the team has no LiteLLM team yet."""

    team: str
    spend_usd: float | None
    max_budget_usd: float | None
    runs: list[RunCost]  # most recent first
