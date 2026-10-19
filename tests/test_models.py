"""Model-level checks that the audit table enforces nothing surprising."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Bookmark, BookmarkAudit


def test_bookmark_defaults_to_utc(session):
    bookmark = Bookmark(team_id=1, url="https://clock.test", title="Clock")
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)

    created = bookmark.created_at
    if created.tzinfo is None:  # SQLite drops the offset but not the UTC value
        created = created.replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - created).total_seconds()) < 60


def test_audit_rows_are_independent_of_bookmarks(session):
    session.add(
        BookmarkAudit(bookmark_id=42, team_id=1, url="https://a.test", title="A", action="delete")
    )
    session.commit()

    audit = session.scalars(select(BookmarkAudit).where(BookmarkAudit.team_id == 1)).one()
    assert audit.bookmark_id == 42
    assert session.scalars(select(Bookmark).where(Bookmark.team_id == 1)).all() == []
