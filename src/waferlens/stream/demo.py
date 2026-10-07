"""Real-time SPC demo: replay a day of the fab as events, inject a drift, watch it caught.

    make stream-demo     (needs make pipeline: the frozen SPC limits come from the batch run)

Picks a 24-hour window after the SPC baselines with no injected excursion in it, adds a
+2 sigma step to one chamber's sensor halfway through, resets the streaming state and topic,
runs the consumer in a background thread while the tool agents publish, and reports how
quickly the drift was caught: in points, in fab time, and in wall-clock latency.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from waferlens.config import get_settings
from waferlens.db.session import get_engine
from waferlens.stream import consumer, producer
from waferlens.stream.consumer import BatchReport

ROOT = Path(__file__).resolve().parents[3]
WINDOW_HOURS = 24
SHIFT_SIGMA = 2.0
RATE = float(os.environ.get("STREAM_RATE", "800"))  # events per second

WINDOW_SQL = """
    -- The first day after every chamber sensor baseline ends with no injected excursion.
    with lim as (
        select max(baseline_end) as live_from
        from spc_control_limits where source = 'sensor' and scope = 'chamber'
    ), days as (
        select generate_series(date_trunc('day', live_from) + interval '1 day',
                               date_trunc('day', live_from) + interval '120 days',
                               interval '1 day') as day
        from lim
    )
    select d.day
    from days as d
    where not exists (
        select 1 from excursions_ground_truth as e
        where e.start_time < d.day + interval '24 hours'
          and coalesce(e.end_time, e.start_time) > d.day
    )
    order by d.day
    limit 1
"""

RESULT_SQL = """
    select a.event_id, a.measured_at, a.chart, a.statistic,
           extract(epoch from a.detected_at - a.produced_at) * 1000 as latency_ms
    from stream_alarms as a
    where a.chamber_id = :c and a.parameter_id = :p and a.measured_at >= :start
    order by a.measured_at, a.chart
    limit 1
"""

# Alarms outside the drifted series: the in-control false-alarm rate on the fab's own data.
BACKGROUND_SQL = """
    select count(*) from stream_alarms where not (chamber_id = :c and parameter_id = :p)
"""

# Wall-clock latency below zero: the clock stepped back between publish and alarm.
WALL_NEGATIVE_SQL = "select count(*) from stream_alarms where detected_at < produced_at"


def pick_series(df: pd.DataFrame, engine: Engine) -> tuple[int, int]:
    """The busiest chamber x sensor in the window that has frozen limits."""
    with engine.connect() as conn:
        monitored = set(conn.execute(text(
            "select chamber_id, parameter_id from spc_control_limits "
            "where source = 'sensor' and scope = 'chamber'")).all())  # fmt: skip
    counts = df.groupby(["chamber_id", "parameter_id"]).size().sort_values(ascending=False)
    for chamber_id, parameter_id in counts.index:
        if (chamber_id, parameter_id) in monitored:
            return int(chamber_id), int(parameter_id)
    raise RuntimeError("no monitored series in the window: run make pipeline first")


def main() -> None:
    settings = get_settings()
    engine = get_engine()
    with engine.connect() as conn:
        day = conn.execute(text(WINDOW_SQL)).scalar_one_or_none()
    if day is None:
        raise SystemExit("no SPC limits or no quiet day: run make pipeline first")

    df = producer.read_readings(ROOT / "data" / "demo", day, WINDOW_HOURS)
    chamber_id, parameter_id = pick_series(df, engine)
    drift = producer.Drift(chamber_id, parameter_id, day + timedelta(hours=WINDOW_HOURS / 2),
                           SHIFT_SIGMA)  # fmt: skip
    df = producer.inject(df, drift)
    with engine.connect() as conn:
        label = conn.execute(text(
            "select c.chamber_label || ' · ' || p.parameter_name from marts.dim_chamber c, "
            "marts.dim_parameter p where c.chamber_id = :c and p.parameter_id = :p"),
            {"c": chamber_id, "p": parameter_id}).scalar_one()  # fmt: skip
    print(f"window {day:%Y-%m-%d} ({len(df):,} events); +{SHIFT_SIGMA}σ step on {label} "
          f"from {drift.start:%H:%M}; publishing at {RATE:.0f}/s")  # fmt: skip

    consumer.reset(engine)
    producer.ensure_topic(settings.kafka_bootstrap, fresh=True)
    # Latency on the monotonic clock: the wall clock can step (WSL2's moves ~1 s at a time
    # when it resyncs with Windows), which made some wall-clock latencies negative.
    sent: dict[str, float] = {}
    raised: dict[tuple[str, str], float] = {}

    def on_alarm(event_id: str, chart: str) -> None:
        raised[(event_id, chart)] = time.monotonic()

    totals: list[BatchReport] = []

    def consume() -> None:
        totals.append(consumer.run(engine, settings.kafka_bootstrap, idle_stop=5.0,
                                   on_alarm=on_alarm))  # fmt: skip

    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    producer.publish(df, settings.kafka_bootstrap, rate=RATE, sent=sent)
    worker.join(timeout=600)
    latency = pd.Series([1000 * (t - sent[e]) for (e, _), t in raised.items() if e in sent])

    series = df[(df["chamber_id"] == chamber_id) & (df["parameter_id"] == parameter_id)]
    with engine.connect() as conn:
        hit = conn.execute(text(RESULT_SQL), {"c": chamber_id, "p": parameter_id,
                                              "start": drift.start}).first()  # fmt: skip
        wall_negative = conn.execute(text(WALL_NEGATIVE_SQL)).scalar_one()
        background = conn.execute(text(BACKGROUND_SQL), {"c": chamber_id, "p": parameter_id}
                                  ).scalar_one()  # fmt: skip
    total = totals[0] if totals else BatchReport()
    print(f"consumed {total.events:,} events: {total.alarms} alarms, {total.replays} replays, "
          f"{total.unmonitored} unmonitored")  # fmt: skip
    if hit is None:
        print("the drift was NOT caught in the window")
    else:
        after = series[(series["time"] >= pd.Timestamp(drift.start))
                       & (series["time"] <= pd.Timestamp(hit.measured_at))]  # fmt: skip
        fab_h = (hit.measured_at - drift.start) / timedelta(hours=1)
        print(f"drift caught by {hit.chart.upper()} after {len(after)} points "
              f"({fab_h:.1f} h of fab time), "
              f"{1000 * (raised[(hit.event_id, hit.chart)] - sent[hit.event_id]):.0f} ms after "
              f"the event was published")  # fmt: skip
    others = len(df) - len(series)
    print(f"other series: {background} alarms on {others:,} events "
          f"({100 * background / max(others, 1):.2f}%, the in-control false-alarm rate; "
          f"EWMA + CUSUM expect ~0.4%)")  # fmt: skip
    if len(latency):
        print(f"end-to-end latency over {len(latency)} alarms (monotonic clock): "
              f"p50 {latency.median():.0f} ms, p95 {latency.quantile(0.95):.0f} ms; "
              f"{wall_negative} came out negative on the wall clock (clock steps)")  # fmt: skip
    print("live view: http://localhost:3000/d/waferlens-stream")


if __name__ == "__main__":
    main()
