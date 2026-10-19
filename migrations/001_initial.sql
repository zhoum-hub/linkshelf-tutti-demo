-- Linkshelf initial schema (Postgres)
-- Reviewed, checked-in baseline for the Linkshelf starter.
--
-- Apply with:
--   psql "$DATABASE_URL" -f migrations/001_initial.sql
--
-- The application itself uses SQLAlchemy metadata for local SQLite development;
-- this file is the canonical migration for Postgres deployments.

BEGIN;

CREATE TABLE IF NOT EXISTS bookmarks (
    id          BIGSERIAL PRIMARY KEY,
    team_id     BIGINT      NOT NULL,
    url         TEXT        NOT NULL,
    title       VARCHAR(200) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_bookmarks_team_id_url UNIQUE (team_id, url)
);

CREATE INDEX IF NOT EXISTS ix_bookmarks_team_id ON bookmarks (team_id);

CREATE TABLE IF NOT EXISTS bookmark_audit (
    id          BIGSERIAL PRIMARY KEY,
    bookmark_id BIGINT       NOT NULL,
    team_id     BIGINT       NOT NULL,
    url         TEXT         NOT NULL,
    title       VARCHAR(200) NOT NULL,
    action      VARCHAR(20)  NOT NULL DEFAULT 'delete',
    deleted_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_bookmark_audit_bookmark_id ON bookmark_audit (bookmark_id);
CREATE INDEX IF NOT EXISTS ix_bookmark_audit_team_id ON bookmark_audit (team_id);

COMMIT;
