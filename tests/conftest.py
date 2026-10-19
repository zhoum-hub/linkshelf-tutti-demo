"""Shared pytest fixtures.

Each test module gets an isolated in-file SQLite database so tests never touch
the developer's ``linkshelf.db`` and never depend on one another.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Must be set before importing the app package: app.db builds its engine at
# import time.
_TMP_DIR = tempfile.mkdtemp(prefix="linkshelf-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_TMP_DIR}/test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    """Drop and recreate every table before each test."""
    Base.metadata.drop_all(bind=engine)
    init_db(target_engine=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session():
    with SessionLocal() as db:
        yield db


def set_created_at(session, bookmark_id: int, created_at) -> None:
    """Pin a bookmark's created_at so ordering tests are deterministic.

    ``utcnow`` commonly returns the same microsecond for several rows created
    in a tight loop, which makes a keyset test pass for the wrong reason.
    """
    from app.models import Bookmark  # local import keeps conftest import-light

    row = session.get(Bookmark, bookmark_id)
    assert row is not None
    row.created_at = created_at
    session.commit()


def team(team_id: int) -> dict[str, str]:
    return {"X-Team-ID": str(team_id)}
