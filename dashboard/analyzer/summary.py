"""Rolling summary maintenance — summarizes old segments that have scrolled past the window."""

from __future__ import annotations

import logging
from typing import Any

from dashboard.config import get_settings
from dashboard.db import fetchall, fetchone

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """
You are a meeting assistant. Summarize the provided transcript segments into a concise rolling summary.
- Maximum {max_words} words
- Written in the same language as the transcript (often Dutch)
- Preserve: named decisions, commitments with owners, unresolved questions, key participants
- If a previous summary is provided, merge it with the new segments into one updated summary
- Do not add headers or bullet points — write flowing prose
""".strip()


async def maybe_update_summary(
    conn: Any,
    provider: Any,
    recording: dict[str, Any],
    newest_segment_num: int,
) -> None:
    """Trigger a summary update when enough segments have scrolled past the analysis window."""
    settings = get_settings()
    window = settings.analysis_window_segments
    lag = settings.summary_lag_segments
    current_summary_up_to = int(recording.get("summary_up_to_segment") or 0)
    threshold = newest_segment_num - window - lag
    if threshold <= current_summary_up_to:
        return  # Not enough new segments have passed the window

    # Fetch segments from current_summary_up_to+1 through threshold (inclusive)
    segments_to_summarize = await fetchall(
        conn,
        """
        SELECT segment_num, text, speaker_label, ts
        FROM segment
        WHERE recording_id = %s
          AND segment_num > %s AND segment_num <= %s
        ORDER BY segment_num
        """,
        (recording["id"], current_summary_up_to, threshold),
    )
    if not segments_to_summarize:
        return

    existing_summary = recording.get("context_summary") or ""
    transcript_lines = []
    for seg in segments_to_summarize:
        speaker = seg.get("speaker_label") or "?"
        ts = str(seg.get("ts") or "")[:5]
        transcript_lines.append(f"[#{seg['segment_num']} {speaker} {ts}] {seg['text']}")
    transcript_text = "\n".join(transcript_lines)

    prompt = ""
    if existing_summary:
        prompt = f"PREVIOUS SUMMARY:\n{existing_summary}\n\nNEW SEGMENTS TO INCORPORATE:\n{transcript_text}"
    else:
        prompt = f"TRANSCRIPT SEGMENTS TO SUMMARIZE:\n{transcript_text}"

    try:
        from dashboard.analyzer.provider import AnalysisContext
        # Use provider directly with a minimal context for the summary call
        summary_text = await _call_summary_provider(provider, prompt, settings.summary_max_words)
        await conn.execute(
            "UPDATE recording SET context_summary = %s, summary_up_to_segment = %s WHERE id = %s",
            (summary_text, threshold, recording["id"]),
        )
        await conn.commit()
        logger.info("Summary updated for recording %s: up to segment %d", recording["recording_id"], threshold)
    except Exception as exc:
        logger.warning("Summary update failed for recording %s: %s", recording.get("recording_id"), exc)


async def _call_summary_provider(provider: Any, prompt: str, max_words: int) -> str:
    """Call the AI provider with a simple summarization prompt."""
    system = _SUMMARY_SYSTEM_PROMPT.format(max_words=max_words)

    # Try Claude tool-use first, fall back to text
    try:
        if hasattr(provider, "_get_client"):
            # ClaudeProvider — use messages API directly for summarization
            client = provider._get_client()
            response = await client.messages.create(
                model=provider.model,
                max_tokens=600,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text.strip()
        elif hasattr(provider, "base_url"):
            # OllamaProvider
            import httpx
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{provider.base_url}/api/chat",
                    json={
                        "model": provider.model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"].strip()
        elif hasattr(provider, "primary"):
            # FallbackProvider — try primary then fallback
            try:
                return await _call_summary_provider(provider.primary, prompt, max_words)
            except Exception:
                return await _call_summary_provider(provider.fallback, prompt, max_words)
    except Exception as exc:
        raise RuntimeError(f"Summary provider call failed: {exc}") from exc
    raise RuntimeError("No summary text returned")
