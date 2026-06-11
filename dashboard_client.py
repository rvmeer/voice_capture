"""Best-effort async client for the dashboard ingest API."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import parse, request

logger = logging.getLogger(__name__)


class DashboardClient:
    def __init__(self) -> None:
        import os

        self.base_url = os.environ.get("VOICE_CAPTURE_DASHBOARD_URL", "http://localhost:8100").rstrip("/")
        self._queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="dashboard-client")
        self._thread.start()
        # Drain any previously spooled events in background
        threading.Thread(target=self._drain_spool, daemon=True, name="dashboard-spool-drain").start()

    def recording_started(self, recording_id: str, title: str | None, started_at: datetime) -> None:
        self._queue.put(
            (
                f"{self.base_url}/ingest/recordings",
                {
                    "recording_id": recording_id,
                    "title": title,
                    "started_at": started_at.isoformat(),
                },
            )
        )

    def segment(
        self,
        recording_id: str,
        num: int,
        text: str,
        ts: datetime,
        duration_seconds: float | None = None,
    ) -> None:
        self._queue.put(
            (
                f"{self.base_url}/ingest/recordings/{parse.quote(recording_id, safe='')}/segments",
                {
                    "segment_num": num,
                    "text": text,
                    "ts": ts.isoformat(),
                    "speaker_label": None,
                    "duration_seconds": duration_seconds,
                },
            )
        )

    def recording_ended(self, recording_id: str, ended_at: datetime) -> None:
        self._queue.put(
            (
                f"{self.base_url}/ingest/recordings/{parse.quote(recording_id, safe='')}/end",
                {"ended_at": ended_at.isoformat()},
            )
        )

    def _worker(self) -> None:
        while True:
            url, payload = self._queue.get()
            try:
                self._post_with_retry(url, payload)
            except Exception as exc:
                logger.warning("Dashboard client worker error: %s", exc)
            finally:
                self._queue.task_done()

    def _post_with_retry(self, url: str, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            try:
                req = request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with request.urlopen(req, timeout=2) as response:
                    response.read()
                return
            except Exception as exc:
                logger.warning("Dashboard request failed (%s, attempt %s/3): %s", url, attempt + 1, exc)
                if attempt == 2:
                    self._spool(url, payload)
                    return
                time.sleep(0.5 * (2**attempt))

    def _drain_spool(self) -> None:
        """On startup, replay any events that were spooled during a previous service outage."""
        spool_path = Path.home() / ".voice_capture_dashboard_spool.jsonl"
        if not spool_path.exists():
            return
        time.sleep(3)  # Give the service a moment to start
        lines_to_retry: list[str] = []
        try:
            with spool_path.open("r", encoding="utf-8") as handle:
                lines_to_retry = [line.strip() for line in handle if line.strip()]
            spool_path.unlink()
        except Exception as exc:
            logger.warning("Dashboard spool read failed: %s", exc)
            return
        failed: list[str] = []
        for line in lines_to_retry:
            try:
                entry = json.loads(line)
                self._post_with_retry(entry["url"], entry["payload"])
            except Exception as exc:
                logger.warning("Spool replay failed: %s", exc)
                failed.append(line)
        if failed:
            try:
                with spool_path.open("a", encoding="utf-8") as handle:
                    for line in failed:
                        handle.write(line + "\n")
            except Exception as exc:
                logger.warning("Dashboard spool re-write failed: %s", exc)
        elif lines_to_retry:
            logger.info("Dashboard: drained %d spooled events", len(lines_to_retry))

    def _spool(self, url: str, payload: dict) -> None:
        spool_path = Path.home() / ".voice_capture_dashboard_spool.jsonl"
        try:
            with spool_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"url": url, "payload": payload}, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Dashboard spool write failed: %s", exc)
