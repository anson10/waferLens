"""SPC engine: Phase I limits from a baseline window, Phase II monitoring of everything after.

Series
    Univariate: sensor values per (chamber, parameter) and per (tool, parameter); metrology
    wafer means per (chamber | tool, route step, parameter). Chamber and tool scope run side by
    side so the cost of pooling chambers can be measured.
    Multivariate: Hotelling T² over all metrology parameters of a route step, per chamber.

Phase I
    Each series' first ``baseline_days`` of data. Limits are robust (median, moving range,
    one trimming pass) and stored in ``spc_control_limits``. Limits are frozen: a later run
    reuses them; ``relearn=True`` writes a new version instead.

Phase II
    Every point after the baseline, standardised against the frozen limits, through Western
    Electric rules 1-4, EWMA and CUSUM (and T² for the multivariate series). Every signalling
    point is one row in ``spc_alarms``; alarms are recomputed in full on every run, so reruns
    are idempotent.

Input is ``marts.fct_measurements`` (dbt), which already ties every value to its chamber.
"""

from __future__ import annotations

import io
import time
from collections.abc import Hashable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, LiteralString, cast

import numpy as np
import pandas as pd
from psycopg import Connection as PgConnection
from sqlalchemy import Engine, text

from waferlens.db.models import Base
from waferlens.db.session import get_engine
from waferlens.ingest.loader import copy_frame
from waferlens.spc.charts import (
    T2Limits,
    cusum,
    ewma,
    hotelling_t2,
    phase1_limits,
    t2_limits,
    western_electric,
)

LIMITS = Base.metadata.tables["spc_control_limits"]
ALARMS = Base.metadata.tables["spc_alarms"]
KEY = ("source", "scope", "chamber_id", "tool_id", "parameter_id", "route_step_id",
       "is_multivariate")  # fmt: skip
SeriesKey = tuple[Any, ...]

MEASUREMENTS_SQL: LiteralString = """
    select f.source, f.measured_at, f.wafer_id, f.route_step_id, f.pass_no, f.parameter_id,
           f.chamber_id, c.tool_id, f.value
    from marts.fct_measurements as f
    join marts.dim_chamber as c on c.chamber_id = f.chamber_id
    order by f.measured_at, f.wafer_id, f.route_step_id, f.pass_no, f.parameter_id
"""


@dataclass(frozen=True)
class SpcConfig:
    baseline_days: float = 30.0
    min_baseline_points: int = 20
    ewma_lambda: float = 0.2
    ewma_width: float = 3.0
    cusum_k: float = 0.5
    cusum_h: float = 5.0
    t2_alpha: float = 0.0027


@dataclass
class SpcReport:
    series: int = 0
    skipped: int = 0  # too few baseline points, or a degenerate baseline
    limits_new: int = 0
    limits_reused: int = 0
    alarms: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0


# --------------------------------------------------------------------------- reading


def _copy_query(engine: Engine, sql: LiteralString) -> pd.DataFrame:
    with engine.connect() as conn:
        pg = conn.connection.driver_connection
        assert isinstance(pg, PgConnection)
        buf = io.BytesIO()
        with pg.cursor() as cur, cur.copy(f"COPY ({sql}) TO STDOUT WITH CSV HEADER") as copy:
            for chunk in copy:
                buf.write(chunk)
    buf.seek(0)
    return pd.read_csv(buf)


def read_measurements(engine: Engine) -> pd.DataFrame:
    df = _copy_query(engine, MEASUREMENTS_SQL)
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True, format="ISO8601")
    return df


def read_current_limits(engine: Engine) -> dict[SeriesKey, dict[str, Any]]:
    """Latest version of every stored series, keyed by its identity."""
    cols = ", ".join(KEY)
    sql = f"SELECT DISTINCT ON ({cols}) * FROM spc_control_limits ORDER BY {cols}, version DESC"
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return {tuple(r[k] for k in KEY): dict(r) for r in rows}


# --------------------------------------------------------------------------- series


def _int(value: Hashable) -> int:
    return int(cast(int, value))


def _key(**kw: Any) -> SeriesKey:
    return tuple(kw.get(k) for k in KEY)


