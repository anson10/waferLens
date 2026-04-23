#!/usr/bin/env python3
"""
pipeline.py  —  CLI entry point
--------------------------------
Usage examples:

  # Generate layouts from CSV, validate, and write reports
  python pipeline.py run --config sample_data/layouts_config.csv

  # Generate only
  python pipeline.py generate --config sample_data/layouts_config.csv --output layouts/

  # Validate only (a directory of existing XML files)
  python pipeline.py validate --input layouts/ --report-dir reports/

  # Inject a deliberate error into one file and re-validate
  python pipeline.py corrupt --file layouts/Alpha_Mask_Test.xml
"""

import argparse
import csv
import sys
import random
from pathlib import Path
from lxml import etree

from generator import generate_layout, save_layout
from validator import validate_file, validate_directory
from reporter  import text_report, save_text_report, save_html_report


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_config(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "project_name":    row["project_name"].strip(),
                "created_by":      row["created_by"].strip(),
                "description":     row["description"].strip(),
                "num_components":  int(row["num_components"]),
                "num_test_points": int(row["num_test_points"]),
                "layer_count":     int(row["layer_count"]),
            })
    return rows


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


# ── Subcommands ───────────────────────────────────────────────────────────────

def cmd_generate(args):
    configs = load_config(args.config)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n  Generating {len(configs)} layout(s) → {out_dir}/\n")
    for cfg in configs:
        root  = generate_layout(**cfg)
        fname = safe_filename(cfg["project_name"]) + ".xml"
        fpath = out_dir / fname
        save_layout(root, str(fpath))
        print(f"  [OK] {fname}")
    print(f"\n  Done. {len(configs)} file(s) written.\n")


def cmd_validate(args):
    in_path  = Path(args.input)
    rep_dir  = Path(args.report_dir)
    rep_dir.mkdir(parents=True, exist_ok=True)

    if in_path.is_file():
        results = [validate_file(str(in_path))]
    else:
        results = validate_directory(str(in_path))

    print(text_report(results))

    txt_path  = rep_dir / "report.txt"
    html_path = rep_dir / "report.html"
    save_text_report(results, str(txt_path))
    save_html_report(results, str(html_path))
    print(f"\n  Reports saved:\n    {txt_path}\n    {html_path}\n")

    failed = [r for r in results if not r["valid"]]
    if failed:
        sys.exit(1)


def cmd_run(args):
    """Full pipeline: generate → validate → report."""
    configs  = load_config(args.config)
    out_dir  = Path("layouts")
    rep_dir  = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*50}")
    print("  STEP 1 — Generating layouts")
    print(f"{'='*50}")
    generated = []
    for cfg in configs:
        root  = generate_layout(**cfg)
        fname = safe_filename(cfg["project_name"]) + ".xml"
        fpath = out_dir / fname
        save_layout(root, str(fpath))
        generated.append(str(fpath))
        print(f"  [GEN] {fname}")

    print(f"\n{'='*50}")
    print("  STEP 2 — Validating against XSD")
    print(f"{'='*50}")
    results = [validate_file(p) for p in generated]
    for r in results:
        status = "PASS" if r["valid"] else "FAIL"
        print(f"  [{status}] {Path(r['file']).name}")

    print(f"\n{'='*50}")
    print("  STEP 3 — Writing reports")
    print(f"{'='*50}")
    save_text_report(results, str(rep_dir / "report.txt"))
    save_html_report(results, str(rep_dir / "report.html"))
    print(f"  report.txt  → {rep_dir}/report.txt")
    print(f"  report.html → {rep_dir}/report.html")

    passed = sum(1 for r in results if r["valid"])
    print(f"\n  Result: {passed}/{len(results)} layouts valid.\n")


def cmd_corrupt(args):
    """Deliberately break a layout file to demonstrate error reporting."""
    path = Path(args.file)
    tree = etree.parse(str(path))
    root = tree.getroot()
    ns   = {"tns": "http://amtc.example.com/ChipLayout"}

    # Remove a required element or inject a bad enum value
    layers = root.findall(".//tns:Layer", ns)
    if layers:
        lyr  = random.choice(layers)
        lyr.set("type", "INVALID_TYPE")   # breaks the LayerTypeEnum restriction
        etree.indent(tree, space="  ")
        tree.write(str(path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
        print(f"\n  [CORRUPT] Injected bad layer type into {path.name}")
        print("  Run 'python pipeline.py validate --input layouts/' to see the error.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Chip Layout XML Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Full pipeline: generate + validate + report")
    p_run.add_argument("--config", default="sample_data/layouts_config.csv")

    # generate
    p_gen = sub.add_parser("generate", help="Generate XML layouts from CSV config")
    p_gen.add_argument("--config",  default="sample_data/layouts_config.csv")
    p_gen.add_argument("--output",  default="layouts")

    # validate
    p_val = sub.add_parser("validate", help="Validate XML file(s) against XSD")
    p_val.add_argument("--input",      default="layouts")
    p_val.add_argument("--report-dir", default="reports")

    # corrupt
    p_cor = sub.add_parser("corrupt", help="Inject an error into a layout file")
    p_cor.add_argument("--file", required=True)

    args = parser.parse_args()
    {"run": cmd_run, "generate": cmd_generate,
     "validate": cmd_validate, "corrupt": cmd_corrupt}[args.command](args)


if __name__ == "__main__":
    main()
