"""Background AI worker for pending segments."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from dashboard.analyzer.apply import apply_curated_result
from dashboard.analyzer.provider import AIProvider, AnalysisContext
from dashboard.config import get_settings
from dashboard.db import fetchall, fetchone, get_pool

logger = logging.getLogger(__name__)


def _fmt_ts(ts: Any) -> str:
    if ts is None:
        return "??:??"
    if isinstance(ts, datetime):
        return ts.strftime("%H:%M")
    return str(ts)[:5]


class AnalyzerWorker:
    def __init__(self, provider: AIProvider, ws_hub: Any) -> None:
        self.provider = provider
        self.ws_hub = ws_hub
        self._stop = asyncio.Event()
        self._settings = get_settings()

    def stop(self) -> None:
        self._stop.set()

    async def _claim_pending_batch(self, conn: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Claim ALL pending segments for the recording that has the oldest pending segment.
        Returns (segments, recording_row) or ([], None) if nothing pending."""
        async with conn.transaction():
            # Find the recording with the oldest pending segment
            oldest = await fetchone(
                conn,
                """
                SELECT recording_id FROM segment
                WHERE ai_status = 'pending'
                ORDER BY id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
            )
            if not oldest:
                return [], None
            recording_uuid = oldest["recording_id"]
            # Claim ALL pending segments for that recording
            segments = await fetchall(
                conn,
                """
                SELECT * FROM segment
                WHERE recording_id = %s AND ai_status = 'pending'
                ORDER BY segment_num
                FOR UPDATE SKIP LOCKED
                """,
                (recording_uuid,),
            )
            if not segments:
                return [], None
            seg_ids = [s["id"] for s in segments]
            await conn.execute(
                """
                UPDATE segment SET ai_status = 'processing', claimed_at = now()
                WHERE id = ANY(%s)
                """,
                (seg_ids,),
            )
        recording = await fetchone(
            conn,
            "SELECT * FROM recording WHERE id = %s",
            (recording_uuid,),
        )
        return segments, recording

    async def _build_context(
        self, conn: Any, segments: list[dict[str, Any]], recording: dict[str, Any]
    ) -> AnalysisContext:
        window_size = self._settings.analysis_window_segments
        newest_seg_num = max(s["segment_num"] for s in segments)
        new_nums = {s["segment_num"] for s in segments}

        # Fetch the window of segments (last window_size up to and including newest claimed)
        window_segs = await fetchall(
            conn,
            """
            SELECT s.segment_num, s.text, s.ts, s.speaker_label, p.name AS participant_name
            FROM segment s
            LEFT JOIN participant p ON p.id = s.participant_id
            WHERE s.recording_id = %s AND s.segment_num <= %s
            ORDER BY s.segment_num DESC
            LIMIT %s
            """,
            (recording["id"], newest_seg_num, window_size),
        )
        window_segs.reverse()

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
            WITH linked AS (
                SELECT topic_id AS id FROM recording_topic WHERE recording_id = %s
            ),
            top20 AS (
                SELECT id FROM topic ORDER BY occurrence_count DESC LIMIT 20
            ),
            combined AS (
                SELECT id FROM linked UNION SELECT id FROM top20
            )
            SELECT t.* FROM topic t JOIN combined c ON t.id = c.id
            ORDER BY t.occurrence_count DESC, lower(t.label)
            """,
            (recording["id"],),
        )
        goals = await fetchall(conn, "SELECT * FROM goal WHERE recording_id = %s ORDER BY created_at", (recording["id"],))
        agenda_items = await fetchall(conn, "SELECT * FROM agenda_item WHERE recording_id = %s ORDER BY position", (recording["id"],))
        key_moments = await fetchall(
            conn,
            "SELECT * FROM key_moment WHERE recording_id = %s AND archived_at IS NULL ORDER BY salience DESC, ts",
            (recording["id"],),
        )
        action_items = await fetchall(
            conn,
            "SELECT ai.*, p.name AS owner_name FROM action_item ai LEFT JOIN participant p ON p.id = ai.owner_participant_id WHERE ai.recording_id = %s AND ai.archived_at IS NULL ORDER BY ai.created_at",
            (recording["id"],),
        )
        decisions = await fetchall(
            conn,
            "SELECT * FROM decision WHERE recording_id = %s AND archived_at IS NULL ORDER BY decided_at",
            (recording["id"],),
        )

        agenda_mode = recording.get("agenda_mode") or "dynamic"
        context_summary = recording.get("context_summary")

        return AnalysisContext(
            recording=recording,
            segments_window=window_segs,
            new_segment_nums=sorted(new_nums),
            participants=participants,
            topics=topics,
            goals=goals,
            agenda_items=agenda_items,
            agenda_mode=agenda_mode,
            key_moments=key_moments,
            action_items=action_items,
            decisions=decisions,
            context_summary=context_summary,
        )

    async def _handle_batch_failure(self, conn: Any, segments: list[dict[str, Any]], exc: Exception) -> None:
        max_attempts = max(int(s.get("ai_attempts") or 0) for s in segments) + 1
        next_status = "failed" if max_attempts >= 3 else "pending"
        seg_ids = [s["id"] for s in segments]
        await conn.execute(
            """
            UPDATE segment
            SET ai_status = %s,
                ai_attempts = ai_attempts + 1,
                claimed_at = NULL
            WHERE id = ANY(%s)
            """,
            (next_status, seg_ids),
        )
        await conn.commit()
        logger.warning("AI batch failed (%d segs, recording %s): %s", len(segments), segments[0]["recording_id"], exc)
        if next_status == "pending":
            await asyncio.sleep(min(2**max_attempts, 8))

    async def _reap_stuck_segments(self, conn: Any) -> None:
        """Reset segments stuck in 'processing' for > 3 minutes back to 'pending'."""
        await conn.execute(
            """
            UPDATE segment
            SET ai_status = 'pending',
                ai_attempts = ai_attempts + 1,
                claimed_at = NULL
            WHERE ai_status = 'processing'
              AND claimed_at < now() - interval '3 minutes'
            """,
        )
        await conn.commit()

    async def run(self) -> None:
        from dashboard.analyzer.summary import maybe_update_summary

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
                    reap_counter += 1
                    if reap_counter >= 300:
                        reap_counter = 0
                        await self._reap_stuck_segments(conn)
                    segments, recording = await self._claim_pending_batch(conn)
                    if not segments:
                        await asyncio.sleep(1.0)
                        continue
                    context = await self._build_context(conn, segments, recording)
                    try:
                        result = await self.provider.analyze(context)
                        await apply_curated_result(
                            conn,
                            recording_uuid=recording["id"],
                            recording_vc_id=recording["recording_id"],
                            claimed_segments=segments,
                            result=result,
                            ws_hub=self.ws_hub,
                        )
                        # Mark all claimed segments done
                        seg_ids = [s["id"] for s in segments]
                        await conn.execute(
                            "UPDATE segment SET ai_status='done', ai_processed_at=now() WHERE id=ANY(%s)",
                            (seg_ids,),
                        )
                        await conn.commit()
                        # Rolling summary maintenance (non-blocking)
                        newest_num = max(s["segment_num"] for s in segments)
                        await maybe_update_summary(conn, self.provider, recording, newest_num)
                    except Exception as exc:
                        await self._handle_batch_failure(conn, segments, exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Analyzer worker loop failed: %s", exc)
                await asyncio.sleep(1.0)
