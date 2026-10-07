"""Writes docs/spc_benchmark.md: simulated ARL per chart and detection on the demo fab.

    python -m waferlens.spc.report        (or: make spc-report; needs SPC + dbt run first)

Part 1 is simulation (waferlens.spc.arl), checked against published tables. Part 2 reads
``marts.fct_excursion_detection``: the same charts on the fab's own data, scored against the
simulator's ground truth, with a placebo window as the chance baseline.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import Engine, text

from waferlens.db.session import get_engine
from waferlens.spc.arl import Arl, multivariate_arl, univariate_arl

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "spc_benchmark.md"
PLOT = ROOT / "docs" / "img" / "arl.svg"
SHIFTS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

# Montgomery, Introduction to Statistical Quality Control: Shewhart individuals chart and
# tabular CUSUM (k = 0.5, h = 5), zero-state ARL by shift in sigma.
PUBLISHED = {
    "Shewhart (WE rule 1)": {0.0: 370.4, 0.5: 155.2, 1.0: 43.9, 1.5: 15.0, 2.0: 6.3, 3.0: 2.0},
    "CUSUM (k 0.5, h 5)": {0.0: 465, 0.25: 139, 0.5: 38.0, 0.75: 17.0, 1.0: 10.4, 1.5: 5.75,
                           2.0: 4.01, 3.0: 2.57},
}  # fmt: skip

DETECTION_SQL = """
    select scope, chart, count(*) as excursions,
        percentile_cont(0.5) within group (order by delay_points) as delay_points,
        percentile_cont(0.5) within group (order by delay_hours) as delay_hours,
        percentile_cont(0.5) within group (
            order by case when placebo_alarm then placebo_delay_points
                          else placebo_window_points end
        ) as placebo_points,
        avg((detected and (not placebo_alarm or delay_points < placebo_delay_points))::int)
            as faster_than_chance
    from marts.fct_excursion_detection
    where monitored and not started_in_baseline
    group by scope, chart
"""

COVERAGE_SQL = """
    select excursion_type, count(distinct excursion_id) as excursions,
        count(distinct excursion_id) filter (where monitored) as monitored,
        count(distinct excursion_id) filter (where started_in_baseline) as in_baseline
    from marts.fct_excursion_detection
    group by excursion_type
    order by excursion_type
"""


def arl_table(rows: list[Arl]) -> str:
    by_chart: dict[str, dict[float, Arl]] = defaultdict(dict)
    for r in rows:
        by_chart[r.chart][r.shift] = r
    shifts = sorted({r.shift for r in rows})
    head = "| Chart | " + " | ".join(f"{s:g}σ" for s in shifts) + " |"
    lines = [head, "|---|" + "---|" * len(shifts)]
    for chart, cells in by_chart.items():
        values = [f"{cells[s].arl:,.1f}" if s in cells else "" for s in shifts]
        lines.append(f"| {chart} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def published_check(rows: list[Arl]) -> str:
    measured = {(r.chart, r.shift): r.arl for r in rows}
    lines = ["| Chart | Shift | Simulated | Published | Difference |", "|---|---|---|---|---|"]
    for chart, table in PUBLISHED.items():
        for shift, value in table.items():
            sim = measured.get((chart, shift))
            if sim is not None:
                lines.append(f"| {chart} | {shift:g}σ | {sim:,.1f} | {value:,.1f} | "
                             f"{100 * (sim / value - 1):+.1f}% |")  # fmt: skip
    return "\n".join(lines)


def plot(rows: list[Arl], path: Path = PLOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    style = {
        "Shewhart (WE rule 1)": ("#8a8a8a", "-"),
        "Western Electric 1-4": ("#8a8a8a", "--"),
        "EWMA (λ 0.2, L 3)": ("#1f6fd1", "-"),
        "CUSUM (k 0.5, h 5)": ("#1f6fd1", "--"),
    }
    for chart, (colour, line) in style.items():
        pts = sorted((r.shift, r.arl) for r in rows if r.chart == chart and r.shift > 0)
        arl0 = next((r.arl for r in rows if r.chart == chart and r.shift == 0), None)
        # The false-alarm cost belongs next to the speed: WE 1-4 looks fastest only because
        # it also alarms ~4x more often when nothing is wrong.
        label = f"{chart}  ·  false alarm every ~{arl0:,.0f} pts" if arl0 else chart
        ax.plot([p[0] for p in pts], [p[1] for p in pts], line, color=colour, marker="o",
                markersize=4, label=label)  # fmt: skip
    ax.set_yscale("log")
    ax.set_xlabel("Mean shift (sigma)")
    ax.set_ylabel("Points to first alarm (ARL, log scale)")
    ax.set_title("EWMA and CUSUM catch small shifts ~4x sooner than a Shewhart chart",
                 fontsize=10.5, loc="left")  # fmt: skip
    ax.grid(True, which="both", color="#e6e6e6", linewidth=0.6)
    ax.legend(frameon=False, fontsize=8.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, format="svg", metadata={"Date": None})
    plt.close(fig)


def detection_tables(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    with engine.connect() as conn:
        detection = pd.DataFrame(conn.execute(text(DETECTION_SQL)).mappings().all())
        coverage = pd.DataFrame(conn.execute(text(COVERAGE_SQL)).mappings().all())
    return detection, coverage


def detection_markdown(detection: pd.DataFrame, coverage: pd.DataFrame) -> str:
    order = ["we1", "we2", "we3", "we4", "ewma", "cusum", "t2"]
    d = detection.assign(rank=detection["chart"].map(order.index)).sort_values(["scope", "rank"])
    rows = ["| Scope | Chart | Excursions | Median delay (points) | Median delay (h) | "
            "Chance baseline (points) | Faster than chance |",
            "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in d.to_dict("records"):
        rows.append(
            f"| {r['scope']} | `{r['chart']}` | {r['excursions']} | {float(r['delay_points']):g} | "
            f"{float(r['delay_hours']):.1f} | {float(r['placebo_points']):g} | "
            f"{100 * float(r['faster_than_chance']):.0f}% |"
        )
    cov = ["| Excursion type | Injected | Watched by a chart | Started inside baseline |",
           "|---|---|---|---|"]  # fmt: skip
    for r in coverage.to_dict("records"):
        cov.append(
            f"| {r['excursion_type']} | {r['excursions']} | {r['monitored']} | {r['in_baseline']} |"
        )
    return "\n".join(rows) + "\n\n" + "\n".join(cov)


def render(arl_rows: list[Arl], detection: str) -> str:
    uni = [r for r in arl_rows if "T²" not in r.chart and "each parameter" not in r.chart]
    multi = [r for r in arl_rows if r not in uni]
    return f"""# SPC benchmark

