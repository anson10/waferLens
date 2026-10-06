"""The Dagster pipeline end to end on the dev fab, against the test database."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from dagster import AssetKey, AssetSelection, materialize
from dagster_dbt import DbtCliResource
from sqlalchemy import Engine, make_url, text

from waferlens.db.models import Base
from waferlens.ingest.contracts import ContractError
from waferlens.orchestration.assets import (
    dbt_models,
    dbt_project,
    fab_contracts,
    fab_tables,
    secom_tables,
    simulated_fab,
)
from waferlens.orchestration.resources import FabData, SecomSource, Warehouse

pytestmark = pytest.mark.integration

ASSETS = [simulated_fab, fab_contracts, fab_tables, secom_tables, dbt_models]


@pytest.fixture
def resources(
    engine: Engine, test_db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, object]]:
    # dbt reads its connection from POSTGRES_* (dbt/profiles.yml): point it at the test db.
    monkeypatch.setenv("POSTGRES_DB", str(make_url(test_db_url).database))
    yield {
        "fab_data": FabData(profile="dev", data_root=str(tmp_path)),
        "warehouse": Warehouse(database_url=test_db_url),
        "secom_source": SecomSource(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    }
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        # dbt's views depend on the source tables; leaving them would block later
        # migration tests from dropping those tables.
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_one_run_rebuilds_simulation_load_and_marts(
    engine: Engine, resources: dict[str, object]
) -> None:
    # Everything except SECOM, which needs the network; its dbt models build on empty tables.
    selection = AssetSelection.all() - AssetSelection.assets(secom_tables)
    result = materialize(ASSETS, resources=resources, selection=selection)

    assert result.success
    checks = {e.asset_check_key.name: e.passed for e in result.get_asset_check_evaluations()}
    assert checks.pop("fab_contracts") is True
    assert checks, "dbt tests should run as asset checks"
    assert all(checks.values()), [name for name, ok in checks.items() if not ok]

    wafers = _count(engine, "wafers")
    assert wafers == 1_000
    assert _count(engine, "marts.fct_wafer_yield") == _count(engine, "wafer_maps")
    assert _count(engine, "marts.fct_measurements") > 100_000
    materialized = {e.asset_key for e in result.get_asset_materialization_events()}
    assert AssetKey(["marts", "fct_measurements"]) in {
        k for k in materialized if isinstance(k, AssetKey)
    }


def test_failed_contracts_block_the_load(
    engine: Engine, resources: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: object) -> None:
        raise ContractError("wafers.slot: expected an integer column")

    monkeypatch.setattr("waferlens.orchestration.assets.check_tables", broken)
    selection = AssetSelection.assets(simulated_fab, fab_tables)
    result = materialize(ASSETS, resources=resources, selection=selection, raise_on_error=False)

    assert not result.success
    evaluation = next(iter(result.get_asset_check_evaluations()))
    assert not evaluation.passed
    assert _count(engine, "wafers") == 0  # the load never ran
