"""Synthetic `sales` and `hr` datasets (K18) and their read-only LOGIN roles (K9, layer 1).

Both live in the `datasets` database, one schema per dataset; the schema name is the dataset id.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import psycopg
import sqlalchemy as sa
from faker import Faker
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.pool import NullPool

from dap.settings import Settings

SEED = 20251101
N_CUSTOMERS = 500
N_ORDERS = 5000
N_EMPLOYEES = 300
ORDER_DATES = (date(2025, 1, 1), date(2026, 10, 31))
HIRE_DATES = (date(2015, 1, 1), date(2026, 6, 30))


@dataclass(frozen=True)
class DatasetSpec:
    id: str  # also the schema name in the datasets database
    name: str
    description: str
    db_role: str


DATASETS = (
    DatasetSpec(
        id="sales",
        name="Sales",
        description="Customers, products, orders and order line items (2025-01 to 2026-10).",
        db_role="ds_sales_ro",
    ),
    DatasetSpec(
        id="hr",
        name="HR",
        description="Departments, employees and their salary history.",
        db_role="ds_hr_ro",
    ),
)


def get_dataset(dataset_id: str) -> DatasetSpec:
    """Raises KeyError for an unknown dataset id."""
    return {spec.id: spec for spec in DATASETS}[dataset_id]


def role_password(settings: Settings, spec: DatasetSpec) -> SecretStr:
    passwords = {
        "ds_sales_ro": settings.ds_sales_ro_password,
        "ds_hr_ro": settings.ds_hr_ro_password,
    }
    return passwords[spec.db_role]


def role_url(settings: Settings, spec: DatasetSpec, driver: str = "psycopg") -> sa.URL:
    """URL that logs in to the datasets database as the dataset's own read-only role."""
    return settings.datasets_db_url(
        driver, username=spec.db_role, password=role_password(settings, spec)
    )


def create_admin_engine(settings: Settings, **kwargs: Any) -> sa.Engine:
    """Engine for the datasets database as the Postgres admin user."""
    return sa.create_engine(settings.datasets_db_url("psycopg"), **kwargs)


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.Integer, primary_key=True, autoincrement=False)


def _money(name: str) -> sa.Column[Decimal]:
    return sa.Column(name, sa.Numeric(12, 2), nullable=False)


def _text(name: str) -> sa.Column[str]:
    return sa.Column(name, sa.Text, nullable=False)


metadata = sa.MetaData()

customers = sa.Table(
    "customers",
    metadata,
    _id(),
    _text("name"),
    _text("email"),
    _text("city"),
    _text("country"),
    _text("segment"),
    schema="sales",
)
products = sa.Table(
    "products",
    metadata,
    _id(),
    _text("name"),
    _text("category"),
    _money("unit_price"),
    schema="sales",
)
orders = sa.Table(
    "orders",
    metadata,
    _id(),
    sa.Column("customer_id", sa.ForeignKey("sales.customers.id"), nullable=False),
    sa.Column("order_date", sa.Date, nullable=False),
    _text("status"),
    schema="sales",
)
order_items = sa.Table(
    "order_items",
    metadata,
    _id(),
    sa.Column("order_id", sa.ForeignKey("sales.orders.id"), nullable=False),
    sa.Column("product_id", sa.ForeignKey("sales.products.id"), nullable=False),
    sa.Column("quantity", sa.Integer, nullable=False),
    _money("unit_price"),
    schema="sales",
)
departments = sa.Table("departments", metadata, _id(), _text("name"), schema="hr")
employees = sa.Table(
    "employees",
    metadata,
    _id(),
    _text("first_name"),
    _text("last_name"),
    _text("email"),
    sa.Column("department_id", sa.ForeignKey("hr.departments.id"), nullable=False),
    _text("title"),
    sa.Column("hire_date", sa.Date, nullable=False),
    schema="hr",
)
salaries = sa.Table(
    "salaries",
    metadata,
    _id(),
    sa.Column("employee_id", sa.ForeignKey("hr.employees.id"), nullable=False),
    _money("annual_salary_usd"),
    sa.Column("effective_from", sa.Date, nullable=False),
    schema="hr",
)

PRODUCT_CATALOG = {
    "Electronics": ["Headphones", "Monitor", "Keyboard", "Mouse", "Webcam", "Speaker"],
    "Office": ["Desk", "Chair", "Desk Lamp", "Notebook", "Pen Set"],
    "Home": ["Coffee Maker", "Blender", "Kettle", "Toaster", "Air Purifier"],
    "Outdoor": ["Backpack", "Tent", "Water Bottle", "Sleeping Bag"],
}
PRODUCT_TIERS = ["Basic", "Plus", "Pro"]
COUNTRIES = ["United States", "Canada", "United Kingdom", "Germany", "France", "Netherlands"]
SEGMENTS = ["consumer", "small_business", "enterprise"]
ORDER_STATUSES = ["completed", "shipped", "cancelled", "returned"]
ORDER_STATUS_WEIGHTS = [80, 8, 7, 5]
DEPARTMENTS = [
    "Engineering",
    "Sales",
    "Marketing",
    "Finance",
    "Human Resources",
    "Operations",
    "Customer Support",
    "Legal",
]
TITLE_BASE_SALARY = {
    "Associate": 55_000,
    "Specialist": 70_000,
    "Senior Specialist": 90_000,
    "Manager": 115_000,
    "Director": 150_000,
}

