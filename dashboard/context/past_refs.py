"""Cross-recording references based on topics and semantic search."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from dashboard.db import fetchall, fetchone

logger = logging.getLogger(__name__)

_VC_INTERNAL_URL = os.environ.get("VC_INTERNAL_API_URL", "http://127.0.0.1:5151")


async def _qdrant_snippets(topic_label: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Query Qdrant via the Voice Capture internal proxy (avoids embedded-storage lock)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_VC_INTERNAL_URL}/qdrant/search",
                json={"query": topic_label, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results") or []
    except Exception as exc:
        logger.debug("Qdrant proxy lookup failed for topic %r: %s", topic_label, exc)
        return []


def _build_summary(source: dict[str, Any], snippets: list[dict[str, Any]]) -> tuple[str, str]:
    summary_bits: list[str] = []
    signal = "new_context"
    if source.get("decisions"):
        summary_bits.append(f"Besluiten: {source['decisions']}")
        signal = "repeated"
    if source.get("actions"):
        summary_bits.append(f"Acties: {source['actions']}")
        signal = "repeated"
    if source.get("moments"):
        summary_bits.append(f"Momenten: {source['moments']}")
    if source.get("resolved_count"):
        signal = "resolved"
    if snippets:
        summary_bits.append("Context: " + " ".join(snippet["text"] for snippet in snippets[:2]))
    summary = " | ".join(part for part in summary_bits if part).strip()
    return signal, summary[:500] if summary else ""



async def auto_check(conn: Any, ws_hub: Any, recording_id: str, topic_id: int) -> list[dict[str, Any]]:
    current_recording = await fetchone(conn, "SELECT id, recording_id FROM recording WHERE id = %s", (recording_id,))
    topic = await fetchone(conn, "SELECT id, label FROM topic WHERE id = %s", (topic_id,))
    if not current_recording or not topic:
        return []
    sources = await fetchall(
        conn,
        """
        SELECT r.id AS source_recording_id,
               r.recording_id AS source_vc_recording_id,
               r.title,
               r.started_at,
               COALESCE(string_agg(DISTINCT d.description, '; '), '') AS decisions,
               COALESCE(string_agg(DISTINCT ai.description, '; '), '') AS actions,
               COALESCE(string_agg(DISTINCT km.quote, '; '), '') AS moments,
               COUNT(*) FILTER (WHERE ai.status = 'done') AS resolved_count
        FROM recording_topic rt
        JOIN recording r ON r.id = rt.recording_id
        LEFT JOIN decision d ON d.recording_id = r.id AND d.topic_id = rt.topic_id
        LEFT JOIN action_item ai ON ai.recording_id = r.id AND ai.topic_id = rt.topic_id
        LEFT JOIN key_moment km ON km.recording_id = r.id
        WHERE rt.topic_id = %s AND rt.recording_id <> %s
        GROUP BY r.id, r.recording_id, r.title, r.started_at
        ORDER BY r.started_at DESC NULLS LAST
        LIMIT 5
        """,
        (topic_id, recording_id),
    )
    snippets = await _qdrant_snippets(topic["label"])
    created: list[dict[str, Any]] = []
    for source in sources[:3]:
        source_snippets = [s for s in snippets if s.get("recording_id") == source.get("source_vc_recording_id")]
        signal, summary = _build_summary(source, source_snippets)
        if not summary:
            continue
        cur = await conn.execute(
            """
            INSERT INTO past_reference (recording_id, topic_id, source_recording_id, signal, summary, source)
            VALUES (%s, %s, %s, %s, %s, 'auto')
            ON CONFLICT (recording_id, topic_id, source_recording_id, source) DO NOTHING
            RETURNING id, recording_id, topic_id, source_recording_id, signal, summary, source, created_at
            """,
            (recording_id, topic_id, source["source_recording_id"], signal, summary),
        )
        row = await cur.fetchone()
        if row:
            created.append(row)
    for row in created:
        await ws_hub.broadcast(current_recording["recording_id"], "past_reference.created", row)
    return created


async def dig_deeper(conn: Any, ws_hub: Any, recording_id: str, topic_id: int) -> list[dict[str, Any]]:
    current_recording = await fetchone(conn, "SELECT id, recording_id FROM recording WHERE id = %s", (recording_id,))
    topic = await fetchone(conn, "SELECT id, label FROM topic WHERE id = %s", (topic_id,))
    if not current_recording or not topic:
        return []
    snippets = await _qdrant_snippets(topic["label"], limit=8)
    created: list[dict[str, Any]] = []
    for snippet in snippets[:3]:
        source = await fetchone(
            conn,
            "SELECT id, recording_id, title FROM recording WHERE recording_id = %s AND id <> %s",
            (snippet.get("recording_id"), recording_id),
        )
        if not source:
            continue
        summary = f"{source['title']}: {snippet.get('text', '').strip()}"[:500]
        cur = await conn.execute(
            """
            INSERT INTO past_reference (recording_id, topic_id, source_recording_id, signal, summary, source)
            VALUES (%s, %s, %s, 'new_context', %s, 'dig_deeper')
            ON CONFLICT (recording_id, topic_id, source_recording_id, source) DO NOTHING
            RETURNING id, recording_id, topic_id, source_recording_id, signal, summary, source, created_at
            """,
            (recording_id, topic_id, source["id"], summary),
        )
        row = await cur.fetchone()
        if row:
            created.append(row)
    for row in created:
        await ws_hub.broadcast(current_recording["recording_id"], "past_reference.created", row)
    return created
