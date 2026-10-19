# ADR 002: Cursor pagination for `GET /bookmarks`

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** Linkshelf engineering
- **Scope:** Pagination of the bookmark list only; no trash or restore semantics

## Context

`GET /bookmarks` returned a tenant-scoped list ordered by
`(created_at DESC, id DESC)` using `OFFSET`/`LIMIT`. Every request re-runs the
query against the current committed state; the server holds no snapshot across
requests. A client that scrolls by incrementing `offset` therefore treats
"row position in the current result set" as a stable address. It is not: the
position of every row after an insert or delete changes while the client is
mid-scroll.

Two consequences follow directly from that mismatch, one for inserts and one
for deletes. They are stated as precise mechanics, not as a reproduction of a
observed incident.

### Insert-between-pages: a row is repeated

Let the active rows for a team, newest first, be `R1 R2 R3 R4 R5`, and let the
page size be 2.

1. Page 1 requests `offset=0` and returns `R1 R2`.
2. Before page 2, a new row `R0` commits. `R0` sorts newest because its
   `created_at` is later. The ordered list is now `R0 R1 R2 R3 R4 R5`.
3. Page 2 requests `offset=2` and returns the rows at positions 2 and 3, which
   are `R2 R3`.

`R2` was already shown on page 1. The client concatenating pages displays it
twice. Each insert that sorts before the offset boundary shifts the boundary by
one row, so repeated inserts produce repeated rows. Symmetrically, a row whose
`created_at` is changed would move the same way, though this API never mutates
`created_at`.

### Delete-between-pages: a row is skipped

Same list `R1 R2 R3 R4 R5`, page size 2.

1. Page 1 requests `offset=0` and returns `R1 R2`.
2. Before page 2, `R1` is deleted. Deletion here is a soft delete: the row's
   `deleted_at` is set and the list filters it out, so from the list's point of
   view it disappears exactly as a hard delete would. The visible list is now
   `R2 R3 R4 R5`.
3. Page 2 requests `offset=2` and returns the rows at positions 2 and 3, which
   are `R4 R5`.

`R3` is never returned by any page. If the deleted row was at position 2 or
later, no visible row is skipped; only deletes before the boundary cause the
skip. Because the client sees no gap and the page is not short, the omission is
silent. The `total` field on each page reflects the state at that request, so a
client that does compare totals can detect an inconsistency but cannot recover
the missing row by continuing to scroll.

Concurrent writers make both cases ordinary rather than exotic: the service
targets browser-extension writes, so inserts and deletes land while a list is
being read. Row identity (`id`) is stable, but `OFFSET` addresses positions,
and positions are not stable.

### Options considered

1. **Keep offsets, add a snapshot** (repeatable-read transaction pinned across
   requests). Correct, but it requires server-side state per scrolling client,
   holds database resources for the duration of a scroll, and is awkward across
   stateless app instances.
2. **Keyset/cursor pagination.** The cursor carries the sort key of the last
   row returned, and the next page asks for rows strictly after that key. This
   is stateless, needs only an index, and makes the boundary a value rather
   than a position.
3. **Increase page size / cap offsets.** Reduces frequency, does not remove the
   failure mode.

Option 2 is chosen.

## Decision

`GET /bookmarks` supports **stable cursor pagination** ordered by
`(created_at DESC, id DESC)`.

- A cursor is an opaque, versioned, base64url token (`v1.<payload>`) containing
  the `(created_at, id)` sort key of the last row on the page.
- The next page is selected with
  `WHERE (created_at, id) < (cursor.created_at, cursor.id)` in descending order.
  Rows that sort strictly after the key are unaffected by inserts and deletes
  that sort before it.
- `created_at` alone is not unique: rows written in the same microsecond are
  possible, and `now()` can repeat within a transaction. `id` is the
  tiebreaker, so the ordering is total and a cursor can never bisect a group of
  equal timestamps.
- `next_cursor` is present only when another page exists. The server reads
  `limit + 1` rows to decide this and returns `limit`; it does not scan ahead
  or count to decide whether to continue.
- The cursor is **not a snapshot**. It does not hold a transaction open. A row
  inserted with a sort key older than the cursor appears in a later page; a row
  deleted after it was returned is simply not returned again. Clients that need
  a coherent point-in-time view should restart from the first page.
- Timestamps in cursors carry an explicit UTC offset and are normalised to
  UTC. Naive timestamps are rejected at decode time: on Postgres a naive
  comparison depends on the session timezone, while SQLite stores the value
  without an offset. Requiring an offset keeps the two backends identical.

### Legacy `page` and `offset` parameters (one release)

Both legacy spellings remain accepted for one release so existing clients do
not break:

- `offset=K` skips `K` rows of the current result set.
- `page=N` (1-based, with the current `limit`) skips `(N - 1) * limit` rows.
  The baseline API did not define `page`; FastAPI ignored it as an unknown
  query parameter, so a client sending it silently received the first page.
  This release honours it for the deprecation window.
- Legacy responses echo the submitted `page`/`offset`, set
  `pagination: "legacy-offset"` and `offset_deprecated: true`, do **not** mint
  a `next_cursor`, and carry
  `Deprecation: @1792368000` (RFC 9745, the 2026-10-19 UTC start of the
  window), `Sunset: Tue, 19 Jan 2027 00:00:00 GMT` (RFC 8594), and
  `Link: </bookmarks>; rel="successor-version"` headers.
