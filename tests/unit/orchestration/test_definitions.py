"""Dagster definitions: graph wiring, jobs, and the drop sensor's decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dagster import (
    AssetKey,
    AssetMaterialization,
    DagsterInstance,
    RunRequest,
    SkipReason,
    build_sensor_context,
)

from waferlens.db.models import PATTERN_TABLES, ROOTCAUSE_TABLES, SPC_TABLES
from waferlens.orchestration.assets import FAB_TABLES, ML_TABLES, SECOM_TABLES, simulated_fab
from waferlens.orchestration.definitions import defs, new_parquet_drop, nightly_rebuild
from waferlens.orchestration.resources import FabData


def test_definitions_load_with_expected_groups() -> None:
    graph = defs.resolve_asset_graph()
    groups = {graph.get(k).group_name for k in graph.get_all_asset_keys()}
    assert groups == {
        "ingest",
        "warehouse",
        "spc",
        "rootcause",
        "ml",
        "patterns",
        "dbt_staging",
        "dbt_intermediate",
        "dbt_marts",
    }
    assert {j.name for j in defs.resolve_all_job_defs()} >= {"full_rebuild", "ingest"}


def test_every_dbt_source_is_produced_by_a_loader_asset() -> None:
    # dagster-dbt names sources ["waferlens", <table>]; the loaders must produce exactly
    # those keys, or the lineage breaks silently between the warehouse and dbt.
    graph = defs.resolve_asset_graph()
    sources = {k for k in graph.get_all_asset_keys() if k.path[0] == "waferlens"}
    produced = {
        AssetKey(["waferlens", t])
        for t in [
            *FAB_TABLES,
            *SECOM_TABLES,
            *SPC_TABLES,
            *ROOTCAUSE_TABLES,
            *ML_TABLES,
            *PATTERN_TABLES,
        ]
    }
    assert sources == produced
    assert all(graph.get(k).is_materializable for k in sources)


def test_lineage_runs_from_simulator_to_marts() -> None:
    graph = defs.resolve_asset_graph()
    lots = AssetKey(["waferlens", "lots"])
    assert simulated_fab.key in graph.get(lots).parent_keys
    assert AssetKey(["marts", "fct_wafer_yield"]) in graph.get_all_asset_keys()
    upstream = graph.upstream_key_iterator(AssetKey(["marts", "fct_wafer_yield"]))
    assert simulated_fab.key in set(upstream)


def test_ingest_job_skips_simulation_and_secom() -> None:
    job = defs.resolve_job_def("ingest")
    keys = job.asset_layer.selected_asset_keys
    assert AssetKey(["waferlens", "lots"]) in keys
    assert AssetKey(["marts", "fct_measurements"]) in keys
    assert simulated_fab.key not in keys
    assert AssetKey(["waferlens", "secom_runs"]) not in keys


def test_contracts_check_is_blocking() -> None:
    graph = defs.resolve_asset_graph()
    check = next(k for k in graph.asset_check_keys if k.name == "fab_contracts")
    assert check.asset_key == simulated_fab.key
    assert graph.get_check_spec(check).blocking


def test_nightly_rebuild_runs_full_rebuild_at_3_utc() -> None:
    assert nightly_rebuild.cron_schedule == "0 3 * * *"
    assert nightly_rebuild.job_name == "full_rebuild"


# --------------------------------------------------------------------------- drop sensor


def _evaluate(instance: DagsterInstance, data: FabData, cursor: str | None = None):
    context = build_sensor_context(instance=instance, cursor=cursor, resources={"fab_data": data})
    return new_parquet_drop(context), context.cursor


def test_sensor_skips_when_there_is_no_drop(tmp_path: Path) -> None:
    with DagsterInstance.ephemeral() as instance:
        result, _ = _evaluate(instance, FabData(profile="dev", data_root=str(tmp_path)))
    assert isinstance(result, SkipReason)


def test_sensor_runs_ingest_once_per_external_drop(tmp_path: Path) -> None:
    data = FabData(profile="dev", data_root=str(tmp_path))
    data.directory.mkdir(parents=True)
    data.manifest.write_text("{}")
    with DagsterInstance.ephemeral() as instance:
        first, cursor = _evaluate(instance, data)
        again, _ = _evaluate(instance, data, cursor)
    assert isinstance(first, RunRequest)
    assert isinstance(again, SkipReason)


def test_sensor_ignores_drops_written_by_the_pipeline(tmp_path: Path) -> None:
    data = FabData(profile="dev", data_root=str(tmp_path))
    data.directory.mkdir(parents=True)
    data.manifest.write_text("{}")
    with DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(
            AssetMaterialization(
                asset_key=simulated_fab.key,
                metadata={"manifest_mtime_ns": data.manifest.stat().st_mtime_ns},
            )
        )
        result, _ = _evaluate(instance, data)
    assert isinstance(result, SkipReason)
    assert "full_rebuild" in str(result.skip_message)


def test_pipeline_docs_describe_the_real_graph() -> None:
    from waferlens.orchestration.docs import render

    doc = render(defs)
    assert "ingest -->|" in doc
    assert "warehouse -->|" in doc
    assert "`fab_contracts` on `simulated_fab` (blocking)" in doc
    assert "dbt tests, which dagster-dbt runs as blocking" in doc
    assert "| `full_rebuild` |" in doc
    assert "| sensor | `new_parquet_drop` | `ingest` |" in doc


def test_memory_heavy_steps_never_run_together() -> None:
    # Two of these at once ran an 8 GB machine out of memory (the kernel killed Postgres).
    # The limit sits on the executor, so it holds whatever run config a job is given.
    from waferlens.orchestration import assets

    heavy = [assets.simulated_fab, assets.fab_contracts, assets.fab_tables,
             assets.spc_results, assets.secom_model]  # fmt: skip
    assert all(a.op.tags == assets.HEAVY for a in heavy)
    for job in ("full_rebuild", "ingest"):
        executor = defs.resolve_job_def(job).executor_def
        assert executor.name == "multiprocess"
        # configured(): a run config can't override it, an empty one resolves to the limits
        schema: Any = executor.config_schema
        resolved = schema.resolve_config({}).value
        assert resolved["config"]["tag_concurrency_limits"] == assets.ONE_HEAVY_STEP
