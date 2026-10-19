-- SQLite: apply once after 002_soft_delete_sqlite.sql with writers stopped.
-- Adds the partial index that backs cursor (keyset) pagination. Creates no
-- table copy and changes no rows; index creation may briefly hold a schema
-- write lock, so stop writers first.
BEGIN IMMEDIATE;
CREATE INDEX IF NOT EXISTS ix_bookmarks_team_created_id_active
    ON bookmarks (team_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;
COMMIT;
