"""Runtime settings, read from environment variables or a local .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://waferlens:waferlens@localhost:5432/waferlens"
    mlflow_tracking_uri: str = "http://localhost:5000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
