"""Root-cause candidates record which signal marked a wafer as bad: low yield (phase 3) or a
wafer-map pattern seen by FabEye (phase 5a, pattern-led investigation). Existing rows are
yield-based, hence the server default.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "rootcause_candidates"
OLD_UNIQUE = "uq_rootcause_candidates_excursion_id_factor_type_chambe_07a3"
NEW_UNIQUE = "uq_rootcause_candidates_excursion_id_signal_factor_type_df02"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("signal", sa.Text(), server_default="yield", nullable=False))
    op.add_column(TABLE, sa.Column("pattern", sa.Text(), nullable=True))
    op.drop_constraint(OLD_UNIQUE, TABLE, type_="unique")
    op.create_unique_constraint(
        NEW_UNIQUE, TABLE, ["excursion_id", "signal", "factor_type", "chamber_id", "recipe_id"],
        postgresql_nulls_not_distinct=True,
    )  # fmt: skip
    op.create_check_constraint(
        "ck_rootcause_candidates_signal_valid", TABLE, "signal IN ('yield', 'pattern')"
    )
    op.create_check_constraint(
        "ck_rootcause_candidates_pattern_iff_signal",
        TABLE,
        "(signal = 'pattern') = (pattern IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM {TABLE} WHERE signal <> 'yield'")
    op.drop_constraint("ck_rootcause_candidates_pattern_iff_signal", TABLE, type_="check")
    op.drop_constraint("ck_rootcause_candidates_signal_valid", TABLE, type_="check")
    op.drop_constraint(NEW_UNIQUE, TABLE, type_="unique")
    op.create_unique_constraint(
        OLD_UNIQUE, TABLE, ["excursion_id", "factor_type", "chamber_id", "recipe_id"],
        postgresql_nulls_not_distinct=True,
    )  # fmt: skip
    op.drop_column(TABLE, "pattern")
    op.drop_column(TABLE, "signal")
