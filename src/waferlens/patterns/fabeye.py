"""Client for the FabEye wafer-map classifier (github.com/anson10/FabEye).

WaferLens never trains a wafer-map model: it sends sorted wafer maps to FabEye's
``/predict/batch`` and stores what comes back. FabEye's input is a 2D grid with 0 outside
the wafer, 1 for a good die and 2 for a failed die; WaferLens' maps hold the sort bin per
die, so every fail bin maps to 2.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

BATCH = 64  # FabEye's per-request limit
CLASSES = ("none", "Center", "Donut", "Edge-Loc", "Edge-Ring", "Loc", "Near-full", "Random",
           "Scratch")  # fmt: skip
# Simulator pattern name -> FabEye (WM-811K) class.
FROM_SIMULATOR = {
    "center": "Center",
    "donut": "Donut",
    "edge_loc": "Edge-Loc",
    "edge_ring": "Edge-Ring",
    "loc": "Loc",
    "near_full": "Near-full",
    "random": "Random",
    "scratch": "Scratch",
}


def to_fabeye(bin_map: Any) -> list[list[int]]:
    """Sort bins (0 off wafer, 1 pass, >= 2 a fail bin) -> FabEye's 0 / 1 / 2."""
    grid = np.asarray(bin_map, dtype=np.int16)
    return np.minimum(grid, 2).tolist()


@dataclass(frozen=True)
class Prediction:
    pattern: str
    confidence: float
    auto_accept: bool
    prediction_set: list[str]


class FabEyeError(RuntimeError):
    pass


class FabEye:
    def __init__(self, url: str, api_key: str, *, timeout: float = 60.0, retries: int = 3):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries

    def _request(self, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.url}{path}", data=data, method="GET" if data is None else "POST",
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
        )  # fmt: skip
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == self.retries - 1:
                    raise FabEyeError(f"{path}: HTTP {e.code} {e.read()[:200]!r}") from e
            except urllib.error.URLError as e:
                if attempt == self.retries - 1:
                    raise FabEyeError(f"{path}: {e.reason}") from e
            time.sleep(2**attempt)
        raise FabEyeError("unreachable")

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def calibration(self) -> dict[str, Any]:
        return self._request("/calibration")

    def version(self) -> str:
        """Model file and API version, e.g. 'wafer_cnn.onnx · api 2.0'."""
        api = self._request("/openapi.json")["info"]["version"]
        return f"{self.health()['model']} · api {api}"

    def predict(self, maps: Sequence[Any], alpha: float = 0.1) -> Iterator[Prediction]:
        """One prediction per map, in order, in batches of 64."""
        for start in range(0, len(maps), BATCH):
            body = {"wafer_maps": [to_fabeye(m) for m in maps[start : start + BATCH]]}
            out = self._request(f"/predict/batch?alpha={alpha}", body)
            for r in out["results"]:
                yield Prediction(r["pattern"], float(r["confidence"]), bool(r["auto_accept"]),
                                 list(r["prediction_set"]))  # fmt: skip
