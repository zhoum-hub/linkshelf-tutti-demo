"""Permanently remove one team's bookmarks deleted at least 30 days ago."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Bookmark, utcnow


def purge_deleted(session: Session, team_id: int, *, now: datetime | None = None) -> int:
    """Delete eligible rows in the caller's transaction; never touch audit rows."""
    if team_id <= 0:
        raise ValueError("team_id must be positive")
    now = now or utcnow()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    result = session.execute(
        delete(Bookmark).where(
            Bookmark.team_id == team_id,
            Bookmark.deleted_at.is_not(None),
            Bookmark.deleted_at <= now - timedelta(days=30),
        )
    )
    return result.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", type=int, required=True)
    args = parser.parse_args()
    if args.team_id <= 0:
        parser.error("--team-id must be positive")
    with SessionLocal.begin() as session:
        count = purge_deleted(session, args.team_id)
    print(f"Purged {count} bookmarks for team {args.team_id}")


if __name__ == "__main__":
    main()
