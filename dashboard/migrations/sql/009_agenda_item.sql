CREATE TABLE IF NOT EXISTS agenda_item (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    title text NOT NULL,
    position int NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','done')),
    topic_id bigint REFERENCES topic(id),
    source text NOT NULL DEFAULT 'apriori',
    started_at timestamptz,
    ended_at timestamptz,
    duration_seconds real GENERATED ALWAYS AS (EXTRACT(EPOCH FROM (ended_at - started_at))) STORED,
    UNIQUE (recording_id, position)
);
