"""Export one excursion as static JSON for the replay page on ansonantony.tech.

Reads the warehouse after `make pipeline` (nothing is written to it) and writes one file:

  series     the excursion chamber's own sensor readings around the excursion, standardised
             against the series' frozen Phase I limits (z = (x - center) / sigma), with the
             Shewhart (WE rule 1), EWMA and CUSUM statistics. The statistics come from
             waferlens.spc.charts run over the whole Phase II series, exactly as the SPC
             engine runs them, then sliced to the window shown.
  alarms     the first alarm of each chart, from marts.fct_excursion_detection. The script
             checks that the recomputed charts first fire on the same reading.
  suspects   the commonality ranking (top 5 and the true cause), from the same query as
             docs/excursion_story.md.
  yield      daily mean yield of wafers that ran on the chamber against the other wafers
             through the same tool, by the day they first ran on it.

    uv run python tools/export_web_replay.py --out /path/to/site/public/projects/waferlens
    uv run python tools/export_web_replay.py 40 --before 120 --after 40 --out ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from waferlens.db.session import get_engine
from waferlens.rootcause.story import EXCURSION_SQL, SUSPECTS_SQL
from waferlens.spc.charts import cusum, ewma, western_electric
from waferlens.spc.engine import SpcConfig

SERIES_SQL = """
    select f.measured_at, f.wafer_id, f.value
    from marts.fct_measurements f
    where f.source = 'sensor' and f.chamber_id = :chamber and f.parameter_id = :param
    order by f.measured_at, f.wafer_id, f.route_step_id, f.pass_no
"""

LIMITS_SQL = """
    select center, sigma, baseline_end, version from spc_control_limits
    where source = 'sensor' and scope = 'chamber' and chamber_id = :chamber
      and parameter_id = :param and not is_multivariate
    order by version desc limit 1
"""

DETECTION_SQL = """
    select chart, detected, first_alarm_at, delay_points, delay_hours, placebo_delay_points
    from marts.fct_excursion_detection
    where excursion_id = :x and scope = 'chamber' and chart in ('we1', 'ewma', 'cusum')
"""

# Yield of every wafer that ran on the excursion chamber's tool, split by whether any of its
# visits used the excursion chamber, by the day of its first visit to that chamber (or, for
# the others, to the tool).
YIELD_SQL = """
    with steps as (
        select s.wafer_id,
               bool_or(s.chamber_id = :chamber) as on_chamber,
               coalesce(min(s.track_in_at) filter (where s.chamber_id = :chamber),
                        min(s.track_in_at)) as track_in_at
        from marts.fct_wafer_steps s
        join marts.dim_chamber c on c.chamber_id = s.chamber_id
        where c.tool_id = :tool and s.track_in_at >= :lo and s.track_in_at < :hi
        group by s.wafer_id
    )
    select date_trunc('day', st.track_in_at) as day,
           st.on_chamber,
           avg(y.yield_pct)::float as yield_pct, count(*) as wafers
    from steps st join marts.fct_wafer_yield y using (wafer_id)
    group by 1, 2 order by 1, 2
