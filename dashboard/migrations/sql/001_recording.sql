CREATE TABLE IF NOT EXISTS recording (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id text UNIQUE,
    title text NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    status meeting_status DEFAULT 'planned'
);
