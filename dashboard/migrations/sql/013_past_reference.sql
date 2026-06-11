CREATE TABLE IF NOT EXISTS past_reference (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    topic_id bigint NOT NULL REFERENCES topic(id),
    source_recording_id uuid NOT NULL REFERENCES recording(id),
    signal text NOT NULL CHECK (signal IN ('repeated','resolved','new_context')),
    summary text NOT NULL,
    source text NOT NULL DEFAULT 'auto',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recording_id, topic_id, source_recording_id, source)
);
