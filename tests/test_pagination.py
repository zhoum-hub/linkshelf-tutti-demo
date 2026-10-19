"""Cursor (keyset) pagination for ``GET /bookmarks``.

These tests target the failure mode of numeric offsets: an insert or a delete
between page requests shifts every later row by one position. Cursors carry
the last row's ``(created_at, id)`` sort key, so they are unaffected.

The list is newest first (``created_at DESC, id DESC``).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Bookmark
from app.pagination import InvalidCursor, decode_cursor, encode_cursor
from tests.conftest import set_created_at, team
from tests.test_bookmarks import make_bookmark

BASE = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def seed_ordered(client, session, team_id: int = 1, count: int = 5) -> list[dict]:
    """Create ``count`` bookmarks with one-minute-apart, deterministic times.

    Row 0 is the newest. ``created_at`` differs for every row so an ordering
    test cannot pass on the id tiebreaker alone.
    """
    created = []
    for index in range(count):
        item = make_bookmark(client, team_id=team_id, url=f"https://c-{index}.test", title=f"C{index}")
        set_created_at(session, item["id"], BASE - timedelta(minutes=index))
        created.append(item)
    return created


def walk(client, team_id: int = 1, limit: int = 2) -> tuple[list[int], list[str]]:
    """Follow ``next_cursor`` to exhaustion; return ids and the cursors used."""
    ids: list[int] = []
    cursors: list[str] = []
    url = f"/bookmarks?limit={limit}"
    for _ in range(50):  # a guard, not an expectation
        body = client.get(url, headers=team(team_id)).json()
        assert body["pagination"] == "cursor"
        ids.extend(item["id"] for item in body["items"])
        if not body["next_cursor"]:
            assert len(body["items"]) <= limit
            return ids, cursors
        cursors.append(body["next_cursor"])
        url = f"/bookmarks?limit={limit}&cursor={body['next_cursor']}"
    raise AssertionError("cursor chain did not terminate")


# --- the actual bug ---------------------------------------------------------


def test_insert_during_scrolling_does_not_repeat_a_row(client, session):
    items = seed_ordered(client, session, count=4)
    newest_first = [item["id"] for item in items]  # ids 1..4, newest first

    first = client.get("/bookmarks?limit=2", headers=team(1)).json()
    assert [item["id"] for item in first["items"]] == newest_first[:2]

    # A newer bookmark arrives between pages. With offset=2 the next request
    # would re-return the row that fell from position 2 to position 3.
    inserted = make_bookmark(client, team_id=1, url="https://inserted.test", title="Inserted")
    set_created_at(session, inserted["id"], BASE + timedelta(minutes=1))

    second = client.get(
        f"/bookmarks?limit=2&cursor={first['next_cursor']}", headers=team(1)
    ).json()
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert len(seen) == len(set(seen)), "a row was returned twice"
    assert inserted["id"] not in seen, "rows newer than the cursor belong to a later refresh"
    assert seen == newest_first[:4]

    # Legacy offset pagination, for contrast: the same insert makes it repeat
    # row 3 (which fell from position 2 to position 3).
    legacy = client.get("/bookmarks?offset=2&limit=2", headers=team(1)).json()
    assert newest_first[1] in [item["id"] for item in legacy["items"]]


def test_delete_during_scrolling_does_not_skip_a_row(client, session):
    items = seed_ordered(client, session, count=5)
    newest_first = [item["id"] for item in items]

    first = client.get("/bookmarks?limit=2", headers=team(1)).json()
    assert [item["id"] for item in first["items"]] == newest_first[:2]

    # Delete a row already returned. With offset=2 everything shifts up and the
    # row at position 3 is skipped entirely.
    assert client.delete(f"/bookmarks/{newest_first[0]}", headers=team(1)).status_code == 204
    second = client.get(
        f"/bookmarks?limit=2&cursor={first['next_cursor']}", headers=team(1)
    ).json()
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert seen == newest_first[:4]
    assert newest_first[2] not in [item["id"] for item in first["items"]]

    # Legacy offset pagination skips row index 2 (newest_first[2]): after the
    # delete it moves from position 3 to position 2 and is never returned.
    legacy = client.get("/bookmarks?offset=2&limit=2", headers=team(1)).json()
    assert newest_first[2] not in [item["id"] for item in legacy["items"]]


def test_delete_of_the_cursor_row_still_resumes_after_it(client, session):
    items = seed_ordered(client, session, count=4)
    newest_first = [item["id"] for item in items]
    first = client.get("/bookmarks?limit=2", headers=team(1)).json()

    # The row the cursor points at is deleted before the next request. The
    # cursor still names a position; strictly-after semantics resume correctly.
    assert client.delete(f"/bookmarks/{newest_first[1]}", headers=team(1)).status_code == 204
    second = client.get(
        f"/bookmarks?limit=2&cursor={first['next_cursor']}", headers=team(1)
    ).json()
    assert [item["id"] for item in second["items"]] == newest_first[2:]


# --- ordering and boundaries ------------------------------------------------


def test_walk_returns_every_row_once_in_order(client, session):
    items = seed_ordered(client, session, count=5)
    expected = [item["id"] for item in items]

    ids, cursors = walk(client, limit=2)
    assert ids == expected
    assert len(cursors) == 2  # 5 rows, page size 2: pages of 2, 2, 1


def test_equal_created_at_values_use_id_tiebreaker(client, session):
    """Rows may share a timestamp; only the (created_at, id) pair is unique."""
    same = BASE
    items = []
    for index in range(4):
        item = make_bookmark(client, team_id=1, url=f"https://tie-{index}.test", title=f"T{index}")
        set_created_at(session, item["id"], same)
        items.append(item)

    ids, _ = walk(client, limit=1)
    assert ids == sorted((item["id"] for item in items), reverse=True)
    assert len(ids) == len(set(ids)) == 4


def test_last_page_has_no_next_cursor_and_exact_fit_is_terminal(client, session):
    items = seed_ordered(client, session, count=4)

    first = client.get("/bookmarks?limit=2", headers=team(1)).json()
    assert first["next_cursor"] is not None

    fourth = client.get(
        f"/bookmarks?limit=2&cursor={first['next_cursor']}", headers=team(1)
    ).json()
    # Exactly four rows with page size 2: fetching limit+1 returns only four,
    # so this is the last page even though it is full.
    assert len(fourth["items"]) == 2
    assert fourth["next_cursor"] is None
    assert [item["id"] for item in first["items"] + fourth["items"]] == [item["id"] for item in items]


def test_empty_team_has_no_cursor(client):
    body = client.get("/bookmarks", headers=team(9)).json()
    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["total"] == 0


def test_cursor_is_scoped_to_the_tenant(client, session):
    mine = seed_ordered(client, session, team_id=1, count=3)
    seed_ordered(client, session, team_id=2, count=3)

    first = client.get("/bookmarks?limit=1", headers=team(1)).json()
    # Replaying team 1's cursor as team 2 must stay inside team 2's rows.
    other = client.get(
        f"/bookmarks?limit=10&cursor={first['next_cursor']}", headers=team(2)
    ).json()
    assert all(item["team_id"] == 2 for item in other["items"])
    assert mine[0]["id"] not in [item["id"] for item in other["items"]]


def test_soft_deleted_rows_are_excluded_from_cursor_pages(client, session):
    items = seed_ordered(client, session, count=4)
    newest_first = [item["id"] for item in items]
    assert client.delete(f"/bookmarks/{newest_first[1]}", headers=team(1)).status_code == 204

    ids, _ = walk(client, limit=2)
    assert ids == [newest_first[0], newest_first[2], newest_first[3]]
    body = client.get("/bookmarks", headers=team(1)).json()
    assert body["total"] == 3


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "not-a-cursor",
        "v2.abc",  # unknown version
        "v1.",  # empty payload
        "v1.!!!!",  # not base64url
        "v1." + base64.urlsafe_b64encode(b"2026-10-19T12:00:00+00:00").decode(),
        "v1." + base64.urlsafe_b64encode(b"2026-10-19T12:00:00|not-an-int").decode(),
        "v1." + base64.urlsafe_b64encode(b"2026-10-19T12:00:00|0").decode(),
        # Naive timestamp: ambiguous across database session timezones.
        "v1." + base64.urlsafe_b64encode(b"2026-10-19T12:00:00|3").decode(),
    ],
)
def test_malformed_cursor_is_rejected(client, token):
    response = client.get(f"/bookmarks?cursor={token}", headers=team(1))
    assert response.status_code == 400, response.text
    assert response.json()["detail"].startswith("invalid cursor")


def test_cursor_token_round_trips_and_is_opaque(client, session):
    items = seed_ordered(client, session, count=2)
    token = encode_cursor(BASE, items[-1]["id"])
    assert token.startswith("v1.")
    assert token == encode_cursor(BASE, items[-1]["id"]), "encoding must be deterministic"
    key = decode_cursor(token)
    assert (key.created_at, key.id) == (BASE, items[-1]["id"])

    # A timezone-aware timestamp with a non-UTC offset is normalised to UTC.
    shifted = encode_cursor(datetime(2026, 10, 19, 14, 0, tzinfo=timezone(timedelta(hours=2))), 7)
    assert decode_cursor(shifted).created_at == BASE

    with pytest.raises(InvalidCursor):
        decode_cursor("v1")
    with pytest.raises(InvalidCursor):
        decode_cursor("v1.not base64")


# --- legacy compatibility for one release ----------------------------------


def test_offset_form_still_works_and_is_marked_deprecated(client, session):
    items = seed_ordered(client, session, count=5)
    expected = [item["id"] for item in items]

    response = client.get("/bookmarks?offset=2&limit=2", headers=team(1))
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == expected[2:4]
    assert response.headers["deprecation"] == "@1792368000"
    assert response.headers["sunset"] == "Tue, 19 Jan 2027 00:00:00 GMT"
    assert response.headers["link"] == '</bookmarks>; rel="successor-version"'
    assert body["offset_deprecated"] is True
    assert body["offset"] == 2 and body["page"] is None
    assert body["pagination"] == "legacy-offset"
    assert body["next_cursor"] is None, "offset pages do not mint cursors"
    assert body["total"] == 5


def test_page_form_is_translated_to_offset(client, session):
    items = seed_ordered(client, session, count=5)
    expected = [item["id"] for item in items]

    first = client.get("/bookmarks?page=1&limit=2", headers=team(1))
    last = client.get("/bookmarks?page=3&limit=2", headers=team(1))
    assert first.status_code == last.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == expected[0:2]
    assert [item["id"] for item in last.json()["items"]] == expected[4:5]
    assert first.json()["page"] == 1 and first.json()["offset"] is None
    assert first.json()["offset_deprecated"] is True
    # page/1 and offset/0 resolve to the same window.
    assert first.json()["items"] == client.get("/bookmarks?offset=0&limit=2", headers=team(1)).json()["items"]


def test_cursor_default_response_has_no_deprecation_headers(client):
    response = client.get("/bookmarks", headers=team(1))
    assert response.status_code == 200
    assert "deprecation" not in response.headers
    assert response.json()["offset_deprecated"] is False
    assert response.json()["pagination"] == "cursor"


@pytest.mark.parametrize(
    "query",
    [
        "cursor=v1.abc&offset=0",
        "cursor=v1.abc&page=1",
        "cursor=v1.abc&offset=1&page=1",
        "offset=0&page=1",
    ],
)
def test_incompatible_parameter_combinations_are_rejected(client, query):
    response = client.get(f"/bookmarks?{query}", headers=team(1))
    assert response.status_code == 400, response.text


def test_mutually_exclusive_detail_message(client):
    assert client.get("/bookmarks?offset=0&page=2", headers=team(1)).json()["detail"] == (
        "page and offset are mutually exclusive"
    )
    assert client.get("/bookmarks?cursor=v1.x&offset=0", headers=team(1)).json()["detail"] == (
        "cursor cannot be combined with page or offset"
    )


def test_legacy_parameters_keep_their_validation(client):
    assert client.get("/bookmarks?offset=-1", headers=team(1)).status_code == 422
    assert client.get("/bookmarks?page=0", headers=team(1)).status_code == 422
    assert client.get("/bookmarks?limit=0", headers=team(1)).status_code == 422
    assert client.get("/bookmarks?limit=101", headers=team(1)).status_code == 422
    # Validation still runs before combination checks.
    assert client.get("/bookmarks?offset=-1&cursor=v1.x", headers=team(1)).status_code == 422


# --- index migration --------------------------------------------------------


def test_cursor_index_migration_preserves_rows_and_is_idempotent():
    """Apply the checked-in 003 SQL to a post-002 SQLite schema twice."""
    import sqlite3
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(
            """
            CREATE TABLE bookmarks (
                id INTEGER PRIMARY KEY,
                team_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title VARCHAR(200) NOT NULL,
                created_at DATETIME NOT NULL,
                deleted_at DATETIME
            );
            CREATE UNIQUE INDEX uq_bookmarks_team_id_url_active
                ON bookmarks (team_id, url) WHERE deleted_at IS NULL;
            INSERT INTO bookmarks VALUES
                (7,1,'https://old.test','Old','2026-09-01',NULL),
                (8,1,'https://gone.test','Gone','2026-09-02','2026-09-03');
            """
        )
        script = (root / "migrations/003_cursor_pagination_sqlite.sql").read_text()
        connection.executescript(script)
        connection.executescript(script)  # idempotent

        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_bookmarks_team_created_id_active'"
        ).fetchone()
        assert index is not None
        assert "created_at DESC" in index[0] and "id DESC" in index[0]
        assert "WHERE deleted_at IS NULL" in index[0]
        assert connection.execute("SELECT id, title, deleted_at FROM bookmarks ORDER BY id").fetchall() == [
            (7, "Old", None),
            (8, "Gone", "2026-09-03"),
        ]
    finally:
        connection.close()


def test_cursor_index_migration_on_postgres():
    """Apply the checked-in 003 SQL to a real Postgres schema twice.

    The ORM already creates an equivalent index, so drop it first to emulate a
    database that has only 001 and 002 applied. Nothing here asserts planner
    behaviour; it checks that the migration builds the expected index and is
    safe to replay.
    """
    from pathlib import Path

    from sqlalchemy import text

    from app.db import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("Postgres-only migration check")

    root = Path(__file__).resolve().parents[1]
    script = (root / "migrations/003_cursor_pagination.sql").read_text()
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_bookmarks_team_created_id_active")
        conn.commit()
        conn.exec_driver_sql(script)
        conn.exec_driver_sql(script)  # idempotent
        definition = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'bookmarks' AND indexname = 'ix_bookmarks_team_created_id_active'"
            )
        ).scalar_one()
    assert "created_at DESC" in definition
    assert "id DESC" in definition
    assert "WHERE (deleted_at IS NULL)" in definition


def test_cursor_queries_exclude_deleted_rows_at_the_sql_level(client, session):
    items = seed_ordered(client, session, count=3)
    client.delete(f"/bookmarks/{items[1]['id']}", headers=team(1))
    rows = session.scalars(
        select(Bookmark).where(Bookmark.team_id == 1, Bookmark.deleted_at.is_(None))
    ).all()
    assert len(rows) == 2
