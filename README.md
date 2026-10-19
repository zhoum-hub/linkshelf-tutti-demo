# Linkshelf (starter)

A deliberately small, readable bookmark service used as the starting point for a
collaboration demo. It is a **starter**, not a finished product: later sessions
will add soft delete/trash/restore and cursor pagination on top of this base.

## What is here

- **FastAPI** app with **SQLAlchemy 2.0** ORM models and **Pydantic v2** schemas.
- **SQLite** by default; switch to **Postgres** with `DATABASE_URL`
  (`psycopg` 3 driver is already a dependency).
- CRUD for bookmarks with `id`, `team_id`, `url`, `title`, `created_at`.
- Unique constraint on `(team_id, url)`.
- `GET /bookmarks` with **offset/limit pagination**.
- **Hard delete** that first writes an audit row (`bookmark_audit`).
- Every read and write is scoped to the team in the `X-Team-ID` header.

## Explicit non-goals (for now)

These are intentionally absent and belong to later sessions:

- soft delete, a trash view, or restore endpoints
- cursor pagination
- real authentication / authorization

## Running it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# SQLite (default) — creates ./linkshelf.db on first boot
uvicorn app.main:app --reload

# Postgres
export DATABASE_URL="postgresql+psycopg://linkshelf:linkshelf@localhost:5432/linkshelf"
psql "$DATABASE_URL" -f migrations/001_initial.sql
uvicorn app.main:app --reload
```

The SQLite app creates its tables on startup via SQLAlchemy metadata. For
Postgres, apply the checked-in migration `migrations/001_initial.sql` instead —
it is the canonical schema and keeps the two stores aligned.

Interactive docs: <http://127.0.0.1:8000/docs>.

## Tests

```bash
python -m pytest
```

Tests use an isolated temporary SQLite database, so they never touch
`./linkshelf.db`.

## The `X-Team-ID` header

`X-Team-ID` is a **demo tenant selector, not authentication**. It must be a
positive integer; missing or non-integer values return `422`, and zero or
negative values return `400`. Any caller can claim any team. Do not deploy this
as-is to a multi-tenant production environment without adding real identity and
authorization.

Reads and writes are always filtered by the header:

- `GET /bookmarks` and `GET /bookmarks/{id}` only see the caller's team.
- `PATCH` and `DELETE` return `404` for another team's bookmark, so IDs do not
  leak across teams.

## API

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe, no team header required |
| `GET` | `/bookmarks?offset=0&limit=20` | Paginated list for the header's team |
| `POST` | `/bookmarks` | Create; `409` on duplicate `(team_id, url)` |
| `GET` | `/bookmarks/{id}` | Fetch one, team-scoped |
| `PATCH` | `/bookmarks/{id}` | Partial update of `url` / `title` |
| `DELETE` | `/bookmarks/{id}` | Hard delete + audit row, `204` |

List responses look like:

```json
{
  "items": [
    {"id": 1, "team_id": 1, "url": "https://example.com", "title": "Example",
     "created_at": "2026-10-19T13:05:00Z"}
  ],
  "offset": 0,
  "limit": 20,
  "total": 1
}
```

`created_at`, `deleted_at` are stored and returned as **UTC**, timezone-aware.

`bookmark_audit` intentionally has no foreign key to `bookmarks`: the audit row
must survive the hard delete and remain readable if the bookmark id is ever
reused.

Pagination parameters are validated: `offset >= 0`, `1 <= limit <= 100`.

## Layout

```
app/
  db.py        engine, session dependency, init_db
  models.py    Bookmark + BookmarkAudit ORM models
  schemas.py   request/response models
  main.py      FastAPI routes
migrations/
  001_initial.sql
tests/
  conftest.py, test_bookmarks.py, test_models.py
```
