CREATE TABLE IF NOT EXISTS segment_topic (
    segment_id bigint REFERENCES segment(id) ON DELETE CASCADE,
    topic_id bigint REFERENCES topic(id),
    confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (segment_id, topic_id)
);
