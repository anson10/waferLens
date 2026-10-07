"""Every SQL statement Grafana will run, and the macro expansion Grafana applies to it, so the
tests can run them against Postgres without a Grafana server.

Only the macros the dashboards use are supported; an unknown one fails loudly rather than
reaching Postgres as invalid SQL.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from waferlens.dashboards.build import DASHBOARDS

ROOT = Path(__file__).resolve().parents[3]
ALERTING = ROOT / "grafana" / "provisioning" / "alerting" / "waferlens.yml"


@dataclass(frozen=True)
class Query:
    where: str  # e.g. "spc / panel 1 / B"
    sql: str


def dashboard_queries(name: str) -> Iterator[Query]:
    """Variables first, in dashboard order (later ones may use earlier ones), then
    annotations and panels."""
    dash = DASHBOARDS[name]()
    for var in dash["templating"]["list"]:
        yield Query(f"{name} / variable {var['name']}", var["query"])
    for anno in dash["annotations"]["list"]:
        if "target" in anno:
            yield Query(f"{name} / annotation {anno['name']}", anno["target"]["rawSql"])
    for p in dash["panels"]:
        for t in p.get("targets", []):
            if "rawSql" in t:  # PromQL targets (FabEye serving) are not SQL
                yield Query(f"{name} / panel {p['id']} / {t['refId']}", t["rawSql"])


def alert_queries() -> Iterator[Query]:
    doc = yaml.safe_load(ALERTING.read_text())
    for group in doc["groups"]:
        for rule in group["rules"]:
            for data in rule["data"]:
                if "rawSql" in data["model"]:
                    yield Query(f"alert {rule['uid']} / {data['refId']}", data["model"]["rawSql"])


def expand(sql: str, variables: Mapping[str, Any], start: datetime, end: datetime) -> str:
    """Grafana's Postgres macros and single-value variables (inserted as is, so string
    variables are quoted in the SQL itself)."""
    t0, t1 = f"'{start.isoformat()}'", f"'{end.isoformat()}'"
    sql = re.sub(r"\$__timeFilter\(([^)]+)\)", rf"\1 BETWEEN {t0} AND {t1}", sql)
    sql = sql.replace("$__timeFrom()", t0).replace("$__timeTo()", t1)
    for name in sorted(variables, key=len, reverse=True):  # $chamber before $c
        sql = sql.replace(f"${{{name}}}", str(variables[name]))
        sql = sql.replace(f"${name}", str(variables[name]))
    if leftover := re.findall(r"\$\{?\w+", sql):
        raise ValueError(f"unexpanded macro or variable: {leftover}")
    return sql
