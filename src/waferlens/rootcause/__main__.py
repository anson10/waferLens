"""CLI.

    python -m waferlens.rootcause                         # evaluate every injected excursion
    python -m waferlens.rootcause --start 2026-03-02 --end 2026-03-09   # ad-hoc window

Needs the dbt marts (make dbt).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import text

from waferlens.db.session import get_engine
from waferlens.rootcause.commonality import commonality
from waferlens.rootcause.evaluate import evaluate_excursions


def _when(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Commonality analysis of low-yield wafers.")
    parser.add_argument("--start", type=_when, help="window start (ISO date/time, UTC)")
    parser.add_argument("--end", type=_when, help="window end")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    if args.start is None:
        report = evaluate_excursions()
        print(f"root cause: {report.windows} excursion windows, {report.candidates:,} ranked"
              f" candidates in {report.seconds} s")  # fmt: skip
        return

    engine = get_engine()
    ranked = commonality(engine, args.start, args.end).head(args.top)
    with engine.connect() as conn:
        chambers = dict(conn.execute(text("SELECT chamber_id, tool_id || '/' || chamber_code "
                                          "FROM chambers")).all())  # fmt: skip
        recipes = dict(conn.execute(text("SELECT recipe_id, name || ' v' || version "
                                         "FROM recipes")).all())  # fmt: skip
    print(f"Suspects for {args.start:%Y-%m-%d %H:%M} to {args.end:%Y-%m-%d %H:%M} UTC")
    for r in ranked.to_dict("records"):
        names = chambers if r["factor_type"] == "chamber" else recipes
        print(
            f"  {r['suspect_rank']:>3}. {r['factor_type']:<7} {names[r['factor_id']]:<26} "
            f"lift {r['lift']:.2f}  chi2 {r['chi2']:7.1f}  "
            f"low {r['low_through']}/{r['n_through']} wafers"
        )


if __name__ == "__main__":
    main()
