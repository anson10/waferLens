"""Fixtures shared by unit and integration tests: the fab config and one dev simulation."""

from __future__ import annotations

import pandas as pd
import pytest

from waferlens.simulate.config import FabConfig, load_config
from waferlens.simulate.run import SimulationResult, simulate


@pytest.fixture(scope="session")
def cfg() -> FabConfig:
    return load_config()


@pytest.fixture(scope="session")
def dev(cfg: FabConfig) -> SimulationResult:
    return simulate(cfg, "dev", seed=42)


def frame(result: SimulationResult, table: str) -> pd.DataFrame:
    t = result.tables[table]
    if isinstance(t, pd.DataFrame):
        return t
    return t.to_pandas()
