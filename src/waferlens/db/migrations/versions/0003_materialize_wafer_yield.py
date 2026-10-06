"""Materialize wafer_yield.

Yield per wafer is read by every report (commonality, weekly yield, excursion impact) but
only changes when data is loaded. As a plain view it was recomputed from wafer_bin_summary
on every query, and once per parallel worker; EXPLAIN on the stress profile showed it as
~570 ms of each ~1 s query. The loader now refreshes it once per load (docs/perf.md).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

YIELD_SELECT = """
-- Yield per sorted wafer: good dies / tested dies. Pass/fail comes from sort_bins.is_pass,
-- so adding a new fail bin never needs a change here.
SELECT
    s.wafer_id,
    SUM(s.die_count)                                        AS tested_dies,
    COALESCE(SUM(s.die_count) FILTER (WHERE b.is_pass), 0)  AS good_dies,
    ROUND(
        100.0 * COALESCE(SUM(s.die_count) FILTER (WHERE b.is_pass), 0)
        / NULLIF(SUM(s.die_count), 0),
        2
    )                                                       AS yield_pct
FROM wafer_bin_summary s
JOIN sort_bins b USING (bin_code)
GROUP BY s.wafer_id
"""


def upgrade() -> None:
    op.execute("DROP VIEW wafer_yield")
    op.execute(f"CREATE MATERIALIZED VIEW wafer_yield AS {YIELD_SELECT}")
    # Unique index: fast lookups by wafer, and allows REFRESH ... CONCURRENTLY later.
    op.execute("CREATE UNIQUE INDEX ux_wafer_yield_wafer_id ON wafer_yield (wafer_id)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW wafer_yield")
    op.execute(f"CREATE VIEW wafer_yield AS {YIELD_SELECT}")
