-- Action item curation: soft-archive for AI-merged duplicates
ALTER TABLE action_item ADD COLUMN IF NOT EXISTS archived_at timestamptz;
