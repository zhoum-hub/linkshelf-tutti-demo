"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BookmarkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=200)


class BookmarkUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    title: str | None = Field(default=None, min_length=1, max_length=200)


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    url: str
    title: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        """SQLite returns naive datetimes; the stored value is always UTC.

        Attaching UTC here keeps the API contract identical on SQLite and
        Postgres, where the column comes back timezone-aware.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class BookmarkPage(BaseModel):
    items: list[BookmarkOut]
    limit: int
    total: int
    # Cursor for the next page; ``None`` when this is the last page.
    next_cursor: str | None = None
    # ``"cursor"`` for the supported mode, ``"legacy-offset"`` when the caller
    # used the deprecated page/offset window.
    pagination: str = "cursor"
    # ``True`` when the legacy page/offset form of this page was requested.
    offset_deprecated: bool = False
    # Legacy fields, kept for one release. They echo the request and are never
    # used to build a cursor.
    page: int | None = None
    offset: int | None = None
