"""SQLAlchemy 2.0 ORM models for Linkshelf."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for every row we write."""
    return datetime.now(timezone.utc)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        Index("uq_bookmarks_team_id_url_active", "team_id", "url", unique=True,
              sqlite_where=text("deleted_at IS NULL"), postgresql_where=text("deleted_at IS NULL")),
        Index("ix_bookmarks_team_deleted_at", "team_id", "deleted_at"),
        # Serves the cursor list: equality on team_id, then the descending
        # (created_at, id) sort key. Partial so deleted rows stay out of it.
        Index(
            "ix_bookmarks_team_created_id_active",
            "team_id",
            desc("created_at"),
            desc("id"),
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class BookmarkAudit(Base):
    """Independent delete/restore snapshots that survive bookmark purge.

    The historical ``deleted_at`` column stores the event time for both actions.
    """

    __tablename__ = "bookmark_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bookmark_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="delete")
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
