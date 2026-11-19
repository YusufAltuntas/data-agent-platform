"""Seed of the dap database (design §5): teams, memberships, datasets and grants. Idempotent.

The dataset catalog is owned by code and updated on every run. Memberships and grants are only
inserted when missing, so changes made later through the admin API are not reverted.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.pool import NullPool

from dap.db.datasets import DATASETS
from dap.db.models import Dataset, DatasetGrant, Membership, Role, Team
from dap.db.session import create_sync_engine
from dap.settings import Settings

TEAMS = {"sales": "Sales", "hr": "HR"}
MEMBERSHIPS = [
    ("sales", "alice@example.com", Role.ANALYST),
    ("sales", "bob@example.com", Role.VIEWER),
    ("hr", "carol@example.com", Role.ADMIN),
]
GRANTS = [("sales", "sales"), ("hr", "hr")]


def apply_seed(settings: Settings) -> None:
    engine = create_sync_engine(settings, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            teams = insert(Team).values([{"id": i, "name": n} for i, n in TEAMS.items()])
            conn.execute(
                teams.on_conflict_do_update(
                    index_elements=[Team.id], set_={"name": teams.excluded.name}
                )
            )

            datasets = insert(Dataset).values(
                [
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "description": spec.description,
                        "db_role": spec.db_role,
                    }
                    for spec in DATASETS
                ]
            )
            conn.execute(
                datasets.on_conflict_do_update(
                    index_elements=[Dataset.id],
                    set_={
                        "name": datasets.excluded.name,
                        "description": datasets.excluded.description,
                        "db_role": datasets.excluded.db_role,
                    },
                )
            )

            conn.execute(
                insert(Membership)
                .values([{"team_id": t, "email": e, "role": r} for t, e, r in MEMBERSHIPS])
                .on_conflict_do_nothing()
            )
            conn.execute(
                insert(DatasetGrant)
                .values([{"team_id": t, "dataset_id": d} for t, d in GRANTS])
                .on_conflict_do_nothing()
            )
    finally:
        engine.dispose()
