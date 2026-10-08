"""Writes docs/excursion_story.md: injected excursions told end to end from the warehouse.

For each excursion: what the simulator injected (ground truth), how early each chamber chart
alarmed against a placebo window, which chamber commonality ranked first and the SPC alarms on
each suspect, what FabEye saw on the wafers, and what it cost.

    python -m waferlens.rootcause.story            (or: make story; after make pipeline and
    python -m waferlens.rootcause.story 7 33        make fabeye-report)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from waferlens.db.session import get_engine

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "excursion_story.md"
DEFAULT = (40, 12, 10)  # a sensor drift, a spatial pattern SPC can't see, commonality's miss

Row = dict[str, Any]

EXCURSION_SQL = """
    select e.excursion_id, e.excursion_label, e.excursion_type, e.chamber_id, e.chamber_label,
           e.recipe_label, e.parameter_name, e.spatial_pattern, e.magnitude_sigma,
           e.started_at, e.ended_at, e.duration_hours,
           i.affected_wafers, i.affected_yield_pct, i.control_yield_pct, i.yield_delta_pct,
           i.dies_lost, ev.true_rank, ev.candidates, ev.pattern_true_rank
    from marts.dim_excursion e
    left join marts.fct_excursion_impact i using (excursion_id)
    left join marts.fct_root_cause_eval ev using (excursion_id)
    where e.excursion_id = :x
"""

# Chamber-scope charts only: the injected chamber is the one whose charts should move.
DETECTION_SQL = """
    select chart, monitored, started_in_baseline, detected, first_alarm_at, delay_hours,
           delay_points, placebo_alarm, placebo_delay_points, placebo_window_points
    from marts.fct_excursion_detection
    where excursion_id = :x and scope = 'chamber'
    order by chart
"""

# Top suspects for the yield signal, plus the true cause wherever it ranked, each with the
# chamber-scope SPC alarms raised on it inside the excursion window (recipes have no chamber).
SUSPECTS_SQL = """
    select c.suspect_rank, c.suspect, c.factor_type, c.lift, c.low_through, c.n_through,
           c.is_true_cause,
           case when c.chamber_id is null then null else (
               select count(*) from marts.fct_spc_alarms a
               where a.scope = 'chamber' and a.chamber_id = c.chamber_id
                 and a.measured_at >= e.started_at and a.measured_at < e.ended_at
           ) end as alarms_in_window
    from marts.fct_root_cause_candidates c
    join marts.dim_excursion e using (excursion_id)
    where c.excursion_id = :x and c.signal = 'yield'
      and (c.suspect_rank <= 5 or c.is_true_cause)
    order by c.suspect_rank, c.suspect
"""

PATTERN_DETECTION_SQL = """
    select pattern, pattern_wafers, sort_lag_hours, detected, delay_hours, placebo_alarm,
           placebo_delay_hours
    from marts.fct_pattern_detection
    where excursion_id = :x
"""

# FabEye's answer for the wafers the simulator says carry this excursion's pattern.
TRUE_PATTERN_WAFERS_SQL = """
    select predicted_pattern as pattern, count(*) as wafers
    from marts.fct_wafer_pattern
    where excursion_id = :x
    group by 1 order by 2 desc, 1
"""

# FabEye's answer for every wafer that ran on the excursion's chamber inside its window.
WINDOW_WAFERS_SQL = """
    with exposed as (
        select distinct s.wafer_id
        from marts.fct_wafer_steps s
        join marts.dim_excursion e
          on s.chamber_id = e.chamber_id
         and s.track_in_at >= e.started_at and s.track_in_at < e.ended_at
        where e.excursion_id = :x
    )
    select p.predicted_pattern as pattern, count(*) as wafers
    from marts.fct_wafer_pattern p join exposed using (wafer_id)
    group by 1 order by 2 desc, 1
"""

# Wafers the chamber processed inside the window, and how many came after a given alarm:
# the wafers a stop at that alarm would have spared.
EXPOSED_SQL = """
    select count(distinct s.wafer_id) as exposed,
           count(distinct s.wafer_id)
               filter (where s.track_in_at >= cast(:alarm as timestamptz)) as after_alarm
    from marts.fct_wafer_steps s
    join marts.dim_excursion e
      on s.chamber_id = e.chamber_id
     and s.track_in_at >= e.started_at and s.track_in_at < e.ended_at
    where e.excursion_id = :x
