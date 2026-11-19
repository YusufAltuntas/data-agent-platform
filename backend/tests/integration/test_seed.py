"""The seed writes design §5's teams, members and datasets; bootstrap is idempotent."""

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from dap.db import bootstrap, datasets, seed
from dap.db.session import create_sync_engine
from dap.settings import Settings

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]

QUERIES = {
    "teams": "SELECT id, name FROM teams ORDER BY id",
    "memberships": "SELECT team_id, email, role FROM memberships ORDER BY team_id, email",
    "datasets": "SELECT id, db_role FROM datasets ORDER BY id",
    "dataset_grants": "SELECT team_id, dataset_id FROM dataset_grants ORDER BY team_id",
}


def _dap_rows(settings: Settings) -> dict[str, list[tuple[object, ...]]]:
    engine = create_sync_engine(settings)
    try:
        with engine.connect() as conn:
            return {
                table: [tuple(row) for row in conn.execute(sa.text(query))]
                for table, query in QUERIES.items()
            }
    finally:
        engine.dispose()


def _dataset_counts(settings: Settings) -> dict[str, int]:
    engine = datasets.create_admin_engine(settings)
    try:
        with engine.connect() as conn:
            return {
                table.fullname: conn.execute(
                    sa.select(sa.func.count()).select_from(table)
                ).scalar_one()
                for table in datasets.metadata.sorted_tables
            }
    finally:
        engine.dispose()


def _fresh(settings: Settings, new_database: Callable[[], str]) -> Settings:
    return settings.model_copy(
        update={"dap_db_name": new_database(), "datasets_db_name": new_database()}
    )


EXPECTED = {
    "teams": [("hr", "HR"), ("sales", "Sales")],
    "memberships": [
        ("hr", "carol@example.com", "admin"),
        ("sales", "alice@example.com", "analyst"),
        ("sales", "bob@example.com", "viewer"),
    ],
    "datasets": [("hr", "ds_hr_ro"), ("sales", "ds_sales_ro")],
    "dataset_grants": [("hr", "hr"), ("sales", "sales")],
}


def test_seed_is_idempotent(settings: Settings, new_database: Callable[[], str]) -> None:
    fresh = _fresh(settings, new_database)
    bootstrap.migrate(fresh)

    seed.apply_seed(fresh)
    assert _dap_rows(fresh) == EXPECTED
    seed.apply_seed(fresh)
    assert _dap_rows(fresh) == EXPECTED


class FakeLiteLLM:
    """A LiteLLM proxy stand-in on a local port for the bootstrap subprocess; records each path."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(self.path)
                if self.path == "/team/new":
                    payload = {"team_id": f"lt-{body['team_alias']}"}
                else:
                    payload = {"key": f"sk-{body['team_id']}"}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:  # keep test output clean
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def fake_litellm() -> Iterator[FakeLiteLLM]:
    fake = FakeLiteLLM()
    thread = threading.Thread(target=fake.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        fake.server.shutdown()
        fake.server.server_close()


def _run_bootstrap_module(settings: Settings, litellm_url: str) -> None:
    env = {
        **os.environ,
        "POSTGRES_HOST": settings.postgres_host,
        "POSTGRES_PORT": str(settings.postgres_port),
        "POSTGRES_USER": settings.postgres_user,
        "POSTGRES_PASSWORD": settings.postgres_password.get_secret_value(),
        "DAP_DB_NAME": settings.dap_db_name,
        "DATASETS_DB_NAME": settings.datasets_db_name,
        "DS_SALES_RO_PASSWORD": settings.ds_sales_ro_password.get_secret_value(),
        "DS_HR_RO_PASSWORD": settings.ds_hr_ro_password.get_secret_value(),
        "DAP_FERNET_KEY": settings.dap_fernet_key.get_secret_value(),
        "RABBITMQ_PASSWORD": settings.rabbitmq_password.get_secret_value(),
        "LITELLM_MASTER_KEY": settings.litellm_master_key.get_secret_value(),
        "LLM_BASE_URL": litellm_url,
    }
    subprocess.run([sys.executable, "-m", "dap.db.bootstrap"], cwd=BACKEND_DIR, env=env, check=True)


def test_bootstrap_runs_twice(
    settings: Settings, new_database: Callable[[], str], fake_litellm: FakeLiteLLM
) -> None:
    fresh = _fresh(settings, new_database)

    _run_bootstrap_module(fresh, fake_litellm.url)
    rows, counts = _dap_rows(fresh), _dataset_counts(fresh)
    assert rows == EXPECTED
    assert counts["sales.orders"] > 0
    assert fake_litellm.calls == ["/team/new", "/key/generate"] * 2

    _run_bootstrap_module(fresh, fake_litellm.url)
    assert _dap_rows(fresh) == rows
    assert _dataset_counts(fresh) == counts
    assert len(fake_litellm.calls) == 4  # the second run creates no LiteLLM team or key
