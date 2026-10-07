"""Renders the dashboards to PNG for the README with Grafana's image renderer.

    make screenshots     (starts the renderer, then runs this)

Each dashboard opens on a view that shows what it is for: the overview over the whole demo
period, the SPC chart on the chamber of a detected excursion, and the excursion review
zoomed to a week either side of that excursion.
"""

from __future__ import annotations

import base64
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from waferlens.db.session import get_engine

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "img"
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
AUTH = (
    "Basic "
    + base64.b64encode(
        f"{os.environ.get('GRAFANA_ADMIN_USER', 'admin')}:"
        f"{os.environ.get('GRAFANA_ADMIN_PASSWORD', 'admin')}".encode()
    ).decode()
)

# A sensor excursion SPC caught quickly and commonality ranked first: the most telling
# example for the screenshots.
EXAMPLE_SQL = """
    SELECT d.excursion_id, e.chamber_id, c.tool_id, e.parameter_id, e.start_time, e.end_time
    FROM marts.fct_excursion_detection AS d
    JOIN excursions_ground_truth AS e ON e.excursion_id = d.excursion_id
    JOIN chambers AS c ON c.chamber_id = e.chamber_id
    JOIN marts.fct_root_cause_eval AS r ON r.excursion_id = d.excursion_id
    WHERE d.chart = 'ewma' AND d.scope = 'chamber' AND d.detected
      AND NOT d.started_in_baseline AND e.excursion_type IN ('step_shift', 'drift')
    -- prefer one commonality ranked first, on a chamber with metrology (so the T² panel
    -- has something to show)
    ORDER BY r.true_rank = 1 DESC, EXISTS (SELECT 1 FROM marts.fct_spc_alarms AS a
                     WHERE a.chart = 't2' AND a.chamber_id = e.chamber_id
                       AND a.measured_at BETWEEN e.start_time - INTERVAL '7 days'
                                             AND e.end_time + INTERVAL '7 days') DESC,
             abs(e.magnitude_sigma) DESC, d.delay_points
    LIMIT 1
"""


def _ms(ts: object) -> int:
    return int(ts.timestamp() * 1000)  # type: ignore[attr-defined]


def render(uid: str, name: str, params: dict[str, object], width: int = 1600,
           height: int = 1000) -> Path:  # fmt: skip
    query = urllib.parse.urlencode({**params, "width": width, "height": height, "tz": "UTC",
                                    "kiosk": "true"})  # fmt: skip
    req = urllib.request.Request(f"{GRAFANA}/render/d/{uid}/{name}?{query}",
                                 headers={"Authorization": AUTH})  # fmt: skip
    for attempt in range(10):  # the renderer needs a moment after it starts
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                path = OUT / f"grafana-{name}.png"
                path.write_bytes(resp.read())
                return path
        except urllib.error.URLError:
            if attempt == 9:
                raise
            time.sleep(3)
    raise RuntimeError("unreachable")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with get_engine().connect() as conn:
        ex = conn.execute(text(EXAMPLE_SQL)).mappings().one()
    week = timedelta(days=7)
    window = {"from": _ms(ex["start_time"] - week), "to": _ms(ex["end_time"] + week)}
    shots = [
        render("waferlens-overview", "overview",
               {"from": "1767571200000", "to": "1783296000000"}, height=920),
        render("waferlens-spc", "spc",
               {**window, "var-tool": ex["tool_id"], "var-chamber": ex["chamber_id"],
                "var-parameter": ex["parameter_id"]}, height=1380),
        render("waferlens-excursions", "excursions",
               {**window, "var-excursion": ex["excursion_id"]}, height=1040),
        render("waferlens-secom", "secom",
               {"from": "1216425600000", "to": "1224288000000"}, height=1180),
    ]  # fmt: skip
    for path in shots:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    main()
