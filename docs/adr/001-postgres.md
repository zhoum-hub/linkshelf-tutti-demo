# ADR 001: Postgres as the production database

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** Linkshelf engineering
- **Scope:** Storage engine for production; development remains flexible

## Context

Linkshelf is a small team-scoped bookmark service. The intended usage is
roughly **40 teams** with **frequent, concurrent writes driven by a browser
extension**, alongside normal reads. Every write is a short transaction; the
delete path writes a `bookmark_audit` row in the same transaction as the hard
delete. The application already supports both backends through `DATABASE_URL`
and uses SQLAlchemy 2.0 against either.

SQLite has served the starter well: it requires no server, creates the schema
automatically, and keeps tests fast. The question is whether that convenience
is the right foundation for the production write pattern, or whether it should
remain a development-only option.

## Decision

**Postgres is the documented production database.** SQLite remains supported
as a development and test option.

- Production deployments use `postgresql+psycopg://...` and apply
  `migrations/001_initial.sql`.
- SQLite (`sqlite+pysqlite:///./linkshelf.db`) stays the zero-setup default for
  local work and the test suite.
- No application feature depends on one backend; the API contract is identical
  on both.

## Why Postgres

The deciding factor is the write pattern, not raw speed:

1. **Concurrent writers do not contend on a single write lock.** SQLite allows
   one writer at a time; a burst of extension writes serialises on the database
   lock and surfaces as `database is locked` under contention unless callers
   add retries and WAL tuning. Postgres handles concurrent short transactions
   natively, which matches how the extension writes.
2. **Operational headroom is built in.** Connection pooling, read replicas,
   online backups, and point-in-time recovery are standard with Postgres. With
   SQLite, durability and backup are a workflow the team must assemble and
   operate itself.
3. **Schema and types match the domain.** `TIMESTAMPTZ` and `BIGSERIAL` are
   native, and the checked-in migration is already the canonical schema. The
   unique `(team_id, url)` constraint and audit table behave the same, but
   without SQLite's affinities and datatype caveats.
4. **It matches the intended deployment shape.** A service that many teams and
   clients write to concurrently is a client/server workload; SQLite is
   optimised for embedded, largely local access.

SQLite with Litestream is a credible way to add continuous replication to a
single-writer deployment. It does not change SQLite's single-writer
concurrency model, so it addresses backup and recovery but not write
contention. For the stated workload, that leaves the core constraint in place.

## Consequences

**Positive**

- Concurrent extension writes no longer funnel through one writer.
- Standard operations: pooling, backups, replication, monitoring.
- One documented production target; the migration file is authoritative.

**Negative / costs**

- A database server must be provisioned, secured, and backed up.
- Local setup needs either a running Postgres or the SQLite path.
- Contributors must keep `models.py` and `migrations/001_initial.sql` in sync
  (already a project rule).

**Neutral**

- Tests continue to run on an isolated SQLite database by default; they can
  also be pointed at Postgres with `DATABASE_URL`.

## Verification

Functional checks already recorded for this decision:

- SQLite: `python -m pytest` → **17 passed, 1 warning**
- Postgres 16.2: same suite with `DATABASE_URL` pointing at a disposable local
  cluster → **17 passed, 1 warning**

The single warning is from Starlette's TestClient (`anyio.abc.BlockingPortal`
deprecation), outside this project's code. See
`postgres-decision-tests.txt` for the exact commands and output.

**No production capacity or performance claim is made here.** These are
functional compatibility results only; no benchmark was run and no throughput
comparison is asserted. Capacity planning for the real deployment should be
done against the actual hosting environment before launch.

## Out of scope

This decision does not add soft delete, trash/restore endpoints, or cursor
pagination. Those remain planned follow-ups. It also does not change the
`X-Team-ID` demo header, which is still **not authentication**.

## Follow-up: soft deletion

The September incident follow-up implements soft deletion and a 30-day
tenant-scoped purge, without changing the production database decision. Apply
migration 002 after 001. The original hard-delete and uniqueness descriptions
above record the decision's baseline; current uniqueness applies only to active
rows. Trash and restore endpoints remain deferred. See
[the incident policy](../incidents/sep-bulk-delete.md) and
`soft-delete-test-output.txt` for current migration and functional verification.
