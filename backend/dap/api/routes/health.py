"""Liveness and readiness probes."""

import asyncio
from collections.abc import Awaitable
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from kombu.connection import Connection

from dap.api.deps import ResourcesDep

CHECK_TIMEOUT_S = 3.0

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(resources: ResourcesDep) -> JSONResponse:
    checks = {
        "postgres": _postgres(resources),
        "redis": resources.redis.ping(),
        "rabbitmq": asyncio.to_thread(_rabbitmq, resources.settings.rabbitmq_url()),
    }
    results = await asyncio.gather(*(_check(c) for c in checks.values()))
    body = dict(zip(checks, results, strict=True))
    ready = all(result == "ok" for result in results)
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)


async def _check(probe: Awaitable[Any]) -> str:
    try:
        await asyncio.wait_for(probe, CHECK_TIMEOUT_S)
    except Exception:  # any failure means "not ready"
        return "error"
    return "ok"


async def _postgres(resources: ResourcesDep) -> None:
    async with resources.engine.connect() as conn:
        await conn.execute(sa.text("SELECT 1"))


def _rabbitmq(url: str) -> None:
    with Connection(url, connect_timeout=CHECK_TIMEOUT_S) as conn:
        conn.ensure_connection(max_retries=1)