def univariate_series(df: pd.DataFrame) -> Iterator[tuple[SeriesKey, pd.DataFrame]]:
    sensor = df[df["source"] == "sensor"]
    metrology = df[df["source"] == "metrology"]
    specs = [
        ("sensor", "chamber", sensor, ["chamber_id", "parameter_id"]),
        ("sensor", "tool", sensor, ["tool_id", "parameter_id"]),
        ("metrology", "chamber", metrology, ["chamber_id", "route_step_id", "parameter_id"]),
        ("metrology", "tool", metrology, ["tool_id", "route_step_id", "parameter_id"]),
    ]
    for source, scope, frame, keys in specs:
        for values, g in frame.groupby(keys, sort=True):
            v = dict(zip(keys, values, strict=True))
            yield (
                _key(
                    source=source,
                    scope=scope,
                    chamber_id=_int(v["chamber_id"]) if scope == "chamber" else None,
                    tool_id=str(g["tool_id"].iloc[0]),
                    parameter_id=_int(v["parameter_id"]),
                    route_step_id=_int(v["route_step_id"]) if source == "metrology" else None,
                    is_multivariate=False,
                ),
                g,
            )


def t2_series(df: pd.DataFrame) -> Iterator[tuple[SeriesKey, pd.DataFrame, list[int]]]:
    """Per (chamber, route step) with 2+ metrology parameters: one row per measured wafer."""
    metrology = df[df["source"] == "metrology"]
    for (chamber_id, route_step_id), g in metrology.groupby(["chamber_id", "route_step_id"]):
        params = sorted(_int(p) for p in g["parameter_id"].unique())
        if len(params) < 2:
            continue
        wide = g.pivot_table(index=["wafer_id", "pass_no"], columns="parameter_id",
                             values="value")  # fmt: skip
        when = g.groupby(["wafer_id", "pass_no"])["measured_at"].min()
        wide = wide.join(when).dropna().sort_values("measured_at").reset_index()
        wide["route_step_id"] = _int(route_step_id)
        yield (
            _key(
                source="metrology",
                scope="chamber",
                chamber_id=_int(chamber_id),
                tool_id=str(g["tool_id"].iloc[0]),
                route_step_id=_int(route_step_id),
                is_multivariate=True,
            ),
            wide,
            params,
        )


# --------------------------------------------------------------------------- run


def run_spc(
    engine: Engine | None = None, config: SpcConfig | None = None, *, relearn: bool = False
) -> SpcReport:
    started = time.perf_counter()
    engine = engine or get_engine()
    config = config or SpcConfig()
    report = SpcReport()
    measurements = read_measurements(engine)
    stored = read_current_limits(engine)
    next_id = 1 + max((r["limit_id"] for r in stored.values()), default=0)
    window = pd.Timedelta(days=config.baseline_days)
    now = datetime.now(UTC)
    new_limits: list[dict[str, Any]] = []
    alarm_frames: list[pd.DataFrame] = []

    def new_row(key: SeriesKey, start: Any, n: int, method: str, **values: Any) -> dict[str, Any]:
        nonlocal next_id
        old = stored.get(key)
        row = dict(zip(KEY, key, strict=True)) | values | {
            "limit_id": next_id, "version": old["version"] + 1 if old else 1, "n_baseline": n,
            "baseline_start": start, "baseline_end": start + window, "method": method,
            "computed_at": now,
        }  # fmt: skip
        next_id += 1
        new_limits.append(row)
        return row

    for key, g in univariate_series(measurements):
        report.series += 1
        times = g["measured_at"]
        limit = None if relearn else stored.get(key)
        if limit is None:
            base = g.loc[times < times.iloc[0] + window, "value"].to_numpy()
            est = phase1_limits(base) if len(base) >= config.min_baseline_points else None
            if est is None:
                report.skipped += 1
                continue
            limit = new_row(key, times.iloc[0], est.n, "median + MR/1.128, 4-sigma trim",
                            center=est.center, sigma=est.sigma)  # fmt: skip
            report.limits_new += 1
        else:
            report.limits_reused += 1
        live = g[times >= limit["baseline_end"]]
        if len(live):
            z = (live["value"].to_numpy() - limit["center"]) / limit["sigma"]
            alarm_frames.append(_univariate_alarms(live, z, limit["limit_id"], config))

    for key, wide, params in t2_series(measurements):
        report.series += 1
        x = wide[params].to_numpy(dtype=float)
        limit = None if relearn else stored.get(key)
        if limit is None:
            in_base = (wide["measured_at"] < wide["measured_at"].iloc[0] + window).to_numpy()
            est = t2_limits(x[in_base], config.t2_alpha)
            if est is None or in_base.sum() < config.min_baseline_points:
                report.skipped += 1
                continue
            limit = new_row(key, wide["measured_at"].iloc[0], est.n,
                            f"Hotelling T2, chi2 alpha={config.t2_alpha}", t2_dims=len(params),
                            t2_limit=est.limit, t2_mean=est.mean.tolist(),
                            t2_cov_inv=est.cov_inv.tolist())  # fmt: skip
            report.limits_new += 1
        else:
            report.limits_reused += 1
            est = T2Limits(np.asarray(limit["t2_mean"]), np.asarray(limit["t2_cov_inv"]),
                           float(limit["t2_limit"]), int(limit["n_baseline"]))  # fmt: skip
        live = (wide["measured_at"] >= limit["baseline_end"]).to_numpy()
        if live.any():
            stat, hit = hotelling_t2(x[live], est)
            rows = wide[live][hit]
            alarm_frames.append(_frame(rows, limit["limit_id"], "t2", stat[hit], None))

    alarms = (
        pd.concat(alarm_frames, ignore_index=True)
        if alarm_frames
        else pd.DataFrame(columns=[c.name for c in ALARMS.columns if c.name != "alarm_id"])
    )
    _write(engine, new_limits, alarms)
    report.alarms = {str(k): int(v) for k, v in alarms["chart"].value_counts().items()}
    report.seconds = round(time.perf_counter() - started, 1)
    return report


