"""Writes docs/root_cause.md: commonality accuracy against ground truth, impact, and how
SPC and commonality cover each other.

    python -m waferlens.rootcause.report     (or: make rootcause-report; after SPC, root cause
                                              and dbt have run)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from waferlens.db.session import get_engine
from waferlens.rootcause.patterns import compare

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "root_cause.md"

EVAL_SQL = "select * from marts.fct_root_cause_eval order by excursion_id"

# SPC "caught it" = chamber-scope EWMA alarmed inside the window, sooner than in the placebo
# window before it, for an excursion that started after the baseline (fct_excursion_detection).
SPC_SQL = """
    select excursion_id,
        bool_or(detected and not started_in_baseline
                and (not placebo_alarm or delay_points < placebo_delay_points)) as spc_caught
    from marts.fct_excursion_detection
    where chart = 'ewma' and scope = 'chamber'
    group by excursion_id
"""


def load_frames(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        evaluation = pd.DataFrame(conn.execute(text(EVAL_SQL)).mappings().all())
        spc = pd.DataFrame(conn.execute(text(SPC_SQL)).mappings().all())
    return evaluation.merge(spc, on="excursion_id", how="left").assign(
        spc_caught=lambda d: d["spc_caught"].fillna(False).astype(bool)
    )


def _pct(series: pd.Series) -> str:
    return f"{100 * series.mean():.0f}%" if len(series) else "–"


def accuracy_table(df: pd.DataFrame) -> str:
    candidates = df["candidates"].mean()
    rows = ["| Excursions | n | Top-1 | Top-3 |", "|---|---|---|---|"]
    for label, part in (
        ("All injected", df),
        ("Measurably cost yield (≥ 1 point vs controls)", df[df["cost_yield"]]),
        ("No measurable yield cost", df[~df["cost_yield"]]),
    ):
        rows.append(f"| {label} | {len(part)} | {int(part['top1'].sum())} ({_pct(part['top1'])})"
                    f" | {int(part['top3'].sum())} ({_pct(part['top3'])}) |")  # fmt: skip
    rows.append(f"| *Random ranking* | | *{100 / candidates:.1f}%* | *{300 / candidates:.1f}%* |")
    return "\n".join(rows)


def by_type_table(df: pd.DataFrame) -> str:
    rows = ["| Excursion type | n | Cost yield | Top-1 | Top-3 | Dies lost |",
            "|---|---|---|---|---|---|"]  # fmt: skip
    for kind, part in df.groupby("excursion_type"):
        rows.append(f"| {kind} | {len(part)} | {int(part['cost_yield'].sum())} | "
                    f"{int(part['top1'].sum())} | {int(part['top3'].sum())} | "
                    f"{int(part['dies_lost'].fillna(0).sum()):,} |")  # fmt: skip
    return "\n".join(rows)


def coverage_table(df: pd.DataFrame) -> str:
    found = df["top3"]
    caught = df["spc_caught"]
    cells = {
        "SPC and commonality": int((found & caught).sum()),
        "SPC only": int((caught & ~found).sum()),
        "Commonality only (top-3)": int((found & ~caught).sum()),
        "Neither": int((~found & ~caught).sum()),
    }
    rows = ["| Found by | Excursions | Of which spatial patterns |", "|---|---|---|"]
    spatial = df["excursion_type"] == "spatial_pattern"
    masks = {
        "SPC and commonality": found & caught,
        "SPC only": caught & ~found,
        "Commonality only (top-3)": found & ~caught,
        "Neither": ~found & ~caught,
    }
    for label, n in cells.items():
        rows.append(f"| {label} | {n} | {int((masks[label] & spatial).sum())} |")
    return "\n".join(rows)


def detail_table(df: pd.DataFrame) -> str:
    rows = ["| Id | Type | Magnitude (σ) | Pattern | True cause rank | Yield Δ vs controls | "
            "Dies lost | SPC caught |", "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in df.to_dict("records"):
        rank = "–" if pd.isna(r["true_rank"]) else f"{int(r['true_rank'])} / {r['candidates']}"
        delta = "–" if pd.isna(r["yield_delta_pct"]) else f"{float(r['yield_delta_pct']):+.1f}"
        # NaN is truthy, so `value or default` would keep it: check for missing explicitly.
        pattern = "" if pd.isna(r["spatial_pattern"]) else r["spatial_pattern"]
        dies = 0 if pd.isna(r["dies_lost"]) else int(r["dies_lost"])
        rows.append(
            f"| {r['excursion_id']} | {r['excursion_type']} | {float(r['abs_magnitude_sigma']):.1f}"
            f" | {pattern} | {rank} | {delta} | {dies:,} | {'yes' if r['spc_caught'] else ''} |"
        )
    return "\n".join(rows)


DETECTION_SQL = "select * from marts.fct_pattern_detection order by excursion_id"
# The pattern section needs FabEye scores and the pattern marts (phase 5a).
SCORED_SQL = """
    select to_regclass('marts.fct_pattern_detection') is not null
       and exists (select 1 from wafer_patterns)
