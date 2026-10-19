# Linkshelf: day-one map

This is a fictional onboarding demo; “3 months / 6 weeks / 2 weeks ago” are simulated labels, not actual elapsed dates. This map reflects the current repository and all three original session conversations, including their continuations.

## Code map

A small synchronous **FastAPI → SQLAlchemy 2.0 → database** service, with Pydantic v2 contracts; there is no frontend.

| Location | Responsibility |
| --- | --- |
| `app/main.py` | Startup, team-header dependency, health and bookmark CRUD/list routes; transaction boundaries and HTTP errors |
| `app/db.py` | `DATABASE_URL`, engine, request-scoped sessions, metadata creation |
| `app/models.py` | `Bookmark`, independent `BookmarkAudit`, UTC clock, partial indexes |
| `app/schemas.py` / `app/pagination.py` | API validation/serialization and opaque cursor encoding/decoding |
| `app/purge.py` | Explicitly team-scoped permanent cleanup CLI |
| `migrations/` | Ordered PostgreSQL schema changes; SQLite upgrade variants for 002/003 |
| `tests/` | API/model, tenant isolation, soft-delete, pagination and migration checks |
| `docs/`, `CONTRIBUTING.md` | Decisions, recovery policy and contributor invariants |

Every bookmark data path must filter by `team_id`; normal reads/updates also require `deleted_at IS NULL`. Cross-team access returns **404**. `X-Team-ID` is a positive-integer **demo tenant selector, not authentication**. Use UTC timestamps via `utcnow()` and keep ORM/schema migrations aligned.

## Run locally

From the repository root, using Python 3.11+:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
unset DATABASE_URL  # use default local SQLite
uvicorn app.main:app --reload
```

Startup creates a fresh `./linkshelf.db`. Try `curl -H 'X-Team-ID: 1' 'http://127.0.0.1:8000/bookmarks?limit=20'`; interactive docs are at `/docs`. These are local-run instructions; no server was started for this map.

For PostgreSQL, provision a database and set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/linkshelf`. Set `POSTGRES_URL` to the same URI **without `+psycopg`**; apply `001_initial.sql`, `002_soft_delete.sql`, then `003_cursor_pagination.sql` with `psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f migrations/<file>`, before starting the app. Back up existing data and stop writers for upgrades. Apply only outstanding migrations; 002 must not be replayed. Existing SQLite needs its 002/003 variants: startup `create_all` does not upgrade tables.

Run `python -m pytest` with `DATABASE_URL` unset for isolated temporary SQLite tests. An explicit database URL is honored and tests **drop/recreate tables**: use only a disposable database.

## Three decisions before touching bookmarks

1. **PostgreSQL in production; SQLite for local development/tests.** About 40 fictional teams with concurrent browser-extension writes drove the choice. Litestream helps replication/recovery but does not remove SQLite’s single-writer constraint. This is an architectural choice, not a measured production-capacity claim. The first conversation’s later user correction explicitly excluded concurrency figures from the decision. Sources: [① Move off SQLite](mention://agent-session/78015a6d-743d-4551-888d-4c0c77e1fe6c?roomId=e1f21be7-6d22-4545-adb4-aeda99212ed5), [ADR 001](docs/adr/001-postgres.md).

2. **Delete retains data; audit and URL reuse must survive.** The fictional loss of 300 bookmarks led to atomic `deleted_at` + audit writes. Uniqueness covers only active `(team_id, url)` pairs, so re-adding creates a new bookmark. Schedule `python -m app.purge --team-id TEAM_ID` daily per configured team: rows deleted at least 30 days ago are eligible; audits survive. Recovery within 30 days needs engineering assistance; trash/restore endpoints remain the next hire’s ticket. After purge, recovery depends on separately operated backups/PITR. Sources: [② Customer lost 300 bookmarks](mention://agent-session/36b46e9a-e3e5-491a-aa9c-7abfda084e39?roomId=e1f21be7-6d22-4545-adb4-aeda99212ed5), [incident and recovery policy](docs/incidents/sep-bulk-delete.md).

3. **Page by stable keys, not shifting positions.** Inserts before an offset repeat rows; deletes before it skip survivors. Follow opaque `next_cursor` until null, ordered by `(created_at DESC, id DESC)` with strict key comparison and both tenant/active filters. The ID resolves timestamp ties. Cursors are not snapshots; `total` is live. Legacy `page`/`offset` remain for one release with sunset **2027-01-19**; mixed pagination forms return 400. Migration 003 supplies the active-row index. Sources: [③ Fix skipped items in pagination](mention://agent-session/ae6eb395-5151-4d01-a494-dc138d02c24c?roomId=e1f21be7-6d22-4545-adb4-aeda99212ed5), [ADR 002](docs/adr/002-cursor-pagination.md).

*Reading guide: `preparation-notes.md` and ADR 001’s original hard-delete text describe the seed, not current behavior. This onboarding pass changed no app code and ran no tests or benchmarks.*
