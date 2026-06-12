"""Read APIs for dashboard snapshots and lists."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from dashboard.api.setup import get_recording_row
from dashboard.db import fetchall, get_db_connection
from dashboard.stats import TONE_WINDOW_SIZE, apply_overdue, header_stats, speaking_ratios, tone_window

router = APIRouter(tags=["read"])


@router.get("/recordings/{recording_id}/snapshot")
async def recording_snapshot(recording_id: str, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    participants = speaking_ratios(
        await fetchall(
            conn,
            """
            SELECT p.id, p.name, p.initials, p.is_user, rp.role, rp.speaking_time_ratio, rp.speaking_seconds, rp.source
            FROM recording_participant rp
            JOIN participant p ON p.id = rp.participant_id
            WHERE rp.recording_id = %s
            ORDER BY rp.speaking_time_ratio DESC, lower(p.name)
            """,
            (recording["recording_id"],),
        )
    )
    goals = await fetchall(
        conn,
        """
        SELECT g.*, t.label AS topic_label
        FROM goal g
        LEFT JOIN topic t ON t.id = g.topic_id
        WHERE g.recording_id = %s
        ORDER BY CASE g.status WHEN 'at_risk' THEN 0 WHEN 'open' THEN 1 ELSE 2 END, g.created_at
        """,
        (recording["id"],),
    )
    agenda_items = await fetchall(
        conn,
        """
        SELECT a.*, t.label AS topic_label
        FROM agenda_item a
        LEFT JOIN topic t ON t.id = a.topic_id
        WHERE a.recording_id = %s
        ORDER BY a.position
        """,
        (recording["id"],),
    )
    decisions = await fetchall(
        conn,
        """
        SELECT d.*, t.label AS topic_label
        FROM decision d
        LEFT JOIN topic t ON t.id = d.topic_id
        WHERE d.recording_id = %s AND d.archived_at IS NULL
        ORDER BY d.decided_at DESC, d.id DESC
        """,
        (recording["id"],),
    )
    action_items = apply_overdue(
        await fetchall(
            conn,
            """
            SELECT a.*, t.label AS topic_label, p.name AS owner_name, p.initials AS owner_initials, p.is_user AS owner_is_user
            FROM action_item a
            LEFT JOIN topic t ON t.id = a.topic_id
            LEFT JOIN participant p ON p.id = a.owner_participant_id
            WHERE a.recording_id = %s AND a.archived_at IS NULL
            ORDER BY a.id DESC
            """,
            (recording["id"],),
        )
    )
    key_moments = await fetchall(
        conn,
        """
        SELECT km.*, p.name AS speaker_name
        FROM key_moment km
        LEFT JOIN participant p ON p.id = km.speaker_participant_id
        WHERE km.recording_id = %s AND km.archived_at IS NULL
        ORDER BY km.salience DESC, km.ts DESC
        LIMIT 10
        """,
        (recording["id"],),
    )
    past_references = await fetchall(
        conn,
        """
        SELECT pr.*, t.label AS topic_label, sr.recording_id AS source_vc_recording_id, sr.title AS source_title, sr.started_at AS source_started_at
        FROM past_reference pr
        JOIN topic t ON t.id = pr.topic_id
        JOIN recording sr ON sr.id = pr.source_recording_id
        WHERE pr.recording_id = %s
        ORDER BY pr.created_at DESC, pr.id DESC
        """,
        (recording["id"],),
    )
    sentiments = await fetchall(
        conn,
        f"SELECT sentiment FROM segment WHERE recording_id = %s AND sentiment IS NOT NULL ORDER BY id DESC LIMIT {TONE_WINDOW_SIZE}",
        (recording["id"],),
    )
    tone = tone_window([row["sentiment"] for row in reversed(sentiments)])
    return {
        "recording": recording,
        "participants": participants,
        "goals": goals,
        "agenda_items": agenda_items,
        "decisions": decisions,
        "action_items": action_items,
        "key_moments": key_moments,
        "past_references": past_references,
        "tone": tone,
        "header_stats": header_stats(participants, goals, action_items, decisions),
    }


@router.get("/recordings")
async def list_recordings(
    status: str | None = Query(default=None, pattern="^(live|ended)$"),
    conn: Any = Depends(get_db_connection),
) -> list[dict[str, Any]]:
    if status:
        return await fetchall(
            conn,
            """
            SELECT id, recording_id, title, started_at, ended_at, status, agenda_mode
            FROM recording
            WHERE status = %s
            ORDER BY started_at DESC NULLS LAST, recording_id DESC
            """,
            (status,),
        )
    return await fetchall(
        conn,
        """
        SELECT id, recording_id, title, started_at, ended_at, status, agenda_mode
        FROM recording
        ORDER BY CASE status WHEN 'live' THEN 0 ELSE 1 END,
                 started_at DESC NULLS LAST,
                 recording_id DESC
        """,
    )


@router.get("/recordings/{recording_id}/segments")
async def list_segments(
    recording_id: str,
    after: int = Query(default=0, ge=0),
    conn: Any = Depends(get_db_connection),
) -> list[dict[str, Any]]:
    recording = await get_recording_row(conn, recording_id)
    return await fetchall(
        conn,
        """
        SELECT s.*, p.name AS participant_name
        FROM segment s
        LEFT JOIN participant p ON p.id = s.participant_id
        WHERE s.recording_id = %s AND s.segment_num > %s
        ORDER BY s.segment_num
        LIMIT 200
        """,
        (recording["id"], after),
    )
