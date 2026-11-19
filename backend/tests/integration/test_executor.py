"""The dataset executor runs queries as the dataset role, read-only, time-limited and limited.

These tests call the executor directly, bypassing the SQL guard, to show that the database-side
settings hold on their own.
"""

import time
from collections.abc import Callable, Iterator

import pytest

from dap.agent.executor import Column, DatasetExecutor, QueryError, connect
from dap.db import datasets
from dap.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def executor(settings: Settings, new_database: Callable[[], str]) -> Iterator[DatasetExecutor]:
    ds_settings = settings.model_copy(update={"datasets_db_name": new_database()})
    datasets.ensure_datasets(ds_settings)
    spec = datasets.get_dataset("sales")
    with connect(ds_settings, spec) as conn:
        yield DatasetExecutor(conn, spec.id)


def test_connects_as_the_dataset_role(executor: DatasetExecutor) -> None:
    result = executor.run(
        "SELECT current_user, session_user, current_setting('search_path')", max_rows=5
    )
    assert result.rows == [("ds_sales_ro", "ds_sales_ro", "sales")]


def test_unqualified_tables_resolve_to_the_dataset_schema(executor: DatasetExecutor) -> None:
    result = executor.run("SELECT count(*) AS n FROM orders", max_rows=5)
    assert result.columns == ["n"]
    assert result.rows[0][0] > 0
    assert result.truncated is False


def test_outer_limit_is_applied(executor: DatasetExecutor) -> None:
    result = executor.run("SELECT id FROM orders ORDER BY id;", max_rows=10)
    assert result.rows == [(i,) for i in range(1, 11)]
    assert result.truncated is True

    exact = executor.run("SELECT id FROM orders WHERE id <= 10", max_rows=10)
    assert len(exact.rows) == 10
    assert exact.truncated is False


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param("SELECT lo_create(0)", id="large-object"),
        pytest.param("SELECT id FROM orders FOR UPDATE", id="row-lock"),
    ],
)
def test_writes_are_rejected_by_read_only_transaction(executor: DatasetExecutor, sql: str) -> None:
    with pytest.raises(QueryError, match="read-only transaction"):
        executor.run(sql, max_rows=5)
    # The failed transaction was rolled back; the connection keeps working.
    assert executor.run("SELECT 1", max_rows=5).rows == [(1,)]


def test_long_query_is_cancelled_by_statement_timeout(executor: DatasetExecutor) -> None:
    started = time.monotonic()
    with pytest.raises(QueryError, match="statement timeout"):
        executor.run("SELECT pg_sleep(30)", max_rows=5)
    assert time.monotonic() - started < 8
    assert executor.run("SELECT 1", max_rows=5).rows == [(1,)]


def test_multiple_statements_cannot_escape_the_transaction(executor: DatasetExecutor) -> None:
    escape = "SELECT 1) AS x; COMMIT; SELECT lo_create(0); SELECT * FROM (SELECT 1"
    with pytest.raises(QueryError):
        executor.run(escape, max_rows=5)
    with pytest.raises(QueryError, match="read-only transaction"):
        executor.run("SELECT lo_create(0)", max_rows=5)
    assert executor.run("SELECT 1", max_rows=5).rows == [(1,)]


def test_list_and_describe_tables(executor: DatasetExecutor) -> None:
    assert executor.list_tables() == ["customers", "order_items", "orders", "products"]
    assert executor.describe_table("orders") == [
        Column("id", "integer", nullable=False),
        Column("customer_id", "integer", nullable=False),
        Column("order_date", "date", nullable=False),
        Column("status", "text", nullable=False),
    ]
    assert executor.describe_table("salaries") == []
