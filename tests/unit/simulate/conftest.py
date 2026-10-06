from __future__ import annotations

import pandas as pd
import pytest

from waferlens.simulate.config import FabConfig, ProfileSpec, load_config
from waferlens.simulate.run import SimulationResult, simulate

# Bigger than dev so every excursion type shows up, still ~2 s.
SIGNAL_PROFILE = ProfileSpec(lots=300, days=60, excursions=16, benign_recipe_changes=2)


@pytest.fixture(scope="session")
def cfg() -> FabConfig:
    return load_config()


@pytest.fixture(scope="session")
def dev(cfg: FabConfig) -> SimulationResult:
    return simulate(cfg, "dev", seed=42)


@pytest.fixture(scope="session")
def signal_run(cfg: FabConfig) -> SimulationResult:
    return simulate(cfg, SIGNAL_PROFILE, seed=7, profile_name="signal")


def frame(result: SimulationResult, table: str) -> pd.DataFrame:
    t = result.tables[table]
    if isinstance(t, pd.DataFrame):
        return t
    return t.to_pandas()
