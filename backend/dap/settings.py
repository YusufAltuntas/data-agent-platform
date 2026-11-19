"""Application settings. This module is the single owner of environment variable names."""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: SecretStr
    dap_db_name: str = "dap"
    datasets_db_name: str = "datasets"
    ds_sales_ro_password: SecretStr
    ds_hr_ro_password: SecretStr
    dap_fernet_key: SecretStr

    redis_host: str = "localhost"
    redis_port: int = 6379
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "dap"
    rabbitmq_password: SecretStr

    # The expected `iss` is the external Keycloak address; the JWKS is fetched from the
    # in-cluster service address (design §7).
    oidc_issuer: str = "http://auth.localhost/realms/dap"
    oidc_jwks_url: str = "http://auth.localhost/realms/dap/protocol/openid-connect/certs"

    # LLM (K22: the fake provider unless the real model is switched on). The API key of the
    # OpenAI-compatible provider is per team, so it is not a setting.
    llm_provider: Literal["fake", "openai_compatible"] = "fake"
    llm_base_url: str = "http://localhost:4000"  # the LiteLLM proxy
    llm_model: str = "default"  # LiteLLM model alias (K17)
    fake_step_delay_s: float = 0.0
    litellm_master_key: SecretStr  # admin key of the proxy; the API reads team spend with it (K4)
    # Budget of each LiteLLM team the bootstrap Job creates (K4); an existing team keeps its own.
    litellm_team_max_budget_usd: float = 1.0

    # Langfuse (K5): tracing is switched off unless both keys are set. An empty host means the
    # SDK's default, Langfuse Cloud.
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    # The worker's Prometheus endpoint (design §9), served by its parent process.
    worker_metrics_port: int = 9200

    def dap_db_url(self, driver: str) -> URL:
        """URL of the dap database for the given SQLAlchemy driver (e.g. `psycopg`)."""
        return self._url(driver, self.dap_db_name)

    def datasets_db_url(
        self, driver: str, *, username: str | None = None, password: SecretStr | None = None
    ) -> URL:
        """URL of the datasets database; the Postgres admin user unless a role is given."""
        return self._url(driver, self.datasets_db_name, username, password)

    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    def rabbitmq_url(self) -> str:
        """AMQP URL of the default vhost."""
        user = quote(self.rabbitmq_user, safe="")
        password = quote(self.rabbitmq_password.get_secret_value(), safe="")
        return f"amqp://{user}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}//"

    def _url(
        self,
        driver: str,
        database: str,
        username: str | None = None,
        password: SecretStr | None = None,
    ) -> URL:
        return URL.create(
            f"postgresql+{driver}",
            username=username or self.postgres_user,
            password=(password or self.postgres_password).get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
