"""FabEye's wafer-map classifications (waferlens.patterns): one row per sorted wafer with the
predicted WM-811K pattern, confidence, auto-accept flag and conformal prediction set. Written
by the scoring asset, not the loader.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wafer_patterns",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("auto_accept", sa.Boolean(), nullable=False),
        sa.Column("prediction_set", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("alpha", sa.Double(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("scored_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_wafer_patterns_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_wafer_patterns_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint("wafer_id", name=op.f("pk_wafer_patterns")),
    )
    op.create_index(op.f("ix_wafer_patterns_pattern"), "wafer_patterns", ["pattern"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_wafer_patterns_pattern"), table_name="wafer_patterns")
    op.drop_table("wafer_patterns")
