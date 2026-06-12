#!/usr/bin/env python3
"""
Import an existing completed recording into the dashboard.

Unlike replay_recording.py this uses the REAL recording_id (no suffix)
and marks the recording as ended when done.

Usage:
    python scripts/import_recording.py --recording-id 20260610_100123
    python scripts/import_recording.py --recording-id 20260610_100123 --port 8100
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib import request, error


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a completed recording into the dashboard")
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    recording_dir = Path.home() / "Documents" / "VoiceCapture" / f"recording_{args.recording_id}"
    metadata_path = recording_dir / f"recording_{args.recording_id}.json"
    if not metadata_path.exists():
        raise SystemExit(f"Metadata not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    segments_dir = recording_dir / "segments"
    segment_files = sorted(segments_dir.glob("transcription_*.txt"))

    base_url = f"http://localhost:{args.port}"
    recording_id = args.recording_id
    title = metadata.get("name") or recording_id
    started_at = datetime.strptime(metadata["date"], "%Y-%m-%d %H:%M:%S")
    segment_duration = float(metadata.get("segment_duration") or 10)

    print(f"Importing: {recording_id}")
    print(f"  Title   : {title}")
    print(f"  Started : {started_at}")
    print(f"  Segments: {len(segment_files)}")

    # Start recording
    post_json(f"{base_url}/ingest/recordings", {
        "recording_id": recording_id,
        "title": title,
        "started_at": started_at.isoformat(),
    })
    print("  ✅ Recording created")

    # Ingest segments
    for index, transcription_file in enumerate(segment_files, start=1):
        text = transcription_file.read_text(encoding="utf-8").strip()
        if not text:
            continue
        ts = started_at + timedelta(seconds=(index - 1) * segment_duration)
        post_json(f"{base_url}/ingest/recordings/{recording_id}/segments", {
            "segment_num": index,
            "text": text,
            "ts": ts.isoformat(),
        })

    print(f"  ✅ {len(segment_files)} segments ingested")

    # End recording
    ended_at = started_at + timedelta(seconds=len(segment_files) * segment_duration)
    post_json(f"{base_url}/ingest/recordings/{recording_id}/end", {
        "ended_at": ended_at.isoformat(),
    })
    print("  ✅ Recording ended")
    print(f"\nDone. Open: http://localhost:{args.port}/live/{recording_id}")


if __name__ == "__main__":
    main()
