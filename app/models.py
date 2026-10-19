"""SQLAlchemy 2.0 ORM models for Linkshelf."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for every row we write."""
    return datetime.now(timezone.utc)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("team_id", "url", name="uq_bookmarks_team_id_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class BookmarkAudit(Base):
    """One row per hard delete, preserving what was removed and for which team."""

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
