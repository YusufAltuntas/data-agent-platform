"""Synthetic datasets are deterministic and each read-only role reaches only its own schema."""

from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa

from dap.db import datasets
from dap.settings import Settings

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "sales.customers",
    "sales.products",
    "sales.orders",
    "sales.order_items",
    "hr.departments",
    "hr.employees",
    "hr.salaries",
}


def _datasets_settings(settings: Settings, new_database: Callable[[], str]) -> Settings:
    return settings.model_copy(update={"datasets_db_name": new_database()})


def _summary(settings: Settings) -> dict[str, tuple[int, str]]:
    """Row count and a content hash per table."""
    engine = datasets.create_admin_engine(settings)
    summary: dict[str, tuple[int, str]] = {}
    try:
        with engine.connect() as conn:
            for name in EXPECTED_TABLES:
                count, digest = conn.execute(
                    sa.text(
                        "SELECT count(*), md5(coalesce(string_agg(t::text, '|'"
                        f" ORDER BY t::text), '')) FROM {name} t"
                    )
                ).one()
                summary[name] = (count, digest)
    finally:
        engine.dispose()
    return summary


@pytest.fixture
def populated(settings: Settings, new_database: Callable[[], str]) -> Iterator[Settings]:
    ds_settings = _datasets_settings(settings, new_database)
    datasets.ensure_datasets(ds_settings)
    yield ds_settings


def _role_engine(settings: Settings, dataset_id: str) -> sa.Engine:
    return sa.create_engine(datasets.role_url(settings, datasets.get_dataset(dataset_id)))


def test_generator_is_deterministic(settings: Settings, new_database: Callable[[], str]) -> None:
    first = _datasets_settings(settings, new_database)
    second = _datasets_settings(settings, new_database)
    assert datasets.ensure_datasets(first) is True
    assert datasets.ensure_datasets(second) is True

    engine = datasets.create_admin_engine(first)
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                sa.text(
                    "SELECT table_schema || '.' || table_name FROM information_schema.tables"
                    " WHERE table_schema IN ('sales', 'hr', 'public')"
                )
            ).scalars()
            assert set(tables) == EXPECTED_TABLES
    finally:
        engine.dispose()

    summary = _summary(first)
    assert summary == _summary(second)
    assert all(count > 0 for count, _ in summary.values())
    assert 4500 <= summary["sales.orders"][0] <= 5500


def test_generation_is_skipped_when_populated(populated: Settings) -> None:
    before = _summary(populated)
    assert datasets.ensure_datasets(populated) is False
    assert _summary(populated) == before


def test_order_dates_cover_fixed_range(populated: Settings) -> None:
    engine = datasets.create_admin_engine(populated)
    try:
        with engine.connect() as conn:
            low, high = conn.execute(
                sa.text("SELECT min(order_date), max(order_date) FROM sales.orders")
            ).one()
    finally:
        engine.dispose()
    assert str(low) >= "2025-01-01"
    assert str(high) <= "2026-10-31"
    assert str(high) >= "2026-08-01"  # the last quarter before the demo has orders


def test_sales_role_reads_only_its_schema(populated: Settings) -> None:
    engine = _role_engine(populated, "sales")
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM sales.orders")).scalar_one() > 0

        denied = [
            "SELECT * FROM hr.salaries",
            "INSERT INTO sales.orders (id, customer_id, order_date, status)"
            " VALUES (999999, 1, '2026-01-01', 'completed')",
            "DELETE FROM sales.order_items",
            "CREATE TABLE sales.scratch (id int)",
            "CREATE TABLE public.scratch (id int)",
            "CREATE TEMP TABLE scratch (id int)",
        ]
        for statement in denied:
            with (
                pytest.raises(sa.exc.ProgrammingError, match="permission denied"),
                engine.connect() as conn,
            ):
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def test_hr_role_reads_only_its_schema(populated: Settings) -> None:
    engine = _role_engine(populated, "hr")
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM hr.salaries")).scalar_one() > 0
        with (
            pytest.raises(sa.exc.ProgrammingError, match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(sa.text("SELECT * FROM sales.orders"))
    finally:
        engine.dispose()
