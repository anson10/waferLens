import pytest
from sqlalchemy import text

from waferlens.db.session import get_engine, get_session

pytestmark = pytest.mark.integration


def test_postgres_is_version_16() -> None:
    with get_engine().connect() as conn:
        version = conn.execute(text("SHOW server_version_num")).scalar_one()
    assert int(version) // 10000 == 16


def test_timescaledb_extension_is_installed() -> None:
    with get_session() as session:
        installed = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one_or_none()
    assert installed is not None, "timescaledb extension missing: is the db container running?"
