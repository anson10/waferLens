"""Grafana dashboards as code: three dashboards generated as JSON into grafana/dashboards/.

    python -m waferlens.dashboards      (or: make dashboards)

Grafana provisions them read-only on start. A test fails if the committed JSON differs from
what this module generates, and another runs every panel's SQL against a loaded database as
the read-only ``grafana_reader`` role.

Panel SQL may use only these Grafana macros: ``$__timeFilter(col)``, ``$__timeFrom()``,
``$__timeTo()``, and the dashboard variables ``$tool``, ``$chamber``, ``$parameter``,
``$excursion``; ``tests/integration/test_dashboards.py`` expands exactly those.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "grafana" / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "waferlens-timescaledb"}
PROM = {"type": "prometheus", "uid": "waferlens-prometheus"}
# The demo fab simulates 2026-01-05 to 2026-07-05; open dashboards on that history.
TIME_RANGE = {"from": "2026-01-05T00:00:00.000Z", "to": "2026-07-06T00:00:00.000Z"}
SECOM_RANGE = {"from": "2008-07-19T00:00:00.000Z", "to": "2008-10-18T00:00:00.000Z"}

Json = dict[str, Any]


# --------------------------------------------------------------------------- building blocks


def target(sql: str, ref: str = "A", fmt: str = "time_series") -> Json:
    # The SQL is collapsed onto one line, so a `--` comment would swallow the rest of it.
    if "--" in sql:
        raise ValueError("no -- comments in dashboard SQL; use the panel description")
    return {"refId": ref, "datasource": DS, "editorMode": "code", "rawQuery": True,
            "format": fmt, "rawSql": " ".join(sql.split())}  # fmt: skip


def panel(
    pid: int,
    title: str,
    kind: str,
    grid: tuple[int, int, int, int],
    targets: list[Json],
    *,
    description: str = "",
    unit: str | None = None,
    decimals: int | None = None,
    overrides: list[Json] | None = None,
    options: Json | None = None,
    custom: Json | None = None,
    no_value: str | None = None,
) -> Json:
    x, y, w, h = grid
    defaults: Json = {"custom": custom or {}}
    if no_value:
        defaults["noValue"] = no_value
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": pid,
        "type": kind,
        "title": title,
        "description": description,
        # Grafana runs a panel's targets on the panel's datasource: take it from the targets.
        "datasource": targets[0]["datasource"] if targets else DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {},
    }


def by_name(name: str, **properties: Any) -> Json:
    return {
        "matcher": {"id": "byName", "options": name},
        "properties": [{"id": k, "value": v} for k, v in properties.items()],
    }


def points_only(name: str, color: str) -> Json:
    return by_name(name, **{"custom.drawStyle": "points", "custom.pointSize": 7,
                            "color": {"mode": "fixed", "fixedColor": color}})  # fmt: skip


def dashed(name: str, color: str) -> Json:
    return by_name(name, **{"custom.drawStyle": "line",
                            "custom.lineStyle": {"fill": "dash", "dash": [10, 6]},
                            "custom.lineWidth": 1, "custom.showPoints": "never",
                            "color": {"mode": "fixed", "fixedColor": color}})  # fmt: skip


def variable(name: str, label: str, sql: str) -> Json:
    query = " ".join(sql.split())
    return {"name": name, "label": label, "type": "query", "datasource": DS, "query": query,
            "definition": query, "refresh": 1, "sort": 0, "current": {}, "options": [],
            "includeAll": False, "multi": False}  # fmt: skip


def dashboard(uid: str, title: str, description: str, panels: list[Json], *,
              variables: list[Json] | None = None,
              annotations: list[Json] | None = None,
              time: Json | None = None, refresh: str = "") -> Json:  # fmt: skip
    builtin = {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
               "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
               "name": "Annotations & Alerts", "type": "dashboard"}  # fmt: skip
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["waferlens"],
        "timezone": "utc",
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "graphTooltip": 1,
        "refresh": refresh,
        "time": time or TIME_RANGE,
        "templating": {"list": variables or []},
        "annotations": {"list": [builtin, *(annotations or [])]},
        "panels": panels,
        "links": [
            {"title": "WaferLens", "type": "dashboards", "tags": ["waferlens"], "asDropdown": True}
        ],
    }


def quiet_stat(pid: int, title: str, x: int, sql: str, **kw: Any) -> Json:
    """A stat without threshold colours: green or red would imply good or bad."""
    return stat(pid, title, x, sql, **kw)


def stat(pid: int, title: str, x: int, sql: str, *, unit: str | None = None,
         decimals: int | None = None, description: str = "",
         text: bool = False) -> Json:  # fmt: skip
    reduce: Json = {"calcs": ["lastNotNull"]}
    if text:  # stat panels show numeric fields only unless told otherwise
        reduce["fields"] = "/.*/"
    return panel(pid, title, "stat", (x, 0, 4, 4), [target(sql, fmt="table")], unit=unit,
                 decimals=decimals, description=description,
                 options={"reduceOptions": reduce, "colorMode": "none", "graphMode": "none",
                          "textMode": "value"})  # fmt: skip


# --------------------------------------------------------------------------- 1. overview


def overview() -> Json:
    panels = [
        stat(1, "Wafers sorted", 0,
             "SELECT count(*) AS wafers FROM marts.fct_wafer_yield WHERE $__timeFilter(tested_at)"),
        stat(2, "Mean yield", 4,
             "SELECT avg(yield_pct) AS yield FROM marts.fct_wafer_yield "
             "WHERE $__timeFilter(tested_at)", unit="percent", decimals=1),
        stat(3, "Lots in WIP", 8,
             "SELECT count(*) AS lots FROM marts.dim_lot WHERE lot_status IN ('active', 'hold')",
             description="Current state at the end of the simulated period, not time-filtered."),
        stat(4, "EWMA + CUSUM alarms", 12,
             "SELECT count(*) AS alarms FROM marts.fct_spc_alarms "
             "WHERE chart_family = 'memory' AND scope = 'chamber' AND $__timeFilter(measured_at)"),
        stat(5, "Excursions started", 16,
             "SELECT count(*) AS excursions FROM marts.fct_excursion_impact "
             "WHERE $__timeFilter(started_at)",
             description="Injected by the simulator (ground truth)."),
        stat(6, "Dies lost to excursions", 20,
             "SELECT coalesce(sum(dies_lost), 0) AS dies FROM marts.fct_excursion_impact "
             "WHERE $__timeFilter(started_at)", unit="short",
             description="Affected wafers vs same-product wafers in the same window."),
        panel(7, "Daily mean yield by product", "timeseries", (0, 4, 12, 9), [target("""
            SELECT time_bucket(INTERVAL '1 day', y.tested_at) AS time, p.product_code AS metric,
                   avg(y.yield_pct) AS yield
            FROM marts.fct_wafer_yield AS y
            JOIN marts.dim_product AS p ON p.product_id = y.product_id
            WHERE $__timeFilter(y.tested_at)
            GROUP BY 1, 2 ORDER BY 1""")], unit="percent", custom={"lineWidth": 1}),
        panel(8, "SPC alarms per day by chart family (chamber scope)", "timeseries",
              (12, 4, 12, 9), [target("""
            SELECT time_bucket(INTERVAL '1 day', measured_at) AS time, chart_family AS metric,
                   count(*) AS alarms
            FROM marts.fct_spc_alarms
            WHERE scope = 'chamber' AND $__timeFilter(measured_at)
            GROUP BY 1, 2 ORDER BY 1""")], custom={"drawStyle": "bars", "stacking":
                                                    {"mode": "normal"}, "fillOpacity": 70}),
        panel(9, "Chambers with the most EWMA + CUSUM alarms", "table", (0, 13, 12, 9), [target("""
            SELECT c.chamber_label AS chamber, c.tool_type AS "tool type",
                   count(*) AS alarms, count(DISTINCT a.wafer_id) AS wafers
            FROM marts.fct_spc_alarms AS a
            JOIN marts.dim_chamber AS c ON c.chamber_id = a.chamber_id
            WHERE a.chart_family = 'memory' AND a.scope = 'chamber'
              AND $__timeFilter(a.measured_at)
            GROUP BY 1, 2 ORDER BY alarms DESC LIMIT 10""", fmt="table")]),
        panel(10, "Excursions in range (ground truth)", "table", (12, 13, 12, 9), [target("""
            SELECT e.excursion_id AS id, e.excursion_type AS type,
                   round(e.abs_magnitude_sigma::numeric, 1) AS sigma,
                   e.true_rank AS "root-cause rank", e.dies_lost AS "dies lost"
            FROM marts.fct_root_cause_eval AS e
            JOIN marts.fct_excursion_impact AS i ON i.excursion_id = e.excursion_id
            WHERE $__timeFilter(i.started_at)
            ORDER BY e.dies_lost DESC NULLS LAST""", fmt="table")],
              overrides=[by_name("id", links=[{
                  "title": "Review this excursion",
                  "url": "/d/waferlens-excursions?var-excursion=${__value.raw}"}])]),
    ]  # fmt: skip
    return dashboard(
        "waferlens-overview",
        "WaferLens · Fab overview",
        "Yield, WIP, SPC alarm load and excursions across the fab.",
        panels,
    )


# --------------------------------------------------------------------------- 2. SPC


LIMITS_CTE = """
    WITH l AS (
        SELECT center, sigma, baseline_end FROM spc_control_limits
        WHERE source = 'sensor' AND scope = 'chamber' AND chamber_id = $chamber
          AND parameter_id = $parameter
        ORDER BY version DESC LIMIT 1
    )"""


def spc() -> Json:
    variables = [
        variable("tool", "Tool", "SELECT tool_id FROM marts.dim_tool ORDER BY 1"),
        variable(
            "chamber",
            "Chamber",
            """
            SELECT chamber_label AS __text, chamber_id AS __value FROM marts.dim_chamber
            WHERE tool_id = '$tool' ORDER BY 1""",
        ),
        variable(
            "parameter",
            "Sensor",
            """
            SELECT p.name AS __text, l.parameter_id AS __value
            FROM spc_control_limits AS l JOIN parameters AS p ON p.parameter_id = l.parameter_id
            WHERE l.source = 'sensor' AND l.scope = 'chamber' AND l.chamber_id = $chamber
            GROUP BY 1, 2 ORDER BY 1""",
        ),
    ]
    panels = [
        panel(1, "Sensor value against frozen 3σ limits", "timeseries", (0, 0, 24, 10), [
            target("""
                SELECT measured_at AS time, value AS "value"
                FROM marts.fct_measurements
                WHERE source = 'sensor' AND chamber_id = $chamber AND parameter_id = $parameter
                  AND $__timeFilter(measured_at)
                ORDER BY 1"""),
            target(LIMITS_CTE + """
                SELECT t AS time, l.center AS "center", l.center + 3 * l.sigma AS "UCL",
                       l.center - 3 * l.sigma AS "LCL"
                FROM l, unnest(ARRAY[$__timeFrom()::timestamptz, $__timeTo()::timestamptz]) AS t
                ORDER BY 1""", ref="B"),
            target("""
                SELECT a.measured_at AS time, f.value AS "EWMA/CUSUM alarm"
                FROM marts.fct_spc_alarms AS a
                JOIN marts.fct_measurements AS f
                  ON f.source = 'sensor' AND f.wafer_id = a.wafer_id
                 AND f.route_step_id = a.route_step_id AND f.pass_no = a.pass_no
                 AND f.parameter_id = a.parameter_id
                WHERE a.scope = 'chamber' AND a.chamber_id = $chamber
                  AND a.parameter_id = $parameter AND a.chart_family = 'memory'
                  AND $__timeFilter(a.measured_at)
                GROUP BY 1, 2 ORDER BY 1""", ref="C"),
        ], description="Limits are the latest frozen Phase I version for this chamber.",
              custom={"drawStyle": "points", "pointSize": 3},
              overrides=[points_only("value", "#8a8a8a"), dashed("UCL", "red"),
                         dashed("LCL", "red"), dashed("center", "green"),
                         points_only("EWMA/CUSUM alarm", "orange")]),
        panel(2, "EWMA of the standardised value (λ 0.2) with its limits", "timeseries",
              (0, 10, 24, 8), [target(LIMITS_CTE + """
                , pts AS (
                    SELECT f.measured_at, (f.value - l.center) / l.sigma AS z
                    FROM marts.fct_measurements AS f, l
                    WHERE f.source = 'sensor' AND f.chamber_id = $chamber
                      AND f.parameter_id = $parameter AND f.measured_at >= l.baseline_end
                ), e AS (
                    SELECT measured_at, ewma(z, 0.2) OVER w AS ewma, row_number() OVER w AS i
                    FROM pts WINDOW w AS (ORDER BY measured_at)
                )
                SELECT measured_at AS time, ewma AS "EWMA",
                       3 * sqrt(0.2 / 1.8 * (1 - power(0.8, 2 * i))) AS "+L",
                       -3 * sqrt(0.2 / 1.8 * (1 - power(0.8, 2 * i))) AS "-L"
                FROM e WHERE $__timeFilter(measured_at) ORDER BY 1""")],
              description="Computed in SQL with the ewma() aggregate from migration 0006, "
                          "from the end of the baseline, exactly as waferlens.spc does.",
              custom={"lineWidth": 1, "showPoints": "never"},
              overrides=[dashed("+L", "red"), dashed("-L", "red")]),
        panel(3, "Daily mean ± 1 sd (continuous aggregate)", "timeseries", (0, 18, 12, 8), [
            target("""
                SELECT day AS time, mean_value AS "mean", mean_value + sd_value AS "+1 sd",
                       mean_value - sd_value AS "-1 sd"
                FROM sensor_daily
                WHERE chamber_id = $chamber AND parameter_id = $parameter
                  AND $__timeFilter(day)
                ORDER BY 1""")],
              description="From the sensor_daily continuous aggregate: ~100x faster than "
                          "scanning raw readings over months (docs/perf.md).",
              overrides=[dashed("+1 sd", "#8a8a8a"), dashed("-1 sd", "#8a8a8a")]),
        panel(4, "Hotelling T² alarms on this chamber's metrology steps", "timeseries",
              (12, 18, 12, 8), [target("""
                SELECT a.measured_at AS time, a.statistic AS "T²", l.t2_limit AS "limit"
                FROM marts.fct_spc_alarms AS a
                JOIN spc_control_limits AS l ON l.limit_id = a.limit_id
                WHERE a.chart = 't2' AND a.chamber_id = $chamber AND $__timeFilter(a.measured_at)
                ORDER BY 1""")],
              description="T² combines a step's metrology parameters; only steps followed by "
                          "metrology have one.",
              custom={"drawStyle": "points", "pointSize": 6},
              no_value="No T² alarms: none, or no metrology after this chamber"),
        panel(5, "Alarm history (this chamber and sensor)", "table", (0, 26, 24, 8), [target("""
            SELECT a.measured_at AS time, a.chart, a.direction,
                   round(a.statistic::numeric, 2) AS statistic, a.wafer_id AS wafer,
                   a.route_step_id AS "route step"
            FROM marts.fct_spc_alarms AS a
            WHERE a.scope = 'chamber' AND a.chamber_id = $chamber AND a.parameter_id = $parameter
              AND $__timeFilter(a.measured_at)
            ORDER BY a.measured_at DESC LIMIT 200""", fmt="table")]),
    ]  # fmt: skip
    return dashboard("waferlens-spc", "WaferLens · SPC control chart",
                     "Phase II monitoring of one chamber's sensor against frozen limits.",
                     panels, variables=variables)  # fmt: skip


# --------------------------------------------------------------------------- 3. excursions


def excursions() -> Json:
    variables = [
        variable(
            "excursion",
            "Excursion",
            """
        SELECT excursion_id AS __value,
               excursion_id || ' · ' || excursion_type || ' · ' || description AS __text
        FROM excursions_ground_truth ORDER BY excursion_id""",
        )
    ]
    annotations = [
        {"name": "Ground-truth window", "datasource": DS, "enable": True, "iconColor": "red",
         "target": target("""
            SELECT start_time AS time, end_time AS timeend,
                   'Injected: ' || description AS text, excursion_type AS tags
            FROM excursions_ground_truth WHERE excursion_id = $excursion""",
                          ref="Anno", fmt="table")},
        {"name": "First SPC alarm per chart", "datasource": DS, "enable": True,
         "iconColor": "orange", "target": target("""
            SELECT first_alarm_at AS time,
                   chart || ' first alarm after ' || delay_points || ' points' AS text,
                   chart AS tags
            FROM marts.fct_excursion_detection
            WHERE excursion_id = $excursion AND scope = 'chamber' AND detected""",
                          ref="Anno", fmt="table")},
    ]  # fmt: skip
    panels = [
        quiet_stat(1, "Affected wafers", 0, """
            SELECT affected_wafers FROM marts.fct_excursion_impact
            WHERE excursion_id = $excursion"""),
        quiet_stat(2, "Yield vs same-window controls", 4, """
            SELECT yield_delta_pct FROM marts.fct_excursion_impact
            WHERE excursion_id = $excursion""", unit="percent", decimals=1),
        quiet_stat(3, "Dies lost", 8, """
            SELECT dies_lost FROM marts.fct_excursion_impact
            WHERE excursion_id = $excursion"""),
        quiet_stat(4, "True cause rank (commonality)", 12, """
            SELECT true_rank::text
                   || coalesce(' · pattern-led ' || pattern_true_rank::text, '') AS rank
            FROM marts.fct_root_cause_eval
            WHERE excursion_id = $excursion""",
                   text=True,
                   description="Rank of the injected chamber or recipe among ~130 suspects, "
                               "from the time window alone: by low yield, and for spatial "
                               "excursions also by the wafer-map pattern FabEye sees."),
        quiet_stat(5, "EWMA first alarm after (points)", 16, """
            SELECT delay_points FROM marts.fct_excursion_detection
            WHERE excursion_id = $excursion AND chart = 'ewma' AND scope = 'chamber'
              AND detected"""),
        quiet_stat(6, "Chance baseline (points)", 20, """
            SELECT CASE WHEN placebo_alarm THEN placebo_delay_points
                        ELSE placebo_window_points END AS placebo
            FROM marts.fct_excursion_detection
            WHERE excursion_id = $excursion AND chart = 'ewma' AND scope = 'chamber'""",
                   description="First EWMA alarm in the equal-length window before the "
                               "excursion."),
        panel(7, "The excursion's sensor: value and EWMA/CUSUM alarms", "timeseries",
              (0, 4, 24, 10), [
            target("""
                SELECT f.measured_at AS time, f.value AS "value"
                FROM marts.fct_measurements AS f
                JOIN excursions_ground_truth AS e
                  ON e.chamber_id = f.chamber_id AND e.parameter_id = f.parameter_id
                WHERE e.excursion_id = $excursion AND f.source = 'sensor'
                  AND $__timeFilter(f.measured_at)
                ORDER BY 1"""),
            target("""
                SELECT a.measured_at AS time, f.value AS "EWMA/CUSUM alarm"
                FROM marts.fct_spc_alarms AS a
                JOIN excursions_ground_truth AS e
                  ON e.chamber_id = a.chamber_id AND e.parameter_id = a.parameter_id
                JOIN marts.fct_measurements AS f
                  ON f.source = 'sensor' AND f.wafer_id = a.wafer_id
                 AND f.route_step_id = a.route_step_id AND f.pass_no = a.pass_no
                 AND f.parameter_id = a.parameter_id
                WHERE e.excursion_id = $excursion AND a.scope = 'chamber'
                  AND a.chart_family = 'memory' AND $__timeFilter(a.measured_at)
                GROUP BY 1, 2 ORDER BY 1""", ref="B")],
              description="Sensor excursions only; red region = ground truth, orange marks "
                          "= first alarm per chart. Spatial patterns move no sensor.",
              custom={"drawStyle": "points", "pointSize": 3},
              overrides=[points_only("value", "#8a8a8a"),
                         points_only("EWMA/CUSUM alarm", "orange")]),
        panel(8, "Commonality suspects for this window", "table", (0, 14, 12, 10), [target("""
            SELECT suspect_rank AS rank, suspect,
                   round(lift::numeric, 2) AS lift, round(chi2::numeric, 1) AS chi2,
                   CASE WHEN is_true_cause THEN 'true cause' ELSE '' END AS truth
            FROM marts.fct_root_cause_candidates
            WHERE excursion_id = $excursion AND signal = 'yield'
            ORDER BY suspect_rank LIMIT 15""", fmt="table")],
              description="Ranked by low yield from the time window only; the true cause is "
                          "marked afterwards."),
        panel(9, "Detection by chart and scope", "table", (12, 14, 12, 10), [target("""
            SELECT chart, scope, delay_points AS "first alarm (points)",
                   CASE WHEN placebo_alarm THEN placebo_delay_points
                        ELSE placebo_window_points END AS "chance (points)"
            FROM marts.fct_excursion_detection
            WHERE excursion_id = $excursion AND monitored
            ORDER BY scope, chart""", fmt="table")]),
    ]  # fmt: skip
    return dashboard("waferlens-excursions", "WaferLens · Excursion review",
                     "One injected excursion: impact, SPC detection vs ground truth, and the "
                     "commonality suspects.", panels, variables=variables,
                     annotations=annotations)  # fmt: skip


# --------------------------------------------------------------------------- 4. SECOM model


def secom() -> Json:
    variables = [
        variable("sensor", "Sensor", """
            SELECT 's' || lpad(sensor_no::text, 3, '0') AS __text, sensor_no AS __value
            FROM secom_sensor_importance WHERE importance_rank <= 20
            ORDER BY importance_rank"""),
    ]  # fmt: skip
    annotations = [
        {"name": "Holdout starts", "datasource": DS, "enable": True, "iconColor": "purple",
         "target": target("""
            SELECT test_starts AS time,
                   'Holdout: ' || test_runs || ' runs never seen in training or selection' AS text
            FROM secom_model_versions""", ref="Anno", fmt="table")},
    ]  # fmt: skip
    model = "FROM secom_model_versions"
    panels = [
        stat(1, "Holdout PR-AUC", 0, f"SELECT holdout_pr_auc {model}", decimals=3,
             description="Last 30% of runs, scored once by the registered model."),
        stat(2, "Chance (holdout fail rate)", 4, f"SELECT holdout_prevalence {model}",
             decimals=3, description="PR-AUC of a random ranking."),
        stat(3, "Same model, random split", 8, f"SELECT random_split_pr_auc {model}", decimals=3,
             description="Mean over 20 stratified random splits: what a time-blind evaluation "
                         "would report."),
        stat(4, "Logistic baseline (holdout)", 12, f"SELECT baseline_pr_auc {model}",
             decimals=3),
        stat(5, "Holdout fails", 16, f"SELECT test_fails {model}"),
        stat(6, "Registered model", 20, f"SELECT model_version || ' · ' || config {model}",
             text=True),
        panel(7, "Out-of-sample fail score per run", "timeseries", (0, 4, 24, 9), [
            target("""
                SELECT r.run_time AS time, s.score AS "pass"
                FROM secom_scores AS s JOIN secom_runs AS r USING (run_id)
                WHERE NOT r.failed AND $__timeFilter(r.run_time) ORDER BY 1"""),
            target("""
                SELECT r.run_time AS time, s.score AS "fail"
                FROM secom_scores AS s JOIN secom_runs AS r USING (run_id)
                WHERE r.failed AND $__timeFilter(r.run_time) ORDER BY 1""", ref="B"),
            target("""
                SELECT t AS time, alarm_threshold AS "threshold (10% false alarms in training)"
                FROM secom_model_versions,
                     unnest(ARRAY[$__timeFrom()::timestamptz, $__timeTo()::timestamptz]) AS t
                ORDER BY 1""", ref="C")],
              description="Walk-forward scores before the holdout (each from a model trained "
                          "only on earlier runs), the registered model's scores after it.",
              custom={"drawStyle": "points", "pointSize": 4},
              overrides=[points_only("pass", "#8a8a8a"), points_only("fail", "red"),
                         dashed("threshold (10% false alarms in training)", "orange")]),
        panel(8, "Weekly fail rate vs alarm rate", "timeseries", (0, 13, 12, 8), [target("""
            SELECT date_trunc('week', r.run_time) AS time,
                   100 * avg(r.failed::int) AS "fail rate",
                   100 * avg(s.alarm::int) AS "alarm rate"
            FROM secom_runs AS r LEFT JOIN secom_scores AS s USING (run_id)
            WHERE $__timeFilter(r.run_time)
            GROUP BY 1 ORDER BY 1""")],
              unit="percent",
              description="Fail rate over every run; alarm rate over scored runs. The fail "
                          "rate drifts, so a threshold from the training period no longer "
                          "gives the false-alarm rate it was set for.",
              custom={"drawStyle": "line", "lineWidth": 2, "showPoints": "always",
                      "pointSize": 6}),
        panel(9, "Sensors behind the scores", "table", (12, 13, 12, 8), [target("""
            SELECT importance_rank AS rank, 's' || lpad(sensor_no::text, 3, '0') AS sensor,
                   round((100 * importance / sum(importance) OVER ())::numeric, 1)
                       AS "share of importance %",
                   round(missing_pct::numeric, 1) AS "missing in training %"
            FROM secom_sensor_importance ORDER BY importance_rank LIMIT 15""", fmt="table")],
              decimals=1, overrides=[by_name("rank", decimals=0)],
              description="Mean |contribution| on the holdout (TreeSHAP for LightGBM)."),
        panel(10, "Sensor value by outcome", "timeseries", (0, 21, 24, 8), [
            target("""
                SELECT r.run_time AS time, v.value AS "pass"
                FROM secom_readings AS v JOIN secom_runs AS r USING (run_id)
                WHERE v.sensor_no = $sensor AND NOT r.failed AND $__timeFilter(r.run_time)
                ORDER BY 1"""),
            target("""
                SELECT r.run_time AS time, v.value AS "fail"
                FROM secom_readings AS v JOIN secom_runs AS r USING (run_id)
                WHERE v.sensor_no = $sensor AND r.failed AND $__timeFilter(r.run_time)
                ORDER BY 1""", ref="B")],
              custom={"drawStyle": "points", "pointSize": 4},
              overrides=[points_only("pass", "#8a8a8a"), points_only("fail", "red")]),
    ]  # fmt: skip
    return dashboard("waferlens-secom", "WaferLens · SECOM fail prediction",
                     "Real UCI SECOM data: the registered fail model's out-of-sample scores, "
                     "its holdout result against chance and a random split, and the sensors "
                     "behind it.", panels, variables=variables, annotations=annotations,
                     time=SECOM_RANGE)  # fmt: skip


# --------------------------------------------------------------------------- 5. FabEye serving


def prom(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> Json:
    """A PromQL target on the Prometheus datasource that scrapes FabEye's /metrics."""
    return {"refId": ref, "datasource": PROM, "editorMode": "code", "expr": " ".join(expr.split()),
            "legendFormat": legend, "instant": instant, "range": not instant}  # fmt: skip


