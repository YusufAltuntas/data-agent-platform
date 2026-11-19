"""Run events (K12), shared by the worker (writes them) and the API (streams them over SSE).

An event is stored in `run_events` first and published to the run's Redis channel only after
the commit, so a subscriber that replays from the database never misses one.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import redis
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dap.db.models import RunEvent, RunStatus

TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BUDGET_EXCEEDED}
)


class EventType(StrEnum):
    STATUS = "status"  # payload: {"status": <runs.status value>, ...}
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ANSWER = "answer"
    ERROR = "error"


def channel(run_id: uuid.UUID) -> str:
    """Redis pub/sub channel of a run's live events."""
    return f"dap:run:{run_id}:events"


def cancel_key(run_id: uuid.UUID) -> str:
    """Redis key whose presence asks the worker to cancel the run."""
    return f"dap:run:{run_id}:cancel"


@dataclass(frozen=True)
class Event:
    seq: int  # increasing within a run; the SSE event id
    attempt: int
    type: str
    payload: dict[str, Any]
    created_at: datetime

    @property
    def is_terminal(self) -> bool:
        """A status event with a final run status: the stream ends after it."""
        return self.type == EventType.STATUS and self.payload.get("status") in TERMINAL_STATUSES

    def to_wire(self) -> str:
        """The JSON object published to Redis and sent as SSE data."""
        return json.dumps(
            {
                "seq": self.seq,
                "attempt": self.attempt,
                "type": self.type,
                "payload": self.payload,
                "created_at": self.created_at.isoformat(),
            }
        )

    @classmethod
    def from_wire(cls, data: str | bytes) -> "Event":
        fields = json.loads(data)
        return cls(
            seq=fields["seq"],
            attempt=fields["attempt"],
            type=fields["type"],
            payload=fields["payload"],
            created_at=datetime.fromisoformat(fields["created_at"]),
        )

    @classmethod
    def from_row(cls, row: RunEvent) -> "Event":
        return cls(row.seq, row.attempt, row.type, row.payload, row.created_at)


def write_event(
    session: Session,
    redis_client: redis.Redis,
    run_id: uuid.UUID,
    *,
    attempt: int,
    type: EventType,
    payload: dict[str, Any],
) -> Event:
    """Store the next event of the run, commit, then publish it.

    Changes already pending in `session` (such as the run's new status) are committed together
    with the event, so a reader never sees a final run status without its status event. Only the
    worker that holds the run's lock writes its events (K11), so `max(seq) + 1` does not race;
    the unique (`run_id`, `seq`) constraint backs this up.
    """
    seq = session.scalar(
        sa.select(sa.func.coalesce(sa.func.max(RunEvent.seq), 0) + 1).where(
            RunEvent.run_id == run_id
        )
    )
    created_at = session.scalar(
        sa.insert(RunEvent)
        .values(run_id=run_id, seq=seq, attempt=attempt, type=type, payload=payload)
        .returning(RunEvent.created_at)
    )
    session.commit()
    assert seq is not None and created_at is not None  # both come from the statements above
    event = Event(seq, attempt, type, payload, created_at)
    redis_client.publish(channel(run_id), event.to_wire())
    return event
