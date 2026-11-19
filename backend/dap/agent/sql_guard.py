"""Application-side SQL guard (K9, layer 2).

The database-side layer is the dataset's own read-only role; this guard rejects everything that
is not a single read-only query on the dataset schema before it reaches the database.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

BLOCKED_FUNCTIONS = frozenset(
    {
        "set_config",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
    }
)
BLOCKED_FUNCTION_PREFIXES = ("pg_sleep", "pg_read_", "lo_", "dblink", "pg_advisory")
DATA_MODIFYING = (exp.DML, exp.DDL, exp.Drop, exp.Alter, exp.TruncateTable, exp.Command)


class SqlRejected(Exception):
    """The query is not allowed; `reason` says why and is safe to show to the model."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def check_sql(sql: str, schema: str) -> None:
    """Raise `SqlRejected` unless `sql` is one read-only SELECT on tables of `schema`."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise SqlRejected(f"Could not parse the query: {exc}") from exc
    if len(statements) != 1:
        raise SqlRejected("The query must be exactly one single statement.")
    tree = statements[0]

    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise SqlRejected("Only SELECT queries are allowed.")
    if tree.find(exp.Into):
        raise SqlRejected("SELECT ... INTO is not allowed.")
    if modifying := tree.find(*DATA_MODIFYING):
        raise SqlRejected(f"The query modifies data ({modifying.key.upper()}).")

    for table in tree.find_all(exp.Table):
        qualifier = table.args.get("db")
        if isinstance(qualifier, exp.Identifier) and _identifier(qualifier) != schema:
            raise SqlRejected(
                f"Table {table.sql(dialect='postgres')} is outside the dataset schema '{schema}'."
            )

    for function in tree.find_all(exp.Func):
        name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        name = name.lower()
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_FUNCTION_PREFIXES):
            raise SqlRejected(f"Function {name}() is not allowed.")


def _identifier(identifier: exp.Identifier) -> str:
    """The name as Postgres resolves it: unquoted identifiers fold to lower case."""
    return identifier.name if identifier.quoted else identifier.name.lower()