def prom_stat(pid: int, title: str, x: int, expr: str, **kw: Any) -> Json:
    return panel(pid, title, "stat", (x, 0, 6, 4), [prom(expr, instant=True)],
                 options={"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "none",
                          "graphMode": "none", "textMode": "value"}, **kw)  # fmt: skip


BATCH = 'path="/predict/batch"'


def fabeye() -> Json:
    panels = [
        prom_stat(1, "Wafers classified", 0, "sum(increase(predictions_total[$__range]))",
                  decimals=0,
                  description="Prometheus extrapolates increase() to the range edges: an "
                              "estimate, a few percent off the exact count."),
        prom_stat(2, "Sent to review", 6, """
            sum(increase(auto_accept_total{decision="review"}[$__range]))
            / sum(increase(auto_accept_total[$__range]))""", unit="percentunit", decimals=1,
                  description="Share of wafers below FabEye's auto-accept confidence: the "
                              "engineer's review queue."),
        prom_stat(3, "p95 latency per batch of 64", 12, f"""
            histogram_quantile(0.95,
              sum by (le) (rate(http_request_duration_seconds_bucket{{{BATCH}}}[$__range])))""",
                  unit="s"),
        prom_stat(4, "Failed requests", 18, """
            (sum(increase(http_requests_total{status!~"2.."}[$__range])) or vector(0))
            / sum(increase(http_requests_total[$__range]))""", unit="percentunit",
                  description="Non-2xx responses. No failing request yet means no series: 0.",
                  decimals=2),
        panel(5, "Predictions per minute by pattern (excluding 'none')", "timeseries",
              (0, 4, 12, 9),
              [prom('sum by (pattern) (rate(predictions_total{pattern!="none"}[2m])) * 60',
                    "{{pattern}}")],
              custom={"drawStyle": "line", "lineWidth": 2, "stacking": {"mode": "normal"},
                      "fillOpacity": 30}),
        panel(6, "Batch latency", "timeseries", (12, 4, 12, 9), [
            prom(f"""histogram_quantile(0.5, sum by (le)
                     (rate(http_request_duration_seconds_bucket{{{BATCH}}}[2m])))""", "p50"),
            prom(f"""histogram_quantile(0.95, sum by (le)
                     (rate(http_request_duration_seconds_bucket{{{BATCH}}}[2m])))""", "p95",
                 ref="B")], unit="s"),
        panel(7, "Review rate", "timeseries", (0, 13, 12, 8), [prom("""
            sum(rate(auto_accept_total{decision="review"}[5m]))
            / sum(rate(auto_accept_total[5m]))""", "review share")], unit="percentunit",
              description="A rising review share means the maps look less like FabEye's "
                          "calibration lots: a domain-shift early warning."),
        panel(8, "Requests per second by endpoint", "timeseries", (12, 13, 12, 8),
              [prom("sum by (path) (rate(http_requests_total[2m]))", "{{path}}")],
              unit="reqps"),
    ]  # fmt: skip
    return dashboard("waferlens-fabeye", "WaferLens · FabEye serving",
                     "The FabEye classifier as a service: volume by pattern, review queue, "
                     "latency and errors, scraped by Prometheus.", panels,
                     time={"from": "now-6h", "to": "now"}, refresh="30s")  # fmt: skip


