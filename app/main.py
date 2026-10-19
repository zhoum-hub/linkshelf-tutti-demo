"""Linkshelf starter API.

Every bookmark read and write is scoped to the team supplied in the
``X-Team-ID`` header. That header is a demo tenant selector, NOT authentication:
there is no user identity, token check, or permission model in this starter.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.models import Bookmark, BookmarkAudit, utcnow
from app.pagination import InvalidCursor, decode_cursor, encode_cursor
from app.schemas import BookmarkCreate, BookmarkOut, BookmarkPage, BookmarkUpdate


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Convenience for local runs (SQLite or an empty Postgres database).
    # Deployments should apply the checked-in migrations in order instead.
    init_db()
    yield


app = FastAPI(
    title="Linkshelf",
    version="0.1.0",
    description="Minimal team-scoped bookmark service. X-Team-ID is a demo tenant header, not auth.",
    lifespan=lifespan,
)


def current_team_id(x_team_id: int = Header(..., alias="X-Team-ID")) -> int:
    """Resolve the demo tenant. It must be a positive integer.

    Missing or non-integer values are rejected by FastAPI (422); zero and
    negative values are rejected here (400).
    """
    if x_team_id <= 0:
        raise HTTPException(status_code=400, detail="X-Team-ID must be a positive integer")
    return x_team_id


def _bookmark_or_404(session: Session, bookmark_id: int, team_id: int) -> Bookmark:
    bookmark = session.scalar(
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.team_id == team_id, Bookmark.deleted_at.is_(None))
    )
    if bookmark is None:
        # Also masks bookmarks owned by other teams so existence does not leak.
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return bookmark


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/bookmarks", response_model=BookmarkPage)
def list_bookmarks(
    response: Response,
    cursor: str | None = Query(None, description="Opaque cursor from a previous response's next_cursor"),
    limit: int = Query(20, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> BookmarkPage:
    """List a team's active bookmarks, newest first.

    Cursor pagination is the supported form: pass ``next_cursor`` from the
    previous response. ``page`` and ``offset`` remain accepted for one release
    as deprecated aliases for a numeric skip; they are translated into an
    offset, never into a cursor. Mixing ``cursor`` with either is rejected
    because the two window definitions are incompatible.
    """
    if cursor is not None and (page is not None or offset is not None):
        raise HTTPException(
            status_code=400,
            detail="cursor cannot be combined with page or offset",
        )
    if page is not None and offset is not None:
        raise HTTPException(
            status_code=400,
            detail="page and offset are mutually exclusive",
        )

    # Legacy numeric window for one release. page=N (1-based) and offset=K are
    # two spellings of the same skip; the response echoes whichever was sent.
    skip: int | None = None
    if page is not None:
        skip = (page - 1) * limit
    elif offset is not None:
        skip = offset

    base = select(Bookmark).where(Bookmark.team_id == team_id, Bookmark.deleted_at.is_(None))
    ordered = base.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
    if skip is not None:
        # Deprecated numeric window. It is deliberately not converted into a
        # cursor: the client asked for a position, and the response says so.
        rows = session.scalars(ordered.offset(skip).limit(limit)).all()
        next_cursor = None
    else:
        if cursor is not None:
            try:
                key = decode_cursor(cursor)
            except InvalidCursor as exc:
                raise HTTPException(status_code=400, detail=f"invalid cursor: {exc}") from None
            # Strictly after the last row of the previous page. Comparing the
            # tuple lexicographically keeps rows with an identical timestamp
            # ordered by id, so equal created_at values cannot repeat or vanish.
            ordered = ordered.where(
                or_(
                    Bookmark.created_at < key.created_at,
                    and_(Bookmark.created_at == key.created_at, Bookmark.id < key.id),
                )
            )
        # One extra row tells us whether another page exists without a count.
        rows = session.scalars(ordered.limit(limit + 1)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

    total = session.scalar(
        select(func.count()).select_from(Bookmark).where(
            Bookmark.team_id == team_id, Bookmark.deleted_at.is_(None)
        )
    )

    if skip is not None:
        # RFC 9745 Deprecation (Structured Fields date) and RFC 8594 Sunset
        # (HTTP-date). The numeric window is deprecated as of 2026-10-19 and
        # will be removed after 2027-01-19.
        response.headers["Deprecation"] = "@1792368000"
        response.headers["Sunset"] = "Tue, 19 Jan 2027 00:00:00 GMT"
        response.headers["Link"] = '</bookmarks>; rel="successor-version"'

    return BookmarkPage(
        items=[BookmarkOut.model_validate(row) for row in rows],
        limit=limit,
        total=total or 0,
        next_cursor=next_cursor,
        # Report which window the request actually used. "cursor" is the
        # supported mode; "legacy-offset" marks the deprecation shim.
        pagination="legacy-offset" if skip is not None else "cursor",
        offset_deprecated=skip is not None,
        page=page,
        offset=offset,
    )


@app.get("/trash", response_model=BookmarkPage)
def list_trash(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    page: int | None = Query(None, ge=1),
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> BookmarkPage:
    """List recoverable rows using the same stable keys as the active list."""
    if offset is not None or page is not None:
        raise HTTPException(status_code=400, detail="trash supports cursor pagination only")
    base = select(Bookmark).where(
        Bookmark.team_id == team_id,
        Bookmark.deleted_at > utcnow() - timedelta(days=30),
    )
    ordered = base.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
    if cursor is not None:
        try:
            key = decode_cursor(cursor)
        except InvalidCursor as exc:
            raise HTTPException(status_code=400, detail=f"invalid cursor: {exc}") from None
        ordered = ordered.where(or_(
            Bookmark.created_at < key.created_at,
            and_(Bookmark.created_at == key.created_at, Bookmark.id < key.id),
        ))
    rows = session.scalars(ordered.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return BookmarkPage(
        items=[BookmarkOut.model_validate(row) for row in rows],
        limit=limit,
        total=session.scalar(select(func.count()).select_from(base.subquery())) or 0,
        next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if has_more else None,
    )


def _is_active_url_conflict(exc: IntegrityError) -> bool:
    """Recognize only the active bookmark URL index on supported databases."""
    original = exc.orig
    if getattr(original, "sqlstate", None) == "23505":
        return (
            getattr(getattr(original, "diag", None), "constraint_name", None)
            == "uq_bookmarks_team_id_url_active"
        )
    return (
        isinstance(original, sqlite3.IntegrityError)
        and getattr(original, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and str(original) == "UNIQUE constraint failed: bookmarks.team_id, bookmarks.url"
    )


@app.post("/bookmarks/{bookmark_id}/restore", response_model=BookmarkOut)
def restore_bookmark(
    bookmark_id: int,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Bookmark:
    restored_at = utcnow()
    # Claim an eligible row atomically. Only this UPDATE can produce a URL
    # conflict; audit and commit failures must remain server errors.
    try:
        bookmark = session.execute(
            update(Bookmark)
            .where(Bookmark.id == bookmark_id, Bookmark.team_id == team_id,
                   Bookmark.deleted_at > restored_at - timedelta(days=30))
            .values(deleted_at=None)
            .returning(Bookmark)
        ).scalar_one_or_none()
    except IntegrityError as exc:
        session.rollback()
        if _is_active_url_conflict(exc):
            raise HTTPException(
                status_code=409, detail="A bookmark with this URL already exists for the team"
            ) from None
        raise
    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    try:
        session.add(
            BookmarkAudit(
                bookmark_id=bookmark.id,
                team_id=bookmark.team_id,
                url=bookmark.url,
                title=bookmark.title,
                action="restore",
                deleted_at=restored_at,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return bookmark


@app.post("/bookmarks", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
def create_bookmark(
    payload: BookmarkCreate,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Bookmark:
    bookmark = Bookmark(team_id=team_id, url=payload.url, title=payload.title)
    session.add(bookmark)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A bookmark with this URL already exists for the team"
        )
    return _bookmark_or_404(session, bookmark.id, team_id)


@app.get("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
def get_bookmark(
    bookmark_id: int,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Bookmark:
    return _bookmark_or_404(session, bookmark_id, team_id)


@app.patch("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
def update_bookmark(
    bookmark_id: int,
    payload: BookmarkUpdate,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Bookmark:
    values = payload.model_dump(exclude_none=True)
    if not values:
        return _bookmark_or_404(session, bookmark_id, team_id)
    try:
        bookmark = session.execute(
            update(Bookmark)
            .where(Bookmark.id == bookmark_id, Bookmark.team_id == team_id,
                   Bookmark.deleted_at.is_(None))
            .values(**values)
            .returning(Bookmark)
        ).scalar_one_or_none()
        if bookmark is None:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A bookmark with this URL already exists for the team"
        )
    return bookmark


@app.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(
    bookmark_id: int,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Response:
    deleted_at = utcnow()
    # The conditional UPDATE claims the active row atomically, including under
    # concurrent DELETE requests. Only the winning transaction writes an audit.
    bookmark = session.execute(
        update(Bookmark)
        .where(Bookmark.id == bookmark_id, Bookmark.team_id == team_id,
               Bookmark.deleted_at.is_(None))
        .values(deleted_at=deleted_at)
        .returning(Bookmark)
    ).scalar_one_or_none()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    session.add(
        BookmarkAudit(
            bookmark_id=bookmark.id,
            team_id=bookmark.team_id,
            url=bookmark.url,
            title=bookmark.title,
            action="delete",
            deleted_at=deleted_at,
        )
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
