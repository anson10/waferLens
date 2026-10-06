"""SECOM download and parsing, on a small fake archive in the real file format."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pytest

from waferlens.db.models import SECOM_SENSORS
from waferlens.ingest.secom import (
    DEFAULT_DIR,
    MEMBERS,
    SecomFormatError,
    download,
    parse,
)

LABELS = ['-1 "19/07/2008 11:55:00"', '1 "19/07/2008 12:32:00"', '-1 "20/07/2008 08:00:00"']


def _data_line(run: int, width: int = SECOM_SENSORS) -> str:
    values = [f"{run * 1000 + s + 0.25}" for s in range(width)]
    values[3] = "NaN"  # every fake run misses sensor 4
    if run == 2:
        values[0] = "NaN"
    return " ".join(values)


def _write_sources(folder: Path, data_lines: list[str], labels: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "secom.data").write_text("\n".join(data_lines) + "\n")
    (folder / "secom_labels.data").write_text("\n".join(labels) + "\n")
    (folder / "secom.names").write_text("fake SECOM for tests\n")


@pytest.fixture
def fake_archive(tmp_path: Path) -> tuple[Path, str]:
    src = tmp_path / "src"
    _write_sources(src, [_data_line(r) for r in (1, 2, 3)], LABELS)
    archive = tmp_path / "upstream.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for member in MEMBERS:
            z.write(src / member, member)
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_download_verifies_and_extracts(fake_archive: tuple[Path, str], tmp_path: Path) -> None:
    archive, sha = fake_archive
    dest = download(tmp_path / "secom", url=archive.as_uri(), sha256=sha)
    assert {p.name for p in dest.iterdir()} == {"secom.zip", *MEMBERS}


def test_verified_archive_is_not_downloaded_again(
    fake_archive: tuple[Path, str], tmp_path: Path
) -> None:
    archive, sha = fake_archive
    dest = download(tmp_path / "secom", url=archive.as_uri(), sha256=sha)
    download(dest, url="file:///does/not/exist.zip", sha256=sha)  # would fail if fetched


def test_checksum_mismatch_is_rejected(fake_archive: tuple[Path, str], tmp_path: Path) -> None:
    archive, _ = fake_archive
    dest = tmp_path / "secom"
    with pytest.raises(SecomFormatError, match="checksum mismatch"):
        download(dest, url=archive.as_uri(), sha256="0" * 64)
    assert not any(dest.iterdir())  # nothing half-downloaded is left behind


def test_archive_without_expected_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("secom.data", "1 2 3\n")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(SecomFormatError, match=r"no secom_labels\.data"):
        download(tmp_path / "secom", url=archive.as_uri(), sha256=sha)


def test_parse_builds_runs_and_long_readings(tmp_path: Path) -> None:
    _write_sources(tmp_path, [_data_line(r) for r in (1, 2, 3)], LABELS)
    secom = parse(tmp_path)

    assert secom.runs["run_id"].tolist() == [1, 2, 3]
    assert secom.runs["failed"].tolist() == [False, True, False]  # -1 pass, 1 fail
    assert str(secom.runs["run_time"].dt.tz) == "UTC"
    assert secom.runs["run_time"].iloc[2].isoformat() == "2008-07-20T08:00:00+00:00"

    # Missing values have no row: 3 runs x 590 sensors, minus sensor 4 everywhere and
    # sensor 1 of run 2.
    assert len(secom.readings) == 3 * SECOM_SENSORS - 3 - 1
    assert secom.readings["sensor_no"].between(1, SECOM_SENSORS).all()
    run2 = secom.readings[secom.readings["run_id"] == 2].set_index("sensor_no")["value"]
    assert 1 not in run2.index
    assert 4 not in run2.index
    assert run2[590] == pytest.approx(2000 + 589 + 0.25)


@pytest.mark.parametrize(
    ("lines", "labels", "message"),
    [
        ([_data_line(1, width=589)], LABELS[:1], "expected 590 values per run"),
        ([_data_line(1), _data_line(2)], LABELS, "2 runs but 3 labels"),
        ([_data_line(1)], ['0 "19/07/2008 11:55:00"'], "labels must be -1"),
    ],
)
def test_parse_rejects_malformed_files(
    tmp_path: Path, lines: list[str], labels: list[str], message: str
) -> None:
    _write_sources(tmp_path, lines, labels)
    with pytest.raises(SecomFormatError, match=message):
        parse(tmp_path)


@pytest.mark.skipif(
    not (DEFAULT_DIR / "secom.data").exists(), reason="real SECOM not downloaded (make secom)"
)
def test_real_secom_matches_the_data_card() -> None:
    secom = parse(DEFAULT_DIR)
    assert len(secom.runs) == 1567
    assert int(secom.runs["failed"].sum()) == 104
    assert len(secom.readings) == 882_579
    assert secom.runs["run_time"].is_monotonic_increasing
    by_month = secom.runs.groupby(secom.runs["run_time"].dt.month)["failed"].mean()
    assert np.round(100 * by_month.to_numpy(), 1).tolist() == [22.2, 9.2, 2.9, 6.1]
