"""Read-only role for dashboards, and a continuous aggregate of daily sensor statistics.

* ``grafana_reader``: LOGIN, SELECT only, on ``public`` and ``marts`` (now and for tables
  created later by the migrating role, i.e. dbt). Dashboards never connect as the owner.
* ``sensor_daily``: TimescaleDB continuous aggregate of ``tool_sensor_readings`` per day,
  chamber and parameter (count, mean, sd, min, max). Dashboard panels over months read ~100
  rows per series instead of scanning millions (docs/perf.md, query 02). Real-time
  aggregation is on, so data newer than the last refresh still shows; the loader refreshes
  it after every load.
* ``ewma(z, lambda)``: an aggregate that, used as a window function
  (``ewma(z, 0.2) OVER (ORDER BY time)``), returns the EWMA statistic of
  ``waferlens.spc.charts.ewma`` in one pass, so a dashboard can draw an EWMA chart in SQL.

Continuous aggregates can't be created inside a transaction, hence the autocommit blocks.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READER = "grafana_reader"


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
    for schema in ("public", "marts"):
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {READER}")
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {READER}")
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {READER}"
        )

    with op.get_context().autocommit_block():
        op.execute("""
            CREATE MATERIALIZED VIEW sensor_daily
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT
                time_bucket(INTERVAL '1 day', time) AS day,
                chamber_id,
                parameter_id,
                count(*) AS n,
                avg(value) AS mean_value,
                stddev_samp(value) AS sd_value,
                min(value) AS min_value,
                max(value) AS max_value
            FROM tool_sensor_readings
            GROUP BY day, chamber_id, parameter_id
            WITH NO DATA
        """)
    op.execute(f"GRANT SELECT ON sensor_daily TO {READER}")

    # w_1 = lambda z_1 (w_0 = 0), w_i = lambda z_i + (1 - lambda) w_{i-1}: as in spc/charts.py.
    op.execute("""
        CREATE FUNCTION ewma_step(state double precision, z double precision,
                                  lam double precision)
        RETURNS double precision LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT CASE WHEN state IS NULL THEN lam * z ELSE lam * z + (1 - lam) * state END
        $$
    """)
    op.execute("""
        CREATE AGGREGATE ewma(double precision, double precision) (
            SFUNC = ewma_step,
            STYPE = double precision
        )
    """)


def downgrade() -> None:
    op.execute("DROP AGGREGATE IF EXISTS ewma(double precision, double precision)")
    op.execute(
        "DROP FUNCTION IF EXISTS ewma_step(double precision, double precision, double precision)"
    )
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS sensor_daily")
    # The role is cluster-wide (other databases, e.g. the test database, may still use it), so
    # only this database's privileges are removed. dbt owns marts and may have dropped it.
    for schema in ("public", "marts"):
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{schema}') THEN
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
                        REVOKE SELECT ON TABLES FROM {READER};
                    REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {READER};
                    REVOKE USAGE ON SCHEMA {schema} FROM {READER};
                END IF;
            END $$;
        """)
    op.execute(f"""
        DO $$ BEGIN
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {READER}', current_database());
        END $$;
    """)
