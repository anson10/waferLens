"""Database engine and session factory.

Reads ``DATABASE_URL`` from the environment (via ``.env`` if present). Defaults
to a local SQLite file so a fresh clone runs without configuration.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///waferlens.db")

engine: Engine = create_engine(DATABASE_URL, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session and guarantee close; commits are the caller's responsibility."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