"""


def iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("excursion", nargs="?", type=int, default=40)
    ap.add_argument("--before", type=int, default=120, help="readings shown before the start")
    ap.add_argument("--after", type=int, default=40, help="readings shown after the last alarm")
    ap.add_argument("--yield-days", type=int, default=10, help="days of yield before the start")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    engine = get_engine()
    cfg = SpcConfig()
    with engine.connect() as conn:
        e = dict(conn.execute(text(EXCURSION_SQL), {"x": args.excursion}).mappings().one())
        param = (
            conn.execute(
                text(
                    "select parameter_id, unit from marts.dim_parameter where parameter_name = :p"
                ),
                {"p": e["parameter_name"]},
            )
            .mappings()
            .one()
        )
        tool = conn.execute(
            text("select tool_id from marts.dim_chamber where chamber_id = :c"),
            {"c": e["chamber_id"]},
        ).scalar_one()
        lim = dict(
            conn.execute(
                text(LIMITS_SQL), {"chamber": e["chamber_id"], "param": param["parameter_id"]}
            )
            .mappings()
            .one()
        )
        det = {
            r["chart"]: dict(r)
            for r in conn.execute(text(DETECTION_SQL), {"x": args.excursion}).mappings()
        }
        suspects = [
            dict(r) for r in conn.execute(text(SUSPECTS_SQL), {"x": args.excursion}).mappings()
        ]
        df = pd.read_sql(
            text(SERIES_SQL),
            conn,
            params={"chamber": e["chamber_id"], "param": param["parameter_id"]},
        )

    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    live = df[df["measured_at"] > lim["baseline_end"]].reset_index(drop=True)
    z = ((live["value"] - lim["center"]) / lim["sigma"]).to_numpy()
    we1 = western_electric(z)["we1"]
    w, ewma_hit = ewma(z, cfg.ewma_lambda, cfg.ewma_width)
    i = np.arange(1, len(z) + 1)
    ewma_limit = cfg.ewma_width * np.sqrt(
        cfg.ewma_lambda / (2 - cfg.ewma_lambda) * (1 - (1 - cfg.ewma_lambda) ** (2 * i))
    )
    c_up, c_down, up, down = cusum(z, cfg.cusum_k, cfg.cusum_h)
    hits = {"we1": we1, "ewma": ewma_hit, "cusum": up | down}

    start = pd.Timestamp(e["started_at"])
    first_in = int(live["measured_at"].searchsorted(start))
    alarms = {}
    for chart, hit in hits.items():
        d = det[chart]
        idx = np.flatnonzero(hit[first_in:])
        assert d["detected"], f"{chart}: the warehouse has no alarm"
        assert len(idx), f"{chart}: the recomputed chart has no alarm"
        k = first_in + int(idx[0])
        # The warehouse counts affected points up to and including the alarm.
        assert k - first_in + 1 == d["delay_points"], (chart, k - first_in + 1, d["delay_points"])
        assert abs(live["measured_at"][k] - pd.Timestamp(d["first_alarm_at"])) < pd.Timedelta("1s")
        alarms[chart] = {
            "index": k,
            "at": iso(live["measured_at"][k]),
            "points": int(d["delay_points"]),
            "hours": round(float(d["delay_hours"]), 1),
            "placebo_points": int(d["placebo_delay_points"]),
        }

    lo = max(0, first_in - args.before)
    hi = min(len(live), max(a["index"] for a in alarms.values()) + args.after + 1)
    series = [
        {
            "t": iso(live["measured_at"][j]),
            "wafer": int(live["wafer_id"][j]),
            "x": round(float(live["value"][j]), 3),
            "z": round(float(z[j]), 3),
            "ewma": round(float(w[j]), 4),
            "ewma_limit": round(float(ewma_limit[j]), 4),
            "cusum_up": round(float(c_up[j]), 3),
            "cusum_down": round(float(c_down[j]), 3),
        }
        for j in range(lo, hi)
    ]
    for a in alarms.values():
        a["index"] -= lo

    ylo = start - pd.Timedelta(days=args.yield_days)
    with engine.connect() as conn:
        y = pd.read_sql(
            text(YIELD_SQL),
            conn,
            params={
                "tool": tool,
                "chamber": e["chamber_id"],
                "lo": ylo.to_pydatetime(),
                "hi": pd.Timestamp(e["ended_at"]).to_pydatetime() + pd.Timedelta(days=3),
            },
        )
    yield_rows = [
        {
            "day": pd.Timestamp(r.day).strftime("%Y-%m-%d"),
            "on_chamber": bool(r.on_chamber),
            "yield_pct": round(float(r.yield_pct), 2),
            "wafers": int(r.wafers),
        }
        for r in y.itertuples()
    ]

    out = {
        "source": (
            "WaferLens demo fab (simulated). Exported by tools/export_web_replay.py from "
            "the warehouse after make pipeline."
        ),
        "excursion": {
            "id": e["excursion_id"],
            "type": e["excursion_type"],
            "chamber": e["chamber_label"],
            "tool": tool,
            "parameter": e["parameter_name"],
            "unit": param["unit"],
            "magnitude_sigma": round(float(e["magnitude_sigma"]), 2),
            "started_at": iso(start),
            "ended_at": iso(pd.Timestamp(e["ended_at"])),
            "duration_hours": round(float(e["duration_hours"])),
            "first_index": first_in - lo,
            "affected_wafers": int(e["affected_wafers"]),
            "yield_pct": round(float(e["affected_yield_pct"]), 2),
            "control_yield_pct": round(float(e["control_yield_pct"]), 2),
            "dies_lost": int(e["dies_lost"]),
            "true_rank": int(e["true_rank"]),
            "candidates": int(e["candidates"]),
        },
        "limits": {
            "center": round(float(lim["center"]), 3),
            "sigma": round(float(lim["sigma"]), 4),
            "baseline_end": iso(pd.Timestamp(lim["baseline_end"])),
            "ewma_lambda": cfg.ewma_lambda,
            "ewma_width": cfg.ewma_width,
            "cusum_k": cfg.cusum_k,
            "cusum_h": cfg.cusum_h,
        },
        "alarms": alarms,
        "series": series,
        "suspects": [
            {
                "rank": int(s["suspect_rank"]),
                "suspect": s["suspect"],
                "type": s["factor_type"],
                "lift": round(float(s["lift"]), 2),
                "low_yield": int(s["low_through"]),
                "through": int(s["n_through"]),
                "true_cause": bool(s["is_true_cause"]),
                "spc_alarms": None if s["alarms_in_window"] is None else int(s["alarms_in_window"]),
            }
            for s in suspects
        ],
        "yield": yield_rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"excursion_{args.excursion}.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(
        f"{path}: {len(series)} readings, {len(suspects)} suspects, {len(yield_rows)} yield rows, "
        f"{path.stat().st_size / 1024:.0f} kB"
    )


if __name__ == "__main__":
    main()
