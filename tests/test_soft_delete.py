from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db import Base, engine
from app.models import Bookmark, BookmarkAudit
from app.purge import purge_deleted
from tests.conftest import team
from tests.test_bookmarks import make_bookmark


def test_deleted_rows_are_hidden_and_retained(client, session):
    first = make_bookmark(client)
    other = make_bookmark(client, url="https://other.test")
    path = f"/bookmarks/{first['id']}"
    assert client.delete(path, headers=team(1)).status_code == 204
    assert client.get(path, headers=team(1)).status_code == 404
    assert client.patch(path, json={"title": "Changed"}, headers=team(1)).status_code == 404
    assert client.delete(path, headers=team(1)).status_code == 404
    page = client.get("/bookmarks?limit=1", headers=team(1)).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == other["id"]
    row = session.scalar(select(Bookmark).where(Bookmark.team_id == 1, Bookmark.id == first['id']))
    audit = session.scalars(select(BookmarkAudit).where(BookmarkAudit.team_id == 1)).one()
    assert row.deleted_at == audit.deleted_at
    assert row.title == "Example"
    # Updating an active row to a deleted URL also works.
    assert client.patch(f"/bookmarks/{other['id']}", json={"url": first['url']}, headers=team(1)).status_code == 200


def test_purge_boundary_tenant_isolation_and_audit_survival(client, session):
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    ids = []
    for tenant, age in [(1, 31), (1, 30), (1, 29), (2, 31)]:
        item = make_bookmark(client, team_id=tenant, url=f"https://{tenant}-{age}.test")
        assert client.delete(f"/bookmarks/{item['id']}", headers=team(tenant)).status_code == 204
        row = session.scalar(select(Bookmark).where(Bookmark.team_id == tenant, Bookmark.id == item['id']))
        row.deleted_at = now - timedelta(days=age)
        ids.append(item['id'])
    active = make_bookmark(client, url="https://active.test")
    session.commit()
    assert purge_deleted(session, 1, now=now) == 2
    session.commit()
    assert set(session.scalars(select(Bookmark.id).where(Bookmark.team_id == 1))) == {ids[2], active['id']}
    assert list(session.scalars(select(Bookmark.id).where(Bookmark.team_id == 2))) == [ids[3]]
    assert len(session.scalars(select(BookmarkAudit).where(BookmarkAudit.team_id == 1)).all()) == 3
    assert purge_deleted(session, 1, now=now) == 0
    session.commit()
    with pytest.raises(ValueError):
        purge_deleted(session, 0, now=now)
    with pytest.raises(ValueError):
        purge_deleted(session, 1, now=now.replace(tzinfo=None))


def test_delete_audit_failure_rolls_back(client, monkeypatch, session):
    from app.db import SessionLocal
    item = make_bookmark(client)
    original = SessionLocal.class_.commit

    def fail_audit(db):
        if any(isinstance(row, BookmarkAudit) for row in db.new):
            raise RuntimeError("simulated audit failure")
        return original(db)

    monkeypatch.setattr(SessionLocal.class_, "commit", fail_audit)
    with pytest.raises(RuntimeError, match="audit failure"):
        client.delete(f"/bookmarks/{item['id']}", headers=team(1))
    assert client.get(f"/bookmarks/{item['id']}", headers=team(1)).status_code == 200
    assert session.scalars(select(BookmarkAudit).where(BookmarkAudit.team_id == 1)).all() == []


def test_upgrade_preserves_data_and_changes_uniqueness():
    """Apply real migration files to an old schema, not ORM create_all."""
    root = Path(__file__).resolve().parents[1]
    if engine.dialect.name == "sqlite":
        connection = sqlite3.connect(":memory:")
        connection.executescript('''
            CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL,
            url TEXT NOT NULL, title VARCHAR(200) NOT NULL, created_at DATETIME NOT NULL,
            CONSTRAINT uq_bookmarks_team_id_url UNIQUE(team_id,url));
            CREATE TABLE bookmark_audit (id INTEGER PRIMARY KEY, team_id INTEGER, title TEXT);
            INSERT INTO bookmarks VALUES (7,1,'https://old.test','Old','2026-09-01');
            INSERT INTO bookmark_audit VALUES (9,1,'Audit');
        ''')
        connection.executescript((root / 'migrations/002_soft_delete_sqlite.sql').read_text())
        assert connection.execute('SELECT id,title,deleted_at FROM bookmarks WHERE team_id=1').fetchone() == (7, 'Old', None)
        connection.execute("UPDATE bookmarks SET deleted_at='2026-09-02' WHERE team_id=1")
        connection.execute("INSERT INTO bookmarks VALUES (8,1,'https://old.test','New','2026-09-03',NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO bookmarks VALUES (9,1,'https://old.test','Dup','2026-09-03',NULL)")
        assert connection.execute('SELECT title FROM bookmark_audit WHERE team_id=1').fetchone() == ('Audit',)
        connection.close()
    else:
        Base.metadata.drop_all(engine)
        with engine.connect() as conn:
            conn.exec_driver_sql((root / 'migrations/001_initial.sql').read_text())
            conn.exec_driver_sql("INSERT INTO bookmarks(team_id,url,title) VALUES(1,'https://old.test','Old')")
            conn.exec_driver_sql("INSERT INTO bookmark_audit(bookmark_id,team_id,url,title) VALUES(1,1,'https://old.test','Audit')")
            conn.commit()
            conn.exec_driver_sql((root / 'migrations/002_soft_delete.sql').read_text())
            assert conn.execute(text('SELECT title,deleted_at FROM bookmarks WHERE team_id=1')).one() == ('Old', None)
            conn.exec_driver_sql('UPDATE bookmarks SET deleted_at=now() WHERE team_id=1')
            conn.exec_driver_sql("INSERT INTO bookmarks(team_id,url,title) VALUES(1,'https://old.test','New')")
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql("INSERT INTO bookmarks(team_id,url,title) VALUES(1,'https://old.test','Dup')")
            conn.rollback()
            assert conn.execute(text('SELECT title FROM bookmark_audit WHERE team_id=1')).scalar_one() == 'Audit'
