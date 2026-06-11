CREATE TABLE IF NOT EXISTS segment (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    segment_num int NOT NULL,
    text text NOT NULL,
    speaker_label text,
    participant_id integer REFERENCES participant(id),
    ts timestamptz NOT NULL,
    duration_seconds real,
    sentiment real CHECK (sentiment BETWEEN -1.0 AND 1.0),
    ai_status text NOT NULL DEFAULT 'pending' CHECK (ai_status IN ('pending','processing','done','failed')),
    ai_processed_at timestamptz,
    ai_attempts int NOT NULL DEFAULT 0,
    UNIQUE (recording_id, segment_num)
);

CREATE INDEX IF NOT EXISTS idx_segment_ai_queue ON segment (ai_status, id);
CREATE INDEX IF NOT EXISTS idx_segment_recording_ts ON segment (recording_id, ts);
