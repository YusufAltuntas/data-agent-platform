"""Runs queries against a dataset as the dataset's own read-only role (K9, layer 1).

Every query runs in its own `BEGIN READ ONLY` transaction with a statement timeout and the
dataset schema as `search_path`. User queries are wrapped in an outer `LIMIT`.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from dap.db.datasets import DatasetSpec, role_url
from dap.settings import Settings

STATEMENT_TIMEOUT = "5s"

Row = tuple[Any, ...]


class QueryError(Exception):
    """The database rejected or cancelled the query; the message is safe to show to the model."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[Row]
    truncated: bool  # the query had more rows than were fetched


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool


def connect(settings: Settings, spec: DatasetSpec) -> psycopg.Connection[Row]:
    """Autocommit connection to the datasets database, logged in as the dataset's own role."""
    url = role_url(settings, spec)
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        autocommit=True,
    )


class DatasetExecutor:
    def __init__(self, conn: psycopg.Connection[Row], schema: str) -> None:
        if not conn.autocommit:
            raise ValueError("the executor manages its own transactions; use autocommit")
        self._conn = conn
        self._schema = schema

    def run(self, query: str, max_rows: int) -> QueryResult:
        """Run a user query, returning at most `max_rows` rows."""
        wrapped = sql.SQL("SELECT * FROM (\n{}\n) AS dap_query LIMIT {}").format(
            sql.SQL(query.strip().rstrip(";")),
            sql.Literal(max_rows + 1),
        )
        columns, rows = self._execute(wrapped)
        return QueryResult(columns, rows[:max_rows], truncated=len(rows) > max_rows)

    def list_tables(self) -> list[str]:
        _, rows = self._execute(
            sql.SQL(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = {} ORDER BY table_name"
            ).format(self._schema)
        )
        return [row[0] for row in rows]

    def describe_table(self, table: str) -> list[Column]:
        """Columns of `table` in the dataset schema; empty if there is no such table."""
        _, rows = self._execute(
            sql.SQL(
                "SELECT column_name, data_type, is_nullable = 'YES'"
                " FROM information_schema.columns"
                " WHERE table_schema = {} AND table_name = {} ORDER BY ordinal_position"
            ).format(self._schema, table)
        )
        return [Column(*row) for row in rows]

    def _execute(self, query: sql.Composed) -> tuple[list[str], list[Row]]:
        with self._conn.cursor() as cursor:
            cursor.execute("BEGIN READ ONLY")
            try:
                cursor.execute(
                    sql.SQL("SET LOCAL search_path = {}").format(sql.Identifier(self._schema))
                )
                cursor.execute(
                    sql.SQL("SET LOCAL statement_timeout = {}").format(STATEMENT_TIMEOUT)
                )
                # binary=True forces the extended protocol, which rejects multiple statements.
                cursor.execute(query, binary=True)
                columns = [c.name for c in cursor.description or []]
                return columns, cursor.fetchall()
            except psycopg.Error as exc:
                raise QueryError(str(exc).strip()) from exc
            finally:
                cursor.execute("ROLLBACK")
