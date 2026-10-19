Adds cursor-paginated `GET /trash` and atomic `POST /bookmarks/{bookmark_id}/restore` for retained bookmarks. Restoring preserves identity and creation time. If the URL was re-added as an active bookmark in the same team, restore returns 409 without overwriting either bookmark. Missing, purged, already-active, foreign-team and expired bookmarks return 404; expiration starts at exactly 30 days, even when purge has not run. Trash uses the same strict retention cutoff, tenant scope and stable opaque v1 cursor ordering as the existing bookmark list.

Successful restores append an `action="restore"` audit snapshot in the same transaction as clearing `deleted_at`. Rejected and conflicting requests add no success event. Audit-write failures roll back both writes and remain server errors; only active-URL uniqueness conflicts translate to 409. Original delete audits and subsequent restore history survive purge. The existing audit `deleted_at` column records each event's UTC time; no migration is needed for restore auditing.

`openapi.yaml` is generated from the actual app and verified against `/openapi.json`. Both new endpoints document their error responses and required tenant header. README setup now defines the native PostgreSQL URL and applies migrations 001, 002 and 003 in order. `X-Team-ID` remains a demo tenant selector, not authentication.

LIN-212 is a fictional demo ticket with no external Linear issue.


Validation:

- Python 3.12.14, final delivered source: **SQLite 80 passed / 1 PostgreSQL-only skip; PostgreSQL 17.11 81 passed**. One existing Starlette/AnyIO dependency warning on each backend.
- **12 independent API/database scenarios passed** against an existing PostgreSQL database upgraded through 001→002→003, including two simultaneous restores producing one success and one audit event, exact retention boundaries, conflict rollback, tenant isolation, purge audit survival and exact exported/live OpenAPI equality.
- [Independent verification receipt](https://github.com/zhoum-hub/linkshelf-tutti-demo/blob/feat/restore-from-trash/verification/final-results.md). Final archive SHA-256: `6ed89ae97cade92a0eae93e6f28fad832854d5decf6ee58421aed6e15e2b3a7d`.

Fictional onboarding example in the [Tutti room](https://tutti.sh/platform/room/e1f21be7-6d22-4545-adb4-aeda99212ed5).
