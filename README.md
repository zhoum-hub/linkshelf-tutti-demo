# Linkshelf (starter)

A deliberately small, readable bookmark service used as the starting point for a
collaboration demo. It is a **starter**, not a finished product: later sessions
will add trash/restore on top of this base.

## What is here

- **FastAPI** app with **SQLAlchemy 2.0** ORM models and **Pydantic v2** schemas.
- **SQLite** by default for local development; **Postgres** is the documented
  production database (see [ADR 001](docs/adr/001-postgres.md)). Switch with
  `DATABASE_URL` (`psycopg` 3 driver is already a dependency).
- CRUD for bookmarks with `id`, `team_id`, `url`, `title`, `created_at`.
- Unique partial index on active `(team_id, url)` pairs.
- `GET /bookmarks` with **cursor pagination** ordered by `created_at`, `id`.
  The legacy `page`/`offset` parameters still work for one release.
- **Soft delete** with a transactional audit row and a tenant-scoped 30-day purge job.
- Every read and write is scoped to the team in the `X-Team-ID` header.

## Explicit non-goals (for now)

These are intentionally absent and belong to later sessions:

- a trash view or restore endpoints
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
psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f migrations/001_initial.sql
psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f migrations/002_soft_delete.sql
uvicorn app.main:app --reload
```

The SQLite app creates its tables on startup via SQLAlchemy metadata. For
Postgres, apply the checked-in migrations in order with a native `POSTGRES_URL`
(without the SQLAlchemy `+psycopg` suffix). Existing databases need migration 002
(and 003 for the cursor index); startup does not upgrade tables. See the
[incident and recovery policy](docs/incidents/sep-bulk-delete.md)
for deployment, SQLite upgrades, and daily purge scheduling.

**Production uses Postgres.** SQLite stays the zero-setup option for local
development and tests. The rationale is recorded in
[docs/adr/001-postgres.md](docs/adr/001-postgres.md).

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
| `GET` | `/bookmarks?limit=20` | Cursor-paginated list for the header's team |
| `GET` | `/bookmarks?limit=20&cursor=<next_cursor>` | Next page |
| `GET` | `/bookmarks?offset=0&limit=20` | Deprecated numeric window (one release) |
| `POST` | `/bookmarks` | Create; `409` on duplicate active `(team_id, url)` |
| `GET` | `/bookmarks/{id}` | Fetch one, team-scoped |
| `PATCH` | `/bookmarks/{id}` | Partial update of `url` / `title` |
| `DELETE` | `/bookmarks/{id}` | Soft delete + audit row, `204` |

List responses look like:

```json
{
  "items": [
    {"id": 1, "team_id": 1, "url": "https://example.com", "title": "Example",
     "created_at": "2026-10-19T13:05:00Z"}
  ],
  "limit": 20,
  "total": 1,
  "next_cursor": null,
  "pagination": "cursor",
  "offset_deprecated": false,
  "page": null,
  "offset": null
}
```

Pass `next_cursor` back as `cursor` to continue; `null` means the last page.
Cursors are opaque and ordered by `(created_at DESC, id DESC)`, so inserts and
deletes between pages do not repeat or skip surviving rows. The cursor is not a
snapshot. `created_at` is not unique; the `id` tiebreaker keeps the order total.

Timestamps are stored in **UTC**. API `created_at` is timezone-aware; the internal
`deleted_at` is not added to the public response.

`bookmark_audit` intentionally has no foreign key to `bookmarks`: the audit row
must survive permanent purge and remain readable if the bookmark id is ever
reused.

Pagination parameters are validated: `page >= 1`, `offset >= 0`,
`1 <= limit <= 100`. `cursor` combined with `page` or `offset`, and `page`
combined with `offset`, return `400`. Legacy `page`/`offset` responses carry
`Deprecation`, `Sunset`, and `Link` headers. See
[ADR 002](docs/adr/002-cursor-pagination.md) for the failure modes and the
deprecation window.

## Layout

```
app/
  db.py           engine, session dependency, init_db
  models.py       Bookmark + BookmarkAudit ORM models
  schemas.py      request/response models
  pagination.py   opaque cursor encode/decode
  main.py         FastAPI routes
  purge.py        python -m app.purge --team-id TEAM_ID
migrations/
  001_initial.sql
  002_soft_delete.sql
  002_soft_delete_sqlite.sql
  003_cursor_pagination.sql
  003_cursor_pagination_sqlite.sql
docs/
  adr/001-postgres.md           production database decision
  adr/002-cursor-pagination.md  cursor pagination decision
tests/
  conftest.py, test_bookmarks.py, test_models.py,
  test_pagination.py, test_soft_delete.py
```

### Trash and restore (LIN-212)

`GET /trash` returns the team's recoverable deleted bookmarks in the existing
`BookmarkPage` shape. Use `limit` (1–100, default 20) and `cursor`; ordering is
`created_at DESC, id DESC`, with the existing opaque v1 cursor and limit+1
lookahead. This new endpoint rejects `page` and `offset` with 400; the active
list's legacy compatibility remains unchanged. Total is a live count, not a
snapshot. Restores, purges and new deletions can change membership during paging;
restart from the first page to refresh. Cursors are values, not tenant credentials.

`POST /bookmarks/{id}/restore` returns 200 with the original bookmark, preserving
its ID, creation timestamp, URL and title. It clears `deleted_at` only for the
selected team and only while deletion age is strictly less than 30 days.
Trash uses that same eligibility rule; expired rows are omitted even if purge
has not run. Missing, purged, expired, foreign-team and already-active IDs all
return the same 404. Repeating a successful restore therefore returns 404.

The active-only `(team_id, url)` unique index remains authoritative. A conflicting
active URL returns 409 and rolls back the restore; no bookmark is overwritten.
Delete or edit the conflicting active bookmark before retrying. Deleted copies
and copies in other teams do not conflict. Conditional SQL updates and the
unique index arbitrate concurrent writes; no pre-read ownership check is used.
Deletion audit snapshots remain unchanged; restoration adds no audit event.
No schema change or migration is needed. `X-Team-ID` is still only a demo tenant
selector: real authentication and authorization remain outside this starter.

Verification and packaging for this change are recorded in `test-output.txt`.