"""


@dataclass
class Story:
    excursion: Row
    detection: list[Row] = field(default_factory=list)
    suspects: list[Row] = field(default_factory=list)
    pattern_detection: Row | None = None
    true_pattern_wafers: list[Row] = field(default_factory=list)
    window_wafers: list[Row] = field(default_factory=list)
    exposed: int | None = None
    after_alarm: int | None = None


def _rows(engine: Engine, sql: str, **params: Any) -> list[Row]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


LEAD_CHARTS = ("ewma", "cusum")  # the charts ADR-006 recommends for chamber drift and shifts


def first_chamber_alarm(detection: list[Row]) -> Row | None:
    """The earliest EWMA or CUSUM alarm on the chamber (monitored, past the baseline).

    Western Electric rules can fire sooner but also fire in the placebo window within a few
    dozen points, so a stop on them would mostly be a stop on noise."""
    caught = [d for d in detection if d["chart"] in LEAD_CHARTS
              and d["detected"] and d["monitored"] and not d["started_in_baseline"]]  # fmt: skip
    return min(caught, key=lambda d: d["first_alarm_at"]) if caught else None


def load_story(engine: Engine, excursion_id: int) -> Story:
    found = _rows(engine, EXCURSION_SQL, x=excursion_id)
    if not found:
        raise ValueError(f"no excursion {excursion_id} in marts.dim_excursion")
    story = Story(
        excursion=found[0],
        detection=_rows(engine, DETECTION_SQL, x=excursion_id),
        suspects=_rows(engine, SUSPECTS_SQL, x=excursion_id),
        true_pattern_wafers=_rows(engine, TRUE_PATTERN_WAFERS_SQL, x=excursion_id),
        window_wafers=_rows(engine, WINDOW_WAFERS_SQL, x=excursion_id),
    )
    pattern = _rows(engine, PATTERN_DETECTION_SQL, x=excursion_id)
    story.pattern_detection = pattern[0] if pattern else None
    alarm = first_chamber_alarm(story.detection)
    if story.excursion["chamber_id"] is not None:
        counts = _rows(engine, EXPOSED_SQL, x=excursion_id,
                       alarm=alarm["first_alarm_at"] if alarm else None)  # fmt: skip
        story.exposed, story.after_alarm = counts[0]["exposed"], counts[0]["after_alarm"]
    return story


# ---- rendering (pure, unit-tested) -------------------------------------------------------


def _n(value: Any, digits: int = 0) -> str:
    if value is None:
        return "–"
    return f"{float(value):,.{digits}f}"


def _when(ts: datetime | None) -> str:
    return ts.strftime("%Y-%m-%d %H:%M") if ts else "–"


def heading(e: Row) -> str:
    where = e["chamber_label"] or e["recipe_label"] or "the fab"
    kind = e["excursion_type"].replace("_", " ")
    return f"## Excursion {e['excursion_id']} · {kind} on {where}"


def injected(e: Row) -> str:
    what = (f"a `{e['spatial_pattern']}` defect pattern" if e["spatial_pattern"]
            else f"{float(e['magnitude_sigma']):+.2f}σ on `{e['parameter_name']}`")  # fmt: skip
    where = e["chamber_label"] or e["recipe_label"]
    return (f"**Injected (ground truth):** {what}, {e['excursion_type'].replace('_', ' ')} on "
            f"{where}, {_when(e['started_at'])} → {_when(e['ended_at'])} "
            f"({_n(e['duration_hours'])} h).")  # fmt: skip


def detection_table(detection: list[Row]) -> str:
    rows = ["| Chart | First alarm | After | Points | Placebo window (same length, before) |",
            "|---|---|---|---|---|"]  # fmt: skip
    for d in detection:
        if not d["monitored"] or d["started_in_baseline"]:
            reason = "not charted" if not d["monitored"] else "started in the baseline"
            rows.append(f"| {d['chart']} | – | – | – | {reason} |")
            continue
        placebo = (f"first alarm after {_n(d['placebo_delay_points'])} points"
                   if d["placebo_alarm"]
                   else f"no alarm in {_n(d['placebo_window_points'])} points")  # fmt: skip
        if d["detected"]:
            after = f"{_n(d['delay_hours'], 1)} h | {_n(d['delay_points'])}"
            rows.append(f"| {d['chart']} | {_when(d['first_alarm_at'])} | {after} | {placebo} |")
        else:
            rows.append(f"| {d['chart']} | not caught | – | – | {placebo} |")
    return "\n".join(rows)


def charted(detection: list[Row]) -> bool:
    return any(d["monitored"] and not d["started_in_baseline"] for d in detection)


def early_summary(story: Story) -> str:
    if not charted(story.detection):
        if story.excursion["spatial_pattern"]:
            return ("No chamber chart watches this one: a spatial defect pattern moves no "
                    "sensor, so SPC can't see it. The wafers can (below).")  # fmt: skip
        return "No chamber chart covered this excursion's window."
    alarm = first_chamber_alarm(story.detection)
    if alarm is None:
        return "Neither EWMA nor CUSUM alarmed on the chamber inside the window."
    text_ = (
        f"The first EWMA/CUSUM alarm on the chamber was **{alarm['chart'].upper()}**, "
        f"{_n(alarm['delay_hours'], 1)} h and {_n(alarm['delay_points'])} points in."
    )
    if story.exposed:
        text_ += (f" The chamber processed {_n(story.exposed)} wafers inside the window; "
                  f"**{_n(story.after_alarm)} of them came after that alarm**, the wafers a "
                  f"stop at the first alarm would have spared.")  # fmt: skip
    return text_


def suspects_table(suspects: list[Row]) -> str:
    rows = ["| Rank | Suspect | Type | Lift | Low-yield wafers / wafers through | "
            "SPC alarms in window |", "|---|---|---|---|---|---|"]  # fmt: skip
    for s in suspects:
        name = f"**{s['suspect']}** ✓ true cause" if s["is_true_cause"] else s["suspect"]
        rows.append(f"| {s['suspect_rank']} | {name} | {s['factor_type']} | {_n(s['lift'], 2)} | "
                    f"{_n(s['low_through'])} / {_n(s['n_through'])} | "
                    f"{_n(s['alarms_in_window'])} |")  # fmt: skip
    return "\n".join(rows)


def rank_summary(e: Row) -> str:
    if e["true_rank"] is None:
        return "Commonality produced no ranking for this window."
    line = (
        f"Commonality ranked the true cause **{_ordinal(e['true_rank'])} of "
        f"{e['candidates']}** suspects from the time window alone"
    )
    if e["pattern_true_rank"] is not None:
        line += (
            f"; starting from the pattern on the wafers instead, {_ordinal(e['pattern_true_rank'])}"
        )
    return line + "."


def _ordinal(n: int) -> str:
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _mix(rows: list[Row], top: int = 3) -> str:
    total = sum(r["wafers"] for r in rows)
    parts = [f"{r['pattern']} {_n(r['wafers'])} ({100 * r['wafers'] / total:.0f}%)"
             for r in rows[:top]]  # fmt: skip
    return ", ".join(parts)


def wafer_summary(story: Story) -> str:
    lines = []
    if story.true_pattern_wafers:
        total = sum(r["wafers"] for r in story.true_pattern_wafers)
        lines.append(f"FabEye on the {_n(total)} wafers that carry the injected pattern: "
                     f"{_mix(story.true_pattern_wafers)}.")  # fmt: skip
    p = story.pattern_detection
    if p is not None:
        if p["detected"]:
            placebo = (f"{_n(p['placebo_delay_hours'], 0)} h in the placebo window"
                       if p["placebo_alarm"] else "no alarm in the placebo window")  # fmt: skip
            lines.append(f"A pattern alarm on sorted wafers fired **{_n(p['delay_hours'], 0)} h** "
                         f"after the excursion began ({placebo}); the first affected wafer "
                         f"reached sort after {_n(p['sort_lag_hours'], 0)} h.")  # fmt: skip
        else:
            lines.append("The pattern alarm did not fire.")
    if story.window_wafers:
        total = sum(r["wafers"] for r in story.window_wafers)
        lines.append(f"Wafers that ran on the chamber inside the window ({_n(total)} sorted): "
                     f"{_mix(story.window_wafers)}.")  # fmt: skip
        clean = sum(r["wafers"] for r in story.window_wafers if r["pattern"] == "none")
        if not story.true_pattern_wafers and clean >= 0.8 * total:
            lines.append(
                "Most of them look normal to FabEye: this excursion cost yield "
                "without a spatial signature, so the sensors had to catch it."
            )
    if not lines:
        return "No FabEye results for these wafers (run `make fabeye-report`)."
    return "\n\n".join(lines)


def cost_summary(e: Row) -> str:
    if e["affected_wafers"] is None:
        return "No sorted wafers inside the window, so no measured impact."
    return (f"{_n(e['affected_wafers'])} affected wafers yielded {_n(e['affected_yield_pct'], 2)}% "
            f"against {_n(e['control_yield_pct'], 2)}% for same-window control wafers "
            f"(**{float(e['yield_delta_pct']):+.2f} points**): **{_n(e['dies_lost'])} dies "
            f"lost**.")  # fmt: skip


def render_story(story: Story) -> str:
    e = story.excursion
    parts = [
        heading(e), injected(e),
        "### How early could we have known?", early_summary(story),
        *([detection_table(story.detection)] if charted(story.detection) else []),
        "### Which chamber caused it?", rank_summary(e), suspects_table(story.suspects),
        "### What does it look like on the wafer?", wafer_summary(story),
        "### What did it cost?", cost_summary(e),
    ]  # fmt: skip
    return "\n\n".join(parts)


def render(stories: list[Story]) -> str:
    intro = (
        "# Excursion stories\n\n"
        "Injected excursions told end to end from the warehouse: what the simulator injected "
        "(the ground truth), how early each chamber chart could have known compared with a "
        "placebo window, which chamber commonality pointed at, what FabEye saw on the wafers, "
        'and what it cost. Generated by `make story` (`make story EXC="7 33"` for others) '
        "after `make pipeline` and `make fabeye-report`.\n\n"
        "Points are readings on the chamber's chart; the placebo window is the same number "
        "of points just before the excursion, so an alarm there is a false alarm."
    )
    return intro + "\n\n" + "\n\n".join(render_story(s) for s in stories) + "\n"


def main(argv: list[str] | None = None) -> None:
    ids = [int(a) for a in (argv if argv is not None else sys.argv[1:])] or list(DEFAULT)
    engine = get_engine()
    stories = [load_story(engine, i) for i in ids]
    OUTPUT.write_text(render(stories))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({', '.join(map(str, ids))})")


if __name__ == "__main__":
    main()
