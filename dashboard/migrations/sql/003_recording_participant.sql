CREATE TABLE IF NOT EXISTS recording_participant (
    recording_id text REFERENCES recording(recording_id),
    participant_id integer REFERENCES participant(id),
    role text,
    speaking_time_ratio real NOT NULL DEFAULT 0,
    speaking_seconds real NOT NULL DEFAULT 0,
    source text NOT NULL DEFAULT 'apriori',
    PRIMARY KEY (recording_id, participant_id)
);

ALTER TABLE recording_participant ADD COLUMN IF NOT EXISTS speaking_time_ratio real NOT NULL DEFAULT 0;
ALTER TABLE recording_participant ADD COLUMN IF NOT EXISTS speaking_seconds real NOT NULL DEFAULT 0;
ALTER TABLE recording_participant ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'apriori';
