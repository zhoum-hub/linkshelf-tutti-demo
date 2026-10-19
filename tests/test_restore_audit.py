"""Restore audit events commit with the bookmark or not at all."""
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.main import app
from app.models import Bookmark, BookmarkAudit
from app.purge import purge_deleted
from tests.conftest import team
from tests.test_restore import NOW, clock, deleted


def audits(db):
    return db.scalars(select(BookmarkAudit).order_by(BookmarkAudit.id)).all()


def test_success_snapshot_and_both_events_survive_purge(client, session):
    row = deleted(client, session, tenant=2)
    original = audits(session)[0]
    original_values = (original.id, original.action, original.deleted_at, original.url, original.title)
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(2)).status_code == 200
    session.expire_all()
    events = audits(session)
    assert [e.action for e in events] == ["delete", "restore"]
    restored = events[1]
    assert (restored.bookmark_id, restored.team_id, restored.url, restored.title) == (row['id'], 2, row['url'], row['title'])
    assert restored.deleted_at.replace(tzinfo=timezone.utc) == NOW
    assert (events[0].id, events[0].action, events[0].deleted_at, events[0].url, events[0].title) == original_values
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(2)).status_code == 404
    assert len(audits(session)) == 2
    assert client.delete(f"/bookmarks/{row['id']}", headers=team(2)).status_code == 204
    session.rollback()
    with SessionLocal.begin() as db:
        assert purge_deleted(db, 2, now=NOW + timedelta(days=30)) == 1
    session.expire_all()
    assert session.get(Bookmark, row['id']) is None
    assert [e.action for e in audits(session)] == ["delete", "restore", "delete"]
    assert audits(session)[0].id == original_values[0]


@pytest.mark.parametrize('rejection', ['missing', 'foreign', 'active', 'expired', 'conflict', 'invalid-team'])
def test_rejected_restore_never_adds_success_event(client, session, rejection):
    row = deleted(client, session, age=30 if rejection == 'expired' else 1)
    headers = team(1)
    target = row['id']
    expected = 404
    if rejection == 'missing':
        target = 999999
    elif rejection == 'foreign':
        headers = team(2)
    elif rejection == 'active':
        target = client.post('/bookmarks', headers=headers, json={'url': 'https://active.test', 'title': 'Active'}).json()['id']
    elif rejection == 'conflict':
        assert client.post('/bookmarks', headers=headers, json={'url': row['url'], 'title': 'Replacement'}).status_code == 201
        expected = 409
    elif rejection == 'invalid-team':
        headers = team(0)
        expected = 400
    assert client.post(f'/bookmarks/{target}/restore', headers=headers).status_code == expected
    session.expire_all()
    assert [e.action for e in audits(session)] == ['delete']
    assert session.get(Bookmark, row['id']).deleted_at is not None


@pytest.mark.parametrize('failure', ['integrity', 'runtime'])
def test_audit_insert_failure_is_server_error_and_rolls_back(client, session, failure):
    row = deleted(client, session)
    session.refresh(session.get(Bookmark, row['id']))
    original_deleted_at = session.get(Bookmark, row['id']).deleted_at
    # Fail the audit INSERT after the conditional UPDATE has executed.
    def fail_audit(mapper, connection, target):
        if target.action == 'restore':
            if failure == 'integrity':
                # A real NOT NULL violation, using the existing database schema.
                target.title = None
            else:
                raise RuntimeError('simulated restore audit failure')
    event.listen(BookmarkAudit, 'before_insert', fail_audit)
    try:
        with TestClient(app, raise_server_exceptions=False) as errors:
            response = errors.post(f"/bookmarks/{row['id']}/restore", headers=team(1))
        assert response.status_code == 500, response.text
    finally:
        event.remove(BookmarkAudit, 'before_insert', fail_audit)
    # Inspect committed state through an independent session.
    with SessionLocal() as db:
        assert db.get(Bookmark, row['id']).deleted_at == original_deleted_at
        assert [e.action for e in audits(db)] == ['delete']
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 200
    session.expire_all()
    assert [e.action for e in audits(session)] == ['delete', 'restore']


def test_unrelated_update_integrity_error_is_not_url_conflict(client, session):
    row = deleted(client, session)
    def fail_update(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('UPDATE BOOKMARKS'):
            raise IntegrityError(statement, parameters, RuntimeError('unrelated update integrity failure'))
    event.listen(engine, 'before_cursor_execute', fail_update)
    try:
        with TestClient(app, raise_server_exceptions=False) as errors:
            assert errors.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 500
    finally:
        event.remove(engine, 'before_cursor_execute', fail_update)
    with SessionLocal() as db:
        assert db.get(Bookmark, row['id']).deleted_at is not None
        assert [e.action for e in audits(db)] == ['delete']


def test_commit_failure_after_audit_flush_rolls_back_both_writes(client, session, monkeypatch):
    row = deleted(client, session)
    original_commit = SessionLocal.class_.commit
    flushed = []

    def fail_commit(db):
        if any(isinstance(item, BookmarkAudit) and item.action == 'restore' for item in db.new):
            db.flush()  # Both UPDATE and INSERT reached the database transaction.
            flushed.append(True)
            raise RuntimeError('simulated commit failure after audit flush')
        return original_commit(db)

    with monkeypatch.context() as patch:
        patch.setattr(SessionLocal.class_, 'commit', fail_commit)
        with TestClient(app, raise_server_exceptions=False) as errors:
            assert errors.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 500
    assert flushed == [True]
    with SessionLocal() as db:
        assert db.get(Bookmark, row['id']).deleted_at is not None
        assert [e.action for e in audits(db)] == ['delete']
