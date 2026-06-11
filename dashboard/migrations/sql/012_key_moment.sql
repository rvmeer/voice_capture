CREATE TABLE IF NOT EXISTS key_moment (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    segment_id bigint REFERENCES segment(id),
    type text NOT NULL CHECK (type IN ('commitment','decision','tension','insight')),
    quote text NOT NULL,
    speaker_participant_id integer REFERENCES participant(id),
    speaker_label text,
    flagged_by text NOT NULL DEFAULT 'ai' CHECK (flagged_by IN ('ai','user')),
    ts timestamptz NOT NULL DEFAULT now(),
    dedup_hash text NOT NULL,
    UNIQUE (recording_id, dedup_hash)
);
