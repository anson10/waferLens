"""Dashboards and alerts as code: the committed JSON is what the generator writes, and every
cross-reference Grafana resolves at provisioning time exists."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import yaml

from waferlens.dashboards.build import DASHBOARDS, render_all
from waferlens.dashboards.sql import ALERTING, ROOT, dashboard_queries, expand

DATASOURCES = ROOT / "grafana" / "provisioning" / "datasources" / "timescaledb.yml"
T0, T1 = datetime(2026, 1, 5, tzinfo=UTC), datetime(2026, 2, 5, tzinfo=UTC)


def _alert_rules() -> list[dict[str, Any]]:
    doc = yaml.safe_load(ALERTING.read_text())
    return [rule for group in doc["groups"] for rule in group["rules"]]


@pytest.mark.parametrize("name", sorted(DASHBOARDS))
def test_committed_json_matches_the_generator(name: str) -> None:
    committed = (ROOT / "grafana" / "dashboards" / f"{name}.json").read_text()
    assert committed == render_all()[name], "run `make dashboards` and commit the result"


@pytest.mark.parametrize("name", sorted(DASHBOARDS))
def test_panels_have_unique_ids_and_fit_the_grid(name: str) -> None:
    panels = DASHBOARDS[name]()["panels"]
    ids = [p["id"] for p in panels]
    assert len(ids) == len(set(ids))
    for p in panels:
        grid = p["gridPos"]
        assert grid["x"] + grid["w"] <= 24, p["title"]


def test_every_query_uses_the_provisioned_datasource() -> None:
    uid = yaml.safe_load(DATASOURCES.read_text())["datasources"][0]["uid"]
    for name in DASHBOARDS:
        dash = DASHBOARDS[name]()
        sources = [v["datasource"] for v in dash["templating"]["list"]]
        sources += [t["datasource"] for p in dash["panels"] for t in p.get("targets", [])]
        assert {s["uid"] for s in sources} == {uid}, name
    for rule in _alert_rules():
        assert {d["datasourceUid"] for d in rule["data"]} <= {uid, "__expr__"}, rule["uid"]


def test_alerts_link_to_existing_dashboard_panels() -> None:
    panels = {d["uid"]: {str(p["id"]) for p in d["panels"]}
              for d in (build() for build in DASHBOARDS.values())}  # fmt: skip
    for rule in _alert_rules():
        notes = rule["annotations"]
        assert notes["__panelId__"] in panels[notes["__dashboardUid__"]], rule["uid"]
        assert rule["condition"] in {d["refId"] for d in rule["data"]}


@pytest.mark.parametrize("name", sorted(DASHBOARDS))
def test_every_query_expands_completely(name: str) -> None:
    variables = {"tool": "ETCH-01", "chamber": 1, "parameter": 1, "excursion": 1, "sensor": 60}
    for q in dashboard_queries(name):
        assert "$" not in expand(q.sql, variables, T0, T1), q.where


def test_expand_matches_grafana_macros() -> None:
    sql = expand("SELECT 1 WHERE $__timeFilter(a.t) AND x = '$tool' AND u = $__timeTo()",
                 {"tool": "ETCH-01"}, T0, T1)  # fmt: skip
    assert sql == (
        "SELECT 1 WHERE a.t BETWEEN '2026-01-05T00:00:00+00:00' AND "
        "'2026-02-05T00:00:00+00:00' AND x = 'ETCH-01' AND u = '2026-02-05T00:00:00+00:00'"
    )


def test_expand_rejects_unknown_macros() -> None:
    with pytest.raises(ValueError, match="__timeGroup"):
        expand("SELECT $__timeGroup(t, '1h')", {}, T0, T1)


def test_sql_comments_are_rejected() -> None:
    # Grafana gets each query on one line; a -- comment would comment out everything after it.
    from waferlens.dashboards.build import target

    with pytest.raises(ValueError, match="comments"):
        target("SELECT 1 -- note\nFROM t")
