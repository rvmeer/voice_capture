-- Key moment curation: salience score + soft-archive
ALTER TABLE key_moment ADD COLUMN IF NOT EXISTS salience real NOT NULL DEFAULT 0.5
    CHECK (salience BETWEEN 0 AND 1);
ALTER TABLE key_moment ADD COLUMN IF NOT EXISTS archived_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_key_moment_active ON key_moment (recording_id) WHERE archived_at IS NULL;
