# September bulk-delete incident (fictional)

## Impact and cause

A fictional customer accidentally bulk-deleted 300 bookmarks. At the time,
DELETE physically removed each bookmark and wrote a separate audit snapshot.
We could not restore the bookmarks. This scenario does not establish that a
usable backup existed, nor that an audit snapshot was a supported recovery path.

The deletion API had no retention window. A valid accidental request therefore
caused immediate loss of the primary records. This change retains deleted
bookmarks for 30 days; it cannot bring back records already hard-deleted.

## Storage and index change

`bookmarks.deleted_at` is nullable and UTC. NULL means active. DELETE atomically
marks an active, team-scoped row and writes its audit snapshot with the same
timestamp in one transaction. A repeated DELETE returns 404 without another
audit. List totals, pages, single reads, and updates exclude deleted rows.
Updates and deletes include both the team and active-row predicate in their
SQL, preventing a concurrent update from modifying an already deleted row.

The old `uq_bookmarks_team_id_url` UNIQUE constraint covered every row. Keeping
it would prevent a customer from re-adding a deleted URL. Migration 002 replaces
it with `uq_bookmarks_team_id_url_active`, a unique partial index on
`(team_id, url) WHERE deleted_at IS NULL`. Active duplicates still return 409;
different teams and retained deleted copies can share a URL. Re-adding creates
a new bookmark; it does not restore the old one. A `(team_id, deleted_at)` index
supports tenant-scoped retention cleanup. Audit records have no bookmark foreign
key and are never deleted by the purge job.

## Deployment and migration

Back up the database and stop writers before applying the migration, then
restart with the new code. Schema and application changes must deploy together.
The PostgreSQL migration takes table locks and builds indexes transactionally;
no online migration or performance claim is made.

For PostgreSQL, use a native PostgreSQL connection URI (without `+psycopg`):

```bash
psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f migrations/001_initial.sql
psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f migrations/002_soft_delete.sql
```

Existing deployments already at 001 apply only 002. For a fresh SQLite database,
ORM startup creates the current schema. For an existing SQLite database, stop
writers and apply `migrations/002_soft_delete_sqlite.sql` once with sqlite3's
`executescript` or the sqlite3 CLI. It rebuilds the bookmark table to remove the
old table-level UNIQUE constraint, preserving IDs, data, and the audit table.
`create_all` does not upgrade existing databases. Migrations are one-time,
ordered changes; do not replay 002. Reverting requires a planned data migration
because retained deleted copies can violate the original UNIQUE constraint.

## Retention, purge job, and recovery policy

Run this job daily for **each explicitly configured team**, using the same
DATABASE_URL as the application. There is no unscoped all-teams mode and no
query to discover tenants. Operations must add new teams to the schedule.
Example cron entry for team 7, with DATABASE_URL supplied securely by the job's
environment:

```cron
0 3 * * * cd /workspace/linkshelf && .venv/bin/python -m app.purge --team-id 7
```

At the job's UTC start time, rows with `deleted_at <= now - 30 days` become
eligible for permanent removal. Active rows, newer deleted rows, other teams,
and all audit records remain. Each invocation commits one transaction, prints
the removed count, and fails visibly on errors. Re-running is safe; a failed
transaction rolls back. Monitor failures and retry them. Daily scheduling means
physical deletion can occur after the exact 30-day point; failed jobs extend
storage time, not the promised recovery window.

During the first 30 days, retained rows provide an engineering-assisted recovery
opportunity. There is **no trash view or restore endpoint in this change**.
Escalate promptly with the team and bookmark IDs. An authorized engineer must
verify ownership, retention age, and active URL conflicts before any separately
reviewed, tenant-scoped recovery procedure. Never overwrite an active bookmark
or erase its deletion audit to resolve a conflict. This ticket does not supply
a restore implementation or promise automatic restoration.

At or after 30 days, recovery is not guaranteed even if a delayed purge has left
the row present. After purge, recovery depends on independently operated and
tested backups/PITR, subject to their retention and access policies; this change
does not establish that service. Audit snapshots survive purge for investigation
but are not a supported restore API or backup. Audit retention remains unchanged;
this job imposes no audit expiry policy.

The next hire's ticket owns trash and restore semantics, including URL conflicts
and authorization. `X-Team-ID` remains a demo tenant selector, not authentication.

## Verification

`soft-delete-test-output.txt` records actual commands and results on SQLite and
a disposable real PostgreSQL 16.2 cluster. Checks cover API behavior, tenant
isolation, transaction rollback, retention boundaries, audit survival, and
migration from an old schema. Only functional and migration checks were run;
there were no load benchmarks, dependency installs, or environment rebuilds.
