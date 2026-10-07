"""Pipeline assets: Parquet drop → contracts (blocking check) → warehouse tables → dbt models.

Asset keys of the loaded tables are ``["waferlens", <table>]``, exactly what dagster-dbt
derives from the dbt sources (``source('waferlens', <table>)``), so the lineage runs unbroken
from the simulator to every mart.
"""

# No `from __future__ import annotations`: Dagster reads these type hints at runtime to
# wire config and resources.
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Config,
    MaterializeResult,
    asset,
    asset_check,
    multi_asset,
)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from waferlens.db.models import PATTERN_TABLES, ROOTCAUSE_TABLES, SPC_TABLES, STREAM_TABLES, Base
from waferlens.ingest.contracts import ContractError, check_tables
from waferlens.ingest.loader import load, read_tables
from waferlens.ingest.secom import download, load_secom, parse
from waferlens.ml.experiment import run_experiment
from waferlens.ml.secom import load as load_secom_dataset
from waferlens.ml.store import write_results
from waferlens.orchestration.resources import (
    ROOT,
    FabData,
    FabEyeService,
    SecomSource,
    Tracking,
    Warehouse,
)
from waferlens.patterns.score import score_wafers
from waferlens.rootcause.evaluate import evaluate_excursions
from waferlens.simulate.config import load_config
from waferlens.simulate.run import simulate, write_parquet
from waferlens.spc.engine import SpcConfig, run_spc

# Steps that hold a whole table in Python memory. On an 8 GB machine two of them at once,
# plus Postgres, run out of memory (it happened: the SECOM model search ran beside the fab
# contracts and the kernel killed Postgres). The executor allows one tagged step at a time.
HEAVY = {"waferlens/memory": "heavy"}
ONE_HEAVY_STEP = [{"key": "waferlens/memory", "value": "heavy", "limit": 1}]

# --------------------------------------------------------------------------- simulate


@asset(
    group_name="ingest",
    kinds={"python", "parquet"},
    description="Simulated fab written as one Parquet file per table + manifest.json.",
    op_tags=HEAVY,
)
def simulated_fab(fab_data: FabData) -> MaterializeResult:
    result = simulate(load_config(), fab_data.profile, fab_data.seed)
    write_parquet(result, fab_data.directory)
    summary = result.summary
    yields = cast(dict[str, float], summary["yield_pct"])
    return MaterializeResult(
        metadata={
            "path": str(fab_data.directory),
            "profile": fab_data.profile,
            "seed": fab_data.seed,
            "total_rows": cast(int, summary["total_rows"]),
            "mean_yield_pct": yields["mean"],
            "excursions": json.dumps(summary["excursions"]),
            "seconds": cast(float, summary["seconds"]),
            # Lets the drop sensor tell the pipeline's own drops from external ones.
            "manifest_mtime_ns": fab_data.manifest.stat().st_mtime_ns,
        }
    )


@asset_check(
    asset=simulated_fab,
    blocking=True,
    op_tags=HEAVY,
    description=(
        "Data contracts (ingest/contracts.py): pandera schemas generated from the ORM "
        "metadata plus cross-table rules. Blocking: a failed check stops the load."
    ),
)
def fab_contracts(fab_data: FabData) -> AssetCheckResult:
    tables = read_tables(fab_data.directory)
    try:
        check_tables(tables)
    except ContractError as exc:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            metadata={"violations": str(exc)[:4000]},
        )
    return AssetCheckResult(passed=True, metadata={"tables_checked": len(tables)})


# --------------------------------------------------------------------------- warehouse

ANALYSIS_TABLES = (
    *SPC_TABLES,
    *ROOTCAUSE_TABLES,
    *PATTERN_TABLES,
)  # written by later assets, not the loader
# The stream consumer is a long-running service, not a pipeline asset: its tables are
# neither loaded nor materialized by Dagster.
FAB_TABLES = [
    t.name
    for t in Base.metadata.sorted_tables
    if t.name not in ANALYSIS_TABLES and t.name not in STREAM_TABLES
] + ["wafer_yield"]
SECOM_TABLES = ["secom_runs", "secom_readings"]
ML_TABLES = ["secom_model_versions", "secom_scores", "secom_sensor_importance"]


