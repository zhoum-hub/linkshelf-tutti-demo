-- SQLite: apply once to an existing 001-era database with writers stopped.
-- Rebuild because SQLite cannot drop the old UNIQUE table constraint.
BEGIN IMMEDIATE;
CREATE TABLE bookmarks_new (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title VARCHAR(200) NOT NULL,
    created_at DATETIME NOT NULL,
    deleted_at DATETIME
);
INSERT INTO bookmarks_new (id, team_id, url, title, created_at)
    SELECT id, team_id, url, title, created_at FROM bookmarks;
DROP TABLE bookmarks;
ALTER TABLE bookmarks_new RENAME TO bookmarks;
CREATE INDEX ix_bookmarks_team_id ON bookmarks (team_id);
CREATE UNIQUE INDEX uq_bookmarks_team_id_url_active
    ON bookmarks (team_id, url) WHERE deleted_at IS NULL;
CREATE INDEX ix_bookmarks_team_deleted_at ON bookmarks (team_id, deleted_at);
COMMIT;
