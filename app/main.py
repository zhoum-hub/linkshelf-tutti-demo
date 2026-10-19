"""Linkshelf starter API.

Every bookmark read and write is scoped to the team supplied in the
``X-Team-ID`` header. That header is a demo tenant selector, NOT authentication:
there is no user identity, token check, or permission model in this starter.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.models import Bookmark, BookmarkAudit
from app.schemas import BookmarkCreate, BookmarkOut, BookmarkPage, BookmarkUpdate


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Convenience for local runs (SQLite or an empty Postgres database).
    # Deployments should apply migrations/001_initial.sql instead.
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
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.team_id == team_id)
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
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> BookmarkPage:
    total = session.scalar(
        select(func.count()).select_from(Bookmark).where(Bookmark.team_id == team_id)
    )
    rows = session.scalars(
        select(Bookmark)
        .where(Bookmark.team_id == team_id)
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return BookmarkPage(
        items=[BookmarkOut.model_validate(row) for row in rows],
        offset=offset,
        limit=limit,
        total=total or 0,
    )


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
    session.refresh(bookmark)
    return bookmark


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
    bookmark = _bookmark_or_404(session, bookmark_id, team_id)
    if payload.url is not None:
        bookmark.url = payload.url
    if payload.title is not None:
        bookmark.title = payload.title
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A bookmark with this URL already exists for the team"
        )
    session.refresh(bookmark)
    return bookmark


@app.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(
    bookmark_id: int,
    team_id: int = Depends(current_team_id),
    session: Session = Depends(get_session),
) -> Response:
    bookmark = _bookmark_or_404(session, bookmark_id, team_id)
    session.add(
        BookmarkAudit(
            bookmark_id=bookmark.id,
            team_id=bookmark.team_id,
            url=bookmark.url,
            title=bookmark.title,
            action="delete",
        )
    )
    session.delete(bookmark)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
