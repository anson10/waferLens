"""Read-only role for Power BI, limited to the dbt marts (the star schema it models).

``powerbi_reader`` can connect and SELECT from ``marts`` only: no raw tables in ``public``,
no staging views, no writes. dbt's ``+grants`` keeps rebuilt marts readable; the default
privileges cover tables the migrating role creates later.

The password is the role name, like ``grafana_reader`` (migration 0006): a local demo
setting; change it with ALTER ROLE outside a demo.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READER = "powerbi_reader"


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} LOGIN PASSWORD '{READER}';
            END IF;
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {READER}', current_database());
        END
        $$;
    """)
    op.execute("CREATE SCHEMA IF NOT EXISTS marts")
    op.execute(f"GRANT USAGE ON SCHEMA marts TO {READER}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA marts TO {READER}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA marts GRANT SELECT ON TABLES TO {READER}")


def downgrade() -> None:
    # The role is cluster-wide (other databases may use it): remove this database's grants.
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'marts') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA marts REVOKE SELECT ON TABLES FROM {READER};
                REVOKE ALL ON ALL TABLES IN SCHEMA marts FROM {READER};
                REVOKE USAGE ON SCHEMA marts FROM {READER};
            END IF;
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {READER}', current_database());
        END $$;
    """)
