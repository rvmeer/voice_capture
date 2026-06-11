"""Recording and segment ingest endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dashboard.api.setup import consume_apriori_setup, get_recording_row
from dashboard.api.ws import ws_hub
from dashboard.db import fetchall, fetchone, get_db_connection

router = APIRouter(prefix="/ingest", tags=["ingest"])


class RecordingStartRequest(BaseModel):
    recording_id: str
    title: str | None = None
    started_at: datetime


class SegmentRequest(BaseModel):
    segment_num: int
    text: str
    ts: datetime
    speaker_label: str | None = None
    duration_seconds: float | None = None


class RecordingEndRequest(BaseModel):
    ended_at: datetime


@router.post("/recordings")
async def ingest_recording(body: RecordingStartRequest, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    title = body.title or body.recording_id
    async with conn.transaction():
        cur = await conn.execute(
            """
            INSERT INTO recording (recording_id, title, started_at, status)
            VALUES (%s, %s, %s, 'live')
            ON CONFLICT (recording_id) DO UPDATE
            SET title = EXCLUDED.title,
                started_at = COALESCE(recording.started_at, EXCLUDED.started_at),
                status = 'live'
            RETURNING id, recording_id
            """,
            (body.recording_id, title, body.started_at),
        )
        row = await cur.fetchone()
        await consume_apriori_setup(conn, row["id"], row["recording_id"], title)
    await ws_hub.broadcast(body.recording_id, "recording.status", {"status": "live", "ended_at": None})
    return row


@router.post("/recordings/{recording_id}/segments")
async def ingest_segment(recording_id: str, body: SegmentRequest, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    cur = await conn.execute(
        """
        INSERT INTO segment (recording_id, segment_num, text, speaker_label, ts, duration_seconds)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (recording_id, segment_num) DO NOTHING
        RETURNING id, recording_id, segment_num, text, speaker_label, participant_id, ts, duration_seconds, sentiment, ai_status, ai_processed_at, ai_attempts
        """,
        (recording["id"], body.segment_num, body.text, body.speaker_label, body.ts, body.duration_seconds),
    )
    row = await cur.fetchone()
    await conn.commit()
    if row:
        await ws_hub.broadcast(recording["recording_id"], "segment.created", row)
        return row
    existing = await fetchone(
        conn,
        """
        SELECT id, recording_id, segment_num, text, speaker_label, participant_id, ts, duration_seconds, sentiment, ai_status, ai_processed_at, ai_attempts
        FROM segment
        WHERE recording_id = %s AND segment_num = %s
        """,
        (recording["id"], body.segment_num),
    )
    return existing


@router.post("/recordings/{recording_id}/end")
async def end_recording(recording_id: str, body: RecordingEndRequest, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    async with conn.transaction():
        cur = await conn.execute(
            """
            UPDATE recording
            SET status = 'ended', ended_at = %s
            WHERE id = %s
            RETURNING id, recording_id, status, ended_at
            """,
            (body.ended_at, recording["id"]),
        )
        row = await cur.fetchone()
        await conn.execute(
            """
            UPDATE agenda_item
            SET status = 'done', ended_at = COALESCE(ended_at, %s)
            WHERE recording_id = %s AND status = 'active'
            """,
            (body.ended_at, recording["id"]),
        )
    agenda_rows = await fetchall(
        conn,
        "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position",
        (recording["id"],),
    )
    await ws_hub.broadcast(recording["recording_id"], "agenda.updated", {"items": agenda_rows})
    await ws_hub.broadcast(recording["recording_id"], "recording.status", {"status": "ended", "ended_at": body.ended_at})
    return row
