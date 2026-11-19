"""The SQL guard (K9, layer 2) accepts read-only queries on the dataset schema and nothing else."""

import pytest

from dap.agent.sql_guard import SqlRejected, check_sql

SCHEMA = "sales"


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param("SELECT id, name FROM customers", id="plain-select"),
        pytest.param("SELECT * FROM sales.orders;", id="own-schema-qualified"),
        pytest.param(
            "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id",
            id="join",
        ),
        pytest.param(
            "WITH recent AS (SELECT * FROM orders WHERE order_date >= '2026-01-01')"
            " SELECT count(*) FROM recent",
            id="read-only-cte",
        ),
        pytest.param(
            "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)",
            id="subquery",
        ),
        pytest.param(
            "SELECT country, count(*), sum(quantity * unit_price) FROM customers"
            " JOIN orders ON orders.customer_id = customers.id"
            " JOIN order_items ON order_items.order_id = orders.id"
            " GROUP BY country HAVING count(*) > 1 ORDER BY 2 DESC",
            id="aggregation",
        ),
        pytest.param("SELECT 1 UNION ALL SELECT 2", id="union"),
        pytest.param("SELECT lower(name), now() FROM customers", id="harmless-functions"),
    ],
)
def test_allowed(sql: str) -> None:
    check_sql(sql, SCHEMA)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        pytest.param("INSERT INTO orders (id) VALUES (1)", "SELECT", id="insert"),
        pytest.param("UPDATE orders SET status = 'x'", "SELECT", id="update"),
        pytest.param("DELETE FROM orders", "SELECT", id="delete"),
        pytest.param("DROP TABLE orders", "SELECT", id="drop"),
        pytest.param("CREATE TABLE scratch (id int)", "SELECT", id="create"),
        pytest.param("ALTER TABLE orders ADD COLUMN x int", "SELECT", id="alter"),
        pytest.param("SELECT 1; SELECT 2", "single statement", id="multiple-statements"),
        pytest.param("SELECT 1; DELETE FROM orders", "single statement", id="select-then-delete"),
        pytest.param("SELECT * INTO scratch FROM orders", "INTO", id="select-into"),
        pytest.param(
            "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone",
            "modifies data",
            id="data-modifying-cte",
        ),
        pytest.param(
            "WITH x AS (INSERT INTO orders (id) VALUES (1) RETURNING id) SELECT * FROM x",
            "modifies data",
            id="inserting-cte",
        ),
        pytest.param(
            "SELECT set_config('search_path', 'hr', false)", "set_config", id="set_config"
        ),
        pytest.param("SELECT pg_sleep(10)", "pg_sleep", id="pg_sleep"),
        pytest.param("SELECT pg_sleep_for('10 seconds')", "pg_sleep_for", id="pg_sleep_for"),
        pytest.param("SELECT pg_catalog.pg_sleep(10)", "pg_sleep", id="schema-qualified-function"),
        pytest.param('SELECT "PG_SLEEP"(1)', "pg_sleep", id="quoted-function"),
        pytest.param("SELECT pg_read_file('/etc/passwd')", "pg_read_file", id="pg_read"),
        pytest.param("SELECT pg_ls_dir('.')", "pg_ls_dir", id="pg_ls_dir"),
        pytest.param("SELECT pg_stat_file('postgresql.conf')", "pg_stat_file", id="pg_stat_file"),
        pytest.param("SELECT lo_import('/etc/passwd')", "lo_import", id="lo"),
        pytest.param("SELECT * FROM dblink('host=x', 'SELECT 1')", "dblink", id="dblink"),
        pytest.param(
            "SELECT pg_terminate_backend(1)", "pg_terminate_backend", id="pg_terminate_backend"
        ),
        pytest.param("SELECT pg_cancel_backend(1)", "pg_cancel_backend", id="pg_cancel_backend"),
        pytest.param("SELECT pg_reload_conf()", "pg_reload_conf", id="pg_reload_conf"),
        pytest.param("SELECT pg_advisory_lock(1)", "pg_advisory_lock", id="pg_advisory"),
        pytest.param(
            "SELECT id FROM orders WHERE id IN (SELECT pg_sleep(1))",
            "pg_sleep",
            id="function-in-subquery",
        ),
        pytest.param("SELECT * FROM hr.salaries", "schema", id="other-schema"),
        pytest.param(
            "SELECT * FROM orders JOIN hr.employees e ON true", "schema", id="other-schema-join"
        ),
        pytest.param("SELECT * FROM pg_catalog.pg_authid", "schema", id="pg_catalog-table"),
        pytest.param('SELECT * FROM "SALES".orders', "schema", id="quoted-schema-case"),
        pytest.param("", "single statement", id="empty"),
        pytest.param("SELEC 1", "parse", id="unparseable"),
        pytest.param("SET search_path = hr", "SELECT", id="set"),
        pytest.param("TRUNCATE orders", "SELECT", id="truncate"),
    ],
)
def test_rejected(sql: str, reason: str) -> None:
    with pytest.raises(SqlRejected, match=reason) as excinfo:
        check_sql(sql, SCHEMA)
    assert excinfo.value.reason == str(excinfo.value)
