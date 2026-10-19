# Independent final verification

Source: Linkshelf final archive, SHA-256 `6ed89ae97cade92a0eae93e6f28fad832854d5decf6ee58421aed6e15e2b3a7d`.

Maintainer verification on October 20, 2026 (Asia/Shanghai), Python 3.12.14. These checks were run independently from the Agent's SQLite checks, using only disposable local databases.

| Backend | Actual result |
|---|---|
| SQLite | 80 passed, 1 skipped, 1 warning in 1.34s |
| PostgreSQL 17.11 | 81 passed, 1 warning in 2.49s |

Command for each backend: set `DATABASE_URL` to the corresponding disposable database and run `.venv/bin/pytest -o addopts= -q`. The single warning is the existing Starlette/AnyIO deprecated alias. The SQLite skip is the PostgreSQL-only migration test.

The additional API integration check used an existing PostgreSQL database upgraded through migrations 001 → 002 → 003, separate from the database recreated by pytest. It exercised real SQL transactions and the application via FastAPI's TestClient, including two concurrent restore requests.

```text
PostgreSQL 17.11 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit
PASS: API restore works against existing rows migrated through 001→002→003
PASS: successful restore preserves identity/data and writes one restore audit
PASS: repeated restore returns 404 without a duplicate success event
PASS: re-added URL returns 409 and rolls back row and audit changes
PASS: cross-team and missing IDs both return 404
PASS: expired unpurged rows return 404 and are omitted from trash
PASS: exactly 30 days is expired; one microsecond inside the window restores
PASS: trash cursor pages preserve timestamp ties, isolate tenants and terminate
PASS: team-scoped purge preserves audit history and leaves other teams intact
PASS: two simultaneous restores produce one success and one audit event
PASS: exported OpenAPI equals the live application and documents restore errors
PASS: README setup includes migration 003
```

Demo data and tenant IDs only. No external/customer database was contacted. `X-Team-ID` remains a demo selector rather than authentication.

