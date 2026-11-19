"""The agent's tools, with the executor and the schema cache replaced by in-memory fakes."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from dap.agent.executor import Column, QueryError, QueryResult, Row
from dap.agent.tools import (
    FINAL_ANSWER_MAX_ROWS,
    MAX_CELL_CHARS,
    RUN_SQL_MAX_ROWS,
    TOOL_SCHEMAS,
    RedisSchemaCache,
    Tools,
)
from dap.db.datasets import get_dataset

COLUMNS = {"orders": [Column("id", "integer", False), Column("status", "text", False)]}


class FakeExecutor:
    def __init__(self, rows: list[Row] | None = None, error: str | None = None) -> None:
        self.rows = rows if rows is not None else [(1, "completed")]
        self.error = error
        self.queries: list[tuple[str, int]] = []
        self.described: list[str] = []

    def run(self, query: str, max_rows: int) -> QueryResult:
        self.queries.append((query, max_rows))
        if self.error:
            raise QueryError(self.error)
        return QueryResult(["id", "status"], self.rows[:max_rows], len(self.rows) > max_rows)

    def list_tables(self) -> list[str]:
        return ["customers", "orders"]

    def describe_table(self, table: str) -> list[Column]:
        self.described.append(table)
        return COLUMNS.get(table, [])


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


def _tools(executor: FakeExecutor | None = None) -> tuple[Tools, FakeExecutor, MemoryCache]:
    executor = executor or FakeExecutor()
    cache = MemoryCache()
    return Tools(executor, cache, get_dataset("sales")), executor, cache


def _call(tools: Tools, name: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
    result = tools.call(name, json.dumps(arguments))
    assert json.loads(result.content()) == result.data
    return result.ok, result.data


def test_schemas_are_openai_function_definitions() -> None:
    names = [schema["function"]["name"] for schema in TOOL_SCHEMAS]
    assert names == ["list_tables", "describe_table", "run_sql", "final_answer"]
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert schema["function"]["description"]
        parameters = schema["function"]["parameters"]
        assert parameters["type"] == "object"
        assert set(parameters["required"]) == set(parameters["properties"])


def test_final_answer_schema_declares_sql_before_the_free_text_answer() -> None:
    final = TOOL_SCHEMAS[3]["function"]["parameters"]
    assert list(final["properties"]) == ["sql", "answer"]
    assert final["required"] == ["sql", "answer"]


def test_list_tables() -> None:
    tools, _, _ = _tools()
    assert _call(tools, "list_tables") == (True, {"tables": ["customers", "orders"]})


def test_describe_table_is_cached_per_dataset() -> None:
    tools, executor, cache = _tools()
    expected = {
        "table": "orders",
        "columns": [
            {"name": "id", "type": "integer", "nullable": False},
            {"name": "status", "type": "text", "nullable": False},
        ],
    }
    assert _call(tools, "describe_table", table="orders") == (True, expected)
    assert _call(tools, "describe_table", table="orders") == (True, expected)
    assert executor.described == ["orders"]
    assert list(cache.values) == ["dap:schema:sales:orders"]


def test_describe_unknown_table_is_a_tool_error_and_not_cached() -> None:
    tools, _, cache = _tools()
    ok, data = _call(tools, "describe_table", table="salaries")
    assert not ok
    assert "salaries" in data["error"]
    assert cache.values == {}


def test_run_sql_returns_at_most_50_rows_with_truncated_cells() -> None:
    long_text = "x" * (MAX_CELL_CHARS + 50)
    rows: list[Row] = [(i, long_text) for i in range(120)]
    tools, executor, _ = _tools(FakeExecutor(rows))
    ok, data = _call(tools, "run_sql", sql="SELECT id, status FROM orders")
    assert ok
    assert executor.queries == [("SELECT id, status FROM orders", RUN_SQL_MAX_ROWS)]
    assert data["columns"] == ["id", "status"]
    assert len(data["rows"]) == RUN_SQL_MAX_ROWS
    assert data["truncated"] is True
    cell = data["rows"][0][1]
    assert cell.startswith("x" * MAX_CELL_CHARS)
    assert len(cell) < len(long_text)


def test_run_sql_serializes_database_values() -> None:
    rows: list[Row] = [(Decimal("12.50"), date(2026, 1, 2), None)]
    tools, _, _ = _tools(FakeExecutor(rows))
    ok, data = _call(tools, "run_sql", sql="SELECT 1")
    assert ok
    assert data["rows"] == [[12.5, "2026-01-02", None]]


def test_run_sql_guard_rejection_is_a_tool_error() -> None:
    tools, executor, _ = _tools()
    ok, data = _call(tools, "run_sql", sql="SELECT * FROM hr.salaries")
    assert not ok
    assert "outside the dataset schema" in data["error"]
    assert executor.queries == []


def test_run_sql_database_error_is_a_tool_error() -> None:
    tools, _, _ = _tools(FakeExecutor(error='column "nope" does not exist'))
    ok, data = _call(tools, "run_sql", sql="SELECT nope FROM orders")
    assert not ok
    assert 'column "nope" does not exist' in data["error"]


def test_final_answer_reruns_sql_with_up_to_200_rows() -> None:
    long_text = "y" * (MAX_CELL_CHARS + 50)
    rows: list[Row] = [(i, long_text) for i in range(300)]
    tools, executor, _ = _tools(FakeExecutor(rows))
    sql = "SELECT id, status FROM orders"
    ok, data = _call(tools, "final_answer", answer="There are many orders.", sql=sql)
    assert ok
    assert executor.queries == [(sql, FINAL_ANSWER_MAX_ROWS)]
    assert data["answer"] == "There are many orders."
    assert data["sql"] == sql
    assert data["columns"] == ["id", "status"]
    assert len(data["rows"]) == FINAL_ANSWER_MAX_ROWS
    assert data["rows"][0] == [0, long_text]  # the user sees full cells
    assert data["truncated"] is True


def test_final_answer_with_rejected_sql_is_a_tool_error() -> None:
    tools, executor, _ = _tools()
    ok, data = _call(tools, "final_answer", answer="Done.", sql="DELETE FROM orders")
    assert not ok
    assert "SELECT" in data["error"]
    assert executor.queries == []


def test_final_answer_with_empty_sql_runs_no_query() -> None:
    tools, executor, _ = _tools()
    ok, data = _call(tools, "final_answer", answer="There is no cost data.", sql=" ")
    assert ok
    assert data == {
        "answer": "There is no cost data.",
        "sql": "",
        "columns": [],
        "rows": [],
        "truncated": False,
    }
    assert executor.queries == []


# Verbatim arguments of a real-model final_answer call (claude-haiku-5-5): the `sql` parameter
# leaked into the free-text `answer` as markup, so the object has a single key.
MALFORMED_FINAL_ANSWER = (
    r'{"answer": "The top 5 products by revenue in Q3 2026 (July 1 to September 30, 2026)'
    r" were:\n\n1. Air Purifier Pro (Home): $72,929.28\n2. Kettle Plus (Home): $68,292.40\n3."
    r" Keyboard Basic (Electronics): $66,579.48\n4. Pen Set Basic (Office): $57,718.19\n5."
    r" Webcam Pro (Electronics): $54,374.20\n\nRevenue is quantity × unit price from completed"  # noqa: RUF001
    r" and shipped orders. Cancelled and returned orders are excluded. I took \"last quarter\""
    r" to mean Q3 2026, based on today's date of 2026-11-19 in the database.</answer>\n"
    r"<parameter name=\"sql\">SELECT p.id, p.name, p.category, SUM(oi.quantity * oi.unit_price)"
    r" AS revenue FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON"
    r" p.id = oi.product_id WHERE o.order_date >= DATE '2026-07-01' AND o.order_date < DATE"
    r" '2026-10-01' AND o.status IN ('completed', 'shipped') GROUP BY p.id, p.name, p.category"
    r' ORDER BY revenue DESC LIMIT 5"}'
)


def test_malformed_final_answer_error_explains_how_to_call_the_tool() -> None:
    tools, executor, _ = _tools()
    assert list(json.loads(MALFORMED_FINAL_ANSWER)) == ["answer"]
    result = tools.call("final_answer", MALFORMED_FINAL_ANSWER)
    assert not result.ok
    error = result.data["error"]
    assert "'sql'" in error
    assert "two separate arguments" in error
    assert "single SELECT statement" in error
    assert "plain text" in error
    assert executor.queries == []


def test_final_answer_without_answer_explains_how_to_call_the_tool() -> None:
    tools, executor, _ = _tools()
    ok, data = _call(tools, "final_answer", sql="SELECT 1")
    assert not ok
    assert "'answer'" in data["error"]
    assert "two separate arguments" in data["error"]
    assert executor.queries == []


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        pytest.param("drop_everything", "{}", "Unknown tool", id="unknown-tool"),
        pytest.param("run_sql", "not json", "not valid JSON", id="invalid-json"),
        pytest.param("run_sql", "[1]", "JSON object", id="not-an-object"),
        pytest.param("run_sql", "{}", "sql", id="missing-argument"),
        pytest.param("describe_table", '{"table": 3}', "table", id="wrong-type"),
    ],
)
def test_bad_calls_are_tool_errors(name: str, arguments: str, message: str) -> None:
    tools, _, _ = _tools()
    result = tools.call(name, arguments)
    assert not result.ok
    assert message in result.data["error"]


class StubRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expiries: dict[str, int] = {}

    def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    def set(self, name: str, value: str, ex: int) -> None:
        self.values[name] = value.encode()
        self.expiries[name] = ex


def test_redis_schema_cache_sets_a_ttl_and_decodes() -> None:
    client = StubRedis()
    cache = RedisSchemaCache(client, ttl_s=60)  # type: ignore[arg-type]
    assert cache.get("k") is None
    cache.set("k", "value")
    assert client.expiries == {"k": 60}
    assert cache.get("k") == "value"
