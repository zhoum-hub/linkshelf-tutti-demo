"""Trash/restore contract, including historical retention and URL constraints."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Bookmark, BookmarkAudit
from app.purge import purge_deleted
from tests.conftest import team

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.main.utcnow", lambda: NOW)


def deleted(client, session, *, tenant=1, url="https://restore.test", age=1):
    row = client.post("/bookmarks", headers=team(tenant), json={"url": url, "title": "Saved"}).json()
    assert client.delete(f"/bookmarks/{row['id']}", headers=team(tenant)).status_code == 204
    stored = session.get(Bookmark, row["id"])
    stored.deleted_at = NOW - timedelta(days=age)
    session.commit()
    return row


def test_restore_preserves_identity_and_audit_and_can_delete_again(client, session):
    row = deleted(client, session)
    response = client.post(f"/bookmarks/{row['id']}/restore", headers=team(1))
    assert response.status_code == 200
    assert response.json() == row
    assert client.get(f"/bookmarks/{row['id']}", headers=team(1)).status_code == 200
    assert client.get("/trash", headers=team(1)).json()["total"] == 0
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 404
    assert len(session.scalars(select(BookmarkAudit)).all()) == 1
    assert client.delete(f"/bookmarks/{row['id']}", headers=team(1)).status_code == 204
    assert len(session.scalars(select(BookmarkAudit)).all()) == 2


def test_conflict_rolls_back_then_restore_after_conflicting_row_deleted(client, session):
    row = deleted(client, session)
    active = client.post("/bookmarks", headers=team(1), json={"url": row["url"], "title": "Replacement"}).json()
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 409
    session.expire_all()
    assert session.get(Bookmark, row["id"]).deleted_at is not None
    assert client.get(f"/bookmarks/{active['id']}", headers=team(1)).json() == active
    assert len(session.scalars(select(BookmarkAudit)).all()) == 1
    client.delete(f"/bookmarks/{active['id']}", headers=team(1))
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 200
    assert client.post(f"/bookmarks/{active['id']}/restore", headers=team(1)).status_code == 409


def test_tenant_boundary_and_cross_team_url(client, session):
    row = deleted(client, session, tenant=2)
    assert client.get("/trash", headers=team(1)).json()["items"] == []
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 404
    client.post("/bookmarks", headers=team(1), json={"url": row["url"], "title": "Other team"})
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(2)).status_code == 200
    assert client.post("/bookmarks/999999/restore", headers=team(1)).status_code == 404


@pytest.mark.parametrize("age,eligible", [(30, False), (31, False), (29.99999, True)])
def test_retention_boundary_and_purge(client, session, age, eligible):
    row = deleted(client, session, age=age)
    assert client.get("/trash", headers=team(1)).json()["total"] == int(eligible)
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == (200 if eligible else 404)
    purge_deleted(session, 1, now=NOW)
    session.commit()
    assert client.post(f"/bookmarks/{row['id']}/restore", headers=team(1)).status_code == 404
    assert len(session.scalars(select(BookmarkAudit)).all()) == 1


def test_trash_cursor_ties_and_changes_between_pages(client, session):
    rows = [deleted(client, session, url=f"https://{i}.test") for i in range(5)]
    for row in rows:
        session.get(Bookmark, row["id"]).created_at = NOW
    session.commit()
    first = client.get("/trash?limit=2", headers=team(1)).json()
    assert [r["id"] for r in first["items"]] == [rows[4]["id"], rows[3]["id"]]
    assert first["total"] == 5 and first["next_cursor"]
    client.post(f"/bookmarks/{rows[4]['id']}/restore", headers=team(1))
    deleted(client, session, url="https://new.test")
    second = client.get("/trash", params={"limit": 2, "cursor": first["next_cursor"]}, headers=team(1)).json()
    assert [r["id"] for r in second["items"]] == [rows[2]["id"], rows[1]["id"]]
    last = client.get("/trash", params={"limit": 2, "cursor": second["next_cursor"]}, headers=team(1)).json()
    assert [r["id"] for r in last["items"]] == [rows[0]["id"]]
    assert last["next_cursor"] is None
    foreign = client.get("/trash", params={"cursor": first["next_cursor"]}, headers=team(2)).json()
    assert foreign["items"] == [] and foreign["total"] == 0


@pytest.mark.parametrize("query,code", [("cursor=bad", 400), ("limit=0", 422), ("limit=101", 422), ("offset=0", 400), ("page=1", 400)])
def test_trash_validation(client, query, code):
    assert client.get(f"/trash?{query}", headers=team(1)).status_code == code


@pytest.mark.parametrize("headers,code", [({}, 422), (team(0), 400), (team(-1), 400), ({"X-Team-ID": "bad"}, 422)])
def test_new_routes_require_valid_team(client, headers, code):
    assert client.get("/trash", headers=headers).status_code == code
    assert client.post("/bookmarks/1/restore", headers=headers).status_code == code
