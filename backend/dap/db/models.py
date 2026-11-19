"""SQLAlchemy models of the dap database (design §5)."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


def _one_of(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(f"'{v}'" for v in values)})"


class Base(DeclarativeBase):
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    litellm_team_id: Mapped[str | None] = mapped_column(sa.String(200))
    llm_key_enc: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (sa.CheckConstraint(_one_of("role", Role), name="role"),)

    team_id: Mapped[str] = mapped_column(
        sa.ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(sa.String(320), primary_key=True)
    role: Mapped[str] = mapped_column(sa.String(16))


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text)
    db_role: Mapped[str] = mapped_column(sa.String(63))


class DatasetGrant(Base):
    __tablename__ = "dataset_grants"

    team_id: Mapped[str] = mapped_column(
        sa.ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[str] = mapped_column(
        sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        sa.CheckConstraint(_one_of("status", RunStatus), name="status"),
        sa.Index("ix_runs_team_id_created_at", "team_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    team_id: Mapped[str] = mapped_column(sa.ForeignKey("teams.id"))
    dataset_id: Mapped[str] = mapped_column(sa.ForeignKey("datasets.id"))
    created_by: Mapped[str] = mapped_column(sa.String(320))
    question: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(32))
    attempts: Mapped[int] = mapped_column(server_default="0")
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.String(200))
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6))
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (sa.UniqueConstraint("run_id", "seq"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"))
    seq: Mapped[int]
    attempt: Mapped[int]
    type: Mapped[str] = mapped_column(sa.String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    actor: Mapped[str] = mapped_column(sa.String(320))
    action: Mapped[str] = mapped_column(sa.String(64))
    target: Mapped[str] = mapped_column(sa.String(200))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = _created_at()
