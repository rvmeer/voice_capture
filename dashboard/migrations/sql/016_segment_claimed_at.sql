-- Add claimed_at to segment so the reaper can use it instead of ai_processed_at
ALTER TABLE segment ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
