CREATE TABLE IF NOT EXISTS decision (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    description text NOT NULL,
    status text NOT NULL DEFAULT 'concept' CHECK (status IN ('agreed','concept','rejected')),
    segment_id bigint REFERENCES segment(id),
    decided_at timestamptz NOT NULL,
    topic_id bigint REFERENCES topic(id),
    dedup_hash text NOT NULL,
    UNIQUE (recording_id, dedup_hash)
);
