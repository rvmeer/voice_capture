-- Create enum type if it does not exist yet (safe on live DB that already has it)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'meeting_status') THEN
        CREATE TYPE meeting_status AS ENUM ('planned', 'live', 'ended');
    END IF;
END
$$;
-- Ensure 'live' and 'ended' values exist (safe if already present)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = 'meeting_status' AND e.enumlabel = 'live') THEN
        ALTER TYPE meeting_status ADD VALUE 'live';
    END IF;
END
$$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = 'meeting_status' AND e.enumlabel = 'ended') THEN
        ALTER TYPE meeting_status ADD VALUE 'ended';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS recording (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id text UNIQUE,
    title text NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    status meeting_status DEFAULT 'planned'
);
