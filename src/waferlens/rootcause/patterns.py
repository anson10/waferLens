"""Does a wafer-map pattern (from FabEye) help root cause? Three rankings per excursion:

1. yield:        phase 3, low-yield wafers (``rootcause_candidates``, signal 'yield');
2. window rule:  the pattern most over-represented in the window, used instead of yield when
                 strong (>= 10 wafers at >= 3x background), a rule fixed before evaluation;
3. pattern-led:  for spatial excursions, the excursion's own pattern, as an engineer starting
                 from the pattern on the wafers (or from a pattern alarm) would use it
                 (``rootcause_candidates``, signal 'pattern').

The window rule is computed here, not stored: it failed, and is kept as the record of why.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

from waferlens.rootcause.commonality import commonality, window_pattern

EVAL_SQL = """
    select r.excursion_id, r.excursion_type, r.spatial_pattern, r.cost_yield,
           r.true_rank, r.pattern_true_rank, g.chamber_id, g.recipe_id, g.start_time, g.end_time
    from marts.fct_root_cause_eval as r
    join excursions_ground_truth as g using (excursion_id)
    order by r.excursion_id
"""


def _true_rank(ranked: pd.DataFrame, chamber_id: object, recipe_id: object) -> int | None:
    if ranked.empty:
        return None
    if pd.notna(recipe_id):  # type: ignore[arg-type]
        hit = ranked[(ranked["factor_type"] == "recipe") & (ranked["factor_id"] == recipe_id)]
    else:
        hit = ranked[(ranked["factor_type"] == "chamber") & (ranked["factor_id"] == chamber_id)]
    return int(hit["suspect_rank"].iloc[0]) if len(hit) else None


def compare(engine: Engine) -> pd.DataFrame:
    """One row per excursion: true-cause rank under each of the three rankings."""
    with engine.connect() as conn:
        ev = pd.DataFrame(conn.execute(text(EVAL_SQL)).mappings().all())
    rule_ranks, rule_patterns = [], []
    for r in ev.to_dict("records"):
        wp = window_pattern(engine, r["start_time"], r["end_time"])
        if wp is not None and wp.strong:
            ranked = commonality(engine, r["start_time"], r["end_time"], pattern=wp.pattern)
            rule_ranks.append(_true_rank(ranked, r["chamber_id"], r["recipe_id"]))
            rule_patterns.append(wp.pattern)
        else:  # no strong pattern: the rule keeps the yield ranking
            rule_ranks.append(None if pd.isna(r["true_rank"]) else int(r["true_rank"]))
            rule_patterns.append(None)
    return ev.assign(rule_rank=pd.array(rule_ranks, dtype="Int64"), rule_pattern=rule_patterns)
