"""
reporter.py
-----------
Builds HTML and plain-text validation reports from a list of
validate_file() result dicts.
"""

from datetime import datetime
from pathlib import Path


# ── Plain-text report ────────────────────────────────────────────────────────

def text_report(results: list[dict]) -> str:
    total   = len(results)
    passed  = sum(1 for r in results if r["valid"])
    failed  = total - passed
    lines   = []

    lines.append("=" * 60)
    lines.append("  CHIP LAYOUT XML PIPELINE — VALIDATION REPORT")
    lines.append(f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("=" * 60)
    lines.append(f"  Total files : {total}")
    lines.append(f"  Passed      : {passed}")
    lines.append(f"  Failed      : {failed}")
    lines.append(f"  Pass rate   : {100*passed/total:.1f}%" if total else "  Pass rate : N/A")
    lines.append("=" * 60)

    for r in results:
        status = "PASS" if r["valid"] else "FAIL"
        name   = Path(r["file"]).name
        lines.append(f"\n[{status}] {name}  ({r['elapsed']*1000:.1f} ms)")
        if r["stats"]:
            s = r["stats"]
            lines.append(f"       Layout ID : {s.get('layout_id','?')}")
            lines.append(f"       Project   : {s.get('project_name','?')}")
            lines.append(f"       Layers    : {s.get('layers',0)}  "
                         f"Components: {s.get('components',0)}  "
                         f"Test Points: {s.get('test_points',0)}")
        if r["errors"]:
            for e in r["errors"]:
                lines.append(f"       ERROR: {e}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ── HTML report ──────────────────────────────────────────────────────────────

def html_report(results: list[dict]) -> str:
    total  = len(results)
    passed = sum(1 for r in results if r["valid"])
    failed = total - passed
    rate   = f"{100*passed/total:.1f}%" if total else "N/A"
    ts     = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = ""
    for r in results:
        s      = r["stats"] or {}
        status = "PASS" if r["valid"] else "FAIL"
        color  = "#1D9E75" if r["valid"] else "#E24B4A"
        errs   = "<br>".join(r["errors"]) if r["errors"] else "—"
        rows += f"""
        <tr>
          <td><span style="color:{color};font-weight:600">{status}</span></td>
          <td style="font-family:monospace;font-size:12px">{Path(r['file']).name}</td>
          <td>{s.get('layout_id','?')}</td>
          <td>{s.get('project_name','?')}</td>
          <td>{s.get('layers',0)}</td>
          <td>{s.get('components',0)}</td>
          <td>{s.get('test_points',0)}</td>
          <td style="color:#E24B4A;font-size:12px">{errs}</td>
          <td>{r['elapsed']*1000:.1f} ms</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>XML Pipeline Report</title>
<style>
  body {{ font-family: sans-serif; padding: 2rem; color: #222; background: #f9f9f7; }}
  h1   {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; }}
  p.sub {{ color: #666; font-size: 0.85rem; margin-top: 0; }}
  .summary {{ display: flex; gap: 1.5rem; margin: 1.5rem 0; }}
  .card {{ background: #fff; border: 1px solid #e0e0da; border-radius: 8px;
           padding: 0.75rem 1.25rem; min-width: 110px; }}
  .card .num {{ font-size: 1.8rem; font-weight: 600; }}
  .card .lbl {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .pass {{ color: #1D9E75; }} .fail {{ color: #E24B4A; }} .total {{ color: #378ADD; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border: 1px solid #e0e0da; border-radius: 8px; overflow: hidden; font-size: 13px; }}
  th    {{ background: #f1efe8; text-align: left; padding: 8px 12px; font-weight: 600;
           border-bottom: 1px solid #e0e0da; }}
  td    {{ padding: 8px 12px; border-bottom: 1px solid #f0efe8; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
</style>
</head>
<body>
<h1>Chip Layout XML Pipeline — Validation Report</h1>
<p class="sub">Generated: {ts}</p>
<div class="summary">
  <div class="card"><div class="num total">{total}</div><div class="lbl">Total</div></div>
  <div class="card"><div class="num pass">{passed}</div><div class="lbl">Passed</div></div>
  <div class="card"><div class="num fail">{failed}</div><div class="lbl">Failed</div></div>
  <div class="card"><div class="num">{rate}</div><div class="lbl">Pass rate</div></div>
</div>
<table>
<thead><tr>
  <th>Status</th><th>File</th><th>Layout ID</th><th>Project</th>
  <th>Layers</th><th>Components</th><th>Test Points</th><th>Errors</th><th>Time</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>"""


def save_text_report(results: list[dict], path: str):
    Path(path).write_text(text_report(results))


def save_html_report(results: list[dict], path: str):
    Path(path).write_text(html_report(results))