def table_key(name: str) -> AssetKey:
    return AssetKey(["waferlens", name])


@multi_asset(
    specs=[
        AssetSpec(table_key(name), deps=[simulated_fab], group_name="warehouse",
                  kinds={"postgres"})
        for name in FAB_TABLES
    ],
    can_subset=False,
    description="One-transaction COPY load of the Parquet drop (contracts already checked).",
    op_tags=HEAVY,
)  # fmt: skip
def fab_tables(fab_data: FabData, warehouse: Warehouse) -> Iterator[MaterializeResult]:
    # The blocking contracts check has already passed in this run, so skip re-validating.
    report = load(fab_data.directory, warehouse.engine(), validate=False)
    for name in FAB_TABLES:
        metadata: dict[str, Any] = {"load_seconds": report.seconds.get(name, 0.0)}
        if name in report.rows:
            metadata["rows"] = report.rows[name]
        yield MaterializeResult(asset_key=table_key(name), metadata=metadata)


@multi_asset(
    specs=[AssetSpec(table_key(name), group_name="warehouse", kinds={"postgres"})
           for name in SECOM_TABLES],
    can_subset=False,
    description="Real UCI SECOM data: checksum-pinned download, parsed to long format.",
)  # fmt: skip
def secom_tables(secom_source: SecomSource, warehouse: Warehouse) -> Iterator[MaterializeResult]:
    directory = download(Path(secom_source.directory), secom_source.url, secom_source.sha256)
    counts = load_secom(parse(directory), warehouse.engine())
    for name in SECOM_TABLES:
        yield MaterializeResult(asset_key=table_key(name), metadata={"rows": counts[name]})


# --------------------------------------------------------------------------- dbt

DBT_DIR = ROOT / "dbt"
dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()
if not dbt_project.manifest_path.exists():
    # Outside `dagster dev` (CLI runs, tests, CI) build the manifest once: dbt deps + parse.
    dbt_project.preparer.prepare(dbt_project)


class WaferlensDbtTranslator(DagsterDbtTranslator):
    """dbt models grouped by layer (dbt_staging, dbt_intermediate, dbt_marts); seeds join marts."""

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        if dbt_resource_props.get("resource_type") == "seed":
            return "dbt_marts"  # seeds are built into the marts schema
        fqn = dbt_resource_props.get("fqn", [])
        layer = next((p for p in fqn if p in ("staging", "intermediate", "marts")), None)
        return f"dbt_{layer}" if layer else super().get_group_name(dbt_resource_props)


class DbtBuildConfig(Config):
    # The loader replaces all data on every run, and after a reload a full rebuild of
    # fct_measurements is faster than its incremental path (48 s vs 131 s, docs/perf.md).
    # Incremental pays off once data is appended rather than reloaded (phase 6).
    full_refresh: bool = True


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=WaferlensDbtTranslator(),
)
def dbt_models(
    context: AssetExecutionContext, dbt: DbtCliResource, config: DbtBuildConfig
) -> Iterator[Any]:
    # Dagster splits the dbt project into several steps around the SPC asset. With dbt's
    # default (eager) selection a step also runs every test touching its models, including
    # tests that need a model from a later step, which then fail. Cautious selection runs a
    # test only when all its models are in the step; the full `dbt build` (make dbt, CI)
    # still runs every test.
    args = ["build", "--indirect-selection", "cautious"]
    if config.full_refresh:
        args.append("--full-refresh")
    yield from dbt.cli(args, context=context).stream()


# --------------------------------------------------------------------------- SPC


class SpcRunConfig(Config):
    baseline_days: float = 30.0
    relearn: bool = False


