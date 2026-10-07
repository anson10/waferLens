"""The FabEye client against a fake FabEye: format conversion, batching, auth, retries."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from tests.fake_fabeye import Fake, fake_fabeye
from waferlens.db.models import SPATIAL_PATTERNS
from waferlens.patterns.fabeye import BATCH, CLASSES, FROM_SIMULATOR, FabEye, FabEyeError, to_fabeye


@pytest.fixture
def fabeye() -> Iterator[FabEye]:
    with fake_fabeye() as client:
        yield client


def test_every_fail_bin_becomes_a_failed_die() -> None:
    bins = [[0, 1, 2], [3, 4, 5], [1, 0, 0]]
    assert to_fabeye(bins) == [[0, 1, 2], [2, 2, 2], [1, 0, 0]]


def test_every_simulated_pattern_has_a_fabeye_class() -> None:
    assert set(FROM_SIMULATOR) == set(SPATIAL_PATTERNS)
    assert set(FROM_SIMULATOR.values()) <= set(CLASSES)


def test_predictions_come_back_in_order_in_batches_of_64(fabeye: FabEye) -> None:
    maps = [np.ones((5, 5), dtype=int) for _ in range(150)]
    maps[100][2, 2] = 4  # a fail bin in the middle of map 100
    preds = list(fabeye.predict(maps))
    assert len(preds) == 150
    assert [p.pattern for p in preds].index("Center") == 100
    assert Fake.batches == [BATCH, BATCH, 150 - 2 * BATCH]
    assert set(Fake.keys) == {"secret"}


def test_server_errors_are_retried(fabeye: FabEye, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("waferlens.patterns.fabeye.time.sleep", lambda _: None)
    Fake.fail_next = 2
    assert len(list(fabeye.predict([np.ones((3, 3), dtype=int)]))) == 1


def test_persistent_errors_raise(fabeye: FabEye, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("waferlens.patterns.fabeye.time.sleep", lambda _: None)
    Fake.fail_next = 5
    with pytest.raises(FabEyeError, match="503"):
        list(fabeye.predict([np.ones((3, 3), dtype=int)]))


def test_version_names_model_and_api(fabeye: FabEye) -> None:
    assert fabeye.version() == "wafer_cnn.onnx · api 2.0"
