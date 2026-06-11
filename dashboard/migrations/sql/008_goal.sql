CREATE TABLE IF NOT EXISTS goal (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id uuid NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    description text NOT NULL,
    coaching_tip text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','achieved','at_risk')),
    topic_id bigint REFERENCES topic(id),
    source text NOT NULL DEFAULT 'apriori',
    achieved_at timestamptz,
    achieved_segment_id bigint REFERENCES segment(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
