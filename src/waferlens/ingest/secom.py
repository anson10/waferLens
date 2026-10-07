"""UCI SECOM: download, parse and load the real semiconductor dataset.

SECOM has 1,567 production runs, 590 anonymised sensor / measurement signals per run and a
pass/fail result from in-house line testing (McCann & Johnston, 2008, CC BY 4.0). See
``docs/data/secom.md`` for the data card.

The archive is pinned by SHA-256 and only the three known file names are extracted, so a
changed or malicious download fails loudly instead of being loaded.

    python -m waferlens.ingest.secom            # download if needed, then load
"""

from __future__ import annotations

import argparse
import hashlib
import io
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from psycopg import Connection as PgConnection
from sqlalchemy import Engine, text
from sqlalchemy.schema import AddConstraint, DropConstraint

from waferlens.db.models import SECOM_SENSORS, ExternalBase
from waferlens.db.session import get_engine
from waferlens.ingest.loader import copy_frame

SECOM_URL = "https://archive.ics.uci.edu/static/public/179/secom.zip"
SECOM_SHA256 = "eea568baf3c2229096d7d294cf0b096b5502bd96d92c0b80a65b84714059be8e"
MEMBERS = ("secom.data", "secom_labels.data", "secom.names")
DEFAULT_DIR = Path("data/secom")
TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"

RUNS = ExternalBase.metadata.tables["secom_runs"]
READINGS = ExternalBase.metadata.tables["secom_readings"]


class SecomFormatError(ValueError):
    pass


@dataclass
class Secom:
    runs: pd.DataFrame  # run_id, run_time, failed
    readings: pd.DataFrame  # run_id, sensor_no, value (non-missing only)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(dest: Path = DEFAULT_DIR, url: str = SECOM_URL, sha256: str = SECOM_SHA256) -> Path:
    """Fetch and extract the archive into ``dest`` unless a verified copy is already there."""
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "secom.zip"
    if not archive.exists() or _sha256(archive) != sha256:
        partial = dest / "secom.zip.part"
        with urllib.request.urlopen(url, timeout=120) as response:
            partial.write_bytes(response.read())
        actual = _sha256(partial)
        if actual != sha256:
            partial.unlink()
            raise SecomFormatError(f"checksum mismatch for {url}: got {actual}")
        partial.replace(archive)

    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        for member in MEMBERS:
            if member not in names:
                raise SecomFormatError(f"{archive} has no {member}")
            (dest / member).write_bytes(z.read(member))  # fixed names: no path traversal
    return dest


def parse(source: Path = DEFAULT_DIR) -> Secom:
    raw = (source / "secom.data").read_bytes()
    widths = {len(line.split()) for line in raw.decode().splitlines() if line.strip()}
    if widths != {SECOM_SENSORS}:
        raise SecomFormatError(f"expected {SECOM_SENSORS} values per run, found {sorted(widths)}")
    values = pd.read_csv(
        io.BytesIO(raw), sep=r"\s+", header=None, na_values=["NaN"], dtype=np.float64
    ).to_numpy()

    labels = pd.read_csv(source / "secom_labels.data", sep=" ", header=None,
                         names=["label", "time"])  # fmt: skip
    if len(labels) != len(values):
        raise SecomFormatError(f"{len(values)} runs but {len(labels)} labels")
    if not labels["label"].isin([-1, 1]).all():
        raise SecomFormatError("labels must be -1 (pass) or 1 (fail)")

    n_runs = len(values)
    runs = pd.DataFrame(
        {
            "run_id": np.arange(1, n_runs + 1, dtype=np.int16),
            "run_time": pd.to_datetime(labels["time"], format=TIMESTAMP_FORMAT).dt.tz_localize(
                "UTC"
            ),
            "failed": (labels["label"] == 1).to_numpy(),
        }
    )
    present = ~np.isnan(values)
    run_idx, sensor_idx = np.nonzero(present)
    readings = pd.DataFrame(
        {
            "run_id": (run_idx + 1).astype(np.int16),
            "sensor_no": (sensor_idx + 1).astype(np.int16),
            "value": values[present],
        }
    )
    return Secom(runs, readings)


def load_secom(data: Secom, engine: Engine | None = None) -> dict[str, int]:
    """Replace the SECOM tables in one transaction (fab tables are untouched)."""
    engine = engine or get_engine()
    fk = next(iter(READINGS.foreign_key_constraints))
    with engine.begin() as conn:
        pg = conn.connection.driver_connection
        assert isinstance(pg, PgConnection)
        # Model results reference the runs and are stale after a reload: retrain (make
        # secom-model) to get them back.
        conn.execute(text("TRUNCATE secom_readings, secom_runs, secom_scores, "
                          "secom_sensor_importance, secom_model_versions"))  # fmt: skip
        conn.execute(DropConstraint(fk))
        copy_frame(pg, RUNS, data.runs)
        copy_frame(pg, READINGS, data.readings)
        conn.execute(AddConstraint(fk))
        conn.execute(text("ANALYZE secom_runs, secom_readings"))
    return {"secom_runs": len(data.runs), "secom_readings": len(data.readings)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and load UCI SECOM.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    started = time.perf_counter()
    data = parse(download(args.dir))
    counts = load_secom(data)
    missing_pct = 100 * (1 - counts["secom_readings"] / (len(data.runs) * SECOM_SENSORS))
    print(
        f"SECOM: {counts['secom_runs']:,} runs ({int(data.runs['failed'].sum())} failed), "
        f"{counts['secom_readings']:,} readings ({missing_pct:.2f}% missing) "
        f"loaded in {time.perf_counter() - started:.1f} s"
    )


if __name__ == "__main__":
    main()