"""


def _top(ranks: pd.Series, k: int = 1) -> str:
    hits = int((ranks.fillna(10**6) <= k).sum())
    return f"{hits} ({_pct(ranks.fillna(10**6) <= k)})"


def pattern_rootcause_table(cmp: pd.DataFrame) -> str:
    spatial = cmp[cmp["excursion_type"] == "spatial_pattern"]
    cost = cmp[cmp["cost_yield"]]
    rankings = [
        ("Low yield (phase 3)", "true_rank", True),
        ("Window rule: the window's dominant pattern", "rule_rank", True),
        ("Pattern-led: the excursion's own pattern", "pattern_true_rank", False),
    ]
    rows = ["| Ranking | Spatial excursions: top-1 | top-3 | Excursions that cost yield: top-1 |",
            "|---|---|---|---|"]  # fmt: skip
    for label, col, all_excursions in rankings:
        on_cost = _top(cost[col]) if all_excursions else "–"
        rows.append(f"| {label} | {_top(spatial[col])} | {_top(spatial[col], 3)} | {on_cost} |")
    return "\n".join(rows)


def pattern_detection_table(det: pd.DataFrame) -> str:
    rows = [
        "| Id | Pattern | Magnitude (σ) | Pattern wafers | First sorted after (h) | "
        "Alarm after (h) | Placebo alarm | SPC caught |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in det.to_dict("records"):
        delay = "–" if pd.isna(r["delay_hours"]) else f"{float(r['delay_hours']):.0f}"
        cells = [
            str(r["excursion_id"]),
            str(r["pattern"]),
            f"{float(r['abs_magnitude_sigma']):.1f}",
            str(int(r["pattern_wafers"])),
            f"{float(r['sort_lag_hours']):.0f}",
            delay,
            "yes" if r["placebo_alarm"] else "",
            "yes" if r["spc_detected"] else "",
        ]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def patterns_section(cmp: pd.DataFrame, det: pd.DataFrame) -> str:
    caught = det[det["detected"]]
    after_sort = (caught["delay_hours"] - caught["sort_lag_hours"]).median()
    rule_fired = int(cmp["rule_pattern"].notna().sum())
    delay = caught["delay_hours"].median()
    lag = det["sort_lag_hours"].median()
    early = int((caught["delay_hours"] < caught["sort_lag_hours"]).sum())
    return f"""
## Wafer-map patterns (phase 5a)

FabEye classifies every sorted wafer map ([docs/fabeye_eval.md](fabeye_eval.md)). Two
questions: does the pattern help find the cause, and does it raise the alarm SPC can't?

### Root cause

{pattern_rootcause_table(cmp)}

- **Pattern-led commonality finds every spatial cause first**: given the pattern on the
  wafers, the wafers showing it share one chamber, even where low yield points elsewhere.
