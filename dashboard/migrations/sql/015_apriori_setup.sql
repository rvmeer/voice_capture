CREATE TABLE IF NOT EXISTS apriori_setup (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_title_hint text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    consumed boolean NOT NULL DEFAULT false
);
