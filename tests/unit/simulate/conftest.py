from __future__ import annotations

import pytest

from waferlens.simulate.config import FabConfig, ProfileSpec
from waferlens.simulate.run import SimulationResult, simulate

# Bigger than dev so every excursion type shows up, still ~2 s.
SIGNAL_PROFILE = ProfileSpec(lots=300, days=60, excursions=16, benign_recipe_changes=2)


@pytest.fixture(scope="session")
def signal_run(cfg: FabConfig) -> SimulationResult:
    return simulate(cfg, SIGNAL_PROFILE, seed=7, profile_name="signal")