def _univariate_alarms(
    live: pd.DataFrame, z: np.ndarray, limit_id: int, config: SpcConfig
) -> pd.DataFrame:
    frames = []
    for chart, hit in western_electric(z).items():
        frames.append(_frame(live[hit], limit_id, chart, z[hit], np.sign(z[hit])))
    w, hit = ewma(z, config.ewma_lambda, config.ewma_width)
    frames.append(_frame(live[hit], limit_id, "ewma", w[hit], np.sign(w[hit])))
    upper, lower, up, down = cusum(z, config.cusum_k, config.cusum_h)
    hit = up | down
    stat = np.where(up, upper, lower)[hit]
    frames.append(_frame(live[hit], limit_id, "cusum", stat, np.where(up[hit], 1.0, -1.0)))
    return pd.concat(frames, ignore_index=True)


def _frame(
    rows: pd.DataFrame, limit_id: int, chart: str, stat: np.ndarray, sign: np.ndarray | None
) -> pd.DataFrame:
    direction = (
        pd.array([None] * len(rows), dtype="string")
        if sign is None
        else pd.array(np.where(sign > 0, "up", "down"), dtype="string")
    )
    return pd.DataFrame(
        {
            "limit_id": np.full(len(rows), limit_id, dtype=np.int32),
            "chart": chart,
            "wafer_id": rows["wafer_id"].to_numpy(dtype=np.int32),
            "route_step_id": rows["route_step_id"].to_numpy(dtype=np.int32),
            "pass_no": rows["pass_no"].to_numpy(dtype=np.int16),
            "measured_at": rows["measured_at"].to_numpy(),
            "statistic": np.asarray(stat, dtype=float),
            "direction": direction,
        }
    )


# --------------------------------------------------------------------------- writing


def _pg_array(values: Any) -> str | None:
    """Python list (or list of lists) of floats -> Postgres array literal."""
    if not isinstance(values, list):  # None, or NaN that pandas put in for a missing value
        return None
    if isinstance(values, list) and values and isinstance(values[0], list):
        return "{" + ",".join(_pg_array(v) or "" for v in values) + "}"
    return "{" + ",".join(repr(float(v)) for v in values) + "}"


def _write(engine: Engine, new_limits: list[dict[str, Any]], alarms: pd.DataFrame) -> None:
    """One transaction: add new limit versions, replace all alarms."""
    limits = pd.DataFrame(new_limits, columns=[c.name for c in LIMITS.columns])
    if len(limits):
        limits["t2_mean"] = limits["t2_mean"].map(_pg_array)
        limits["t2_cov_inv"] = limits["t2_cov_inv"].map(_pg_array)
        for col in ("baseline_start", "baseline_end", "computed_at"):
            limits[col] = pd.to_datetime(limits[col], utc=True)
        for col in ("chamber_id", "parameter_id", "route_step_id", "t2_dims"):
            limits[col] = limits[col].astype("Int32")
    alarms = alarms.copy()
    alarms.insert(0, "alarm_id", np.arange(1, len(alarms) + 1, dtype=np.int64))
    alarms["measured_at"] = pd.to_datetime(alarms["measured_at"], utc=True)
    with engine.begin() as conn:
        pg = conn.connection.driver_connection
        assert isinstance(pg, PgConnection)
        conn.execute(text("TRUNCATE spc_alarms"))
        if len(limits):
            copy_frame(pg, LIMITS, limits)
        copy_frame(pg, ALARMS, alarms)
        for table, col in (("spc_control_limits", "limit_id"), ("spc_alarms", "alarm_id")):
            conn.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                     f"COALESCE((SELECT max({col}) FROM {table}), 0) + 1, false)")
            )  # fmt: skip
        conn.execute(text("ANALYZE spc_control_limits, spc_alarms"))