- **Picking the pattern from the time window fails.** The rule (fixed before evaluation:
  the window's most over-represented pattern, if >= 10 wafers at >= 3x background) fired
  for {rule_fired} of {len(cmp)} windows, because excursions overlap and almost every window
  holds *some* other excursion's pattern; it then blamed that excursion's chamber. It is
  reported, not tuned: the lesson is to start from the pattern, as an alarm on it does.

### Detection: the pattern alarm vs SPC

Alarm rule (`fct_pattern_alarms`, fixed before evaluation): at least max(3, 3x background
per day) wafers auto-accepted with the same pattern sorted within 24 hours; background from
the first 30 days, like SPC's Phase I.

{pattern_detection_table(det)}

- **The pattern alarm caught {len(caught)} of {len(det)} spatial excursions; SPC caught
  {int(det["spc_detected"].sum())}**: no sensor or metrology value moves, by design.
- **It is slow, and the floor is the fab, not the model:** median {delay:.0f} h after the
  excursion started, but the first patterned wafer only reached sort after a median
  {lag:.0f} h, and the alarm followed it by a median {after_sort:.0f} h.
  Wafer sort comes after the whole route; SPC sees a tool within minutes.
- **The chance baseline is not clean:** {int(det["placebo_alarm"].sum())} of {len(det)} placebo
  windows also alarmed, because another excursion with the same pattern was running.
  Overlap also credits alarms early: {early} fired before the excursion's own first
  patterned wafer was sorted, so another excursion raised them.
- So the two monitors cover each other: SPC for sensor shifts within minutes, the pattern
  alarm for spatial defects within about two days, and pattern-led commonality to name the
  chamber.
"""


def render(df: pd.DataFrame, patterns: str = "") -> str:
    cost = df[df["cost_yield"]]
    return f"""# Root cause: commonality analysis vs ground truth

Generated by `make rootcause-report`; don't edit by hand. Code: `src/waferlens/rootcause/`;
marts: `fct_root_cause_candidates`, `fct_excursion_impact`, `fct_root_cause_eval`.

**Commonality ranked the true chamber or recipe first for {int(cost["top1"].sum())} of
{len(cost)} injected excursions that measurably cost yield ({_pct(cost["top1"])}), against
{100 / df["candidates"].mean():.1f}% for a random pick among ~{df["candidates"].mean():.0f}
suspects.** The analysis sees only the time window, never the chamber.

## Method

For a time window (here: each excursion's start to end):

1. Population: every sorted wafer processed at any step inside the window.
2. Low yield: below the 20th percentile of the wafer's *own product*, over the product's
   whole history. Per product, so a lower-yielding product can't frame its chambers; over
   history rather than the window, so a cause that hits every wafer of one product (a bad
   recipe) still shows.
3. Candidates: every chamber and recipe version a wafer met *inside the window*.
4. Score: lift (low-yield rate through the candidate / overall) and the 2×2 chi-square;
   over-represented candidates (lift > 1) ranked by chi-square, then lift; at least 5 wafers.

Impact compares the excursion's affected wafers with same-product wafers processed in the same
window that escaped it, so overlapping excursions don't inflate each other's cost.

## Accuracy

{accuracy_table(df)}

{by_type_table(df)}

## SPC and commonality cover each other

SPC "caught" = chamber-scope EWMA alarmed inside the window sooner than in the placebo
window before it (docs/spc_benchmark.md). Commonality "found" = true cause in the top 3.

{coverage_table(df)}

Spatial patterns change no sensor or metrology value, so SPC never sees them; they cost the
most yield, so commonality finds most of them. Small chamber offsets are the reverse: SPC sees
the sensor move, but they cost little yield, so there is little for commonality to find.

## Limitations

- **Confounding:** chambers that always process the same wafers cannot be told apart. The
  planted-data test hit exactly this until the scenario was fixed; real dispatch rules can
  create it too.
- **Overlap:** another excursion in the same window can outrank the true cause; it counts as a
  miss here although it is a real problem too.
- **Yield-only signal:** excursions that cost no yield are SPC's job, not this method's.

## Every excursion

{detail_table(df)}
{patterns}"""


def main() -> None:
    engine = get_engine()
    det = None
    with engine.connect() as conn:
        if conn.execute(text(SCORED_SQL)).scalar_one():
            det = pd.DataFrame(conn.execute(text(DETECTION_SQL)).mappings().all())
    patterns = "" if det is None else patterns_section(compare(engine), det)
    OUTPUT.write_text(render(load_frames(engine), patterns))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
