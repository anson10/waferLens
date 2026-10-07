"""Dagster resources: where the fab data lives, which database to load, the SECOM source."""

# No `from __future__ import annotations`: Dagster reads these type hints at runtime to
# wire config and resources.
from pathlib import Path

from dagster import ConfigurableResource
from sqlalchemy import Engine, create_engine, pool

from waferlens.config import get_settings
from waferlens.ingest import secom
from waferlens.patterns.fabeye import FabEye

ROOT = Path(__file__).resolve().parents[3]


class FabData(ConfigurableResource):  # type: ignore[type-arg]
    """Which simulated fab the pipeline builds, and where its Parquet drop lives."""

    profile: str = "demo"
    seed: int = 42
    data_root: str = str(ROOT / "data")

    @property
    def directory(self) -> Path:
        return Path(self.data_root) / self.profile

    @property
    def manifest(self) -> Path:
        return self.directory / "manifest.json"


class Warehouse(ConfigurableResource):  # type: ignore[type-arg]
    """The PostgreSQL/TimescaleDB database. Empty URL = the app settings (DATABASE_URL)."""

    database_url: str = ""

    def engine(self) -> Engine:
        # NullPool: each asset run opens and closes its own connections.
        return create_engine(
            self.database_url or get_settings().database_url, poolclass=pool.NullPool
        )


class SecomSource(ConfigurableResource):  # type: ignore[type-arg]
    """The pinned UCI SECOM archive and where it is cached."""

    url: str = secom.SECOM_URL
    sha256: str = secom.SECOM_SHA256
    directory: str = str(ROOT / secom.DEFAULT_DIR)


class Tracking(ConfigurableResource):  # type: ignore[type-arg]
    """MLflow tracking server and model registry. Empty URI = the app settings
    (MLFLOW_TRACKING_URI)."""

    tracking_uri: str = ""

    def uri(self) -> str:
        return self.tracking_uri or get_settings().mlflow_tracking_uri


class FabEyeService(ConfigurableResource):  # type: ignore[type-arg]
    """The FabEye wafer-map classifier (docker-compose service). Empty = the app settings
    (FABEYE_URL, FABEYE_API_KEY)."""

    url: str = ""
    api_key: str = ""

    def client(self) -> FabEye:
        settings = get_settings()
        return FabEye(self.url or settings.fabeye_url, self.api_key or settings.fabeye_api_key)
