"""Commonality analysis: which chamber or recipe do the low-yield wafers have in common?

Given only a time window (when yield dropped), the query

1. takes every sorted wafer processed at any step inside the window;
2. labels a wafer *low yield* when it is below its own product's normal yield: the
   ``low_quantile`` of that product over all its sorted wafers. Per product, so a product that
   always yields lower can't pose as a cause; over the product's whole history, not just the
   window, so a cause that hits every wafer of one product (a bad recipe, which belongs to
   one product's route) still shows up as low yield;
3. lists every chamber and every recipe version a wafer met **inside the window**;
4. scores each candidate on the 2x2 table (through it or not x low yield or not): lift
   (low-yield rate through it / overall) and the chi-square statistic;
5. ranks over-represented candidates (lift > 1) by chi-square, the evidence that the excess is
   not chance, then by lift.

The counting and scoring are one SQL statement over the dbt marts, so the same logic serves
an engineer's ad-hoc window and the evaluation against every injected excursion.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, text

COMMONALITY_SQL = """
with population as (
    select distinct wafer_id
    from marts.fct_wafer_steps
    where track_in_at >= :window_start and track_in_at < :window_end
),

yields as (
    select y.wafer_id, y.product_id, y.yield_pct
    from marts.fct_wafer_yield as y
    inner join population as p on y.wafer_id = p.wafer_id
),

-- Low yield = below the product's normal (its own history): products differ in die size and
-- node, and a window-only cut would hide a cause that degrades every wafer of one product.
cutoffs as (
    select product_id, percentile_cont(:low_quantile) within group (order by yield_pct) as cut
    from marts.fct_wafer_yield
    group by product_id
),

labelled as (
    select y.wafer_id, y.yield_pct < c.cut as is_low
    from yields as y
    inner join cutoffs as c on y.product_id = c.product_id
),

-- Every chamber and recipe version each wafer met inside the window (not before or after).
usage as (
    select distinct s.wafer_id, 'chamber' as factor_type, s.chamber_id as factor_id
    from marts.fct_wafer_steps as s
    inner join labelled as l on s.wafer_id = l.wafer_id
    where s.track_in_at >= :window_start and s.track_in_at < :window_end
    union
    select distinct s.wafer_id, 'recipe', s.recipe_id
    from marts.fct_wafer_steps as s
    inner join labelled as l on s.wafer_id = l.wafer_id
    where s.track_in_at >= :window_start and s.track_in_at < :window_end
),

totals as (
    select count(*) as n_population, sum(is_low::int) as n_low from labelled
),

counts as (
    select u.factor_type, u.factor_id, count(*) as n_through, sum(l.is_low::int) as low_through
    from usage as u
    inner join labelled as l on u.wafer_id = l.wafer_id
    group by u.factor_type, u.factor_id
),

-- 2x2 table per candidate:      low                       not low
--   through it          a = low_through             b = n_through - a
--   not through it      c = n_low - a               d = n_population - n_through - c
-- chi-square = N (ad - bc)^2 / ((a+b)(c+d)(a+c)(b+d))
scored as (
    select
        c.factor_type,
        c.factor_id,
        c.n_through,
        c.low_through,
        t.n_population,
        t.n_low,
        (c.low_through::float / c.n_through) / nullif(t.n_low::float / t.n_population, 0)
            as lift,
        t.n_population * power(
            c.low_through::float * (t.n_population - c.n_through - (t.n_low - c.low_through))
            - (c.n_through - c.low_through)::float * (t.n_low - c.low_through),
            2
        ) / nullif(
            c.n_through::float * (t.n_population - c.n_through) * t.n_low
            * (t.n_population - t.n_low),
            0
        ) as chi2
    from counts as c
    cross join totals as t
    where c.n_through >= :min_support
)

select
    *,
    rank() over (
        order by case when lift > 1 then chi2 else 0 end desc nulls last, lift desc nulls last
    ) as suspect_rank
from scored
order by suspect_rank
"""


def commonality(
    engine: Engine,
    window_start: datetime,
    window_end: datetime,
    *,
    low_quantile: float = 0.2,
    min_support: int = 5,
) -> pd.DataFrame:
    """Ranked suspects (chambers and recipe versions) for a yield problem in a time window."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(COMMONALITY_SQL),
            {"window_start": window_start, "window_end": window_end,
             "low_quantile": low_quantile, "min_support": min_support},
        ).mappings().all()  # fmt: skip
    return pd.DataFrame(rows)