@multi_asset(
    specs=[
        AssetSpec(table_key(name), deps=[AssetKey(["marts", "fct_measurements"])],
                  group_name="spc", kinds={"python", "postgres"})
        for name in SPC_TABLES
    ],
    can_subset=False,
    description=(
        "Phase I limits (frozen; relearn writes a new version) and Phase II alarms from "
        "Western Electric rules, EWMA, CUSUM and Hotelling T² (waferlens.spc)."
    ),
    op_tags=HEAVY,
)  # fmt: skip
def spc_results(config: SpcRunConfig, warehouse: Warehouse) -> Iterator[MaterializeResult]:
    report = run_spc(
        warehouse.engine(), SpcConfig(baseline_days=config.baseline_days), relearn=config.relearn
    )
    yield MaterializeResult(
        asset_key=table_key("spc_control_limits"),
        metadata={"series": report.series, "skipped": report.skipped,
                  "new": report.limits_new, "reused": report.limits_reused},
    )  # fmt: skip
    yield MaterializeResult(
        asset_key=table_key("spc_alarms"),
        metadata={"alarms": sum(report.alarms.values()), "by_chart": json.dumps(report.alarms),
                  "seconds": report.seconds},
    )  # fmt: skip


# --------------------------------------------------------------------------- root cause


@asset(
    key=table_key("rootcause_candidates"),
    deps=[
        AssetKey(["marts", "fct_wafer_steps"]),
        AssetKey(["marts", "fct_wafer_yield"]),
        AssetKey(["marts", "fct_wafer_pattern"]),  # pattern-led rankings (phase 5a)
        table_key("excursions_ground_truth"),
    ],
    group_name="rootcause",
    kinds={"python", "postgres"},
    description=(
        "Commonality analysis of every injected excursion's time window: chambers and recipe "
        "versions ranked by over-representation among low-yield wafers (waferlens.rootcause)."
    ),
)
def rootcause_candidates(warehouse: Warehouse) -> MaterializeResult:
    report = evaluate_excursions(warehouse.engine())
    return MaterializeResult(
        metadata={"windows": report.windows, "candidates": report.candidates,
                  "seconds": report.seconds}
    )  # fmt: skip


# --------------------------------------------------------------------------- SECOM model


@multi_asset(
    specs=[
        AssetSpec(table_key(name), deps=[table_key(t) for t in SECOM_TABLES],
                  group_name="ml", kinds={"python", "postgres", "mlflow"})
        for name in ML_TABLES
    ],
    can_subset=False,
    description=(
        "SECOM fail model: selected by walk-forward CV, scored once on the latest 30% of runs, "
        "registered in MLflow; out-of-sample scores and sensor importance for Grafana "
        "(waferlens.ml)."
    ),
    op_tags=HEAVY,
)  # fmt: skip
def secom_model(warehouse: Warehouse, tracking: Tracking) -> Iterator[MaterializeResult]:
    engine = warehouse.engine()
    exp = run_experiment(load_secom_dataset(engine), tracking.uri())
    written = write_results(engine, exp)
    c = exp.chosen
    yield MaterializeResult(
        asset_key=table_key("secom_model_versions"),
        metadata={"model_version": exp.model_version, "config": c.config.name,
                  "holdout_pr_auc": c.scores.pr_auc, "chance": c.scores.prevalence,
                  "random_split_pr_auc": float(c.random_split.mean()),
                  "mlflow_run_id": str(exp.extras["mlflow_run_id"])},
    )  # fmt: skip
    yield MaterializeResult(asset_key=table_key("secom_scores"),
                            metadata={"rows": written["scores"]})  # fmt: skip
    yield MaterializeResult(asset_key=table_key("secom_sensor_importance"),
                            metadata={"rows": written["sensors"]})  # fmt: skip


# --------------------------------------------------------------------------- wafer-map patterns


@asset(
    key=table_key("wafer_patterns"),
    deps=[table_key("wafer_maps")],
    group_name="patterns",
    kinds={"python", "postgres"},
    description=(
        "Every sorted wafer map classified by FabEye (/predict/batch): WM-811K pattern, "
        "confidence, auto-accept flag, conformal prediction set (waferlens.patterns)."
    ),
)
def wafer_patterns(warehouse: Warehouse, fabeye: FabEyeService) -> MaterializeResult:
    report = score_wafers(warehouse.engine(), fabeye.client())
    return MaterializeResult(
        metadata={"wafers": report.wafers, "auto_accepted": report.accepted,
                  "by_pattern": json.dumps(report.by_pattern), "model": report.model,
                  "seconds": report.seconds}
    )  # fmt: skip
