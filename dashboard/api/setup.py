"""Setup and CRUD API for a-priori meeting context."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dashboard.api.ws import ws_hub
from dashboard.context import past_refs
from dashboard.db import fetchall, fetchone, get_db_connection
from dashboard.stats import header_stats

router = APIRouter(tags=["setup"])


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _dedup_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()[:16]


async def get_recording_row(conn: Any, recording_id: str) -> dict[str, Any]:
    row = await fetchone(
        conn,
        """
        SELECT id, recording_id, title, started_at, ended_at, status
        FROM recording
        WHERE recording_id = %s OR id::text = %s
        """,
        (recording_id, recording_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    return row


async def ensure_participant(
    conn: Any,
    name: str,
    *,
    initials: str | None = None,
    is_user: bool | None = None,
) -> dict[str, Any]:
    existing = await fetchone(conn, "SELECT id, name, initials, is_user FROM participant WHERE lower(name) = lower(%s)", (name,))
    if existing:
        await conn.execute(
            """
            UPDATE participant
            SET initials = COALESCE(%s, initials),
                is_user = COALESCE(%s, is_user)
            WHERE id = %s
            """,
            (initials, is_user, existing["id"]),
        )
        return await fetchone(conn, "SELECT id, name, initials, is_user FROM participant WHERE id = %s", (existing["id"],))
    cur = await conn.execute(
        """
        INSERT INTO participant (name, initials, is_user)
        VALUES (%s, %s, COALESCE(%s, false))
        RETURNING id, name, initials, is_user
        """,
        (name, initials, is_user),
    )
    return await cur.fetchone()


async def resolve_participant_ref(conn: Any, ref: Any, *, create: bool = False) -> dict[str, Any] | None:
    if ref in (None, ""):
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return await fetchone(conn, "SELECT id, name, initials, is_user FROM participant WHERE id = %s", (int(ref),))
    if isinstance(ref, str):
        row = await fetchone(conn, "SELECT id, name, initials, is_user FROM participant WHERE lower(name) = lower(%s)", (ref,))
        if row or not create:
            return row
        return await ensure_participant(conn, ref)
    return None


async def ensure_topic(
    conn: Any,
    label: str,
    *,
    synonyms: list[str] | None = None,
    parent_topic_id: int | None = None,
) -> dict[str, Any]:
    synonyms = [item.strip() for item in (synonyms or []) if item and item.strip()]
    existing = await fetchone(
        conn,
        """
        SELECT id, label, synonyms, parent_topic_id, occurrence_count, created_at
        FROM topic
        WHERE lower(label) = lower(%s)
           OR EXISTS (
               SELECT 1
               FROM unnest(synonyms) AS synonym
               WHERE lower(synonym) = lower(%s)
           )
        LIMIT 1
        """,
        (label, label),
    )
    if existing:
        merged = list(existing.get("synonyms") or [])
        seen = {item.lower() for item in merged}
        for synonym in synonyms:
            if synonym.lower() not in seen:
                merged.append(synonym)
                seen.add(synonym.lower())
        await conn.execute(
            """
            UPDATE topic
            SET synonyms = %s,
                parent_topic_id = COALESCE(%s, parent_topic_id)
            WHERE id = %s
            """,
            (merged, parent_topic_id, existing["id"]),
        )
        return await fetchone(conn, "SELECT * FROM topic WHERE id = %s", (existing["id"],))
    cur = await conn.execute(
        """
        INSERT INTO topic (label, synonyms, parent_topic_id)
        VALUES (%s, %s, %s)
        RETURNING *
        """,
        (label, synonyms, parent_topic_id),
    )
    return await cur.fetchone()


async def resolve_topic_ref(conn: Any, ref: Any, *, create: bool = False) -> dict[str, Any] | None:
    if ref in (None, ""):
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return await fetchone(conn, "SELECT * FROM topic WHERE id = %s", (int(ref),))
    if isinstance(ref, str):
        row = await fetchone(
            conn,
            """
            SELECT * FROM topic
            WHERE lower(label) = lower(%s)
               OR EXISTS (
                   SELECT 1
                   FROM unnest(synonyms) AS synonym
                   WHERE lower(synonym) = lower(%s)
               )
            LIMIT 1
            """,
            (ref, ref),
        )
        if row or not create:
            return row
        return await ensure_topic(conn, ref)
    return None


async def _recording_stats(conn: Any, vc_recording_id: str) -> dict[str, int]:
    participants = await fetchall(
        conn,
        "SELECT participant_id FROM recording_participant WHERE recording_id = %s",
        (vc_recording_id,),
    )
    goals = await fetchall(conn, "SELECT status FROM goal g JOIN recording r ON r.id = g.recording_id WHERE r.recording_id = %s", (vc_recording_id,))
    actions = await fetchall(conn, "SELECT id FROM action_item a JOIN recording r ON r.id = a.recording_id WHERE r.recording_id = %s", (vc_recording_id,))
    decisions = await fetchall(conn, "SELECT id FROM decision d JOIN recording r ON r.id = d.recording_id WHERE r.recording_id = %s", (vc_recording_id,))
    return header_stats(participants, goals, actions, decisions)


async def consume_apriori_setup(conn: Any, recording_uuid: str, recording_vc_id: str, title: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        """
        SELECT id, recording_title_hint, payload
        FROM apriori_setup
        WHERE consumed = false
          AND (
              recording_title_hint IS NULL
              OR lower(recording_title_hint) = lower(%s)
              OR lower(recording_title_hint) = lower(%s)
          )
        ORDER BY CASE WHEN recording_title_hint IS NULL THEN 1 ELSE 0 END,
                 created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """,
        (title, recording_vc_id),
    )
    row = await cur.fetchone()
    if not row:
        return None
    payload = row.get("payload") or {}
    created = {"participants": 0, "topics": 0, "goals": 0, "agenda_items": 0}
    for participant_payload in payload.get("participants", []):
        if isinstance(participant_payload, str):
            participant_payload = {"name": participant_payload}
        participant = await ensure_participant(
            conn,
            participant_payload["name"],
            initials=participant_payload.get("initials"),
            is_user=participant_payload.get("is_user"),
        )
        await conn.execute(
            """
            INSERT INTO recording_participant (recording_id, participant_id, role, source)
            VALUES (%s, %s, %s, COALESCE(%s, 'apriori'))
            ON CONFLICT (recording_id, participant_id) DO UPDATE
            SET role = COALESCE(EXCLUDED.role, recording_participant.role),
                source = EXCLUDED.source
            """,
            (
                recording_vc_id,
                participant["id"],
                participant_payload.get("role"),
                participant_payload.get("source", "apriori"),
            ),
        )
        created["participants"] += 1
    for topic_payload in payload.get("topics", []):
        if isinstance(topic_payload, str):
            topic_payload = {"label": topic_payload}
        topic = await ensure_topic(
            conn,
            topic_payload["label"],
            synonyms=topic_payload.get("synonyms"),
            parent_topic_id=topic_payload.get("parent_topic_id"),
        )
        await conn.execute(
            "INSERT INTO recording_topic (recording_id, topic_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (recording_uuid, topic["id"]),
        )
        created["topics"] += 1
    for index, agenda_payload in enumerate(payload.get("agenda_items", payload.get("agenda", [])), start=1):
        topic = await resolve_topic_ref(conn, agenda_payload.get("topic_ref"), create=True)
        position = agenda_payload.get("position") or index
        await conn.execute(
            """
            INSERT INTO agenda_item (recording_id, title, position, status, topic_id, source, started_at, ended_at)
            VALUES (%s, %s, %s, COALESCE(%s, 'pending'), %s, COALESCE(%s, 'apriori'), %s, %s)
            ON CONFLICT (recording_id, position) DO UPDATE
            SET title = EXCLUDED.title,
                topic_id = COALESCE(EXCLUDED.topic_id, agenda_item.topic_id),
                source = EXCLUDED.source
            """,
            (
                recording_uuid,
                agenda_payload["title"],
                position,
                agenda_payload.get("status"),
                topic["id"] if topic else None,
                agenda_payload.get("source", "apriori"),
                agenda_payload.get("started_at"),
                agenda_payload.get("ended_at"),
            ),
        )
        created["agenda_items"] += 1
    for goal_payload in payload.get("goals", []):
        topic = await resolve_topic_ref(conn, goal_payload.get("topic_ref"), create=True)
        await conn.execute(
            """
            INSERT INTO goal (recording_id, description, coaching_tip, status, topic_id, source)
            VALUES (%s, %s, %s, COALESCE(%s, 'open'), %s, COALESCE(%s, 'apriori'))
            """,
            (
                recording_uuid,
                goal_payload["description"],
                goal_payload.get("coaching_tip"),
                goal_payload.get("status"),
                topic["id"] if topic else None,
                goal_payload.get("source", "apriori"),
            ),
        )
        created["goals"] += 1
    await conn.execute("UPDATE apriori_setup SET consumed = true WHERE id = %s", (row["id"],))
    return created


class PrecreateRequest(BaseModel):
    recording_title_hint: str | None = None
    payload: dict[str, Any]


class ParticipantCreate(BaseModel):
    name: str
    initials: str | None = None
    is_user: bool | None = None
    role: str | None = None
    source: str = "apriori"


class ParticipantPatch(BaseModel):
    name: str | None = None
    initials: str | None = None
    is_user: bool | None = None
    role: str | None = None
    source: str | None = None


class TopicCreate(BaseModel):
    label: str
    synonyms: list[str] = Field(default_factory=list)
    parent_topic_id: int | None = None


class TopicPatch(BaseModel):
    label: str | None = None
    synonyms: list[str] | None = None
    parent_topic_id: int | None = None


class GoalCreate(BaseModel):
    description: str
    coaching_tip: str | None = None
    status: str = "open"
    topic_ref: int | str | None = None
    source: str = "apriori"


class GoalPatch(BaseModel):
    description: str | None = None
    coaching_tip: str | None = None
    status: str | None = None
    topic_ref: int | str | None = None
    achieved_at: datetime | None = None


class AgendaItemCreate(BaseModel):
    title: str
    position: int | None = None
    status: str = "pending"
    topic_ref: int | str | None = None
    source: str = "apriori"
    started_at: datetime | None = None
    ended_at: datetime | None = None


class AgendaItemPatch(BaseModel):
    title: str | None = None
    position: int | None = None
    status: str | None = None
    topic_ref: int | str | None = None
    source: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class KeyMomentCreate(BaseModel):
    type: str
    quote: str
    speaker_ref: int | str | None = None
    speaker_label: str | None = None
    ts: datetime | None = None


@router.post("/recordings/precreate")
async def precreate_recording(body: PrecreateRequest, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    cur = await conn.execute(
        """
        INSERT INTO apriori_setup (recording_title_hint, payload)
        VALUES (%s, %s)
        RETURNING id, recording_title_hint, payload, created_at, consumed
        """,
        (body.recording_title_hint, body.payload),
    )
    await conn.commit()
    return await cur.fetchone()


@router.post("/recordings/{recording_id}/participants")
async def create_participant(recording_id: str, body: ParticipantCreate, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    participant = await ensure_participant(conn, body.name, initials=body.initials, is_user=body.is_user)
    await conn.execute(
        """
        INSERT INTO recording_participant (recording_id, participant_id, role, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (recording_id, participant_id) DO UPDATE
        SET role = COALESCE(EXCLUDED.role, recording_participant.role),
            source = EXCLUDED.source
        """,
        (recording["recording_id"], participant["id"], body.role, body.source),
    )
    await conn.commit()
    row = await fetchone(
        conn,
        """
        SELECT p.id, p.name, p.initials, p.is_user, rp.role, rp.speaking_time_ratio, rp.speaking_seconds, rp.source
        FROM participant p
        JOIN recording_participant rp ON rp.participant_id = p.id
        WHERE rp.recording_id = %s AND p.id = %s
        """,
        (recording["recording_id"], participant["id"]),
    )
    await ws_hub.broadcast(recording["recording_id"], "header.stats", await _recording_stats(conn, recording["recording_id"]))
    return row


@router.patch("/recordings/{recording_id}/participants/{participant_id}")
async def patch_participant(recording_id: str, participant_id: int, body: ParticipantPatch, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    participant = await fetchone(conn, "SELECT id FROM participant WHERE id = %s", (participant_id,))
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    await conn.execute(
        """
        UPDATE participant
        SET name = COALESCE(%s, name),
            initials = COALESCE(%s, initials),
            is_user = COALESCE(%s, is_user)
        WHERE id = %s
        """,
        (body.name, body.initials, body.is_user, participant_id),
    )
    await conn.execute(
        """
        UPDATE recording_participant
        SET role = COALESCE(%s, role),
            source = COALESCE(%s, source)
        WHERE recording_id = %s AND participant_id = %s
        """,
        (body.role, body.source, recording["recording_id"], participant_id),
    )
    await conn.commit()
    return await fetchone(
        conn,
        """
        SELECT p.id, p.name, p.initials, p.is_user, rp.role, rp.speaking_time_ratio, rp.speaking_seconds, rp.source
        FROM participant p
        JOIN recording_participant rp ON rp.participant_id = p.id
        WHERE rp.recording_id = %s AND p.id = %s
        """,
        (recording["recording_id"], participant_id),
    )


@router.post("/recordings/{recording_id}/topics")
async def create_topic(recording_id: str, body: TopicCreate, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    topic = await ensure_topic(conn, body.label, synonyms=body.synonyms, parent_topic_id=body.parent_topic_id)
    await conn.execute(
        "INSERT INTO recording_topic (recording_id, topic_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (recording["id"], topic["id"]),
    )
    await conn.commit()
    return await fetchone(conn, "SELECT * FROM topic WHERE id = %s", (topic["id"],))


@router.patch("/recordings/{recording_id}/topics/{topic_id}")
async def patch_topic(recording_id: str, topic_id: int, body: TopicPatch, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    await get_recording_row(conn, recording_id)
    topic = await fetchone(conn, "SELECT * FROM topic WHERE id = %s", (topic_id,))
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    synonyms = topic.get("synonyms") if body.synonyms is None else body.synonyms
    await conn.execute(
        """
        UPDATE topic
        SET label = COALESCE(%s, label),
            synonyms = %s,
            parent_topic_id = COALESCE(%s, parent_topic_id)
        WHERE id = %s
        """,
        (body.label, synonyms, body.parent_topic_id, topic_id),
    )
    await conn.commit()
    return await fetchone(conn, "SELECT * FROM topic WHERE id = %s", (topic_id,))


@router.post("/recordings/{recording_id}/goals")
async def create_goal(recording_id: str, body: GoalCreate, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    topic = await resolve_topic_ref(conn, body.topic_ref, create=True)
    cur = await conn.execute(
        """
        INSERT INTO goal (recording_id, description, coaching_tip, status, topic_id, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (recording["id"], body.description, body.coaching_tip, body.status, topic["id"] if topic else None, body.source),
    )
    row = await cur.fetchone()
    await conn.commit()
    await ws_hub.broadcast(recording["recording_id"], "goal.updated", row)
    await ws_hub.broadcast(recording["recording_id"], "header.stats", await _recording_stats(conn, recording["recording_id"]))
    return row


@router.patch("/recordings/{recording_id}/goals/{goal_id}")
async def patch_goal(recording_id: str, goal_id: int, body: GoalPatch, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    topic = await resolve_topic_ref(conn, body.topic_ref, create=True) if body.topic_ref is not None else None
    await conn.execute(
        """
        UPDATE goal
        SET description = COALESCE(%s, description),
            coaching_tip = COALESCE(%s, coaching_tip),
            status = COALESCE(%s, status),
            topic_id = COALESCE(%s, topic_id),
            achieved_at = CASE
                WHEN COALESCE(%s, status) = 'achieved' THEN COALESCE(%s, achieved_at, now())
                ELSE achieved_at
            END
        WHERE id = %s AND recording_id = %s
        """,
        (
            body.description,
            body.coaching_tip,
            body.status,
            topic["id"] if topic else None,
            body.status,
            body.achieved_at,
            goal_id,
            recording["id"],
        ),
    )
    await conn.commit()
    row = await fetchone(conn, "SELECT * FROM goal WHERE id = %s", (goal_id,))
    await ws_hub.broadcast(recording["recording_id"], "goal.updated", row)
    return row


@router.post("/recordings/{recording_id}/agenda_items")
async def create_agenda_item(recording_id: str, body: AgendaItemCreate, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    topic = await resolve_topic_ref(conn, body.topic_ref, create=True)
    position = body.position
    if position is None:
        row = await fetchone(conn, "SELECT COALESCE(MAX(position), 0) + 1 AS next_pos FROM agenda_item WHERE recording_id = %s", (recording["id"],))
        position = row["next_pos"]
    cur = await conn.execute(
        """
        INSERT INTO agenda_item (recording_id, title, position, status, topic_id, source, started_at, ended_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (recording["id"], body.title, position, body.status, topic["id"] if topic else None, body.source, body.started_at, body.ended_at),
    )
    row = await cur.fetchone()
    await conn.commit()
    agenda = await fetchall(conn, "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position", (recording["id"],))
    await ws_hub.broadcast(recording["recording_id"], "agenda.updated", {"items": agenda})
    return row


@router.patch("/recordings/{recording_id}/agenda_items/{agenda_item_id}")
async def patch_agenda_item(recording_id: str, agenda_item_id: int, body: AgendaItemPatch, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    topic = await resolve_topic_ref(conn, body.topic_ref, create=True) if body.topic_ref is not None else None
    await conn.execute(
        """
        UPDATE agenda_item
        SET title = COALESCE(%s, title),
            position = COALESCE(%s, position),
            status = COALESCE(%s, status),
            topic_id = COALESCE(%s, topic_id),
            source = COALESCE(%s, source),
            started_at = COALESCE(%s, started_at),
            ended_at = COALESCE(%s, ended_at)
        WHERE id = %s AND recording_id = %s
        """,
        (body.title, body.position, body.status, topic["id"] if topic else None, body.source, body.started_at, body.ended_at, agenda_item_id, recording["id"]),
    )
    await conn.commit()
    row = await fetchone(conn, "SELECT * FROM agenda_item WHERE id = %s", (agenda_item_id,))
    agenda = await fetchall(conn, "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position", (recording["id"],))
    await ws_hub.broadcast(recording["recording_id"], "agenda.updated", {"items": agenda})
    return row


@router.post("/recordings/{recording_id}/key_moments")
async def create_key_moment(recording_id: str, body: KeyMomentCreate, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    speaker = await resolve_participant_ref(conn, body.speaker_ref)
    cur = await conn.execute(
        """
        INSERT INTO key_moment (recording_id, segment_id, type, quote, speaker_participant_id, speaker_label, flagged_by, ts, dedup_hash)
        VALUES (%s, NULL, %s, %s, %s, %s, 'user', COALESCE(%s, now()), %s)
        ON CONFLICT (recording_id, dedup_hash) DO UPDATE
        SET flagged_by = 'user',
            speaker_participant_id = COALESCE(EXCLUDED.speaker_participant_id, key_moment.speaker_participant_id),
            speaker_label = COALESCE(EXCLUDED.speaker_label, key_moment.speaker_label)
        RETURNING *
        """,
        (
            recording["id"],
            body.type,
            body.quote,
            speaker["id"] if speaker else None,
            body.speaker_label or (speaker["name"] if speaker else None),
            body.ts,
            _dedup_hash(body.quote),
        ),
    )
    row = await cur.fetchone()
    await conn.commit()
    await ws_hub.broadcast(recording["recording_id"], "key_moment.created", row)
    return row


@router.post("/recordings/{recording_id}/topics/{topic_id}/dig_deeper")
async def dig_deeper_topic(recording_id: str, topic_id: int, conn: Any = Depends(get_db_connection)) -> dict[str, Any]:
    recording = await get_recording_row(conn, recording_id)
    created = await past_refs.dig_deeper(conn, ws_hub, recording["id"], topic_id)
    await conn.commit()
    return {"created": created}
