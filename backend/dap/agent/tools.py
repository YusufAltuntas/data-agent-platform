"""The agent's tools (design §8) and their OpenAI function-calling schemas.

`Tools.call` executes one tool call. Bad arguments, guard rejections and database errors come
back as an unsuccessful `ToolResult` that is handed to the model, never as exceptions. A
successful `final_answer` result is the run's final answer.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Protocol

import redis

from dap.agent.executor import Column, QueryError, QueryResult
from dap.agent.sql_guard import SqlRejected, check_sql
from dap.db.datasets import DatasetSpec

RUN_SQL_MAX_ROWS = 50
FINAL_ANSWER_MAX_ROWS = 200
MAX_CELL_CHARS = 200
SCHEMA_CACHE_TTL_S = 3600


class Executor(Protocol):
    def run(self, query: str, max_rows: int) -> QueryResult: ...
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> list[Column]: ...


class SchemaCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class RedisSchemaCache:
    def __init__(self, client: redis.Redis, ttl_s: int = SCHEMA_CACHE_TTL_S) -> None:
        self._client = client
        self._ttl_s = ttl_s

    def get(self, key: str) -> str | None:
        value = self._client.get(key)
        return value.decode() if isinstance(value, bytes) else value

    def set(self, key: str, value: str) -> None:
        self._client.set(key, value, ex=self._ttl_s)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any]  # {"error": message} when not ok

    def content(self) -> str:
        """The tool message content handed back to the model."""
        return json.dumps(self.data)


class ToolCallError(Exception):
    """A tool call failed in a way the model can correct."""


def _function(name: str, description: str, properties: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _function("list_tables", "List the tables of the dataset.", {}),
    _function(
        "describe_table",
        "Show the columns of one table: name, type and whether it can be null.",
        {"table": {"type": "string", "description": "Table name, without a schema."}},
    ),
    _function(
        "run_sql",
        f"Run one read-only PostgreSQL SELECT query on the dataset. Returns at most"
        f" {RUN_SQL_MAX_ROWS} rows; long values are cut. Errors are returned so you can fix"
        f" the query.",
        {"sql": {"type": "string", "description": "A single SELECT statement."}},
    ),
    _function(
        "final_answer",
        f"Finish with the answer for the user. The SQL is run again and its result (at most"
        f" {FINAL_ANSWER_MAX_ROWS} rows) is shown to the user next to the answer.",
        {  # `sql` first: the long free-text `answer` must be last so it swallows nothing
            "sql": {
                "type": "string",
                "description": "The single SELECT statement behind the answer. An empty string"
                " only when the dataset cannot answer the question.",
            },
            "answer": {
                "type": "string",
                "description": "A short answer in plain language: a few sentences, no markup.",
            },
        },
    ),
]
FINAL_ANSWER_USAGE = (
    "Call final_answer with two separate arguments: 'sql' = the single SELECT statement behind"
    " the answer, 'answer' = a short answer in plain text (a few sentences, no markup)."
)


class Tools:
    def __init__(self, executor: Executor, cache: SchemaCache, dataset: DatasetSpec) -> None:
        self._executor = executor
        self._cache = cache
        self._dataset = dataset
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "list_tables": self._list_tables,
            "describe_table": self._describe_table,
            "run_sql": self._run_sql,
            "final_answer": self._final_answer,
        }

    def call(self, name: str, arguments: str) -> ToolResult:
        """Execute a tool call by name with the model's JSON-encoded arguments."""
        try:
            handler = self._handlers.get(name)
            if handler is None:
                raise ToolCallError(f"Unknown tool '{name}'.")
            return ToolResult(True, handler(_parse_arguments(arguments)))
        except ToolCallError as exc:
            return ToolResult(False, {"error": str(exc)})

    def _list_tables(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"tables": self._query(self._executor.list_tables)}

    def _describe_table(self, args: dict[str, Any]) -> dict[str, Any]:
        table = _string(args, "table")
        key = f"dap:schema:{self._dataset.id}:{table}"
        if (cached := self._cache.get(key)) is not None:
            return {"table": table, "columns": json.loads(cached)}
        columns = [asdict(c) for c in self._query(lambda: self._executor.describe_table(table))]
        if not columns:
            raise ToolCallError(f"Unknown table '{table}'. Use list_tables to see the tables.")
        self._cache.set(key, json.dumps(columns))
        return {"table": table, "columns": columns}

    def _run_sql(self, args: dict[str, Any]) -> dict[str, Any]:
        result = self._select(_string(args, "sql"), RUN_SQL_MAX_ROWS)
        return {
            "columns": result.columns,
            "rows": [[_cut(_jsonable(v)) for v in row] for row in result.rows],
            "truncated": result.truncated,
        }

    def _final_answer(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            sql, answer = _string(args, "sql"), _string(args, "answer")
        except ToolCallError as exc:
            raise ToolCallError(f"{exc} {FINAL_ANSWER_USAGE}") from exc
        if not sql.strip():  # the question cannot be answered from the dataset: no query to run
            return {"answer": answer, "sql": "", "columns": [], "rows": [], "truncated": False}
        result = self._select(sql, FINAL_ANSWER_MAX_ROWS)
        return {
            "answer": answer,
            "sql": sql,
            "columns": result.columns,
            "rows": [[_jsonable(v) for v in row] for row in result.rows],
            "truncated": result.truncated,
        }

    def _select(self, sql: str, max_rows: int) -> QueryResult:
        try:
            check_sql(sql, self._dataset.id)
        except SqlRejected as exc:
            raise ToolCallError(f"SQL rejected: {exc.reason}") from exc
        return self._query(lambda: self._executor.run(sql, max_rows))

    def _query[T](self, run: Callable[[], T]) -> T:
        try:
            return run()
        except QueryError as exc:
            raise ToolCallError(f"SQL error: {exc}") from exc


def _parse_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ToolCallError(f"Arguments are not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ToolCallError("Arguments must be a JSON object.")
    return parsed


def _string(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise ToolCallError(f"Argument '{name}' is required and must be a string.")
    return value


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime | time):
        return value.isoformat()
    return str(value)


def _cut(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value
