"""API behaviour checks for the Linkshelf starter."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import BookmarkAudit
from tests.conftest import team


def make_bookmark(client, team_id: int = 1, url: str = "https://example.com", title: str = "Example"):
    response = client.post("/bookmarks", json={"url": url, "title": title}, headers=team(team_id))
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_fetch_bookmark(client):
    created = make_bookmark(client, team_id=7)

    assert created["team_id"] == 7
    assert created["url"] == "https://example.com"
    assert created["title"] == "Example"
    assert isinstance(created["id"], int) and created["id"] > 0

    # created_at is UTC and serialised with an explicit offset.
    parsed = datetime.fromisoformat(created["created_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)

    fetched = client.get(f"/bookmarks/{created['id']}", headers=team(7))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_missing_team_header_is_rejected(client):
    assert client.get("/bookmarks").status_code == 422
    assert client.post("/bookmarks", json={"url": "https://a.test", "title": "A"}).status_code == 422


def test_non_positive_team_header_is_rejected(client):
    assert client.get("/bookmarks", headers=team(0)).status_code == 400
    assert client.get("/bookmarks", headers=team(-3)).status_code == 400


def test_non_integer_team_header_is_rejected(client):
    response = client.get("/bookmarks", headers={"X-Team-ID": "not-a-number"})
    assert response.status_code == 422


def test_reads_are_scoped_to_team(client):
    mine = make_bookmark(client, team_id=1, url="https://mine.test", title="Mine")
    theirs = make_bookmark(client, team_id=2, url="https://theirs.test", title="Theirs")

    listing = client.get("/bookmarks", headers=team(1))
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [mine["id"]]

    # Another team's bookmark is indistinguishable from a missing one.
    assert client.get(f"/bookmarks/{theirs['id']}", headers=team(1)).status_code == 404
    assert client.patch(
        f"/bookmarks/{theirs['id']}", json={"title": "hacked"}, headers=team(1)
    ).status_code == 404
    assert client.delete(f"/bookmarks/{theirs['id']}", headers=team(1)).status_code == 404

    # ...and it is still there for its owner.
    assert client.get(f"/bookmarks/{theirs['id']}", headers=team(2)).status_code == 200


def test_unique_url_per_team(client):
    make_bookmark(client, team_id=1, url="https://dup.test", title="First")

    duplicate = client.post(
        "/bookmarks", json={"url": "https://dup.test", "title": "Second"}, headers=team(1)
    )
    assert duplicate.status_code == 409

    # The same URL is allowed for a different team.
    other_team = client.post(
        "/bookmarks", json={"url": "https://dup.test", "title": "Second"}, headers=team(2)
    )
    assert other_team.status_code == 201


def test_update_bookmark(client):
    created = make_bookmark(client, team_id=1, url="https://old.test", title="Old")

    response = client.patch(
        f"/bookmarks/{created['id']}", json={"title": "New"}, headers=team(1)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New"
    assert body["url"] == "https://old.test"
    assert body["created_at"] == created["created_at"]


def test_update_to_existing_url_is_conflict(client):
    first = make_bookmark(client, team_id=1, url="https://one.test", title="One")
    make_bookmark(client, team_id=1, url="https://two.test", title="Two")

    response = client.patch(
        f"/bookmarks/{first['id']}", json={"url": "https://two.test"}, headers=team(1)
    )
    assert response.status_code == 409


def test_offset_pagination(client):
    for index in range(5):
        make_bookmark(client, team_id=1, url=f"https://site-{index}.test", title=f"Site {index}")

    first_page = client.get("/bookmarks?offset=0&limit=2", headers=team(1)).json()
    second_page = client.get("/bookmarks?offset=2&limit=2", headers=team(1)).json()
    last_page = client.get("/bookmarks?offset=4&limit=2", headers=team(1)).json()

    assert first_page["total"] == second_page["total"] == last_page["total"] == 5
    assert (first_page["offset"], first_page["limit"]) == (0, 2)
    assert len(first_page["items"]) == len(second_page["items"]) == 2
    assert len(last_page["items"]) == 1

    ids = [item["id"] for item in first_page["items"] + second_page["items"] + last_page["items"]]
    assert len(set(ids)) == 5, "pages must not overlap"

    beyond = client.get("/bookmarks?offset=99&limit=2", headers=team(1)).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5


def test_pagination_validation(client):
    assert client.get("/bookmarks?offset=-1", headers=team(1)).status_code == 422
    assert client.get("/bookmarks?limit=0", headers=team(1)).status_code == 422
    assert client.get("/bookmarks?limit=101", headers=team(1)).status_code == 422


def test_soft_delete_writes_audit_row(client, session):
    created = make_bookmark(client, team_id=3, url="https://gone.test", title="Gone")

    response = client.delete(f"/bookmarks/{created['id']}", headers=team(3))
    assert response.status_code == 204
    assert response.content == b""

    assert client.get(f"/bookmarks/{created['id']}", headers=team(3)).status_code == 404
    assert client.get("/bookmarks", headers=team(3)).json()["total"] == 0

    audits = session.scalars(select(BookmarkAudit).where(BookmarkAudit.team_id == 3)).all()
    assert len(audits) == 1
    audit = audits[0]
    assert audit.bookmark_id == created["id"]
    assert audit.team_id == 3
    assert audit.url == "https://gone.test"
    assert audit.title == "Gone"
    assert audit.action == "delete"
    assert audit.deleted_at is not None


def test_delete_does_not_remove_other_teams_rows(client):
    mine = make_bookmark(client, team_id=1, url="https://safe.test", title="Safe")
    make_bookmark(client, team_id=2, url="https://mine-only.test", title="Other")

    assert client.delete(f"/bookmarks/{mine['id']}", headers=team(2)).status_code == 404
    assert client.get(f"/bookmarks/{mine['id']}", headers=team(1)).status_code == 200


def test_validation_errors(client):
    assert client.post("/bookmarks", json={"url": "", "title": "x"}, headers=team(1)).status_code == 422
    assert client.post("/bookmarks", json={"url": "https://x.test", "title": ""}, headers=team(1)).status_code == 422
    assert client.post("/bookmarks", json={"title": "x"}, headers=team(1)).status_code == 422


def test_deleted_url_can_be_reused(client):
    first = make_bookmark(client, team_id=1, url="https://reuse.test", title="First")
    assert client.delete(f"/bookmarks/{first['id']}", headers=team(1)).status_code == 204

    second = client.post(
        "/bookmarks", json={"url": "https://reuse.test", "title": "Second"}, headers=team(1)
    )
    assert second.status_code == 201
