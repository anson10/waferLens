"""Real-time SPC on the dev fab, without a broker: every sensor reading goes through the
stream processor as an event, with a restart halfway. Its EWMA and CUSUM alarms must equal
the batch engine's, replays must change nothing, and the offsets must match what was read."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
from sqlalchemy import Engine, create_engine, make_url, text

from waferlens.dashboards.sql import dashboard_queries, expand
from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.orchestration.resources import ROOT
from waferlens.simulate.run import SimulationResult, write_parquet
from waferlens.spc.engine import SpcConfig, run_spc
from waferlens.stream import producer
from waferlens.stream.consumer import Message, SpcProcessor, reset
from waferlens.stream.events import SensorReading

pytestmark = pytest.mark.integration

BATCH_ALARMS_SQL = """
    select l.chamber_id, l.parameter_id, a.measured_at, a.chart
    from spc_alarms as a
    join spc_control_limits as l on l.limit_id = a.limit_id
    where l.source = 'sensor' and l.scope = 'chamber' and a.chart in ('ewma', 'cusum')
"""
STREAM_ALARMS_SQL = "select chamber_id, parameter_id, measured_at, chart from stream_alarms"


@pytest.fixture(scope="module")
def drop(dev: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("stream")
    write_parquet(dev, path)
    return path


@pytest.fixture(scope="module")
def fab(engine: Engine, test_db_url: str, drop: Path) -> Iterator[None]:
    load(drop, engine)
    dbt = ROOT / "dbt"
    subprocess.run(
        ["dbt", "build", "--select", "+fct_measurements", "+dim_chamber", "+dim_parameter",
         "--exclude", "test_type:data", "--profiles-dir", str(dbt), "--project-dir", str(dbt)],
        check=True, capture_output=True,
        env={**os.environ, "POSTGRES_DB": str(make_url(test_db_url).database)},
    )  # fmt: skip
    run_spc(engine, SpcConfig(baseline_days=7), relearn=True)  # dev covers 30 days
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


def _messages(drop: Path) -> list[Message]:
    """The tool agents' events, partitioned by chamber as Kafka would, offsets per partition."""
    df = producer.read_readings(drop)
    now = datetime.now(UTC)
    next_offset: dict[int, int] = {}
    out = []
    for r in df.to_dict("records"):
        e = SensorReading(measured_at=pd.Timestamp(r["time"]).to_pydatetime(),
                          wafer_id=int(r["wafer_id"]), route_step_id=int(r["route_step_id"]),
                          parameter_id=int(r["parameter_id"]), chamber_id=int(r["chamber_id"]),
                          value=float(r["value"]), produced_at=now)  # fmt: skip
        partition = e.chamber_id % producer.PARTITIONS
        offset = next_offset.get(partition, 0)
        next_offset[partition] = offset + 1
        out.append(Message(partition, offset, e.to_bytes()))
    return out


def _alarms(engine: Engine, sql: str) -> set[tuple[object, ...]]:
    with engine.connect() as conn:
        return {tuple(r) for r in conn.execute(text(sql)).all()}


def _feed(processor: SpcProcessor, messages: list[Message], size: int = 500) -> int:
    alarms = 0
    for i in range(0, len(messages), size):
        alarms += processor.process(messages[i : i + size]).alarms
    return alarms


@pytest.fixture(scope="module")
def streamed(engine: Engine, fab: None, drop: Path) -> list[Message]:
    reset(engine)
    messages = _messages(drop)
    half = len(messages) // 2
    _feed(SpcProcessor(engine), messages[:half])
    _feed(SpcProcessor(engine), messages[half:])  # a restart: state comes back from Postgres
    return messages


def test_stream_alarms_equal_the_batch_engine(engine: Engine, streamed: list[Message]) -> None:
    batch = _alarms(engine, BATCH_ALARMS_SQL)
    stream = _alarms(engine, STREAM_ALARMS_SQL)
    assert len(batch) > 50
    assert stream == batch


