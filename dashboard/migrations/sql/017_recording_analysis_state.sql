-- Recording analysis state: rolling summary + agenda_mode
ALTER TABLE recording ADD COLUMN IF NOT EXISTS context_summary text;
ALTER TABLE recording ADD COLUMN IF NOT EXISTS summary_up_to_segment int NOT NULL DEFAULT 0;
ALTER TABLE recording ADD COLUMN IF NOT EXISTS agenda_mode text NOT NULL DEFAULT 'dynamic'
    CHECK (agenda_mode IN ('apriori','dynamic'));
