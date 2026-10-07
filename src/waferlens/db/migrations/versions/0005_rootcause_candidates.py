"""Root-cause candidates: ranked suspects from commonality analysis of each excursion window.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rootcause_candidates",
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("excursion_id", sa.Integer(), nullable=False),
        sa.Column("window_start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("window_end", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("factor_type", sa.Text(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("n_through", sa.Integer(), nullable=False),
        sa.Column("low_through", sa.Integer(), nullable=False),
        sa.Column("n_population", sa.Integer(), nullable=False),
        sa.Column("n_low", sa.Integer(), nullable=False),
        sa.Column("lift", sa.Double(), nullable=True),
        sa.Column("chi2", sa.Double(), nullable=True),
        sa.Column("suspect_rank", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(factor_type = 'chamber') = (chamber_id IS NOT NULL AND recipe_id IS NULL) AND (factor_type = 'recipe') = (recipe_id IS NOT NULL AND chamber_id IS NULL)",
            name=op.f("ck_rootcause_candidates_one_factor"),
        ),
        sa.CheckConstraint(
            "factor_type IN ('chamber', 'recipe')",
            name=op.f("ck_rootcause_candidates_factor_type_valid"),
        ),
        sa.CheckConstraint(
            "0 <= low_through AND low_through <= n_through AND n_through <= n_population",
            name=op.f("ck_rootcause_candidates_counts_consistent"),
        ),
        sa.CheckConstraint("suspect_rank >= 1", name=op.f("ck_rootcause_candidates_rank_positive")),
        sa.CheckConstraint(
            "window_end > window_start", name=op.f("ck_rootcause_candidates_window_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_rootcause_candidates_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["excursion_id"],
            ["excursions_ground_truth.excursion_id"],
            name=op.f("fk_rootcause_candidates_excursion_id_excursions_ground_truth"),
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.recipe_id"],
            name=op.f("fk_rootcause_candidates_recipe_id_recipes"),
        ),
        sa.PrimaryKeyConstraint("candidate_id", name=op.f("pk_rootcause_candidates")),
        sa.UniqueConstraint(
            "excursion_id",
            "factor_type",
            "chamber_id",
            "recipe_id",
            name=op.f("uq_rootcause_candidates_excursion_id_factor_type_chamber_id_recipe_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_rootcause_candidates_excursion_id"),
        "rootcause_candidates",
        ["excursion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rootcause_candidates_excursion_id"), table_name="rootcause_candidates")
    op.drop_table("rootcause_candidates")
