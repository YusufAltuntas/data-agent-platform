"""FastAPI application factory (`uvicorn --factory dap.api.app:create_app`)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import metrics as http_metrics
from sqlalchemy.ext.asyncio import async_sessionmaker

from dap.api.auth import JwksCache, JwksFetcher, TokenVerifier, http_jwks_fetcher
from dap.api.deps import Resources
from dap.api.routes import budget, health, me, runs, teams
from dap.celery_app import create_celery_app
from dap.db.session import create_async_engine
from dap.observability.logging import configure_logging
from dap.settings import Settings, get_settings

HTTP_TIMEOUT_S = 5.0  # JWKS and LiteLLM calls
# Scraped from inside the cluster only; the Ingress does not route it (design §7).
METRICS_PATH = "/api/metrics"
# The request duration histogram (and the instrumentator's other defaults), registered once per
# process in the default registry; every app built in the process (tests build many) records
# into it, as a second registration would be dropped silently.
# The library's default buckets (0.1, 0.5, 1 s) put every API request in the first one.
API_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5)
_HTTP_METRICS = http_metrics.default(latency_lowr_buckets=API_LATENCY_BUCKETS)


def create_app(
    settings: Settings | None = None, *, jwks_fetcher: JwksFetcher | None = None
) -> FastAPI:
    """Build the app. Tests pass their own settings and a JWKS fetcher that needs no network."""
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(settings, pool_pre_ping=True)
        redis = aioredis.Redis.from_url(settings.redis_url())
        http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        celery = create_celery_app(settings)
        fetch = jwks_fetcher or http_jwks_fetcher(http, settings.oidc_jwks_url)
        app.state.resources = Resources(
            settings=settings,
            engine=engine,
            sessions=async_sessionmaker(engine, expire_on_commit=False),
            redis=redis,
            verifier=TokenVerifier(JwksCache(fetch), issuer=settings.oidc_issuer),
            http=http,
            celery=celery,
        )
        try:
            yield
        finally:
            celery.close()
            await http.aclose()
            await redis.aclose()
            await engine.dispose()

    api = APIRouter(prefix="/api")  # K16: one origin, the API under /api
    for module in (health, me, teams, runs, budget):
        api.include_router(module.router)

    app = FastAPI(title="data-agent-platform", lifespan=lifespan)
    app.include_router(api)
    # Serves the default registry, `dap_runs_created_total` included.
    instrumentator = Instrumentator(excluded_handlers=[METRICS_PATH])
    if _HTTP_METRICS is not None:  # None only if the metrics were registered elsewhere
        instrumentator.add(_HTTP_METRICS)
    instrumentator.instrument(app).expose(app, endpoint=METRICS_PATH, include_in_schema=False)
    return app
