"""Real-time SPC consumer: sensor events in, EWMA/CUSUM alarms out, exactly once.

    python -m waferlens.stream.consumer     (needs the stream profile: see make stream-demo)

Exactly once, without Kafka transactions: each batch of events is processed in memory, then
its alarms, the updated chart states and the next offset per partition are written in **one
Postgres transaction**. On start (and on every partition assignment) the consumer seeks to
the offsets stored in Postgres, not Kafka's: whatever committed is never reprocessed, and
whatever didn't commit is reprocessed from the same state. Kafka's own offsets are committed
too, but only so ``rpk group describe`` can show the lag.

Two more guards: an event older than a series' last processed point is a replay (a re-run
producer) and is skipped; alarms are unique on (event_id, chart).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import insert

from waferlens.db.models import StreamAlarm, StreamOffset, StreamSpcState
from waferlens.stream.events import TOPIC, SensorReading
from waferlens.stream.online import Limits, SeriesState, is_new, update

SeriesKey = tuple[int, int]  # (chamber_id, parameter_id)

# Current frozen limits of every chamber-scope sensor series (the batch engine's Phase I).
LIMITS_SQL = """
    select distinct on (chamber_id, parameter_id)
           chamber_id, parameter_id, limit_id, center, sigma, baseline_end
    from spc_control_limits
    where source = 'sensor' and scope = 'chamber' and not is_multivariate
    order by chamber_id, parameter_id, version desc
"""


@dataclass(frozen=True)
class Message:
    """What the consumer needs from a Kafka message (and what tests build without Kafka)."""

    partition: int
    offset: int
    value: bytes


@dataclass
class BatchReport:
    events: int = 0
    alarms: int = 0
    replays: int = 0  # older than the series' last point: skipped
    unmonitored: int = 0  # no frozen limits for the series (yet)
    invalid: int = 0  # not a valid event of a known schema version
    seconds: float = 0.0
    alarm_events: list[str] = field(default_factory=list)


class SpcProcessor:
    def __init__(self, engine: Engine, topic: str = TOPIC,
                 on_alarm: Callable[[str, str], None] | None = None):  # fmt: skip
        self.engine = engine
        self.topic = topic
        self.on_alarm = on_alarm  # (event_id, chart), called as each alarm is raised
        self.limits = self._load_limits()
        self.states = self._load_states()

    def _load_limits(self) -> dict[SeriesKey, Limits]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(LIMITS_SQL)).all()
        return {(r.chamber_id, r.parameter_id): Limits(r.limit_id, r.center, r.sigma,
                                                         r.baseline_end) for r in rows}  # fmt: skip

    def _load_states(self) -> dict[SeriesKey, SeriesState]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM stream_spc_state")).mappings().all()
        return {
            (r["chamber_id"], r["parameter_id"]): SeriesState(
                r["limit_id"], r["n"], r["ewma"], r["cusum_up"], r["cusum_down"],
                r["last_measured_at"], r["last_event_id"],
            )
            for r in rows
        }  # fmt: skip

    def stored_offsets(self) -> dict[int, int]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT partition, next_offset FROM stream_offsets WHERE topic = :t"),
                {"t": self.topic},
            ).all()
        return {int(p): int(o) for p, o in rows}

    def process(self, messages: Sequence[Message]) -> BatchReport:
        started = time.perf_counter()
        report = BatchReport(events=len(messages))
        states = dict(self.states)  # committed only if the transaction commits
        dirty: set[SeriesKey] = set()
        alarm_rows: list[dict[str, object]] = []
        next_offsets: dict[int, int] = {}
        for m in messages:
            next_offsets[m.partition] = max(next_offsets.get(m.partition, 0), m.offset + 1)
            try:
                e = SensorReading.from_bytes(m.value)
            except ValidationError:
                report.invalid += 1
                continue
            key = (e.chamber_id, e.parameter_id)
            limits = self.limits.get(key)
            if limits is None:
                report.unmonitored += 1
                continue
            state = states.get(key, SeriesState(limit_id=limits.limit_id))
            if not is_new(state, e.measured_at, e.event_id):
                report.replays += 1
                continue
            states[key], alarms = update(state, limits, e.value, e.measured_at, e.event_id)
            dirty.add(key)
            for a in alarms:
                alarm_rows.append({
                    "event_id": e.event_id, "chart": a.chart, "chamber_id": e.chamber_id,
                    "parameter_id": e.parameter_id, "limit_id": limits.limit_id,
                    "wafer_id": e.wafer_id, "route_step_id": e.route_step_id,
                    "measured_at": e.measured_at, "statistic": a.statistic,
                    "direction": a.direction, "produced_at": e.produced_at,
                    # Wall clock, like produced_at: comparable across hosts only if their
                    # clocks are synced (WSL2's steps by ~1 s; the demo measures monotonically).
                    "detected_at": datetime.now(UTC),
                })  # fmt: skip
                report.alarm_events.append(f"{a.chart}:{e.event_id}")
                if self.on_alarm is not None:
                    self.on_alarm(e.event_id, a.chart)
        self._commit(states, dirty, alarm_rows, next_offsets)
        self.states = states
        report.alarms = len(alarm_rows)
        report.seconds = time.perf_counter() - started
        return report

    def _commit(
        self,
        states: dict[SeriesKey, SeriesState],
        dirty: Iterable[SeriesKey],
        alarm_rows: list[dict[str, object]],
        next_offsets: dict[int, int],
    ) -> None:
        state_rows = [_state_row(key, states[key]) for key in dirty]
        offset_rows = [{"topic": self.topic, "partition": p, "next_offset": o}
                       for p, o in next_offsets.items()]  # fmt: skip
        with self.engine.begin() as conn:  # alarms, states and offsets commit together
            if alarm_rows:
                conn.execute(insert(StreamAlarm).on_conflict_do_nothing(), alarm_rows)
            if state_rows:
                stmt = insert(StreamSpcState)
                keep = ("chamber_id", "parameter_id")
                updated = {c: stmt.excluded[c] for c in state_rows[0] if c not in keep}
                updated["updated_at"] = text("now()")
                upsert = stmt.on_conflict_do_update(index_elements=list(keep), set_=updated)
                conn.execute(upsert, state_rows)
            if offset_rows:
                stmt = insert(StreamOffset)
                updated: dict[str, Any] = {"next_offset": stmt.excluded.next_offset,
                                           "updated_at": text("now()")}  # fmt: skip
                upsert = stmt.on_conflict_do_update(
                    index_elements=["topic", "partition"], set_=updated
                )
                conn.execute(upsert, offset_rows)


def _state_row(key: SeriesKey, s: SeriesState) -> dict[str, object]:
    return {"chamber_id": key[0], "parameter_id": key[1], "limit_id": s.limit_id, "n": s.n,
            "ewma": s.ewma, "cusum_up": s.cusum_up, "cusum_down": s.cusum_down,
            "last_measured_at": s.last_measured_at, "last_event_id": s.last_event_id}  # fmt: skip


def reset(engine: Engine) -> None:
    """Forget all streaming state: offsets, chart states and alarms (the demo starts clean)."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE stream_alarms, stream_spc_state, stream_offsets"))


