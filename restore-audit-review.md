# Restore audit review

Reviewed and implemented 2026-10-19 UTC in the shared Linkshelf workspace.

## Inspection and outcome

Before this change, `restore_bookmark` conditionally cleared `deleted_at` and committed without inserting an audit row. README explicitly said restoration added no audit event; the existing successful-restore test asserted that only the delete event remained. Restore audit logging was therefore missing. The existing 30-day eligibility behavior was already correct and was preserved.

The initial new regression run against the unmodified implementation produced **4 failed, 6 passed**: success had no restore event; two audit-failure cases incorrectly succeeded because there was no audit insertion; an unrelated UPDATE integrity failure was incorrectly translated to 409. Full before/after output is preserved in `restore-audit-tests.txt`. These failures demonstrate the missing behavior rather than claiming it was already implemented.

## Changes

`app/main.py` now appends a `BookmarkAudit` snapshot with `action="restore"`, bookmark ID, team ID, URL and title after the eligible atomic UPDATE, committing both writes once. A single UTC clock value supplies the retention cutoff and restore event time. The existing audit column named `deleted_at` stores the event timestamp for both actions; deletion snapshots are never modified. The audit model documentation explains this historical column name. No schema change or migration is necessary: existing columns already support both action values.

The UPDATE retains the ID, tenant and strict `deleted_at > now - 30 days` predicates and `RETURNING`. Only its active-URL uniqueness error becomes 409: PostgreSQL recognition requires SQLSTATE 23505 and the exact `uq_bookmarks_team_id_url_active` constraint name; SQLite requires its UNIQUE error code and the exact `(bookmarks.team_id, bookmarks.url)` column error. Other integrity errors propagate. Audit insertion and commit have a separate rollback-and-reraise handler; even audit integrity errors remain server errors, never URL conflicts. No new commit or audit event is attempted for rejected restores.

Updated README, CONTRIBUTING, recovery notes and the existing restore tests to document/assert the new audit contract. Added `tests/test_restore_audit.py` with API-level regressions for:

- One successful restore snapshot, with correct team, identity, URL, title and frozen UTC event time; repeat restore adds nothing.
- Missing, foreign-team, active, expired, invalid-team and URL-conflicting requests producing no success event.
- A real audit INSERT NOT NULL violation and an injected runtime failure each yielding HTTP 500, retaining the deleted bookmark and original delete audit; a subsequent retry succeeds exactly once.
- An unrelated UPDATE integrity error yielding HTTP 500 rather than 409.
- Failure after both UPDATE and audit INSERT have flushed, before commit, rolling back both writes.
- Delete, restore and subsequent delete history surviving physical purge, including the original delete audit.

The exact 30-day boundary tests (one microsecond before, exactly at, and one microsecond after), tenant tests, cursor tests and existing delete/purge regressions remain passing. Existing pre-review workspace changes and staged work were preserved; no push, merge or commit was performed.

## Actual validation

Used the existing `.venv` dependencies, Python 3.13.14 and SQLite 3.53.1. No packages were installed. `DATABASE_URL` explicitly targets a newly allocated temporary SQLite database; pytest plugin autoload and cache are disabled. Actual environment, commands, full results and exit codes are in `restore-audit-tests.txt`.

The final workspace command was:

```text
.venv/bin/python -m pytest -o addopts= -p no:cacheprovider -vv
```

Result: **80 passed, 1 skipped, 1 warning**, exit 0. The independently extracted source archive also passed **80 passed, 1 skipped, 1 warning**, exit 0, using a separate isolated SQLite database and the same existing dependencies. Both staged and unstaged `git diff --check` passed. The skip is the PostgreSQL-only cursor migration; the warning is the existing Starlette/AnyIO deprecation warning. A targeted intermediate run passed all 29 cases then present, before adding the final commit-failure test.

PostgreSQL was not run by the Agent. The maintainer will independently validate PostgreSQL 17.11 from `linkshelf-restore-audit-source.zip`. PostgreSQL constraint recognition is implemented, but SQLite success is not claimed as PostgreSQL verification. Functional tests do not establish concurrent load performance.

## Delivery

`restore-audit-review.md` and `restore-audit-tests.txt` are published together with the completed source archive. The archive includes current application source, migrations, all tests (including the additional retention and restore-audit tests), requirements, project documentation and these audit records. Old source archives, caches, databases and prior generated review records are excluded. The older `restore-review-window.md` and `review-window-tests.txt` remain preserved outside the source project at `/tmp/linkshelf-review-working-notes`.
