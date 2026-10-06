"""Integration fixtures.

Tests run against a separate ``<dbname>_test`` database on the same server, rebuilt from the
Alembic migrations once per session. Each test gets a session inside a transaction that is
rolled back afterwards, so tests never see each other's rows and never touch dev data.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from waferlens.config import get_settings
from waferlens.db import models as m

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    base = make_url(get_settings().database_url)
    test_url = base.set(database=f"{base.database}_test")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    yield test_url.render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_url.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def alembic_cfg(test_db_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_db_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def engine(alembic_cfg: Config, test_db_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_cfg, "head")
    eng = create_engine(test_db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    outer.rollback()
    conn.close()


@dataclass
class MiniFab:
    """Smallest fab that exercises every table: 1 product, 2 steps, 1 tool with 2 chambers,
    1 lot of 3 wafers."""

    product: m.Product
    route: m.Route
    etch: m.RouteStep
    cmp: m.RouteStep
    chamber_a: m.Chamber
    chamber_b: m.Chamber
    etch_recipe: m.Recipe
    cmp_recipe: m.Recipe
    rf_power: m.Parameter
    thickness: m.Parameter
    lot: m.Lot
    wafers: list[m.Wafer]
    run: m.SimulationRun


@pytest.fixture
def fab(db: Session) -> MiniFab:
    # Inserted in dependency stages: the unit of work orders inserts by relationship(), not
    # by bare foreign-key columns, so parents are flushed before the rows that reference them.
    node = m.TechnologyNode(node_id=1, name="28nm", feature_size_nm=28)
    product = m.Product(
        product_id=1,
        code="MCU28",
        node=node,
        die_area_cm2=Decimal("0.2500"),
        map_rows=10,
        map_cols=10,
        gross_dies=80,
    )
    route = m.Route(route_id=1, product=product, version=1)
    rf_power = m.Parameter(parameter_id=1, name="rf_power_w", unit="W", kind="sensor")
    thickness = m.Parameter(parameter_id=2, name="thickness_nm", unit="nm", kind="metrology")
    run = m.SimulationRun(run_id=1, profile="dev", seed=42, config={"lots": 1})
    db.add_all(
        [
            route,
            rf_power,
            thickness,
            run,
            m.ToolType(tool_type="etch", description="Plasma etch"),
            m.ToolType(tool_type="cmp", description="Chemical mechanical polish"),
            m.SortBin(bin_code=1, name="pass", is_pass=True),
            m.SortBin(bin_code=2, name="func_fail", is_pass=False),
            m.SortBin(bin_code=3, name="leakage_fail", is_pass=False),
        ]
    )
    db.flush()

    etch = m.RouteStep(
        route_step_id=1,
        route=route,
        sequence_no=1,
        step_name="m1_etch",
        layer="M1",
        tool_type="etch",
    )
    cmp = m.RouteStep(
        route_step_id=2,
        route=route,
        sequence_no=2,
        step_name="m1_cmp",
        layer="M1",
        tool_type="cmp",
    )
    tool = m.Tool(tool_id="ETCH-01", tool_type="etch")
    chamber_a = m.Chamber(chamber_id=1, tool=tool, chamber_code="A")
    chamber_b = m.Chamber(chamber_id=2, tool=tool, chamber_code="B")
    lot = m.Lot(
        lot_id=1,
        lot_code="L26001.1",
        product=product,
        route_id=1,
        start_time=T0,
        status="active",
    )
    db.add_all([etch, cmp, chamber_a, chamber_b, lot])
    db.flush()

    etch_recipe = m.Recipe(
        recipe_id=1, route_step_id=1, name="M1_ETCH", version=1, effective_from=T0
    )
    cmp_recipe = m.Recipe(recipe_id=2, route_step_id=2, name="M1_CMP", version=1, effective_from=T0)
    wafers = [
        m.Wafer(wafer_id=i, wafer_code=f"L26001-{i:02d}", lot=lot, slot=i, status="active")
        for i in (1, 2, 3)
    ]
    db.add_all([etch_recipe, cmp_recipe, *wafers])
    db.flush()

    return MiniFab(
        product,
        route,
        etch,
        cmp,
        chamber_a,
        chamber_b,
        etch_recipe,
        cmp_recipe,
        rf_power,
        thickness,
        lot,
        wafers,
        run,
    )


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)
