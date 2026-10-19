# Contributing to Linkshelf

This repository is a **starter** for a collaboration demo. Keep changes small,
readable, and covered by tests.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

Use an isolated virtualenv. Do not install project packages into the system
Python.

## Ground rules

1. **Every data path is team-scoped.** Any query touching `bookmarks` must
   filter on `team_id`, and every route must depend on `current_team_id`.
   Cross-team reads and writes must return `404`, not `403`, so bookmark IDs do
   not leak.
2. **`X-Team-ID` is not authentication.** Do not describe it as such, and do not
   build permission logic on it. It is a demo tenant selector.
3. **UTC everywhere.** Use `app.models.utcnow` for timestamps and keep the
   columns `timezone=True`. Do not introduce local-time comparisons.
4. **Both databases must stay in sync.** If you change a model, update
   `migrations/001_initial.sql` (or add a new migration) in the same change.
5. **Deletes and successful restores write audit snapshots in the same transaction as their bookmark update.**
   Reads and updates must exclude deleted rows. The tenant-scoped purge job
   removes bookmarks after 30 days and must never remove audit records.

## What to leave for later

Do not add these unless the task explicitly asks for them; they are planned
historical follow-ups, not forgotten work:

- real authentication

If a change would add one of these early, call it out in the pull request
instead.

## Tests

```bash
python -m pytest              # full suite
python -m pytest -k delete    # one area
```

Add an API-level pytest for new behaviour. Tests run against a temporary SQLite
database and must not depend on execution order or on `./linkshelf.db`.

When you change dependencies, pin exact versions in `requirements.txt` and note
why in the commit message.

## Code style

- Python 3.11+ typing (`str | None`, `list[...]`), `from __future__ import annotations`.
- Keep modules focused: routes in `app/main.py`, persistence in `app/models.py`
  and `app/db.py`, contracts in `app/schemas.py`.
- Prefer explicit, boring SQLAlchemy 2.0 constructs (`select(...)`,
  `session.scalars(...)`) over legacy query APIs.
