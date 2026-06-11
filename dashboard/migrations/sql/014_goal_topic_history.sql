CREATE OR REPLACE VIEW goal_topic_history AS
SELECT g.id AS goal_id, g.recording_id, g.description, g.status, g.achieved_at,
       t.id AS topic_id, t.label AS topic_label,
       r.recording_id AS vc_recording_id, r.title, r.started_at
FROM goal g
LEFT JOIN topic t ON g.topic_id = t.id
LEFT JOIN recording r ON g.recording_id = r.id;
