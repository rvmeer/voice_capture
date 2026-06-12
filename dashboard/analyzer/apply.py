"""Apply AI results transactionally."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from typing import Any

from dashboard.api.setup import ensure_participant, ensure_topic, resolve_participant_ref, resolve_topic_ref
from dashboard.analyzer.sentiment import clamp_sentiment
from dashboard.context.past_refs import auto_check
from dashboard.db import fetchall, fetchone
from dashboard.stats import TONE_WINDOW_SIZE, header_stats, tone_window

logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _dedup_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()[:16]


def apply_agenda_transition(items: list[dict], new_active_id: int, now: str) -> list[dict]:
    """Pure function: mark active items done, activate `new_active_id` (unless already done)."""
    result = []
    for item in items:
        if item["status"] == "active" and item["id"] != new_active_id:
            result.append({**item, "status": "done", "ended_at": now})
        elif item["id"] == new_active_id and item["status"] != "done":
            result.append({**item, "status": "active", "started_at": item.get("started_at") or now})
        else:
            result.append(item)
    return result


def apply_goal_latch(current_status: str, requested_status: str) -> str:
    """Achieved is terminal: never downgrade a goal that has been achieved."""
    if current_status == "achieved" and requested_status != "achieved":
        return "achieved"
    return requested_status


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
        f"SELECT sentiment FROM segment WHERE recording_id = %s AND sentiment IS NOT NULL ORDER BY id DESC LIMIT {TONE_WINDOW_SIZE}",
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


# ═══════════════════════════════════════════════════════════════════════════
# Curated result reconciler (v2 pipeline)
# ═══════════════════════════════════════════════════════════════════════════

KEY_MOMENTS_MAX = 10  # server-side hard cap


async def apply_curated_result(
    conn: Any,
    recording_uuid: str,
    recording_vc_id: str,
    claimed_segments: list[dict[str, Any]],
    result: dict[str, Any],
    ws_hub: Any,
) -> None:
    """Reconcile AI curation result with the DB. All writes within one transaction."""
    events: list[tuple[str, Any]] = []
    topic_ids_for_context: list[int] = []
    speaker_changed = False

    async with conn.transaction():
        # ── 1. segment_updates (per new segment) ──────────────────────────
        claimed_by_num = {s["segment_num"]: s for s in claimed_segments}
        for seg_update in result.get("segment_updates") or []:
            seg_num = seg_update.get("segment_num")
            seg_row = claimed_by_num.get(seg_num)
            if not seg_row:
                continue
            try:
                sentiment = clamp_sentiment(seg_update.get("sentiment"))
                await conn.execute(
                    "UPDATE segment SET sentiment = %s WHERE id = %s",
                    (sentiment, seg_row["id"]),
                )
                # Speaker
                speaker_payload = seg_update.get("speaker")
                if isinstance(speaker_payload, dict):
                    if "participant_id" in speaker_payload:
                        speaker = await resolve_participant_ref(conn, speaker_payload["participant_id"])
                    elif "new_participant" in speaker_payload:
                        p = speaker_payload["new_participant"]
                        speaker = await ensure_participant(conn, p["name"], initials=p.get("initials"))
                    else:
                        speaker = None
                    if speaker:
                        await conn.execute(
                            "UPDATE segment SET participant_id = %s WHERE id = %s",
                            (speaker["id"], seg_row["id"]),
                        )
                        speaker_changed = True
                # Topic tags
                for tag in seg_update.get("topic_tags") or []:
                    try:
                        confidence = float(tag.get("confidence") or 0.0)
                        topic = None
                        if "topic_id" in tag:
                            topic = await resolve_topic_ref(conn, tag["topic_id"])
                        elif "new_topic" in tag:
                            tp = tag["new_topic"]
                            topic = await ensure_topic(conn, tp["label"], synonyms=tp.get("synonyms"), parent_topic_id=tp.get("parent_topic_id"))
                        if not topic:
                            continue
                        await conn.execute(
                            """
                            INSERT INTO segment_topic (segment_id, topic_id, confidence)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (segment_id, topic_id) DO UPDATE
                            SET confidence = GREATEST(segment_topic.confidence, EXCLUDED.confidence)
                            """,
                            (seg_row["id"], topic["id"], confidence),
                        )
                        cur = await conn.execute(
                            "INSERT INTO recording_topic (recording_id, topic_id) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING recording_id, topic_id",
                            (recording_uuid, topic["id"]),
                        )
                        if await cur.fetchone():
                            topic_ids_for_context.append(topic["id"])
                    except Exception as exc:
                        logger.warning("segment_update topic_tag failed: %s", exc)
            except Exception as exc:
                logger.warning("segment_update failed for seg %s: %s", seg_num, exc)

        # ── 2. add_synonyms ────────────────────────────────────────────────
        for syn_payload in result.get("add_synonyms") or []:
            try:
                topic = await resolve_topic_ref(conn, syn_payload.get("topic_id"))
                synonym = (syn_payload.get("synonym") or "").strip()
                if not topic or not synonym:
                    continue
                synonyms = list(topic.get("synonyms") or [])
                if synonym.lower() not in {v.lower() for v in synonyms}:
                    synonyms.append(synonym)
                    await conn.execute("UPDATE topic SET synonyms = %s WHERE id = %s", (synonyms, topic["id"]))
            except Exception as exc:
                logger.warning("add_synonym failed: %s", exc)

        # ── 3. Key moments — reconcile + enforce cap ──────────────────────
        try:
            ai_moments = result.get("key_moments") or []
            ai_ids_present = {int(m["id"]) for m in ai_moments if m.get("id")}

            # Fetch currently active moments
            active = await fetchall(
                conn,
                "SELECT id, flagged_by FROM key_moment WHERE recording_id = %s AND archived_at IS NULL",
                (recording_uuid,),
            )
            user_flagged_ids = {row["id"] for row in active if row.get("flagged_by") == "user"}

            # Archive moments not in AI list (but never user-flagged)
            for row in active:
                if row["id"] not in ai_ids_present and row["id"] not in user_flagged_ids:
                    await conn.execute(
                        "UPDATE key_moment SET archived_at = now() WHERE id = %s",
                        (row["id"],),
                    )

            # Upsert/create moments from AI list
            for m in ai_moments:
                try:
                    salience = float(m.get("salience") or 0.5)
                    quote = (m.get("quote") or "").strip()
                    if not quote:
                        continue
                    speaker_ref = m.get("speaker_ref")
                    identified = await resolve_participant_ref(conn, speaker_ref)
                    if m.get("id"):
                        # Update existing
                        await conn.execute(
                            """
                            UPDATE key_moment
                            SET type = %s, quote = %s, salience = %s,
                                speaker_participant_id = COALESCE(%s, speaker_participant_id),
                                archived_at = NULL
                            WHERE id = %s AND recording_id = %s
                            """,
                            (m["type"], quote, salience, identified["id"] if identified else None, m["id"], recording_uuid),
                        )
                    else:
                        # Create new (dedup_hash guard; un-archive if hash matches an archived row)
                        dedup = _dedup_hash(quote)
                        existing = await fetchone(
                            conn,
                            "SELECT id, archived_at FROM key_moment WHERE recording_id = %s AND dedup_hash = %s",
                            (recording_uuid, dedup),
                        )
                        if existing:
                            await conn.execute(
                                "UPDATE key_moment SET archived_at = NULL, salience = %s WHERE id = %s",
                                (salience, existing["id"]),
                            )
                        else:
                            await conn.execute(
                                """
                                INSERT INTO key_moment (recording_id, segment_id, type, quote, salience,
                                    speaker_participant_id, speaker_label, flagged_by, ts, dedup_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai', now(), %s)
                                """,
                                (
                                    recording_uuid,
                                    claimed_segments[-1]["id"],
                                    m["type"], quote, salience,
                                    identified["id"] if identified else None,
                                    identified["name"] if identified else (speaker_ref if isinstance(speaker_ref, str) else None),
                                    dedup,
                                ),
                            )
                except Exception as exc:
                    logger.warning("key_moment upsert failed: %s", exc)

            # Server-side hard cap: if >KEY_MOMENTS_MAX active, archive lowest salience AI moments first
            active_now = await fetchall(
                conn,
                "SELECT id, salience, flagged_by FROM key_moment WHERE recording_id = %s AND archived_at IS NULL ORDER BY salience DESC, id DESC",
                (recording_uuid,),
            )
            if len(active_now) > KEY_MOMENTS_MAX:
                # Keep user-flagged + highest salience AI moments
                to_keep_ids = {r["id"] for r in active_now if r.get("flagged_by") == "user"}
                remaining = [r for r in active_now if r["id"] not in to_keep_ids]
                for r in remaining[:KEY_MOMENTS_MAX - len(to_keep_ids)]:
                    to_keep_ids.add(r["id"])
                for r in active_now:
                    if r["id"] not in to_keep_ids:
                        await conn.execute("UPDATE key_moment SET archived_at = now() WHERE id = %s", (r["id"],))

            final_moments = await fetchall(
                conn,
                "SELECT * FROM key_moment WHERE recording_id = %s AND archived_at IS NULL ORDER BY salience DESC, ts",
                (recording_uuid,),
            )
            events.append(("key_moments.updated", {"items": final_moments}))
        except Exception as exc:
            logger.warning("key_moments reconcile failed: %s", exc)

        # ── 4. Action items reconcile ──────────────────────────────────────
        try:
            for ai in result.get("action_items") or []:
                try:
                    if ai.get("id"):
                        row = await fetchone(conn, "SELECT * FROM action_item WHERE id = %s AND recording_id = %s", (ai["id"], recording_uuid))
                        if not row:
                            continue
                        if ai.get("archive"):
                            await conn.execute("UPDATE action_item SET archived_at = now() WHERE id = %s", (ai["id"],))
                            continue
                        due_date = None
                        if ai.get("due_date"):
                            try:
                                due_date = date.fromisoformat(ai["due_date"])
                            except ValueError:
                                pass
                        owner = await resolve_participant_ref(conn, ai.get("owner_ref"), create=True) if ai.get("owner_ref") else None
                        await conn.execute(
                            """
                            UPDATE action_item SET
                                status = COALESCE(%s, status),
                                owner_participant_id = COALESCE(%s, owner_participant_id),
                                due_date = COALESCE(%s, due_date)
                            WHERE id = %s
                            """,
                            (ai.get("status"), owner["id"] if owner else None, due_date, ai["id"]),
                        )
                    else:
                        # Create new
                        desc = (ai.get("description") or "").strip()
                        if not desc:
                            continue
                        dedup = _dedup_hash(desc)
                        existing = await fetchone(conn, "SELECT id, archived_at FROM action_item WHERE recording_id = %s AND dedup_hash = %s", (recording_uuid, dedup))
                        if existing:
                            if existing.get("archived_at"):
                                await conn.execute("UPDATE action_item SET archived_at = NULL WHERE id = %s", (existing["id"],))
                            continue
                        topic = await resolve_topic_ref(conn, ai.get("topic_ref"), create=True)
                        owner = await resolve_participant_ref(conn, ai.get("owner_ref"), create=True)
                        due_date = None
                        if ai.get("due_date"):
                            try:
                                due_date = date.fromisoformat(ai["due_date"])
                            except ValueError:
                                pass
                        await conn.execute(
                            """
                            INSERT INTO action_item (recording_id, description, owner_participant_id, due_date, status, topic_id, segment_id, dedup_hash)
                            VALUES (%s, %s, %s, %s, 'open', %s, %s, %s)
                            """,
                            (recording_uuid, desc, owner["id"] if owner else None, due_date, topic["id"] if topic else None, claimed_segments[-1]["id"], dedup),
                        )
                except Exception as exc:
                    logger.warning("action_item reconcile failed: %s", exc)
            active_actions = await fetchall(conn, "SELECT ai.*, p.name AS owner_name FROM action_item ai LEFT JOIN participant p ON p.id = ai.owner_participant_id WHERE ai.recording_id = %s AND ai.archived_at IS NULL ORDER BY ai.id", (recording_uuid,))
            events.append(("action_items.updated", {"items": active_actions}))
        except Exception as exc:
            logger.warning("action_items reconcile failed: %s", exc)

        # ── 5. Decisions reconcile ─────────────────────────────────────────
        try:
            for dec in result.get("decisions") or []:
                try:
                    if dec.get("id"):
                        row = await fetchone(conn, "SELECT * FROM decision WHERE id = %s AND recording_id = %s", (dec["id"], recording_uuid))
                        if not row:
                            continue
                        if dec.get("archive"):
                            await conn.execute("UPDATE decision SET archived_at = now() WHERE id = %s", (dec["id"],))
                            continue
                        new_status = dec.get("status") or row["status"]
                        # Apply upgrade rules
                        if row["status"] == "agreed" and new_status != "agreed":
                            new_status = "agreed"
                        await conn.execute("UPDATE decision SET status = %s WHERE id = %s", (new_status, dec["id"]))
                    else:
                        desc = (dec.get("description") or "").strip()
                        if not desc:
                            continue
                        dedup = _dedup_hash(desc)
                        existing = await fetchone(conn, "SELECT id, archived_at FROM decision WHERE recording_id = %s AND dedup_hash = %s", (recording_uuid, dedup))
                        if existing:
                            if existing.get("archived_at"):
                                await conn.execute("UPDATE decision SET archived_at = NULL, status = %s WHERE id = %s", (dec.get("status", "concept"), existing["id"]))
                            continue
                        topic = await resolve_topic_ref(conn, dec.get("topic_ref"), create=True)
                        await conn.execute(
                            "INSERT INTO decision (recording_id, description, status, segment_id, decided_at, topic_id, dedup_hash) VALUES (%s, %s, %s, %s, now(), %s, %s)",
                            (recording_uuid, desc, dec.get("status", "concept"), claimed_segments[-1]["id"], topic["id"] if topic else None, dedup),
                        )
                except Exception as exc:
                    logger.warning("decision reconcile failed: %s", exc)
            active_decisions = await fetchall(conn, "SELECT * FROM decision WHERE recording_id = %s AND archived_at IS NULL ORDER BY decided_at", (recording_uuid,))
            events.append(("decisions.updated", {"items": active_decisions}))
        except Exception as exc:
            logger.warning("decisions reconcile failed: %s", exc)

        # ── 6. Goals ──────────────────────────────────────────────────────
        try:
            for gu in result.get("goal_updates") or []:
                try:
                    goal = await fetchone(conn, "SELECT * FROM goal WHERE id = %s AND recording_id = %s", (gu["goal_id"], recording_uuid))
                    if not goal:
                        continue
                    new_status = apply_goal_latch(goal["status"], gu["status"])
                    await conn.execute(
                        """
                        UPDATE goal SET status = %s,
                            coaching_tip = COALESCE(%s, coaching_tip),
                            achieved_at = CASE WHEN %s = 'achieved' THEN COALESCE(achieved_at, now()) ELSE achieved_at END
                        WHERE id = %s
                        """,
                        (new_status, gu.get("coaching_tip"), new_status, goal["id"]),
                    )
                    updated = await fetchone(conn, "SELECT * FROM goal WHERE id = %s", (goal["id"],))
                    events.append(("goal.updated", updated))
                except Exception as exc:
                    logger.warning("goal_update failed: %s", exc)
            for gp in result.get("new_goals") or []:
                try:
                    topic = await resolve_topic_ref(conn, gp.get("topic_ref"), create=True)
                    cur = await conn.execute(
                        "INSERT INTO goal (recording_id, description, coaching_tip, status, topic_id, source) VALUES (%s, %s, %s, 'open', %s, 'ai') RETURNING *",
                        (recording_uuid, gp["description"], gp.get("coaching_tip"), topic["id"] if topic else None),
                    )
                    events.append(("goal.updated", await cur.fetchone()))
                except Exception as exc:
                    logger.warning("new_goal failed: %s", exc)
        except Exception as exc:
            logger.warning("goals reconcile failed: %s", exc)

        # ── 7. Agenda ─────────────────────────────────────────────────────
        try:
            agenda_payload = result.get("agenda")
            recording_row = await fetchone(conn, "SELECT agenda_mode FROM recording WHERE id = %s", (recording_uuid,))
            agenda_mode = (recording_row or {}).get("agenda_mode") or "dynamic"
            if isinstance(agenda_payload, dict):
                active_item_id = agenda_payload.get("active_item_id")
                if active_item_id:
                    await conn.execute(
                        "UPDATE agenda_item SET status = 'done', ended_at = COALESCE(ended_at, now()) WHERE recording_id = %s AND status = 'active' AND id <> %s",
                        (recording_uuid, active_item_id),
                    )
                    await conn.execute(
                        "UPDATE agenda_item SET status = 'active', started_at = COALESCE(started_at, now()) WHERE recording_id = %s AND id = %s AND status <> 'done'",
                        (recording_uuid, active_item_id),
                    )
                for item_op in agenda_payload.get("items") or []:
                    try:
                        item_id = item_op.get("id")
                        if item_id:
                            # Verify this ID actually exists for this recording
                            existing = await fetchone(
                                conn,
                                "SELECT id FROM agenda_item WHERE id = %s AND recording_id = %s",
                                (item_id, recording_uuid),
                            )
                        else:
                            existing = None
                        if item_id and existing:
                            # Status change — allowed in both modes
                            new_status = item_op.get("status")
                            if new_status and new_status != "active":  # active handled above
                                await conn.execute(
                                    "UPDATE agenda_item SET status = %s WHERE id = %s AND recording_id = %s AND status <> 'done'",
                                    (new_status, item_id, recording_uuid),
                                )
                        elif agenda_mode == "dynamic" and item_op.get("title"):
                            # Create new item (also handles AI hallucinating a non-existent id)
                            topic = await resolve_topic_ref(conn, item_op.get("topic_ref"), create=True)
                            next_pos = await fetchone(conn, "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM agenda_item WHERE recording_id = %s", (recording_uuid,))
                            await conn.execute(
                                "INSERT INTO agenda_item (recording_id, title, position, status, topic_id, source, started_at) VALUES (%s, %s, %s, 'active', %s, 'ai', now())",
                                (recording_uuid, item_op["title"], next_pos["p"], topic["id"] if topic else None),
                            )
                            await conn.execute(
                                "UPDATE agenda_item SET status = 'done', ended_at = COALESCE(ended_at, now()) WHERE recording_id = %s AND status = 'active' AND id < (SELECT MAX(id) FROM agenda_item WHERE recording_id = %s)",
                                (recording_uuid, recording_uuid),
                            )
                        elif agenda_mode == "apriori" and not (item_id and existing):
                            logger.debug("Ignored AI agenda create in apriori mode: %s", item_op.get("title"))
                    except Exception as exc:
                        logger.warning("agenda item_op failed: %s", exc)
                events.append(("agenda.updated", {"items": await _agenda_rows(conn, recording_uuid)}))
        except Exception as exc:
            logger.warning("agenda reconcile failed: %s", exc)

        # ── 8. Speaker stats + tone + header ──────────────────────────────
        if speaker_changed:
            participant_stats = await _participant_stats(conn, recording_uuid, recording_vc_id)
            events.append(("participant.stats", {"participants": participant_stats}))
        events.append(("sentiment.updated", await _tone_payload(conn, recording_uuid)))
        events.append(("header.stats", await _header_stats(conn, recording_uuid)))

    for event_type, payload in events:
        await ws_hub.broadcast(recording_vc_id, event_type, payload)
    for topic_id in topic_ids_for_context:
        await auto_check(conn, ws_hub, recording_uuid, topic_id)

