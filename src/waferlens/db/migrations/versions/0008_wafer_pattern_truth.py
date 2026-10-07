"""Per-wafer ground truth for wafer-map patterns: which sorted wafers show an injected
spatial pattern, and from which excursion. FabEye's predictions (phase 5a) are scored
against it; it is loaded with the rest of the simulated fab.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wafer_pattern_truth",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("excursion_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["excursion_id"],
            ["excursions_ground_truth.excursion_id"],
            name=op.f("fk_wafer_pattern_truth_excursion_id_excursions_ground_truth"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_wafer_pattern_truth_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint("wafer_id", name=op.f("pk_wafer_pattern_truth")),
    )
    op.create_index(
        op.f("ix_wafer_pattern_truth_excursion_id"),
        "wafer_pattern_truth",
        ["excursion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wafer_pattern_truth_excursion_id"), table_name="wafer_pattern_truth")
    op.drop_table("wafer_pattern_truth")
