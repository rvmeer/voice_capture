"""Background AI worker for pending segments."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from dashboard.analyzer.apply import apply_result
from dashboard.analyzer.provider import AIProvider, AnalysisContext
from dashboard.db import fetchall, fetchone, get_pool

logger = logging.getLogger(__name__)


class AnalyzerWorker:
    def __init__(self, provider: AIProvider, ws_hub: Any) -> None:
        self.provider = provider
        self.ws_hub = ws_hub
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _claim_next_segment(self, conn: Any) -> dict[str, Any] | None:
        async with conn.transaction():
            segment = await fetchone(
                conn,
                """
                SELECT *
                FROM segment
                WHERE ai_status = 'pending'
                ORDER BY id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
            )
            if not segment:
                return None
            await conn.execute("UPDATE segment SET ai_status = %s WHERE id = %s", ("processing", segment["id"]))
            return segment

    async def _build_context(self, conn: Any, segment: dict[str, Any]) -> tuple[AnalysisContext, dict[str, Any]]:
        recording = await fetchone(
            conn,
            "SELECT id, recording_id, title, started_at, ended_at, status FROM recording WHERE id = %s",
            (segment["recording_id"],),
        )
        participants = await fetchall(
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
        topics = await fetchall(
            conn,
            """
            SELECT t.* FROM topic t
            WHERE EXISTS (
                SELECT 1 FROM recording_topic rt WHERE rt.topic_id = t.id AND rt.recording_id = %s
            )
            UNION
            (
                SELECT t2.* FROM topic t2
                ORDER BY t2.occurrence_count DESC
                LIMIT 20
            )
            ORDER BY occurrence_count DESC, lower(label)
            """,
            (recording["id"],),
        )
        goals = await fetchall(conn, "SELECT * FROM goal WHERE recording_id = %s ORDER BY created_at", (recording["id"],))
        agenda_items = await fetchall(conn, "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position", (recording["id"],))
        recent_segments = await fetchall(
            conn,
            """
            SELECT s.id, s.segment_num, s.text, s.speaker_label, s.ts, s.duration_seconds, p.name AS participant_name
            FROM segment s
            LEFT JOIN participant p ON p.id = s.participant_id
            WHERE s.recording_id = %s AND s.id <= %s
            ORDER BY s.id DESC
            LIMIT 6
            """,
            (recording["id"], segment["id"]),
        )
        recent_segments.reverse()
        context = AnalysisContext(
            recording=recording,
            segment=segment,
            participants=participants,
            topics=topics,
            goals=goals,
            agenda_items=agenda_items,
            recent_segments=recent_segments,
        )
        return context, recording

    async def _handle_failure(self, conn: Any, segment: dict[str, Any], exc: Exception) -> None:
        attempts = int(segment.get("ai_attempts") or 0) + 1
        next_status = "failed" if attempts >= 3 else "pending"
        await conn.execute(
            """
            UPDATE segment
            SET ai_status = %s,
                ai_attempts = %s
            WHERE id = %s
            """,
            (next_status, attempts, segment["id"]),
        )
        await conn.commit()
        logger.warning("AI processing failed for segment %s: %s", segment["id"], exc)
        if next_status == "pending":
            await asyncio.sleep(min(2**attempts, 8))

    async def _reap_stuck_segments(self, conn: Any) -> None:
        """Reset segments stuck in 'processing' for > 3 minutes back to 'pending'."""
        await conn.execute(
            """
            UPDATE segment
            SET ai_status = 'pending',
                ai_attempts = LEAST(ai_attempts + 1, 2)
            WHERE ai_status = 'processing'
              AND (ai_processed_at IS NULL OR ai_processed_at < now() - interval '3 minutes')
            """,
        )
        await conn.commit()

    async def run(self) -> None:
        pool = get_pool()
        # On startup, reap any segments left in 'processing' from a previous crash
        try:
            async with pool.connection() as conn:
                await self._reap_stuck_segments(conn)
        except Exception as exc:
            logger.warning("Startup reap failed: %s", exc)
        reap_counter = 0
        while not self._stop.is_set():
            try:
                async with pool.connection() as conn:
                    # Periodically reap stuck segments (every ~5 minutes)
                    reap_counter += 1
                    if reap_counter >= 300:
                        reap_counter = 0
                        await self._reap_stuck_segments(conn)
                    segment = await self._claim_next_segment(conn)
                    if not segment:
                        await asyncio.sleep(1.0)
                        continue
                    context, recording = await self._build_context(conn, segment)
                    try:
                        result = await self.provider.analyze(context)
                        await apply_result(
                            conn,
                            recording_uuid=recording["id"],
                            recording_vc_id=recording["recording_id"],
                            segment_id=segment["id"],
                            result=result,
                            ws_hub=self.ws_hub,
                        )
                        await conn.commit()
                    except Exception as exc:
                        await self._handle_failure(conn, segment, exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Analyzer worker loop failed: %s", exc)
                await asyncio.sleep(1.0)