def run(engine: Engine, bootstrap: str, *, topic: str = TOPIC, group: str = "waferlens-spc",
        idle_stop: float | None = None, batch: int = 500,
        on_alarm: Callable[[str, str], None] | None = None) -> BatchReport:  # fmt: skip
    """Consume until interrupted (or ``idle_stop`` seconds without events). Returns totals."""
    from confluent_kafka import Consumer, TopicPartition

    processor = SpcProcessor(engine, topic, on_alarm)
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": group,
                         "enable.auto.commit": False, "auto.offset.reset": "earliest"})  # fmt: skip

    def on_assign(c: Consumer, partitions: list[TopicPartition]) -> None:
        stored = processor.stored_offsets()  # Postgres is the source of truth
        for p in partitions:
            if p.partition in stored:
                p.offset = stored[p.partition]
        c.assign(partitions)

    consumer.subscribe([topic], on_assign=on_assign)
    total = BatchReport()
    last_event = time.monotonic()
    try:
        while True:
            msgs = [m for m in consumer.consume(num_messages=batch, timeout=0.5) if not m.error()]
            if not msgs:
                if idle_stop is not None and time.monotonic() - last_event > idle_stop:
                    break
                continue
            last_event = time.monotonic()
            r = processor.process([_message(m) for m in msgs])
            consumer.commit(asynchronous=True)  # only for lag monitoring
            for f in ("events", "alarms", "replays", "unmonitored", "invalid"):
                setattr(total, f, getattr(total, f) + getattr(r, f))
            total.alarm_events += r.alarm_events
    finally:
        consumer.close()
    return total


def _message(m: Any) -> Message:
    """A confluent_kafka message: partition, offset and value are set on consumed ones."""
    return Message(int(m.partition()), int(m.offset()), bytes(m.value()))


def main() -> None:
    from waferlens.config import get_settings
    from waferlens.db.session import get_engine

    try:
        total = run(get_engine(), get_settings().kafka_bootstrap)
    except KeyboardInterrupt:
        return
    print(f"{total.events:,} events, {total.alarms} alarms")


if __name__ == "__main__":
    main()