Rows = list[dict[str, Any]]


def _random_date(rng: random.Random, span: tuple[date, date]) -> date:
    return span[0] + timedelta(days=rng.randint(0, (span[1] - span[0]).days))


def _cents(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _sales_rows(fake: Faker, rng: random.Random) -> list[tuple[sa.Table, Rows]]:
    customer_rows = [
        {
            "id": i,
            "name": fake.name(),
            "email": fake.email(),
            "city": fake.city(),
            "country": rng.choice(COUNTRIES),
            "segment": rng.choice(SEGMENTS),
        }
        for i in range(1, N_CUSTOMERS + 1)
    ]
    product_rows = [
        {"name": f"{item} {tier}", "category": category, "unit_price": _cents(rng.uniform(5, 800))}
        for category, items in PRODUCT_CATALOG.items()
        for item in items
        for tier in PRODUCT_TIERS
    ]
    for i, row in enumerate(product_rows, start=1):
        row["id"] = i

    order_rows: Rows = []
    item_rows: Rows = []
    for order_id in range(1, N_ORDERS + 1):
        order_rows.append(
            {
                "id": order_id,
                "customer_id": rng.randint(1, N_CUSTOMERS),
                "order_date": _random_date(rng, ORDER_DATES),
                "status": rng.choices(ORDER_STATUSES, ORDER_STATUS_WEIGHTS)[0],
            }
        )
        for product in rng.sample(product_rows, rng.randint(1, 4)):
            item_rows.append(
                {
                    "id": len(item_rows) + 1,
                    "order_id": order_id,
                    "product_id": product["id"],
                    "quantity": rng.randint(1, 5),
                    "unit_price": product["unit_price"],
                }
            )
    return [
        (customers, customer_rows),
        (products, product_rows),
        (orders, order_rows),
        (order_items, item_rows),
    ]


def _hr_rows(fake: Faker, rng: random.Random) -> list[tuple[sa.Table, Rows]]:
    department_rows = [{"id": i, "name": name} for i, name in enumerate(DEPARTMENTS, start=1)]
    employee_rows: Rows = []
    salary_rows: Rows = []
    for employee_id in range(1, N_EMPLOYEES + 1):
        first, last = fake.first_name(), fake.last_name()
        title = rng.choice(list(TITLE_BASE_SALARY))
        hire_date = _random_date(rng, HIRE_DATES)
        employee_rows.append(
            {
                "id": employee_id,
                "first_name": first,
                "last_name": last,
                "email": f"{first}.{last}.{employee_id}@example.com".lower().replace(" ", ""),
                "department_id": rng.randint(1, len(DEPARTMENTS)),
                "title": title,
                "hire_date": hire_date,
            }
        )
        # One salary record at hire, then a raise roughly every year up to the data cutoff.
        salary = TITLE_BASE_SALARY[title] * rng.uniform(0.85, 1.25)
        effective_from = hire_date
        while effective_from <= ORDER_DATES[1]:
            salary_rows.append(
                {
                    "id": len(salary_rows) + 1,
                    "employee_id": employee_id,
                    "annual_salary_usd": _cents(salary),
                    "effective_from": effective_from,
                }
            )
            salary *= rng.uniform(1.02, 1.08)
            effective_from += timedelta(days=rng.randint(330, 420))
    return [(departments, department_rows), (employees, employee_rows), (salaries, salary_rows)]


def _is_populated(conn: sa.Connection) -> bool:
    inspector = sa.inspect(conn)
    return all(inspector.has_schema(spec.id) for spec in DATASETS)


def _generate(conn: sa.Connection) -> None:
    fake = Faker("en_US")
    fake.seed_instance(SEED)
    rng = random.Random(SEED)
    for spec in DATASETS:
        conn.execute(sa.schema.CreateSchema(spec.id))
    metadata.create_all(conn)
    for table, rows in [*_sales_rows(fake, rng), *_hr_rows(fake, rng)]:
        conn.execute(table.insert(), rows)


def _execute(conn: sa.Connection, query: sql.SQL | sql.Composed) -> None:
    """Run a statement that needs client-side quoting (identifiers, password literals)."""
    raw = cast(psycopg.Connection[Any], conn.connection.driver_connection)
    with raw.cursor() as cursor:
        cursor.execute(query)


def _apply_roles(conn: sa.Connection, settings: Settings) -> None:
    database = sql.Identifier(settings.datasets_db_name)
    # Nobody gets anything by default: no CONNECT/TEMP on the database, nothing in `public`.
    _execute(conn, sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database))
    _execute(conn, sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
    for spec in DATASETS:
        role, schema = sql.Identifier(spec.db_role), sql.Identifier(spec.id)
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": spec.db_role}
        ).first()
        verb = sql.SQL("ALTER" if exists else "CREATE")
        statements = [
            sql.SQL(
                "{} ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}"
            ).format(verb, role, sql.Literal(role_password(settings, spec).get_secret_value())),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role),
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role),
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema, role),
        ]
        for statement in statements:
            _execute(conn, statement)


def ensure_datasets(settings: Settings) -> bool:
    """Generate the datasets unless present, then (re)apply the roles and their grants.

    Returns whether the data was generated. Safe to run repeatedly.
    """
    engine = create_admin_engine(settings, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            generate = not _is_populated(conn)
            if generate:
                _generate(conn)
            _apply_roles(conn, settings)
    finally:
        engine.dispose()
    return generate