Generated by `make spc-report`; don't edit by hand. Methods: `docs/spc.md`. Decision: ADR-006.

## 1. Average run length (simulation)

Zero-state ARL: the mean shifts by the given number of sigma from the first point, and each
cell is the mean number of points until the chart signals (2,000 runs each). The 0σ column is
ARL₀, the mean number of points between false alarms; every other column is a detection delay.

![ARL by shift](img/arl.svg)

{arl_table(uni)}

Two correlated parameters (ρ = 0.6), one of them shifting; T² against a 3σ chart on each
parameter separately:

{arl_table(multi)}

**Reading it:** at 0.5σ a Shewhart chart needs ~156 points, EWMA ~42 and CUSUM ~38, while both
false-alarm *less* often (ARL₀ ~540 and ~475 vs ~370). Western Electric rules 1-4 together are
faster still, but at an ARL₀ of ~90: a false alarm every 90 points. For large shifts (3σ) every
chart signals within 2-3 points, so Shewhart's one-point rule stays useful as a backstop.

### Check against published values

{published_check(arl_rows)}

## 2. Detection on the demo fab (ground truth)

`marts.fct_excursion_detection` scores every chart against every injected excursion
(chamber and tool scope), using only alarms on affected points. Excursion windows run for
days, so *some* false alarm inside one is likely; the chance baseline is the median number of
affected points until the first alarm in an equal-length window right before the excursion,
where there is nothing to detect. Excursions that started inside the 30-day baseline are left
out (their limits may have learned the shift).

{detection}

**Reading it:** at chamber scope EWMA and CUSUM raise their first alarm after a median of
8-9 affected points, Shewhart after ~33, against a chance baseline of 140-200 points. Pooling a
tool's chambers (tool scope) slows EWMA and CUSUM and nearly disables WE rule 4, whose
"8 in a row on one side" fires on the chambers' static offsets. Spatial-pattern excursions
are watched by no chart at all: they change no sensor or metrology value, only the wafer map
(phase 5, FabEye). T² saw too few recipe-change cases on demo to conclude anything.
"""


def main() -> None:
    rows = univariate_arl(SHIFTS) + multivariate_arl([0.0, 0.5, 1.0, 2.0, 3.0])
    plot(rows)
    detection, coverage = detection_tables(get_engine())
    OUTPUT.write_text(render(rows, detection_markdown(detection, coverage)))
    print(f"wrote {OUTPUT.relative_to(ROOT)} and {PLOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
