"""Tool agents: replay the simulated fab's sensor readings as a live event stream.

The simulator stays the source of truth and stays decoupled: it writes Parquet, and this
reads it, like the loader does. Readings are published in event-time order (the batch SPC
engine's order), keyed by chamber, at a fixed rate; a drift can be injected into one series
from a given time on, to watch real-time SPC catch it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from waferlens.stream.events import TOPIC, SensorReading

ORDER = ["time", "wafer_id", "route_step_id", "parameter_id"]  # = the batch engine's order
PARTITIONS = 6


@dataclass(frozen=True)
class Drift:
    """Add ``shift_sigma`` standard deviations of the series to every reading of one chamber
    x sensor from ``start`` on: a step shift injected live."""

    chamber_id: int
    parameter_id: int
    start: datetime
    shift_sigma: float


def read_readings(drop: Path, start: datetime | None = None,
                  hours: float | None = None) -> pd.DataFrame:  # fmt: skip
    df = pd.read_parquet(drop / "tool_sensor_readings.parquet")
    if start is not None:
        df = df[df["time"] >= pd.Timestamp(start)]
    if start is not None and hours is not None:
        df = df[df["time"] < pd.Timestamp(start) + pd.Timedelta(hours=hours)]
    return df.sort_values(ORDER, kind="stable").reset_index(drop=True)


def inject(df: pd.DataFrame, drift: Drift) -> pd.DataFrame:
    series = (df["chamber_id"] == drift.chamber_id) & (df["parameter_id"] == drift.parameter_id)
    sigma = float(df.loc[series, "value"].std())
    hit = series & (df["time"] >= pd.Timestamp(drift.start))
    out = df.copy()
    out.loc[hit, "value"] += drift.shift_sigma * sigma
    return out


def ensure_topic(bootstrap: str, topic: str = TOPIC, *, fresh: bool = False) -> None:
    """Create the topic (6 partitions); ``fresh`` deletes it first, for a clean demo."""
    from confluent_kafka.admin import (  # NewTopic exists at runtime, not in the stubs
        AdminClient,
        NewTopic,  # pyright: ignore[reportPrivateImportUsage]
    )

    admin = AdminClient({"bootstrap.servers": bootstrap})
    if fresh and topic in admin.list_topics(timeout=10).topics:
        admin.delete_topics([topic])[topic].result(timeout=30)
        time.sleep(1)
    if topic not in admin.list_topics(timeout=10).topics:
        admin.create_topics([NewTopic(topic, num_partitions=PARTITIONS, replication_factor=1)])[
            topic
        ].result(timeout=30)


def publish(df: pd.DataFrame, bootstrap: str, *, rate: float = 1000.0, topic: str = TOPIC,
            sent: dict[str, float] | None = None) -> int:  # fmt: skip
    """Publish every row as an event, ``rate`` events per second. Idempotent producer: a
    broker retry never writes an event twice. ``sent`` collects each event's monotonic send
    time, for measuring latency without the wall clock (see the demo)."""
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True,
                         "linger.ms": 5})  # fmt: skip
    started = time.monotonic()
    for i, r in enumerate(df.to_dict("records")):
        event = SensorReading(
            measured_at=pd.Timestamp(r["time"]).to_pydatetime(), wafer_id=int(r["wafer_id"]),
            route_step_id=int(r["route_step_id"]), parameter_id=int(r["parameter_id"]),
            chamber_id=int(r["chamber_id"]), value=float(r["value"]),
            produced_at=datetime.now(UTC),
        )  # fmt: skip
        if sent is not None:
            sent[event.event_id] = time.monotonic()
        producer.produce(topic, key=event.key, value=event.to_bytes())
        if i % 200 == 0:
            producer.poll(0)
            ahead = started + i / rate - time.monotonic()
            if ahead > 0:
                time.sleep(ahead)
    producer.flush(30)
    return len(df)


def hours_between(a: datetime, b: datetime) -> float:
    return (b - a) / timedelta(hours=1)
