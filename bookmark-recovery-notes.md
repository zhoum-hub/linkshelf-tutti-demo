# Bookmark recovery notes

`deleted_at` provides a recovery window after accidental deletion. In the [original incident conversation](mention://agent-session/36b46e9a-e3e5-491a-aa9c-7abfda084e39?roomId=e1f21be7-6d22-4545-adb4-aeda99212ed5), a fictional customer lost 300 bookmarks to hard deletion. The requested fix retained rows for 30 days and deliberately deferred trash/restore endpoints. It cannot recover records already hard-deleted. See the [incident policy](docs/incidents/sep-bulk-delete.md).

Today, DELETE atomically sets a UTC timestamp and writes an audit snapshot in one transaction; normal reads and updates hide deleted rows. NULL means active. See [delete and query code](app/main.py) and [models](app/models.py).

Before implementing restore:

- **Handle URL conflicts explicitly.** The unique index covers only active `(team_id, url)` pairs. A user may have re-added the URL as a new bookmark, so clearing the old row’s timestamp can violate uniqueness. Never overwrite that active bookmark. Recommended implementation: rely on the database constraint as the final concurrency check, roll back conflicts, and define the API response. See [models](app/models.py) and [migration 002](migrations/002_soft_delete.sql).
- **Preserve tenant isolation and add proper authorization.** Every lookup/update must include the team; cross-team IDs remain 404. The existing active-only helper cannot find restore candidates. `X-Team-ID` lets callers claim any team and supplies no authentication. The incident explicitly leaves restore authorization to the follow-up. See [route dependencies and helper](app/main.py) and [recovery policy](docs/incidents/sep-bulk-delete.md#retention-purge-job-and-recovery-policy).
- **Respect expiry and concurrent purge.** The [purge job](app/purge.py) permanently removes rows where `deleted_at <= now - 30 days`, scoped to one team. Delayed cleanup does not extend the promised window; after purge, recovery depends on separately operated backups/PITR. Recommended implementation: check eligibility using UTC inside the restore transaction and handle another restore or purge winning the race; a prior read alone is insufficient.
- **Keep the deletion audit.** Audit rows intentionally have no bookmark foreign key and survive purge. They are investigation records, not a supported backup or restore API. Never erase a deletion audit to resolve a conflict. Define repeat-restore behavior and any restore audit event explicitly; neither exists today. See [audit model](app/models.py) and [incident policy](docs/incidents/sep-bulk-delete.md).

The implementation recommendations above are implications of the current constraints, not existing restore behavior. No app code changed; no tests or benchmarks ran for these notes.