- Legacy responses remain subject to the offset failure modes above. They are
  compatibility shims, not a second supported mode.

Deprecation date: **2027-01-19** (one release after this change). After that
date the parameters can be removed; removal is a breaking change and should be
announced in the release notes.

### Incompatible combinations

These requests are rejected with **400** before any query runs, because the
two windows cannot be reconciled:

| Combination | Why |
| --- | --- |
| `cursor` + `offset` | A cursor addresses a value; `offset` addresses a position |
| `cursor` + `page` | Same, with the page translated to a position |
| `page` + `offset` | Two different numeric positions for one request |

A request with none of `cursor`, `page`, or `offset` is a normal first page in
cursor mode: it returns `next_cursor` and no deprecation headers.

Parameter validation is unchanged and still returns **422**: `offset >= 0`,
`page >= 1`, `1 <= limit <= 100`. Validation runs before the combination
checks, so `offset=-1&cursor=...` is 422, while a well-formed `cursor` plus
`offset=0` is 400. An unparseable or versionless cursor is 400 with a message
beginning `invalid cursor:`.

### Tenant boundary and soft-delete filtering

The cursor is a value, not a capability. Every request still derives
`team_id` from `X-Team-ID` and filters `Bookmark.team_id == team_id` and
`Bookmark.deleted_at IS NULL` before the cursor predicate. A cursor minted for
one team and replayed by another simply selects from the other team's rows; it
cannot widen the tenant boundary. No cursor field is trusted as an identity or
used to look up a row across tenants. `next_cursor` is derived from a row in
the filtered result, and `total` runs the same tenant and soft-delete filters.

## Index and migration

The access path is equality on `team_id`, then the descending key, restricted
to active rows. Migration 003 adds:

```sql
CREATE INDEX ix_bookmarks_team_created_id_active
    ON bookmarks (team_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;
```

Both checked-in variants
(`migrations/003_cursor_pagination.sql` for Postgres,
`migrations/003_cursor_pagination_sqlite.sql` for SQLite) are idempotent
(`IF NOT EXISTS`) and change no rows. The partial predicate matches the list's
filter, so deleted rows are not indexed. SQLite creates the index in place; no
table rebuild is needed. Postgres builds it inside the migration transaction —
which locks out writes for the build — so apply it with writers stopped, as
with migration 002. `CONCURRENTLY` is deliberately not used: it cannot run in a
transaction, and the project's migrations are applied as single transactional
steps with writers stopped. No performance claim is made; the index is
justified by the access pattern, not by a benchmark.

The ORM metadata in `app/models.py` defines the same index so `create_all`
builds an equivalent schema for local SQLite development and tests.

## API contract

```json
{
  "items": [{"id": 7, "team_id": 1, "url": "...", "title": "...", "created_at": "..."}],
  "limit": 20,
  "total": 42,
  "next_cursor": "v1.MjAyNi0xMC0xOVQxMjowMDowMCswMDowMHw3",
  "pagination": "cursor",
  "offset_deprecated": false,
  "page": null,
  "offset": null
}
```

- Cursor traversal: send `next_cursor` back as `cursor`; stop when it is
  `null`.
- `total` is still returned for compatibility. It is a live count and is not
  consistent with any particular cursor position; do not derive pagination
  decisions from it.
- Cursors are opaque. Their internal format may change; only the `v1.` prefix
  and the round-trip behaviour are contractual.

## Consequences

**Positive**

- Inserts and deletes between pages no longer repeat or skip surviving rows
  that sort after the cursor.
- Stateless and index-friendly; no per-client server state and no held
  transactions.
- Tenancy and soft-delete filters are part of the same query, before the cursor
  predicate, so paging cannot widen the visible set.

**Negative / costs**

- The cursor is not a snapshot; a client must accept that the list is
  eventually consistent across pages.
- Clients must thread `next_cursor` through instead of incrementing `offset`.
- Cursors are longer than offsets and must be treated as opaque.
- Two pagination modes coexist for one release, including a narrow set of
  rejected combinations.

**Neutral**

- `total` still runs on every page. It is a count of matching rows, served from
  the tenant-filtered query; it is not constant-time in the number of rows and
  is not meaningful across cursor pages.

## Verification

Recorded in `cursor-test-output.txt` with the actual commands and output:

- SQLite, full suite: the insert-repeat and delete-skip scenarios,
  equal-timestamp tiebreaking, tenant isolation, soft-delete filtering, cursor
  validation, legacy compatibility, and the SQLite 003 index migration
  (including a replay). The Postgres-only migration test reports *skipped*.
- Disposable PostgreSQL 16.2: migrations 001 → 002 → 003 applied, 003 replayed
  as a no-op, the full suite (51 tests, including the Postgres 003 migration
  test), and an `EXPLAIN` showing the cursor query using
  `ix_bookmarks_team_created_id_active`.

Only functional tests and migration checks were run. No load benchmark, no
environment rebuild, and no dependency installation was performed; the
existing project-local `.venv` and Postgres binaries were reused.

## Out of scope

Trash and restore are **not** implemented here. `DELETE` continues to soft
delete and purge after 30 days exactly as before; this ADR only changes how the
active list is paginated. `X-Team-ID` remains a demo tenant selector, not
authentication.
