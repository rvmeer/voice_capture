CREATE TABLE IF NOT EXISTS recording_topic (
    recording_id uuid REFERENCES recording(id) ON DELETE CASCADE,
    topic_id bigint REFERENCES topic(id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recording_id, topic_id)
);

CREATE OR REPLACE FUNCTION recording_topic_occurrence_increment() RETURNS trigger AS $$
BEGIN
    UPDATE topic SET occurrence_count = occurrence_count + 1 WHERE id = NEW.topic_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION recording_topic_occurrence_decrement() RETURNS trigger AS $$
BEGIN
    UPDATE topic SET occurrence_count = GREATEST(0, occurrence_count - 1) WHERE id = OLD.topic_id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recording_topic_occurrence_insert ON recording_topic;
CREATE TRIGGER trg_recording_topic_occurrence_insert
AFTER INSERT ON recording_topic
FOR EACH ROW
EXECUTE FUNCTION recording_topic_occurrence_increment();

DROP TRIGGER IF EXISTS trg_recording_topic_occurrence_delete ON recording_topic;
CREATE TRIGGER trg_recording_topic_occurrence_delete
AFTER DELETE ON recording_topic
FOR EACH ROW
EXECUTE FUNCTION recording_topic_occurrence_decrement();
