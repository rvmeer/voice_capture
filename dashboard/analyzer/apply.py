"""Apply AI results transactionally."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from dashboard.api.setup import ensure_participant, ensure_topic, resolve_participant_ref, resolve_topic_ref
from dashboard.context.past_refs import auto_check
from dashboard.db import fetchall, fetchone
from dashboard.stats import header_stats, tone_window


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _dedup_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()[:16]


async def _participant_stats(conn: Any, recording_uuid: str, vc_recording_id: str) -> list[dict[str, Any]]:
    totals = await fetchall(
        conn,
        """
        SELECT participant_id, COALESCE(SUM(duration_seconds), 0) AS speaking_seconds
        FROM segment
        WHERE recording_id = %s AND participant_id IS NOT NULL
        GROUP BY participant_id
        """,
        (recording_uuid,),
    )
    total_seconds = sum(float(row["speaking_seconds"] or 0.0) for row in totals)
    await conn.execute(
        "UPDATE recording_participant SET speaking_seconds = 0, speaking_time_ratio = 0 WHERE recording_id = %s",
        (vc_recording_id,),
    )
    for row in totals:
        ratio = float(row["speaking_seconds"] or 0.0) / total_seconds if total_seconds > 0 else 0.0
        await conn.execute(
            """
            INSERT INTO recording_participant (recording_id, participant_id, speaking_seconds, speaking_time_ratio, source)
            VALUES (%s, %s, %s, %s, 'ai')
            ON CONFLICT (recording_id, participant_id) DO UPDATE
            SET speaking_seconds = EXCLUDED.speaking_seconds,
                speaking_time_ratio = EXCLUDED.speaking_time_ratio,
                source = CASE WHEN recording_participant.source = 'apriori' THEN recording_participant.source ELSE 'ai' END
            """,
            (vc_recording_id, row["participant_id"], row["speaking_seconds"], ratio),
        )
    return await fetchall(
        conn,
        """
        SELECT p.id, p.name, p.initials, p.is_user, rp.speaking_seconds,
               rp.speaking_time_ratio, rp.role, rp.source
        FROM recording_participant rp
        JOIN participant p ON p.id = rp.participant_id
        WHERE rp.recording_id = %s
        ORDER BY rp.speaking_time_ratio DESC, lower(p.name)
        """,
        (vc_recording_id,),
    )


async def _header_stats(conn: Any, recording_uuid: str) -> dict[str, int]:
    participants = await fetchall(conn, "SELECT participant_id FROM recording_participant rp JOIN recording r ON r.recording_id = rp.recording_id WHERE r.id = %s", (recording_uuid,))
    goals = await fetchall(conn, "SELECT status FROM goal WHERE recording_id = %s", (recording_uuid,))
    actions = await fetchall(conn, "SELECT id FROM action_item WHERE recording_id = %s", (recording_uuid,))
    decisions = await fetchall(conn, "SELECT id FROM decision WHERE recording_id = %s", (recording_uuid,))
    return header_stats(participants, goals, actions, decisions)


async def _agenda_rows(conn: Any, recording_uuid: str) -> list[dict[str, Any]]:
    return await fetchall(conn, "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position", (recording_uuid,))


async def _tone_payload(conn: Any, recording_uuid: str) -> dict[str, Any]:
    sentiments = await fetchall(
        conn,
        "SELECT sentiment FROM segment WHERE recording_id = %s AND sentiment IS NOT NULL ORDER BY id DESC LIMIT 18",
        (recording_uuid,),
    )
    return tone_window([row["sentiment"] for row in reversed(sentiments)])


async def apply_result(
    conn: Any,
    recording_uuid: str,
    recording_vc_id: str,
    segment_id: int,
    result: dict[str, Any],
    ws_hub: Any,
) -> None:
    events: list[tuple[str, dict[str, Any] | list[dict[str, Any]]]] = []
    topic_ids_for_context: list[int] = []
    async with conn.transaction():
        segment = await fetchone(conn, "SELECT * FROM segment WHERE id = %s", (segment_id,))
        if not segment:
            return

        speaker_payload = result.get("speaker")
        speaker = None
        try:
            if isinstance(speaker_payload, dict):
                if "participant_id" in speaker_payload:
                    speaker = await resolve_participant_ref(conn, speaker_payload["participant_id"])
                elif "new_participant" in speaker_payload:
                    payload = speaker_payload["new_participant"]
                    speaker = await ensure_participant(conn, payload["name"], initials=payload.get("initials"))
                if speaker:
                    await conn.execute("UPDATE segment SET participant_id = %s WHERE id = %s", (speaker["id"], segment_id))
        except Exception as exc:
            logger.warning("apply_result: speaker block failed for segment %s: %s", segment_id, exc)

        for synonym_payload in result.get("add_synonyms") or []:
            try:
                topic = await resolve_topic_ref(conn, synonym_payload.get("topic_id"))
                synonym = (synonym_payload.get("synonym") or "").strip()
                if not topic or not synonym:
                    continue
                synonyms = list(topic.get("synonyms") or [])
                if synonym.lower() not in {value.lower() for value in synonyms}:
                    synonyms.append(synonym)
                    await conn.execute("UPDATE topic SET synonyms = %s WHERE id = %s", (synonyms, topic["id"]))
            except Exception as exc:
                logger.warning("apply_result: synonym block failed: %s", exc)

        for tag in result.get("topic_tags") or []:
            try:
                confidence = float(tag.get("confidence") or 0.0)
                topic = None
                if "topic_id" in tag:
                    topic = await resolve_topic_ref(conn, tag.get("topic_id"))
                elif "new_topic" in tag:
                    payload = tag["new_topic"]
                    topic = await ensure_topic(
                        conn,
                        payload["label"],
                        synonyms=payload.get("synonyms"),
                        parent_topic_id=payload.get("parent_topic_id"),
                    )
                if not topic:
                    continue
                await conn.execute(
                    """
                    INSERT INTO segment_topic (segment_id, topic_id, confidence)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (segment_id, topic_id) DO UPDATE
                    SET confidence = GREATEST(segment_topic.confidence, EXCLUDED.confidence)
                    """,
                    (segment_id, topic["id"], confidence),
                )
                cur = await conn.execute(
                    """
                    INSERT INTO recording_topic (recording_id, topic_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING recording_id, topic_id, first_seen_at
                    """,
                    (recording_uuid, topic["id"]),
                )
                recording_topic = await cur.fetchone()
                events.append(("topic.tagged", {"segment_id": segment_id, "topic_id": topic["id"], "confidence": confidence}))
                if recording_topic:
                    topic_ids_for_context.append(topic["id"])
            except Exception as exc:
                logger.warning("apply_result: topic_tag block failed: %s", exc)

        for goal_update in result.get("goal_updates") or []:
            try:
                goal = await fetchone(conn, "SELECT * FROM goal WHERE id = %s AND recording_id = %s", (goal_update["goal_id"], recording_uuid))
                if not goal:
                    continue
                new_status = goal_update["status"]
                if goal.get("status") == "achieved" and new_status != "achieved":
                    new_status = "achieved"
                await conn.execute(
                    """
                    UPDATE goal
                    SET status = %s,
                        coaching_tip = COALESCE(%s, coaching_tip),
                        achieved_at = CASE WHEN %s = 'achieved' THEN COALESCE(achieved_at, now()) ELSE achieved_at END,
                        achieved_segment_id = CASE WHEN %s = 'achieved' THEN COALESCE(achieved_segment_id, %s) ELSE achieved_segment_id END
                    WHERE id = %s
                    """,
                    (new_status, goal_update.get("coaching_tip"), new_status, new_status, segment_id, goal["id"]),
                )
                updated_goal = await fetchone(conn, "SELECT * FROM goal WHERE id = %s", (goal["id"],))
                events.append(("goal.updated", updated_goal))
            except Exception as exc:
                logger.warning("apply_result: goal_update block failed: %s", exc)

        for goal_payload in result.get("new_goals") or []:
            try:
                topic = await resolve_topic_ref(conn, goal_payload.get("topic_ref"), create=True)
                cur = await conn.execute(
                    """
                    INSERT INTO goal (recording_id, description, coaching_tip, status, topic_id, source)
                    VALUES (%s, %s, %s, 'open', %s, 'ai')
                    RETURNING *
                    """,
                    (recording_uuid, goal_payload["description"], goal_payload.get("coaching_tip"), topic["id"] if topic else None),
                )
                events.append(("goal.updated", await cur.fetchone()))
            except Exception as exc:
                logger.warning("apply_result: new_goal block failed: %s", exc)

        try:
            agenda_payload = result.get("agenda")
            if isinstance(agenda_payload, dict):
                if "active_item_id" in agenda_payload:
                    active_item_id = agenda_payload["active_item_id"]
                    await conn.execute(
                        """
                        UPDATE agenda_item
                        SET status = 'done', ended_at = COALESCE(ended_at, now())
                        WHERE recording_id = %s AND status = 'active' AND id <> %s
                        """,
                        (recording_uuid, active_item_id),
                    )
                    await conn.execute(
                        """
                        UPDATE agenda_item
                        SET status = 'active', started_at = COALESCE(started_at, now())
                        WHERE recording_id = %s AND id = %s AND status <> 'done'
                        """,
                        (recording_uuid, active_item_id),
                    )
                elif "new_item" in agenda_payload:
                    new_item = agenda_payload["new_item"]
                    topic = await resolve_topic_ref(conn, new_item.get("topic_ref"), create=True)
                    await conn.execute(
                        "UPDATE agenda_item SET status = 'done', ended_at = COALESCE(ended_at, now()) WHERE recording_id = %s AND status = 'active'",
                        (recording_uuid,),
                    )
                    next_position = await fetchone(conn, "SELECT COALESCE(MAX(position), 0) + 1 AS next_pos FROM agenda_item WHERE recording_id = %s", (recording_uuid,))
                    await conn.execute(
                        """
                        INSERT INTO agenda_item (recording_id, title, position, status, topic_id, source, started_at)
                        VALUES (%s, %s, %s, 'active', %s, 'ai', now())
                        """,
                        (recording_uuid, new_item["title"], next_position["next_pos"], topic["id"] if topic else None),
                    )
                events.append(("agenda.updated", {"items": await _agenda_rows(conn, recording_uuid)}))
        except Exception as exc:
            logger.warning("apply_result: agenda block failed: %s", exc)

        for decision_payload in result.get("decisions") or []:
            try:
                topic = await resolve_topic_ref(conn, decision_payload.get("topic_ref"), create=True)
                dedup = _dedup_hash(decision_payload["description"])
                cur = await conn.execute(
                    """
                    INSERT INTO decision (recording_id, description, status, segment_id, decided_at, topic_id, dedup_hash)
                    VALUES (%s, %s, %s, %s, COALESCE(%s, now()), %s, %s)
                    ON CONFLICT (recording_id, dedup_hash) DO UPDATE
                    SET status = CASE
                            WHEN decision.status = 'agreed' THEN decision.status
                            WHEN EXCLUDED.status = 'agreed' THEN 'agreed'
                            WHEN EXCLUDED.status = 'rejected' AND decision.status <> 'agreed' THEN 'rejected'
                            ELSE decision.status
                        END,
                        topic_id = COALESCE(decision.topic_id, EXCLUDED.topic_id),
                        segment_id = COALESCE(decision.segment_id, EXCLUDED.segment_id)
                    RETURNING *
                    """,
                    (recording_uuid, decision_payload["description"], decision_payload["status"], segment_id, segment.get("ts"), topic["id"] if topic else None, dedup),
                )
                events.append(("decision.upserted", await cur.fetchone()))
            except Exception as exc:
                logger.warning("apply_result: decision block failed: %s", exc)

        for action_payload in result.get("action_items") or []:
            try:
                topic = await resolve_topic_ref(conn, action_payload.get("topic_ref"), create=True)
                owner = await resolve_participant_ref(conn, action_payload.get("owner_ref"), create=True)
                due_date = action_payload.get("due_date")
                if due_date:
                    due_date = date.fromisoformat(due_date)
                dedup = _dedup_hash(action_payload["description"])
                cur = await conn.execute(
                    """
                    INSERT INTO action_item (recording_id, description, owner_participant_id, due_date, status, topic_id, segment_id, dedup_hash)
                    VALUES (%s, %s, %s, %s, 'open', %s, %s, %s)
                    ON CONFLICT (recording_id, dedup_hash) DO UPDATE
                    SET owner_participant_id = COALESCE(action_item.owner_participant_id, EXCLUDED.owner_participant_id),
                        due_date = COALESCE(action_item.due_date, EXCLUDED.due_date),
                        topic_id = COALESCE(action_item.topic_id, EXCLUDED.topic_id),
                        segment_id = COALESCE(action_item.segment_id, EXCLUDED.segment_id)
                    RETURNING *
                    """,
                    (recording_uuid, action_payload["description"], owner["id"] if owner else None, due_date, topic["id"] if topic else None, segment_id, dedup),
                )
                events.append(("action_item.upserted", await cur.fetchone()))
            except Exception as exc:
                logger.warning("apply_result: action_item block failed: %s", exc)

        for moment_payload in result.get("key_moments") or []:
            try:
                speaker_ref = moment_payload.get("speaker_ref")
                identified_speaker = await resolve_participant_ref(conn, speaker_ref)
                dedup = _dedup_hash(moment_payload["quote"])
                cur = await conn.execute(
                    """
                    INSERT INTO key_moment (recording_id, segment_id, type, quote, speaker_participant_id, speaker_label, flagged_by, ts, dedup_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, 'ai', COALESCE(%s, now()), %s)
                    ON CONFLICT (recording_id, dedup_hash) DO NOTHING
                    RETURNING *
                    """,
                    (
                        recording_uuid,
                        segment_id,
                        moment_payload["type"],
                        moment_payload["quote"],
                        identified_speaker["id"] if identified_speaker else None,
                        identified_speaker["name"] if identified_speaker else (speaker_ref if isinstance(speaker_ref, str) else segment.get("speaker_label")),
                        segment.get("ts"),
                        dedup,
                    ),
                )
                key_moment = await cur.fetchone()
                if key_moment:
                    events.append(("key_moment.created", key_moment))
            except Exception as exc:
                logger.warning("apply_result: key_moment block failed: %s", exc)

        await conn.execute(
            """
            UPDATE segment
            SET sentiment = %s,
                ai_status = 'done',
                ai_processed_at = now()
            WHERE id = %s
            """,
            (result.get("sentiment"), segment_id),
        )
        events.append(("segment.analyzed", {"segment_id": segment_id, "sentiment": result.get("sentiment")}))

        if speaker:
            participant_stats = await _participant_stats(conn, recording_uuid, recording_vc_id)
            events.append(("participant.stats", {"participants": participant_stats}))

        events.append(("sentiment.updated", await _tone_payload(conn, recording_uuid)))
        events.append(("header.stats", await _header_stats(conn, recording_uuid)))

    for event_type, payload in events:
        await ws_hub.broadcast(recording_vc_id, event_type, payload)
    for topic_id in topic_ids_for_context:
        await auto_check(conn, ws_hub, recording_uuid, topic_id)
