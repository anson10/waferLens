"""A fake FabEye for tests: same endpoints and response shape, a trivially simple model."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import numpy as np

from waferlens.patterns.fabeye import FabEye


class Fake(BaseHTTPRequestHandler):
    """Answers like FabEye: 'Center' when the map's middle die failed, else 'none'."""

    batches: ClassVar[list[int]] = []
    keys: ClassVar[list[str | None]] = []
    fail_next: ClassVar[int] = 0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, code: int, body: Any) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": "wafer_cnn.onnx"})
        elif self.path == "/openapi.json":
            self._send(200, {"info": {"version": "2.0"}})
        else:
            self._send(404, {})

    def do_POST(self) -> None:
        if Fake.fail_next:
            Fake.fail_next -= 1
            self._send(503, {"detail": "busy"})
            return
        maps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["wafer_maps"]
        Fake.batches.append(len(maps))
        Fake.keys.append(self.headers.get("X-API-Key"))
        results = []
        for m in maps:
            grid = np.asarray(m)
            assert set(np.unique(grid)) <= {0, 1, 2}
            center = grid[grid.shape[0] // 2, grid.shape[1] // 2] == 2
            pattern = "Center" if center else "none"
            results.append({"pattern": pattern, "confidence": 0.9, "auto_accept": True,
                            "prediction_set": [pattern]})  # fmt: skip
        self._send(200, {"results": results})


@contextmanager
def fake_fabeye() -> Iterator[FabEye]:
    Fake.batches, Fake.keys, Fake.fail_next = [], [], 0
    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield FabEye(f"http://127.0.0.1:{server.server_port}", "secret", retries=3)
    finally:
        server.shutdown()
