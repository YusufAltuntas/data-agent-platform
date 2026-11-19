"""Integration fixtures: a seeded dap database, a fake JWKS with a test RSA key, an in-process
API client, and for the worker a populated datasets database plus helpers to set up runs.
"""

import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Protocol

import httpx
import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from dap.api.app import create_app
from dap.db import bootstrap, datasets, seed
from dap.db.models import Run, RunEvent, RunStatus
from dap.db.session import create_sync_engine
from dap.settings import Settings

ISSUER = "http://auth.test/realms/dap"
AUDIENCE = "dap-api"


class FakeJwks:
    """A JWKS with one test RSA key, served without the network."""

    def __init__(self) -> None:
        self.fetches = 0
        self.kid = uuid.uuid4().hex
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self._jwks = {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    async def fetch(self) -> dict[str, Any]:
        self.fetches += 1
        return self._jwks

    def sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})


class MakeToken(Protocol):
    def __call__(self, email: str, /, **overrides: Any) -> str: ...


class Auth(Protocol):
    def __call__(self, email: str, /, *, platform_admin: bool = False) -> dict[str, str]: ...


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_jwks() -> FakeJwks:
    return FakeJwks()


@pytest.fixture
def make_token(fake_jwks: FakeJwks) -> MakeToken:
    """Keycloak-shaped access token; `None` in `overrides` removes a claim."""

    def make(email: str, /, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": [AUDIENCE, "account"],
            "sub": uuid.uuid4().hex,
            "iat": now,
            "exp": now + 300,
            "email": email,
            "email_verified": True,
            "realm_access": {"roles": ["default-roles-dap"]},
        }
        claims.update(overrides)
        return fake_jwks.sign({k: v for k, v in claims.items() if v is not None})

    return make


@pytest.fixture
def auth(make_token: MakeToken) -> Auth:
    """Authorization header for a user; `platform_admin=True` adds the realm role."""

    def headers(email: str, /, *, platform_admin: bool = False) -> dict[str, str]:
        roles = ["default-roles-dap", *(["platform-admin"] if platform_admin else [])]
        token = make_token(email, realm_access={"roles": roles})
        return {"Authorization": f"Bearer {token}"}

    return headers


@pytest.fixture
def api_settings(settings: Settings, new_database: Callable[[], str]) -> Settings:
    """Settings with a freshly migrated and seeded dap database."""
    fresh = settings.model_copy(
        update={
            "dap_db_name": new_database(),
            "oidc_issuer": ISSUER,
            "oidc_jwks_url": "http://keycloak.test/certs",  # never fetched: JWKS is injected
        }
    )
    bootstrap.migrate(fresh)
    seed.apply_seed(fresh)
    return fresh


@pytest.fixture
async def client(api_settings: Settings, fake_jwks: FakeJwks) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(api_settings, jwks_fetcher=fake_jwks.fetch)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture(scope="session")
def datasets_db(settings: Settings) -> Iterator[str]:
    """One populated datasets database for the whole session; generating it takes a while."""
    name = f"test_datasets_{uuid.uuid4().hex[:12]}"
    admin = create_sync_engine(settings, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        datasets.ensure_datasets(settings.model_copy(update={"datasets_db_name": name}))
        yield name
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@pytest.fixture
def worker_settings(api_settings: Settings, datasets_db: str) -> Settings:
    """Settings for the worker: a fresh seeded dap database and the populated datasets."""
    return api_settings.model_copy(update={"datasets_db_name": datasets_db})


def insert_run(
    settings: Settings, *, status: RunStatus = RunStatus.QUEUED, attempts: int = 0
) -> uuid.UUID:
    """A `sales` run, as the API would store it (or as an earlier attempt left it)."""
    engine = create_sync_engine(settings, poolclass=NullPool)
    try:
        with Session(engine) as session:
            run = Run(
                team_id="sales",
                dataset_id="sales",
                created_by="alice@example.com",
                question="How many customers are there?",
                status=status,
                attempts=attempts,
            )
            session.add(run)
            session.commit()
            return run.id
    finally:
        engine.dispose()


def load_run(settings: Settings, run_id: uuid.UUID) -> tuple[Run, list[RunEvent]]:
    """The run and its events in `seq` order, detached from any session."""
    engine = create_sync_engine(settings, poolclass=NullPool)
    try:
        with Session(engine, expire_on_commit=False) as session:
            run = session.get_one(Run, run_id)
            events = list(
                session.scalars(
                    sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                )
            )
            session.expunge_all()
            return run, events
    finally:
        engine.dispose()
