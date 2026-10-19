# Linkshelf seed — preparation notes

Prepared: 2026-10-19 (UTC). This document records what was built, what was
verified, and what the environment can and cannot do. It is preparation for a
collaboration demo, not the onboarding story itself.

## What was produced

`linkshelf-seed/` contains a small, readable starter:

| Piece | Notes |
| --- | --- |
| FastAPI app (`app/main.py`) | CRUD + offset pagination, team-scoped via `X-Team-ID` |
| SQLAlchemy 2.0 models (`app/models.py`) | `Bookmark`, `BookmarkAudit`; UTC timestamps |
| Pydantic v2 schemas (`app/schemas.py`) | Request/response contracts, naive datetimes normalised to UTC |
| `migrations/001_initial.sql` | Checked-in initial Postgres schema |
| `tests/` | 17 pytest API/model checks |
| `requirements.txt` | Pinned direct deps (full freeze is in `baseline-test-output.txt`) |
| `README.md`, `CONTRIBUTING.md` | Setup, API, ground rules for later contributors |

Deliberately excluded, as requested, and documented as later work: soft
delete, trash/restore endpoints, cursor pagination, real authentication.

## Design decisions worth knowing

- **`X-Team-ID` is a demo tenant header, not authentication.** It must be a
  positive integer. Missing/non-integer → `422` (FastAPI validation); zero or
  negative → `400`. Any caller can claim any team; this is stated in the README,
  the app description, and CONTRIBUTING.
- **Cross-team access returns `404`, not `403`,** so bookmark ids do not leak
  existence. Verified by tests for `GET`, `PATCH`, and `DELETE`.
- **Delete is hard, with an audit row written in the same transaction.** The
  audit table has no foreign key so the record survives and remains meaningful
  if ids are reused. A test confirms a deleted URL can be re-created.
- **UTC everywhere.** `utcnow()` is timezone-aware; SQLite drops the offset on
  read, so `BookmarkOut` re-attaches UTC to keep the API contract identical on
  both backends. Postgres stores `TIMESTAMPTZ`.
- **Unique `(team_id, url)`** is enforced in both the ORM metadata and the SQL
  migration (`uq_bookmarks_team_id_url`); duplicates return `409`.
- **DATABASE_URL is selectable.** Default is
  `sqlite+pysqlite:///./linkshelf.db`; `psycopg` 3 is included so
  `postgresql+psycopg://...` works unchanged.
- Page ordering is `created_at DESC, id DESC` for stable pagination; the
  response includes `offset`, `limit`, and `total`.

## Exact dependency versions

Direct pins from `requirements.txt`:

```
fastapi==0.116.1
uvicorn[standard]==0.35.0
SQLAlchemy==2.0.43
pydantic==2.11.7
psycopg[binary]==3.2.9
pytest==8.4.1
httpx==0.28.1
```

The complete transitive freeze at test time (30 packages) is recorded at the
top of `baseline-test-output.txt`.

## Test results (actual)

```
17 passed, 1 warning in 0.46s
```

- Python 3.13.14, Linux x86_64, isolated `.venv`.
- Database: temporary SQLite file, not `./linkshelf.db`.
- The single warning is from Starlette's TestClient
  (`anyio.abc.BlockingPortal` deprecation), outside this project's code.
- Coverage includes: health, create/fetch, missing/zero/negative/non-integer
  team headers, cross-team read/patch/delete isolation, duplicate handling per
  team vs across teams, offset pagination (non-overlapping pages, beyond-end,
  validation), hard delete + audit content, URL reuse after delete, and model
  timestamp defaults.
- The full suite was **also** run against a real Postgres 16.2 instance:
  `17 passed`. See below.

## Real Postgres capability check (truthful report)

**Question:** can a disposable real Postgres run in this environment?

**Answer: yes, but only via project-local binaries fetched from PyPI. No
system Postgres is installed.**

What was checked:

| Path | Result |
| --- | --- |
| `postgres`, `initdb`, `pg_ctl`, `psql`, `pg_config` on `PATH` | not present |
| Docker / Podman | not present |
| `apt-get install postgresql` | unavailable: no package index (`apt-cache policy` empty, `/var/lib/apt/lists` is root-owned) and no root (`sudo` blocked by `no_new_privs`) |
| `pip install pgserver` under system Python 3.13 | no matching distribution (wheels stop at cp312) |
| `pgserver` cp310 manylinux wheel (Postgres 16.2 embedded), downloaded and extracted to `/tmp` | **works** |

The verified procedure was entirely local and disposable:

1. Download the `pgserver` 0.1.4 `cp310` Linux wheel; extract
   `pgserver/pginstall` (contains PostgreSQL 16.2 server binaries).
2. `initdb` a fresh cluster under `/tmp` with trust auth.
3. Start on `127.0.0.1:55432`.
4. Apply `migrations/001_initial.sql` with the bundled `psql` — succeeded.
5. Run the app with
   `DATABASE_URL=postgresql+psycopg://linkshelf@127.0.0.1:55432/linkshelf`.
   Confirmed `engine.dialect.name == "postgresql"` (driver `psycopg`).
   Create/list/duplicate-409/team-isolation/delete/audit all behaved correctly,
   with timezone-aware timestamps.
6. Run `python -m pytest` with that `DATABASE_URL`: **17 passed**.
7. Stop the cluster and remove it. No external or hosted database was used.

Caveats for a later contributor:

- The `pgserver` Python package itself could not be imported under this
  environment's default Python 3.13; only the extracted native binaries were
  used. On Python 3.10–3.12 it can be used as a library.
- The wheel is an external download (~11 MB) and is **not** vendored into the
  zip. If offline reproducibility matters, install Postgres via the OS package
  manager on a machine that permits it.
- This capability is useful for optional integration testing, not required by
  the starter; the committed tests default to SQLite.

## Packaging

`linkshelf-seed.zip` contains the project sources and docs. It excludes `.git`,
`__pycache__`, `.pytest_cache`, `.venv`, `*.db`, and credentials/`.env` files.
Rebuild with:

```bash
cd /workspace
zip -r linkshelf-seed.zip linkshelf-seed \
  -x '*/__pycache__/*' '*/.pytest_cache/*' '*/.venv/*' '*.db' '*.env' '*.git/*'
```
