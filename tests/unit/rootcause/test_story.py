"""docs/excursion_story.md rendering from warehouse rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from waferlens.rootcause.story import (
    Story,
    detection_table,
    first_chamber_alarm,
    rank_summary,
    render,
    render_story,
)

T0 = datetime(2026, 6, 6, 6, 0, tzinfo=UTC)


def _excursion(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "excursion_id": 40, "excursion_label": "40 · drift", "excursion_type": "drift",
        "chamber_id": 3, "chamber_label": "STRIP-01/A", "recipe_label": None,
        "parameter_name": "plasma_power_w", "spatial_pattern": None, "magnitude_sigma": 2.48,
        "started_at": T0, "ended_at": T0 + timedelta(hours=325), "duration_hours": 325,
        "affected_wafers": 1632, "affected_yield_pct": 87.68, "control_yield_pct": 90.28,
        "yield_delta_pct": -2.6, "dies_lost": 31853, "true_rank": 1, "candidates": 131,
        "pattern_true_rank": None,
    }  # fmt: skip
    row.update(overrides)
    return row


def _chart(chart: str, hours: float | None, points: int, placebo: int | None,
           **overrides: object) -> dict[str, object]:  # fmt: skip
    row: dict[str, object] = {
        "chart": chart, "monitored": True, "started_in_baseline": False,
        "detected": hours is not None,
        "first_alarm_at": T0 + timedelta(hours=hours) if hours is not None else None,
        "delay_hours": hours, "delay_points": points, "placebo_alarm": placebo is not None,
        "placebo_delay_points": placebo or 0, "placebo_window_points": 1876,
    }  # fmt: skip
    row.update(overrides)
    return row


def _suspect(
    rank: int, name: str, true: bool = False, alarms: int | None = 10
) -> dict[str, object]:
    return {"suspect_rank": rank, "suspect": name, "factor_type": "chamber", "lift": 1.37,
            "low_through": 356, "n_through": 1632, "is_true_cause": true,
            "alarms_in_window": alarms}  # fmt: skip


def _drift() -> Story:
    return Story(
        excursion=_excursion(),
        detection=[_chart("cusum", 9.4, 42, 153), _chart("ewma", 11.0, 60, 583),
                   _chart("we3", 5.4, 33, 40), _chart("t2", None, 0, None, monitored=False)],
        suspects=[_suspect(1, "STRIP-01/A", true=True, alarms=5293), _suspect(2, "RTP-01/A")],
        window_wafers=[{"pattern": "none", "wafers": 1626}, {"pattern": "Random", "wafers": 3}],
        exposed=1638, after_alarm=1623,
    )  # fmt: skip


def test_first_alarm_ignores_charts_that_false_alarm_in_the_placebo() -> None:
    # WE3 fires first but also within 40 points of the placebo window: CUSUM leads instead.
    alarm = first_chamber_alarm(_drift().detection)
    assert alarm is not None
    assert alarm["chart"] == "cusum"


def test_drift_story_states_the_alarm_the_wafers_spared_and_the_cost() -> None:
    text = render_story(_drift())
    assert "**CUSUM**, 9.4 h and 42 points in" in text
    assert "**1,623 of them came after that alarm**" in text
    assert "| 1 | **STRIP-01/A** ✓ true cause | chamber | 1.37 | 356 / 1,632 | 5,293 |" in text
    assert "without a spatial signature" in text
    assert "(**-2.60 points**): **31,853 dies lost**" in text


def test_detection_table_marks_uncharted_and_placebo_alarms() -> None:
    table = detection_table(_drift().detection)
    assert "| t2 | – | – | – | not charted |" in table
    assert "| ewma | 2026-06-06 17:00 | 11.0 h | 60 | first alarm after 583 points |" in table


def test_spatial_story_says_spc_cannot_see_it_and_uses_the_wafers() -> None:
    story = Story(
        excursion=_excursion(excursion_type="spatial_pattern", spatial_pattern="Random",
                             parameter_name=None, magnitude_sigma=2.29, pattern_true_rank=1),
        detection=[_chart("ewma", None, 0, None, monitored=False)],
        suspects=[_suspect(1, "STRIP-02/B", true=True, alarms=67)],
        pattern_detection={"pattern": "Random", "pattern_wafers": 196, "sort_lag_hours": 37.7,
                           "detected": True, "delay_hours": 63.4, "placebo_alarm": True,
                           "placebo_delay_hours": 87.1},
        true_pattern_wafers=[{"pattern": "Random", "wafers": 112},
                             {"pattern": "Near-full", "wafers": 84}],
    )  # fmt: skip
    text = render_story(story)
    assert "SPC can't see it" in text
    assert "| Chart |" not in text  # no table of empty charts
    assert "a `Random` defect pattern" in text
    assert "Random 112 (57%), Near-full 84 (43%)" in text
    assert "fired **63 h** after the excursion began (87 h in the placebo window)" in text
    assert "starting from the pattern on the wafers instead, 1st" in text


def test_a_miss_reports_the_true_rank_out_of_all_suspects() -> None:
    assert "**10th of 134**" in rank_summary(_excursion(true_rank=10, candidates=134))
    assert "**1st of 131**" in rank_summary(_excursion())
    assert "no ranking" in rank_summary(_excursion(true_rank=None))


def test_render_joins_stories_under_one_intro() -> None:
    text = render([_drift(), _drift()])
    assert text.startswith("# Excursion stories")
    assert text.count("## Excursion 40 · drift on STRIP-01/A") == 2
