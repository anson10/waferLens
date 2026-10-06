import pytest

from waferlens.config import Settings


def test_default_database_url_targets_local_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "localhost:5432" in settings.database_url


def test_database_url_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
