# Restore retention review v2

Reviewed 2026-10-19 UTC: [actual draft PR #1](https://github.com/zhoum-hub/linkshelf-tutti-demo/pull/1), open and draft, branch `feat/restore-from-trash`, head `340295dcaac10dda66c2ea892263b67e367ad70b`, base `482878a1fc9a53a2a3bb19b00bb21ab7168e484f`.

## Finding

The restore-window behavior is already correct. No application defect requiring a fix was found in this scope. No source or test edits were made in this review. The additional workspace tests already cover the requested regression meaningfully, so no duplicate regression was added.

The PR was inspected through `gh pr view`, `gh pr diff`, and exact-head GitHub contents API reads. Workspace `app/main.py` is byte-for-byte identical to the PR version. Local HEAD is the earlier cursor commit `ce6bd4d`; staged feature work and the pre-existing unstaged retention-test additions were preserved. The reviewed workspace test file differs from the PR: the PR has 16 restore cases with floating-day near-boundary input, while the workspace has 19 cases using precise timedeltas and stronger assertions.

`app/main.py:196-220` performs an atomic SQL UPDATE constrained by bookmark ID, team ID and `deleted_at > utcnow() - timedelta(days=30)`. A nonmatching row returns 404 with `{"detail":"Bookmark not found"}`. Consequently, physical purge timing does not extend eligibility. NULL deletion timestamps, missing IDs and foreign-team rows also cannot match. Eligible same-team URL collisions retain the active-only unique-index rollback/409 behavior; expired rows never reach that conflict.

Trash uses the same strict greater-than cutoff (`app/main.py:170-173`). Purge uses the complementary less-than-or-equal cutoff (`app/purge.py`). The existing opaque v1 cursor format, descending `(created_at, id)` order, strict continuation key, lookahead, tenant filters and legacy active-list rules remain unchanged.

## Exact boundary verification

The workspace tests freeze API time at `2026-10-19T12:00:00Z`. These existing cases all passed against isolated SQLite:

| Age since deletion | Restore | Trash before restore | Purge after restore attempt |
| --- | --- | --- | --- |
| 30 days minus 1 microsecond | 200 | Included; total 1 | 0 rows (restored row survives) |
| Exactly 30 days | 404 | Excluded; total 0 | 1 row |
| 30 days plus 1 microsecond | 404 | Excluded; total 0 | 1 row |
| 31 days; purge delayed | 404 | Excluded; total 0 | 1 row |

`tests/test_restore.py:64-99` asserts that expired records still physically exist with unchanged deletion timestamps when restore returns 404, before purge runs. It verifies exact error body, normal API visibility, affected purge count, physical removal and audit survival. Purge runs in a fresh session, as the CLI does. `tests/test_restore.py:102-114` additionally confirms expired rows with a reused same-team URL return 404 rather than 409, without altering the replacement or audit. Tenant isolation and cursor ties, page changes, foreign-team continuation and input validation tests also passed.

## Actual checks and limits

Used the existing `.venv`, Python 3.13.14, SQLite 3.53.1 and the installed versions pinned in `requirements.txt`. No dependencies were installed or rebuilt. `DATABASE_URL` explicitly pointed to a newly allocated file under `/tmp/linkshelf-review-v2-mni9ls_0/`, avoiding the project database and all PostgreSQL connections. Pytest plugin autoload and cache were disabled.

Actual commands, environment, complete output and exit codes are in `review-window-tests-v2.txt`:

- `.venv/bin/python -m pytest -o addopts= -p no:cacheprovider -vv tests/test_restore.py`: **19 passed**, exit 0.
- `.venv/bin/python -m pytest -o addopts= -p no:cacheprovider -vv`: **69 passed, 1 skipped**, exit 0.
- `git diff --check` and `git diff --cached --check`: exit 0.

Each pytest run emitted the existing Starlette/AnyIO deprecation warning. The skipped case is the PostgreSQL-only cursor migration. SQLite migration preservation/idempotence checks passed. These are functional checks, not concurrent load tests. No PostgreSQL run was attempted in v2; PostgreSQL 17.11 validation belongs to the maintainer using the completed source archive. Historical PostgreSQL success or failure in older notes is not evidence for this run.

The older review records describe a separate SQLite ORM session-synchronization limitation when purge is called with loaded naive timestamps. This review's fresh-session purge checks match the CLI and do not establish correctness for arbitrary loaded-session callers; no purge helper fix is claimed.

## Deliverables and preservation

The original `restore-review-window.md` and `review-window-tests.txt` were moved unchanged to `/tmp/linkshelf-review-working-notes`, outside the source project. Neither is included in `linkshelf-source-v2.zip`. That archive contains the current application, migrations, tests, requirements and project documentation, including the pre-existing strengthened retention tests and these v2 records. It excludes old archives, virtual environments, Git internals, caches, databases and the older review records. Archive validation is recorded in the v2 test log.

No push, merge, commit, remote PR write, dependency change or application/test modification was performed.
