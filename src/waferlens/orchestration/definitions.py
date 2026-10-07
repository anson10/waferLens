"""Dagster definitions for WaferLens: ``dagster dev -m waferlens.orchestration.definitions``.

Jobs
    full_rebuild  simulate → contracts → load → SECOM → dbt → SPC + root cause → their marts
    ingest        load the current Parquet drop → dbt → SPC → SPC marts (no simulation)

Triggers
    new_parquet_drop  sensor: runs ``ingest`` when a Parquet drop appears that this pipeline
                      did not write itself (an external producer, or `make simulate`)
    nightly_rebuild   schedule: ``full_rebuild`` at 03:00 UTC

Both triggers start stopped; turn them on in the UI.
"""

# No `from __future__ import annotations`: Dagster reads these type hints at runtime to
# wire config and resources.
from dagster import (
    AssetSelection,
    DagsterInstance,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    define_asset_job,
    schedule,
    sensor,
)
from dagster_dbt import DbtCliResource

from waferlens.orchestration.assets import (
    dbt_models,
    dbt_project,
    fab_contracts,
    fab_tables,
    rootcause_candidates,
    secom_model,
    secom_tables,
    simulated_fab,
    spc_results,
)
from waferlens.orchestration.resources import FabData, SecomSource, Tracking, Warehouse

full_rebuild = define_asset_job(
    "full_rebuild",
    selection=AssetSelection.all(),
    description="Simulate, check contracts, load, load SECOM, build dbt, run SPC and root cause.",
)

ingest = define_asset_job(
    "ingest",
    selection=AssetSelection.assets(fab_tables).downstream(),
    description="Load the current Parquet drop and rebuild everything downstream of it.",
)


def last_pipeline_drop(instance: DagsterInstance) -> int | None:
    """manifest mtime recorded by the last simulated_fab materialization, if any."""
    event = instance.get_latest_materialization_event(simulated_fab.key)
    if event is None or event.asset_materialization is None:
        return None
    value = event.asset_materialization.metadata.get("manifest_mtime_ns")
    return int(value.value) if value is not None else None  # type: ignore[arg-type]


@sensor(job=ingest, minimum_interval_seconds=60, default_status=DefaultSensorStatus.STOPPED)
def new_parquet_drop(
    context: SensorEvaluationContext, fab_data: FabData
) -> RunRequest | SkipReason:
    manifest = fab_data.manifest
    if not manifest.exists():
        return SkipReason(f"no drop at {manifest}")
    stamp = manifest.stat().st_mtime_ns
    if context.cursor == str(stamp):
        return SkipReason("drop already ingested")
    context.update_cursor(str(stamp))
    if stamp == last_pipeline_drop(context.instance):
        return SkipReason("drop was written by full_rebuild, which loads it itself")
    return RunRequest(run_key=f"drop-{stamp}")


@schedule(
    job=full_rebuild,
    cron_schedule="0 3 * * *",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.STOPPED,
)
def nightly_rebuild() -> RunRequest:
    return RunRequest()


defs = Definitions(
    assets=[
        simulated_fab,
        fab_tables,
        secom_tables,
        dbt_models,
        spc_results,
        rootcause_candidates,
        secom_model,
    ],
    asset_checks=[fab_contracts],
    jobs=[full_rebuild, ingest],
    sensors=[new_parquet_drop],
    schedules=[nightly_rebuild],
    resources={
        "fab_data": FabData(),
        "warehouse": Warehouse(),
        "secom_source": SecomSource(),
        "tracking": Tracking(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
