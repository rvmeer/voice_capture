#!/usr/bin/env python3
"""Queue all segments of a specific recording for AI analysis.

Usage:
    python scripts/analyze_recording.py --recording-id 20260609_140126
    python scripts/analyze_recording.py --recording-id 20260609_140126_replay01
    python scripts/analyze_recording.py --recording-id 20260609_140126 --reset  # re-analyze already done segments
"""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg.rows import dict_row


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue a recording's segments for AI analysis")
    parser.add_argument("--recording-id", required=True, help="The recording_id (vc identifier) to analyze")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Also re-queue already analyzed (done/failed) segments",
    )
    parser.add_argument("--dsn", default="dbname=recordings", help="PostgreSQL DSN")
    args = parser.parse_args()

    with psycopg.connect(args.dsn, row_factory=dict_row) as conn:
        recording = conn.execute(
            "SELECT id, recording_id, title FROM recording WHERE recording_id = %s",
            (args.recording_id,),
        ).fetchone()

        if not recording:
            print(f"ERROR: recording '{args.recording_id}' not found in dashboard DB.", file=sys.stderr)
            print("Tip: run the replay script first to ingest it.", file=sys.stderr)
            sys.exit(1)

        if args.reset:
            statuses = ("pending", "processing", "done", "failed")
        else:
            statuses = ("pending", "processing", "failed")

        cur = conn.execute(
            """
            UPDATE segment
            SET ai_status = 'pending', ai_attempts = 0
            WHERE recording_id = %s
              AND ai_status = ANY(%s)
            """,
            (recording["id"], list(statuses)),
        )
        conn.commit()
        count = cur.rowcount

    print(f"Recording : {recording['recording_id']} — {recording['title']}")
    print(f"Queued    : {count} segment(s) for AI analysis")
    if count == 0:
        print("Nothing to do. Use --reset to re-analyze already completed segments.")


if __name__ == "__main__":
    main()
