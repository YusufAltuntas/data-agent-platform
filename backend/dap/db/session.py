"""Engines for the dap database: async (asyncpg) for the API, sync (psycopg) for the worker."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext import asyncio as sa_asyncio

from dap.settings import Settings


def create_sync_engine(settings: Settings, **kwargs: Any) -> sa.Engine:
    return sa.create_engine(settings.dap_db_url("psycopg"), **kwargs)


def create_async_engine(settings: Settings, **kwargs: Any) -> sa_asyncio.AsyncEngine:
    return sa_asyncio.create_async_engine(settings.dap_db_url("asyncpg"), **kwargs)
