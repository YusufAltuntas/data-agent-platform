"""Both engines reach the dap database from the same settings."""

import asyncio

import pytest
import sqlalchemy as sa

from dap.db.session import create_async_engine, create_sync_engine
from dap.settings import Settings

pytestmark = pytest.mark.integration


def test_sync_engine_uses_psycopg(settings: Settings) -> None:
    engine = create_sync_engine(settings)
    try:
        assert engine.dialect.driver == "psycopg"
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT current_database()")).scalar_one() == (
                settings.dap_db_name
            )
    finally:
        engine.dispose()


def test_async_engine_uses_asyncpg(settings: Settings) -> None:
    async def current_database() -> str:
        engine = create_async_engine(settings)
        try:
            assert engine.dialect.driver == "asyncpg"
            async with engine.connect() as conn:
                result = await conn.execute(sa.text("SELECT current_database()"))
                return str(result.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(current_database()) == settings.dap_db_name
