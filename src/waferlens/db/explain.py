"""Runs the key workload queries in ``sql/queries`` under EXPLAIN ANALYZE.

    python -m waferlens.db.explain              # summary table (markdown)
    python -m waferlens.db.explain --plan 04    # full text plan of one query

Each query runs ``--runs`` times (default 3) and the median execution time is reported, so
the numbers reflect a warm cache. "Chunks" counts hypertable chunks actually read.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from waferlens.db.session import get_engine

QUERY_DIR = Path(__file__).resolve().parents[3] / "sql" / "queries"


@dataclass
class QueryStats:
    name: str
    ms: float
    rows: int
    shared_blocks: int  # hit + read: how much data the query touched (8 kB blocks)
    chunks: int
    scans: list[str]


def queries(directory: Path = QUERY_DIR) -> dict[str, str]:
    return {p.stem: p.read_text() for p in sorted(directory.glob("*.sql"))}


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [node, *(n for child in node.get("Plans", []) for n in _walk(child))]


def _describe(node: dict[str, Any]) -> str | None:
    kind = node["Node Type"]
    if "Scan" not in kind:
        return None
    relation = node.get("Relation Name", "")
    if relation.startswith("_hyper_"):
        relation = "<chunk>"
    index = node.get("Index Name")
    return f"{kind} {relation}" + (f" ({index})" if index and relation != "<chunk>" else "")


def explain(engine: Engine, sql: str, runs: int = 3) -> tuple[list[float], dict[str, Any]]:
    times, plan = [], {}
    with engine.connect() as conn:
        for _ in range(runs):
            result = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))
            plan = result.scalar_one()[0]
            times.append(plan["Execution Time"])
    return times, plan


def measure(engine: Engine, name: str, sql: str, runs: int = 3) -> QueryStats:
    times, plan = explain(engine, sql, runs)
    nodes = _walk(plan["Plan"])
    scans: dict[str, int] = {}
    for n in nodes:
        label = _describe(n)
        if label:
            scans[label] = scans.get(label, 0) + 1
    # Chunks actually read: TimescaleDB keeps excluded chunks in the plan but never runs them.
    chunks = sum(
        1
        for n in nodes
        if str(n.get("Relation Name", "")).startswith("_hyper_") and n.get("Actual Loops", 0) > 0
    )
    root = plan["Plan"]
    return QueryStats(
        name=name,
        ms=round(statistics.median(times), 1),
        rows=int(root["Actual Rows"]),
        shared_blocks=int(root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0)),
        chunks=chunks,
        scans=[f"{k} x{v}" if v > 1 else k for k, v in sorted(scans.items())],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EXPLAIN ANALYZE the key workload queries.")
    parser.add_argument("--plan", help="print the full plan of the query whose name starts so")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args()
    engine = get_engine()
    found = queries()

    if args.plan:
        name = next(n for n in found if n.startswith(args.plan))
        with engine.connect() as conn:
            rows = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {found[name]}")).scalars()
            print(f"-- {name}\n" + "\n".join(rows))
        return

    stats = [measure(engine, name, sql, args.runs) for name, sql in found.items()]
    if args.json:
        print(json.dumps([s.__dict__ for s in stats], indent=2))
        return
    print("| Query | ms (median) | Rows | Blocks | Chunks | Scans |\n|---|---|---|---|---|---|")
    for s in stats:
        print(f"| {s.name} | {s.ms:,.1f} | {s.rows:,} | {s.shared_blocks:,} | {s.chunks} | "
              f"{'; '.join(s.scans)} |")  # fmt: skip


if __name__ == "__main__":
    main()
