#!/usr/bin/env python3
"""Replay an existing recording into the dashboard ingest API."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib import request


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a Voice Capture recording into the dashboard API")
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--speed", type=float, default=10.0)
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--suffix", default="_replay01")
    args = parser.parse_args()

    recording_dir = Path.home() / "Documents" / "VoiceCapture" / f"recording_{args.recording_id}"
    metadata_path = recording_dir / f"recording_{args.recording_id}.json"
    if not metadata_path.exists():
        raise SystemExit(f"Metadata not found: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    segments_dir = recording_dir / "segments"
    segment_files = sorted(segments_dir.glob("transcription_*.txt"))
    synthetic_id = f"{args.recording_id}{args.suffix}"
    base_url = f"http://localhost:{args.port}"
    started_at = datetime.strptime(metadata["date"], "%Y-%m-%d %H:%M:%S")
    segment_duration = float(metadata.get("segment_duration") or 10)

    post_json(
        f"{base_url}/ingest/recordings",
        {
            "recording_id": synthetic_id,
            "title": f"{metadata.get('name', synthetic_id)}{args.suffix}",
            "started_at": started_at.isoformat(),
        },
    )

    for index, transcription_file in enumerate(segment_files, start=1):
        text = transcription_file.read_text(encoding="utf-8").strip()
        post_json(
            f"{base_url}/ingest/recordings/{synthetic_id}/segments",
            {
                "segment_num": index,
                "text": text,
                "ts": (started_at + timedelta(seconds=(index - 1) * segment_duration)).isoformat(),
                "speaker_label": None,
                "duration_seconds": segment_duration,
            },
        )
        if index < len(segment_files):
            time.sleep(max(segment_duration / max(args.speed, 0.1), 0.01))

    post_json(
        f"{base_url}/ingest/recordings/{synthetic_id}/end",
        {"ended_at": (started_at + timedelta(seconds=len(segment_files) * segment_duration)).isoformat()},
    )


if __name__ == "__main__":
    main()
