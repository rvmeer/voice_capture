-- Decision curation: soft-archive for superseded decisions
ALTER TABLE decision ADD COLUMN IF NOT EXISTS archived_at timestamptz;
