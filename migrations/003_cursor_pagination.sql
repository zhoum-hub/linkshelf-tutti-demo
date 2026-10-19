-- PostgreSQL: apply after 002_soft_delete.sql with psql -v ON_ERROR_STOP=1.
-- Adds the index that backs cursor (keyset) pagination. No table rewrite and no
-- data change; only an index build. Stop writers to avoid piling up writes
-- during the build, then restart with the new application code.
BEGIN;
CREATE INDEX IF NOT EXISTS ix_bookmarks_team_created_id_active
    ON bookmarks (team_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;
COMMIT;
