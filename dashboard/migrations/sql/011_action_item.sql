CREATE TABLE IF NOT EXISTS action_item (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    description text NOT NULL,
    owner_participant_id integer REFERENCES participant(id),
    due_date date,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','overdue')),
    topic_id bigint REFERENCES topic(id),
    segment_id bigint REFERENCES segment(id),
    dedup_hash text NOT NULL,
    UNIQUE (recording_id, dedup_hash)
);
