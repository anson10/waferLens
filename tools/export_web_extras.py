"""Two more files for the replay page on ansonantony.tech, next to tools/export_web_replay.py.

ranks.json           every injected excursion with the rank commonality gave its true cause,
                     the number of suspects and whether it measurably cost yield
                     (marts.fct_root_cause_eval). The page draws the 72% from this.
excursion_<id>.json  for a SPATIAL excursion: no sensor moves, so there is no chart series.
                     Carries the ground truth, the commonality ranking, the yield, and what
                     FabEye saw on the wafers (the same queries as docs/excursion_story.md).

  uv run python tools/export_web_extras.py --spatial 12 --out /path/to/site/src/data/waferlens
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from export_web_replay import YIELD_SQL, iso
from sqlalchemy import text

from waferlens.db.session import get_engine
from waferlens.rootcause.story import (
    EXCURSION_SQL,
    PATTERN_DETECTION_SQL,
    SUSPECTS_SQL,
    TRUE_PATTERN_WAFERS_SQL,
)

RANKS_SQL = """
    select excursion_id, excursion_type, spatial_pattern, true_rank, candidates,
           pattern_true_rank, cost_yield
    from marts.fct_root_cause_eval order by excursion_id
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spatial", type=int, default=12)
    ap.add_argument("--yield-days", type=int, default=10)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    with engine.connect() as conn:
        ranks = [dict(r) for r in conn.execute(text(RANKS_SQL)).mappings()]
        x = {"x": args.spatial}
        e = dict(conn.execute(text(EXCURSION_SQL), x).mappings().one())
        assert e["spatial_pattern"], f"excursion {args.spatial} is not a spatial excursion"
        tool = conn.execute(
            text("select tool_id from marts.dim_chamber where chamber_id = :c"),
            {"c": e["chamber_id"]},
        ).scalar_one()
        suspects = [dict(r) for r in conn.execute(text(SUSPECTS_SQL), x).mappings()]
        det = dict(conn.execute(text(PATTERN_DETECTION_SQL), x).mappings().one())
        seen = [dict(r) for r in conn.execute(text(TRUE_PATTERN_WAFERS_SQL), x).mappings()]
        start, end = pd.Timestamp(e["started_at"]), pd.Timestamp(e["ended_at"])
        y = pd.read_sql(
            text(YIELD_SQL),
            conn,
            params={
                "tool": tool,
                "chamber": e["chamber_id"],
                "lo": (start - pd.Timedelta(days=args.yield_days)).to_pydatetime(),
                "hi": (end + pd.Timedelta(days=3)).to_pydatetime(),
            },
        )

    cost = [r for r in ranks if r["cost_yield"]]
    out_ranks = {
        "source": "marts.fct_root_cause_eval, exported by tools/export_web_extras.py",
        "cost_yield": len(cost),
        "cost_yield_top1": sum(r["true_rank"] == 1 for r in cost),
        "excursions": [
            {
                "id": int(r["excursion_id"]),
                "type": r["excursion_type"],
                "pattern": r["spatial_pattern"],
                "rank": None if r["true_rank"] is None else int(r["true_rank"]),
                "candidates": None if r["candidates"] is None else int(r["candidates"]),
                "pattern_rank": (
                    None if r["pattern_true_rank"] is None else int(r["pattern_true_rank"])
                ),
                "cost_yield": bool(r["cost_yield"]),
            }
            for r in ranks
        ],
    }
    (args.out / "ranks.json").write_text(json.dumps(out_ranks, separators=(",", ":")))

    out = {
        "source": "WaferLens demo fab (simulated). Exported by tools/export_web_extras.py.",
        "excursion": {
            "id": e["excursion_id"],
            "type": e["excursion_type"],
            "chamber": e["chamber_label"],
            "tool": tool,
            "pattern": e["spatial_pattern"],
            "started_at": iso(start),
            "ended_at": iso(end),
            "duration_hours": round(float(e["duration_hours"])),
            "affected_wafers": int(e["affected_wafers"]),
            "yield_pct": round(float(e["affected_yield_pct"]), 2),
            "control_yield_pct": round(float(e["control_yield_pct"]), 2),
            "dies_lost": int(e["dies_lost"]),
            "true_rank": int(e["true_rank"]),
            "candidates": int(e["candidates"]),
            "pattern_true_rank": int(e["pattern_true_rank"]),
        },
        "pattern": {
            "wafers": int(det["pattern_wafers"]),
            "first_sorted_after_hours": round(float(det["sort_lag_hours"]), 1),
            "alarm_detected": bool(det["detected"]),
            "alarm_after_hours": round(float(det["delay_hours"]), 1) if det["detected"] else None,
            "fabeye_saw": [{"pattern": r["pattern"], "wafers": int(r["wafers"])} for r in seen],
        },
        "suspects": [
            {
                "rank": int(s["suspect_rank"]),
                "suspect": s["suspect"],
                "type": s["factor_type"],
                "lift": round(float(s["lift"]), 2),
                "low_yield": int(s["low_through"]),
                "through": int(s["n_through"]),
                "true_cause": bool(s["is_true_cause"]),
                "spc_alarms": (
                    None if s["alarms_in_window"] is None else int(s["alarms_in_window"])
                ),
            }
            for s in suspects
        ],
        "yield": [
            {
                "day": pd.Timestamp(r.day).strftime("%Y-%m-%d"),
                "on_chamber": bool(r.on_chamber),
                "yield_pct": round(float(r.yield_pct), 2),
                "wafers": int(r.wafers),
            }
            for r in y.itertuples()
        ],
    }
    path = args.out / f"excursion_{args.spatial}.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"ranks: {out_ranks['cost_yield_top1']} of {out_ranks['cost_yield']} top-1; {path.name}")


if __name__ == "__main__":
    main()
