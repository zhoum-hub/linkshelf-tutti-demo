-- PostgreSQL: apply after 001_initial.sql with psql -v ON_ERROR_STOP=1.
-- Stop application writers during this transactional schema change.
BEGIN;
ALTER TABLE bookmarks ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE bookmarks DROP CONSTRAINT uq_bookmarks_team_id_url;
CREATE UNIQUE INDEX uq_bookmarks_team_id_url_active
    ON bookmarks (team_id, url) WHERE deleted_at IS NULL;
CREATE INDEX ix_bookmarks_team_deleted_at ON bookmarks (team_id, deleted_at);
COMMIT;
