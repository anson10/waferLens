# ADR-0012: Real-time SPC on Redpanda, exactly once through Postgres

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Batch SPC (ADR-0006) charts the fab after each load: fine for the evaluation, but a drifting
chamber keeps processing wafers until the next batch run. Fabs run SPC as data arrives. Phase
6 adds a streaming path for the sensor charts that catch drifts fastest (EWMA and CUSUM),
with three requirements: the same alarms as the batch engine, no lost or duplicated alarm
when the consumer crashes or the producer replays, and a measured end-to-end latency.

## Options considered

**Broker**
1. **Apache Kafka:** the standard; a JVM and (or KRaft) controller to run, ~1 GB to idle.
2. **Redpanda:** Kafka-API compatible (same clients, same concepts), one C++ binary, runs in
   512 MB on one core; what the demo machine (7.4 GB, already running eight services) affords.
3. **Postgres LISTEN/NOTIFY or a queue table:** no new service, but no partitions, offsets,
   replay or consumer groups: the concepts the phase is about.

**Delivery guarantee**
1. **At least once + idempotent writes:** commit Kafka offsets after writing; duplicates
   are harmless only if every write is idempotent. Alarms can be (unique key), but the
   EWMA/CUSUM state can't: a replayed point would move the charts twice.
2. **Kafka transactions** (read-process-write within Kafka): exactly once only for output
   written back to Kafka, not to Postgres.
3. **Offsets stored in Postgres** with the state and alarms, in one transaction; the consumer
   seeks to them on every partition assignment.

## Decision

Redpanda in docker-compose under an opt-in `stream` profile; JSON events with a versioned
schema (`waferlens.sensor_reading/v1`), keyed by chamber so each chamber's points stay in
order; tool agents replay the simulator's Parquet readings (the simulator stays decoupled).
The consumer keeps online EWMA/CUSUM state per chamber x sensor, using the batch engine's
frozen limits, and commits **alarms, chart state and next offsets in one Postgres
transaction** (option 3). Two further guards: events at or before a series' last processed
point are replays and are skipped; alarms are unique on (event, chart).

## Consequences

- **Same answers as batch:** fed the dev fab's readings as events, with a restart from the
  saved state halfway, the stream raises exactly the batch engine's EWMA and CUSUM alarms
  (integration test); the online update equals `charts.ewma` / `charts.cusum` on 60
  generated series (unit test).
- **Crash- and replay-safe:** a restart resumes from Postgres; resending the tail of the
  stream changes nothing (tested).
- **Measured:** `make stream-demo` replays a day (17,632 events) at 800/s with a +2σ step on
  one chamber: caught by CUSUM after 3 points; end-to-end latency p50 ~270 ms, p95 ~515 ms,
  dominated by the consumer's 0.5 s batching window. Background alarms on the other series
  ran at ~0.5%, near the charts' designed in-control rate.
- **Latency needs a steady clock:** on WSL2 the wall clock stepped back by ~1 s twice a
  minute (two time-sync mechanisms), which made some wall-clock latencies negative. The demo
  measures on the monotonic clock; the stored latency is wall clock (the only cross-host
  option) and is only as good as the hosts' clock sync.
- **Scope:** sensor EWMA/CUSUM only. Western Electric rules, tool-scope charts and T² stay in
  batch; the stream doesn't load readings into the warehouse (the batch loader does).
- **Costs:** another service (opt-in), a Kafka client dependency, and offsets that live in
  Postgres, so `rpk group describe` shows lag only because the consumer also commits to
  Kafka, for monitoring.