def test_offsets_record_every_event(engine: Engine, streamed: list[Message]) -> None:
    expected: dict[int, int] = {}
    for m in streamed:
        expected[m.partition] = max(expected.get(m.partition, 0), m.offset + 1)
    with engine.connect() as conn:
        stored = dict(conn.execute(text("select partition, next_offset from stream_offsets")).all())
    assert stored == expected


def test_replaying_changes_nothing(engine: Engine, streamed: list[Message]) -> None:
    before = _alarms(engine, STREAM_ALARMS_SQL)
    processor = SpcProcessor(engine)
    report = processor.process(streamed[-2000:])  # a re-run producer resends the tail
    assert report.alarms == 0
    assert report.replays + report.unmonitored == 2000
    assert _alarms(engine, STREAM_ALARMS_SQL) == before


def test_bad_events_are_counted_not_fatal(engine: Engine, streamed: list[Message]) -> None:
    report = SpcProcessor(engine).process([
        Message(0, 10**9, b"not json"),
        Message(0, 10**9 + 1, streamed[0].value.replace(b"/v1", b"/v9")),
    ])  # fmt: skip
    assert report.invalid == 2


def test_stream_dashboard_queries_run_as_the_reader(
    engine: Engine, test_db_url: str, streamed: list[Message]
) -> None:
    reader = create_engine(
        make_url(test_db_url).set(username="grafana_reader", password="grafana_reader")
    )
    now = datetime.now(UTC)
    empty = []
    try:
        with reader.connect() as conn:
            for q in dashboard_queries("stream"):
                sql = expand(q.sql, {}, now - timedelta(hours=1), now + timedelta(minutes=1))
                if not conn.execute(text(sql)).first():
                    empty.append(q.where)
    finally:
        reader.dispose()
    assert empty == []


def _broker() -> str | None:
    from confluent_kafka.admin import AdminClient

    from waferlens.config import get_settings

    bootstrap = get_settings().kafka_bootstrap
    try:
        AdminClient({"bootstrap.servers": bootstrap}).list_topics(timeout=3)
    except Exception:
        return None
    return bootstrap


def test_end_to_end_through_redpanda(engine: Engine, fab: None, drop: Path) -> None:
    """Producer -> Redpanda -> consumer -> Postgres, with an injected drift. Needs the
    broker (docker compose --profile stream up -d redpanda); skipped without it, as in CI."""
    from waferlens.stream.consumer import run

    bootstrap = _broker()
    if bootstrap is None:
        pytest.skip("no Kafka broker (start it with: docker compose --profile stream up -d)")
    reset(engine)
    df = producer.read_readings(drop)
    busiest = df.groupby(["chamber_id", "parameter_id"]).size().idxmax()
    chamber_id, parameter_id = cast(tuple[int, int], busiest)
    series = df[(df["chamber_id"] == chamber_id) & (df["parameter_id"] == parameter_id)]
    drift_at = series["time"].iloc[len(series) * 3 // 4]
    df = producer.inject(series, producer.Drift(int(chamber_id), int(parameter_id),
                                                drift_at.to_pydatetime(), 3.0))  # fmt: skip
    topic = f"test-readings-{os.getpid()}"
    producer.ensure_topic(bootstrap, topic, fresh=True)
    try:
        producer.publish(df, bootstrap, rate=5000, topic=topic)
        total = run(engine, bootstrap, topic=topic, group=topic, idle_stop=3.0)
    finally:
        from confluent_kafka.admin import AdminClient

        AdminClient({"bootstrap.servers": bootstrap}).delete_topics([topic])
    assert total.events == len(df)
    with engine.connect() as conn:
        caught = conn.execute(text(
            "select count(*) from stream_alarms where chamber_id = :c and parameter_id = :p "
            "and measured_at >= :t"), {"c": int(chamber_id), "p": int(parameter_id),
                                       "t": drift_at.to_pydatetime()}).scalar_one()  # fmt: skip
        stored = conn.execute(text(
            "select sum(next_offset) from stream_offsets where topic = :t"), {"t": topic}
        ).scalar_one()  # fmt: skip
    assert caught > 0
    assert stored == len(df)