# --------------------------------------------------------------------------- 6. real-time SPC


STREAM_LATENCY = "extract(epoch from detected_at - produced_at) * 1000"


def stream() -> Json:
    def live_stat(pid: int, title: str, x: int, sql: str, **kw: Any) -> Json:
        return stat(pid, title, x, sql, **kw) | {"gridPos": {"x": x, "y": 0, "w": 6, "h": 4}}

    panels = [
        live_stat(1, "Events consumed", 0,
                  "SELECT coalesce(sum(next_offset), 0) AS events FROM stream_offsets",
                  description="Next offset per partition, summed: every event the consumer "
                              "has committed (exactly once, with its state and alarms)."),
        live_stat(2, "Alarms", 6,
                  "SELECT count(*) FROM stream_alarms WHERE $__timeFilter(detected_at)"),
        live_stat(3, "Latency p50", 12, f"""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY {STREAM_LATENCY})
            FROM stream_alarms WHERE $__timeFilter(detected_at)""", unit="ms", decimals=0,
                  description="From the tool agent publishing the event to the alarm "
                              "committing in Postgres."),
        live_stat(4, "Latency p95", 18, f"""
            SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY {STREAM_LATENCY})
            FROM stream_alarms WHERE $__timeFilter(detected_at)""", unit="ms", decimals=0),
        panel(5, "Alarms per 10 s", "timeseries", (0, 4, 12, 9), [
            target(f"""
                SELECT time_bucket('10 seconds', detected_at) AS time, count(*) AS "{chart}"
                FROM stream_alarms
                WHERE chart = '{chart}' AND $__timeFilter(detected_at)
                GROUP BY 1 ORDER BY 1""", ref=chr(65 + i))
            for i, chart in enumerate(("ewma", "cusum"))],
              custom={"drawStyle": "bars", "fillOpacity": 70, "stacking": {"mode": "normal"}}),
        panel(6, "End-to-end latency per alarm", "timeseries", (12, 4, 12, 9), [target(f"""
            SELECT detected_at AS time, {STREAM_LATENCY} AS "latency"
            FROM stream_alarms WHERE $__timeFilter(detected_at) ORDER BY 1""")],
              unit="ms", custom={"drawStyle": "points", "pointSize": 5}),
        panel(7, "Latest alarms", "table", (0, 13, 24, 9), [target(f"""
            SELECT a.detected_at AS "detected", c.chamber_label AS chamber,
                   p.parameter_name AS sensor, a.chart, a.direction,
                   round(a.statistic::numeric, 2) AS statistic, a.measured_at AS "fab time",
                   round(({STREAM_LATENCY})::numeric) AS "latency ms"
            FROM stream_alarms AS a
            JOIN marts.dim_chamber AS c ON c.chamber_id = a.chamber_id
            JOIN marts.dim_parameter AS p ON p.parameter_id = a.parameter_id
            WHERE $__timeFilter(a.detected_at)
            ORDER BY a.detected_at DESC LIMIT 50""", fmt="table")]),
    ]  # fmt: skip
    return dashboard("waferlens-stream", "WaferLens · Real-time SPC",
                     "EWMA and CUSUM on the live event stream (Redpanda): alarms as they "
                     "commit, and the latency from tool event to alarm.", panels,
                     time={"from": "now-15m", "to": "now"}, refresh="5s")  # fmt: skip


DASHBOARDS = {"overview": overview, "spc": spc, "excursions": excursions, "secom": secom,
              "fabeye": fabeye, "stream": stream}  # fmt: skip


def render_all() -> dict[str, str]:
    return {name: json.dumps(build(), indent=2, sort_keys=True) + "\n"
            for name, build in DASHBOARDS.items()}  # fmt: skip


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in render_all().items():
        (OUT_DIR / f"{name}.json").write_text(content)
    print(f"wrote {len(DASHBOARDS)} dashboards to {OUT_DIR.relative_to(ROOT)}/")
