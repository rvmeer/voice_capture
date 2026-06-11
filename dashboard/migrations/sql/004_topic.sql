CREATE TABLE IF NOT EXISTS topic (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label text UNIQUE NOT NULL,
    synonyms text[] NOT NULL DEFAULT '{}',
    parent_topic_id bigint REFERENCES topic(id),
    occurrence_count int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topic_synonyms_gin ON topic USING GIN (synonyms);
CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_label_lower ON topic (lower(label));
