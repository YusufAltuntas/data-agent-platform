"""Run ownership with a Postgres session advisory lock (K11).

The lock lives on a connection of its own, from an engine without a pool: closing that
connection ends the Postgres session, which releases the lock. A locked connection returned to
a pool would keep its lock (a rollback does not release session locks), so it must never be
pooled. If the worker dies, Postgres drops the lock with the dead connection.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from dap.db.session import create_sync_engine
from dap.settings import Settings


def create_lock_engine(settings: Settings) -> sa.Engine:
    return create_sync_engine(settings, poolclass=NullPool, isolation_level="AUTOCOMMIT")


def lock_key(run_id: uuid.UUID) -> int:
    """The first 64 bits of the run id as a signed bigint, the key type of advisory locks."""
    return int.from_bytes(run_id.bytes[:8], "big", signed=True)


@contextmanager
def run_lock(engine: sa.Engine, run_id: uuid.UUID) -> Iterator[bool]:
    """Try to lock the run without waiting; yields whether this caller now owns it.

    The lock is held until the block exits, when its connection is closed.
    """
    with engine.connect() as conn:
        yield bool(conn.scalar(sa.select(sa.func.pg_try_advisory_lock(lock_key(run_id)))))
