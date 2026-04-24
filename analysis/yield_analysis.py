"""Yield aggregations: by lot, product, technology node, tool."""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from analysis.queries import (
    low_yield_wafers,
    yield_by_lot,
    yield_by_node,
    yield_by_product,
)


def yield_summary(session: Session) -> dict[str, pd.DataFrame]:
    """Return yield DataFrames keyed by grouping dimension."""
    return {
        "by_lot": pd.DataFrame(yield_by_lot(session)),
        "by_product": pd.DataFrame(yield_by_product(session)),
        "by_node": pd.DataFrame(yield_by_node(session)),
    }


def defect_density_trend(session: Session) -> pd.DataFrame:
    """Defect density over time, one row per lot ordered by start_date."""
    rows = yield_by_lot(session)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)[["lot_id", "start_date", "avg_defect_density"]]
    df["start_date"] = pd.to_datetime(df["start_date"])
    return df.sort_values("start_date").reset_index(drop=True)


def low_yield_summary(session: Session, threshold: float = 80.0) -> pd.DataFrame:
    """DataFrame of wafers below threshold, with lot context."""
    rows = low_yield_wafers(session, threshold)
    return pd.DataFrame(rows) if rows else pd.DataFrame()
