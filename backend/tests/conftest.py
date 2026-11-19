"""Shared fixtures: session-scoped service containers for integration tests."""

import os
import secrets
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import SecretStr
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from dap.db.session import create_sync_engine
from dap.settings import Settings

POSTGRES_IMAGE = "postgres:17"
REDIS_IMAGE = "redis:8"
RABBITMQ_IMAGE = "rabbitmq:4"
RABBITMQ_USER = "dap"
RABBITMQ_PORT = 5672

# Ryuk, testcontainers' reaper container, fails to start intermittently on Docker Desktop. The
# session-scoped fixtures below stop their own containers, so it is not needed on the host.
# testcontainers reads this variable lazily, when the first container starts.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def rabbitmq_container() -> Iterator[DockerContainer]:
    # A plain container: testcontainers' RabbitMqContainer uses a deprecated wait decorator.
    container = (
        DockerContainer(RABBITMQ_IMAGE)
        .with_env("RABBITMQ_DEFAULT_USER", RABBITMQ_USER)
        .with_env("RABBITMQ_DEFAULT_PASS", secrets.token_urlsafe(16))
        .with_exposed_ports(RABBITMQ_PORT)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def settings(
    postgres_container: PostgresContainer,
    redis_container: RedisContainer,
    rabbitmq_container: DockerContainer,
) -> Settings:
    """Settings that point the application at the test containers."""
    return Settings(
        postgres_host=postgres_container.get_container_host_ip(),
        postgres_port=int(postgres_container.get_exposed_port(5432)),
        postgres_user=postgres_container.username,
        postgres_password=SecretStr(postgres_container.password),
        dap_db_name=postgres_container.dbname,
        ds_sales_ro_password=SecretStr(secrets.token_urlsafe(16)),
        ds_hr_ro_password=SecretStr(secrets.token_urlsafe(16)),
        dap_fernet_key=SecretStr(Fernet.generate_key().decode()),
        redis_host=redis_container.get_container_host_ip(),
        redis_port=int(redis_container.get_exposed_port(redis_container.port)),
        rabbitmq_host=rabbitmq_container.get_container_host_ip(),
        rabbitmq_port=int(rabbitmq_container.get_exposed_port(RABBITMQ_PORT)),
        rabbitmq_user=RABBITMQ_USER,
        rabbitmq_password=SecretStr(rabbitmq_container.env["RABBITMQ_DEFAULT_PASS"]),
        litellm_master_key=SecretStr(secrets.token_urlsafe(16)),
    )


@pytest.fixture
def new_database(settings: Settings) -> Iterator[Callable[[], str]]:
    """Factory that creates empty databases in the shared container; drops them afterwards.

    In the cluster the Postgres chart creates the databases; here the tests do it.
    """
    admin = create_sync_engine(settings, isolation_level="AUTOCOMMIT")
    created: list[str] = []

    def create() -> str:
        name = f"test_{uuid.uuid4().hex[:12]}"
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return name

    try:
        yield create
        with admin.connect() as conn:
            for name in created:
                conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
