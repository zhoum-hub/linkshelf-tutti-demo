"""Database setup: engine, session factory, and table metadata.

The app is deliberately not tied to SQLite. Set ``DATABASE_URL`` to point at
SQLite (the default) or at Postgres, e.g.
``postgresql+psycopg://linkshelf:linkshelf@localhost:5432/linkshelf``.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./linkshelf.db"


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_db_engine(url: str | None = None):
    """Build an engine for ``url`` (or ``DATABASE_URL``).

    SQLite needs ``check_same_thread=False`` so the TestClient's worker thread
    can share the connection pool used by request handlers. Postgres ignores
    the ``connect_args``.
    """
    resolved = url or database_url()
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    return create_engine(resolved, connect_args=connect_args, future=True)


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """FastAPI dependency yielding a request-scoped SQLAlchemy session."""
    with SessionLocal() as session:
        yield session


def init_db(target_engine=None) -> None:
    """Create tables for local development and the starter tests.

    Production environments are expected to use the checked-in migrations in order
    (see README) instead of this helper.
    """
    from app import models  # noqa: F401  (register mappers before create_all)

    Base.metadata.create_all(bind=target_engine or engine)


# Re-exported for tests that prefer importing the session type.
__all__ = ["Base", "Session", "SessionLocal", "create_db_engine", "database_url", "engine", "get_session", "init_db"]
