"""Commonality analysis on a small planted dataset: it finds the cause and avoids the traps.

The SQL reads marts.fct_wafer_steps and marts.fct_wafer_yield; this module creates those two
tables with only the columns the query uses, in the test database.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import Engine, text

from waferlens.rootcause.commonality import commonality

pytestmark = pytest.mark.integration

T0 = datetime(2026, 3, 1, tzinfo=UTC)
WINDOW = (T0 + timedelta(days=10), T0 + timedelta(days=20))


def _scenario() -> tuple[pd.DataFrame, pd.DataFrame]:
    """400 wafers, two products, two steps; wafers start evenly over 30 days.

    Planted:  chamber 2 (step 1) costs 15 yield points, but only inside the window.
    Traps:    product 2 always yields ~10 points lower and always runs in chamber 3;
              chamber 6 (step 2) was bad only *before* the window.
    Recipes:  step 2 runs recipe 20 (v1); product 1 switches to recipe 21 (v2) inside the
              window, and v2 costs nothing.
    """
    steps, yields = [], []
    for w in range(400):
        product = 2 if w % 4 == 0 else 1
        start = T0 + timedelta(hours=w * 1.8)
        chamber1 = 3 if product == 2 else 1 + (w % 2)  # chambers 1, 2 for product 1
        chamber2 = 5 + (w // 2) % 2  # independent of the step-1 chamber choice
        t1, t2 = start, start + timedelta(hours=2)
        in_window = WINDOW[0] <= t1 < WINDOW[1]
        recipe2 = 21 if product == 1 and in_window else 20
        steps += [(w, chamber1, 10, t1), (w, chamber2, recipe2, t2)]
        y = 90.0 - (10.0 if product == 2 else 0.0) + (w % 7) * 0.3
        if chamber1 == 2 and in_window:
            y -= 15
        if chamber2 == 6 and t2 < WINDOW[0]:
            y -= 15
        yields.append((w, product, y))
    return (
        pd.DataFrame(steps, columns=["wafer_id", "chamber_id", "recipe_id", "track_in_at"]),
        pd.DataFrame(yields, columns=["wafer_id", "product_id", "yield_pct"]),
    )


@pytest.fixture(scope="module")
def planted(engine: Engine) -> Iterator[None]:
    steps, yields = _scenario()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS marts"))
        conn.execute(text("DROP TABLE IF EXISTS marts.fct_wafer_steps, marts.fct_wafer_yield"))
        conn.execute(text("CREATE TABLE marts.fct_wafer_steps (wafer_id int, chamber_id int, "
                          "recipe_id int, track_in_at timestamptz)"))  # fmt: skip
        conn.execute(text("CREATE TABLE marts.fct_wafer_yield (wafer_id int, product_id int, "
                          "yield_pct numeric)"))  # fmt: skip
        conn.execute(
            text("INSERT INTO marts.fct_wafer_steps VALUES (:w, :c, :r, :t)"),
            [{"w": w, "c": c, "r": r, "t": t} for w, c, r, t in steps.itertuples(index=False)],
        )
        conn.execute(
            text("INSERT INTO marts.fct_wafer_yield VALUES (:w, :p, :y)"),
            [{"w": w, "p": p, "y": y} for w, p, y in yields.itertuples(index=False)],
        )
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS marts.fct_wafer_steps, marts.fct_wafer_yield"))


def _rank(ranked: pd.DataFrame, factor_type: str, factor_id: int) -> int | None:
    hit = ranked[(ranked["factor_type"] == factor_type) & (ranked["factor_id"] == factor_id)]
    return int(hit["suspect_rank"].iloc[0]) if len(hit) else None


def test_planted_chamber_ranks_first(engine: Engine, planted: None) -> None:
    ranked = commonality(engine, *WINDOW)
    assert _rank(ranked, "chamber", 2) == 1
    top = ranked.iloc[0]
    assert top["lift"] > 1.5
    assert top["low_through"] <= top["n_through"] <= top["n_population"]


def test_a_low_yield_product_does_not_frame_its_chamber(engine: Engine, planted: None) -> None:
    # Chamber 3 runs only product 2, which always yields ~10 points lower. Judged against
    # its own product's normal yield, it is not a suspect.
    ranked = commonality(engine, *WINDOW)
    row = ranked[(ranked["factor_type"] == "chamber") & (ranked["factor_id"] == 3)].iloc[0]
    assert row["lift"] < 1.2
    assert int(row["suspect_rank"]) > 3


def test_only_usage_inside_the_window_counts(engine: Engine, planted: None) -> None:
    # Chamber 6 was bad before the window; inside it, it is just another chamber.
    ranked = commonality(engine, *WINDOW)
    row = ranked[(ranked["factor_type"] == "chamber") & (ranked["factor_id"] == 6)].iloc[0]
    assert row["lift"] < 1.3
    earlier = commonality(engine, T0, WINDOW[0])
    assert _rank(earlier, "chamber", 6) == 1  # in its own window it is the top suspect


def test_a_harmless_recipe_change_is_not_blamed(engine: Engine, planted: None) -> None:
    ranked = commonality(engine, *WINDOW)
    rank = _rank(ranked, "recipe", 21)
    assert rank is not None
    assert rank > _rank(ranked, "chamber", 2)  # type: ignore[operator]


def test_min_support_drops_tiny_groups(engine: Engine, planted: None) -> None:
    window_hours = (WINDOW[0], WINDOW[0] + timedelta(hours=6))
    assert commonality(engine, *window_hours, min_support=50).empty
