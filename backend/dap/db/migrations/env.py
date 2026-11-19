"""Alembic environment: runs migrations online with the sync (psycopg) engine."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy.pool import NullPool

from dap.db.models import Base
from dap.db.session import create_sync_engine
from dap.settings import Settings, get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Callers (tests, bootstrap) may pass settings; otherwise they come from the environment.
settings: Settings = config.attributes.get("settings") or get_settings()

engine = create_sync_engine(settings, poolclass=NullPool)
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
