"""Bootstrap Job (`python -m dap.db.bootstrap`): migrations, synthetic datasets, seed, LiteLLM keys.

Idempotent: it runs on every `helm upgrade`. The databases themselves must already exist.
"""

import logging
from pathlib import Path

import httpx
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from dap import litellm_client
from dap.crypto import encrypt
from dap.db import datasets, seed
from dap.db.models import Team
from dap.db.session import create_sync_engine
from dap.settings import Settings, get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
LITELLM_TIMEOUT_S = 30.0

log = logging.getLogger(__name__)


def migrate(settings: Settings) -> None:
    config = Config(ALEMBIC_INI)
    config.attributes["settings"] = settings
    command.upgrade(config, "head")


def ensure_llm_keys(settings: Settings, http: httpx.Client) -> list[str]:
    """Give each team a LiteLLM team with a budget and a virtual key (K3, K4).

    A team that has both is left alone, so a re-run creates no second team or key. The LiteLLM
    team id is stored as soon as it exists: a run that fails before the key resumes with it.
    Returns the ids of the teams that changed.
    """
    engine = create_sync_engine(settings, poolclass=NullPool)
    try:
        with Session(engine) as session:
            teams = session.scalars(
                sa.select(Team)
                .where(sa.or_(Team.litellm_team_id.is_(None), Team.llm_key_enc.is_(None)))
                .order_by(Team.id)
            ).all()
            for team in teams:
                if team.litellm_team_id is None:
                    team.litellm_team_id = litellm_client.create_team(
                        http, settings, team.id, max_budget_usd=settings.litellm_team_max_budget_usd
                    )
                    session.commit()
                key = litellm_client.generate_key(
                    http, settings, team.litellm_team_id, key_alias=f"dap-{team.id}"
                )
                team.llm_key_enc = encrypt(settings, key)
                session.commit()
            return [team.id for team in teams]
    finally:
        engine.dispose()


def run(settings: Settings) -> None:
    migrate(settings)
    generated = datasets.ensure_datasets(settings)
    log.info("datasets %s; roles applied", "generated" if generated else "already present")
    seed.apply_seed(settings)
    log.info("seed applied")
    with httpx.Client(timeout=LITELLM_TIMEOUT_S) as http:
        changed = ensure_llm_keys(settings, http)
    log.info("LiteLLM teams and keys created for: %s", ", ".join(changed) or "none (all present)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Alembic's fileConfig resets the root level; keep this module's messages visible.
    log.setLevel(logging.INFO)
    run(get_settings())
