#!/usr/bin/env python3
"""
Curate orphaned recordings: remove DB + Qdrant entries for recordings
that no longer have a folder in ~/Documents/VoiceCapture/.

Usage:
    python scripts/curate_recordings.py            # dry-run: show what would be removed
    python scripts/curate_recordings.py --yes      # actually delete
    python scripts/curate_recordings.py --recordings-dir /path/to/dir
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_RECORDINGS_DIR = Path.home() / "Documents" / "VoiceCapture"
DEFAULT_DSN = "dbname=recordings"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_filesystem_ids(recordings_dir: Path) -> set[str]:
    """Return recording_ids that exist as folders on disk."""
    ids: set[str] = set()
    for entry in recordings_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("recording_"):
            rec_id = entry.name.removeprefix("recording_")
            if rec_id:
                ids.add(rec_id)
    return ids


def get_db_ids(conn: psycopg.Connection) -> list[dict]:
    """Return all recordings from the database."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, recording_id, title, status, started_at FROM recording ORDER BY recording_id")
        return cur.fetchall()


def delete_from_qdrant(recording_id: str) -> bool:
    """Delete all Qdrant points for a recording. Returns True on success."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from qdrant import QdrantIndexer
        indexer = QdrantIndexer()
        indexer.delete_recording_points(recording_id)
        return True
    except Exception as exc:
        print(f"  ⚠️  Qdrant deletion failed for {recording_id}: {exc}")
        return False


def delete_from_db(conn: psycopg.Connection, recording_uuid: str) -> None:
    """Delete a recording from PostgreSQL (cascades to all child tables)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM recording WHERE id = %s", (recording_uuid,))
    conn.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Remove orphaned recordings from DB + Qdrant")
    parser.add_argument("--yes", "-y", action="store_true", help="Actually delete (default is dry-run)")
    parser.add_argument("--recordings-dir", default=str(DEFAULT_RECORDINGS_DIR), help="Path to VoiceCapture recordings folder")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")
    parser.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant deletion (only remove from DB)")
    args = parser.parse_args()

    recordings_dir = Path(args.recordings_dir)
    if not recordings_dir.exists():
        print(f"❌ Recordings directory not found: {recordings_dir}")
        sys.exit(1)

    print(f"📂 Recordings dir : {recordings_dir}")
    print(f"🗄️  Database DSN   : {args.dsn}")
    print()

    # ── Collect data ──────────────────────────────────────────────────────────
    fs_ids = get_filesystem_ids(recordings_dir)
    print(f"Found {len(fs_ids)} recording folders on disk.")

    with psycopg.connect(args.dsn, row_factory=dict_row) as conn:
        db_rows = get_db_ids(conn)
        print(f"Found {len(db_rows)} recordings in database.")

        db_id_set = {row["recording_id"] for row in db_rows}
        orphaned = [row for row in db_rows if row["recording_id"] not in fs_ids]
        on_disk_not_in_db = fs_ids - db_id_set

    print()

    # ── Report on_disk_not_in_db (informational) ─────────────────────────────
    if on_disk_not_in_db:
        print(f"ℹ️  {len(on_disk_not_in_db)} folder(s) on disk but NOT in DB (not touched):")
        for rec_id in sorted(on_disk_not_in_db):
            print(f"   {rec_id}")
        print()

    # ── Report orphans ────────────────────────────────────────────────────────
    if not orphaned:
        print("✅ No orphaned recordings found. Nothing to do.")
        return

    print(f"🗑️  {len(orphaned)} orphaned recording(s) (in DB but no folder on disk):")
    print()
    for row in orphaned:
        started = row["started_at"].strftime("%Y-%m-%d %H:%M") if row["started_at"] else "?"
        print(f"  [{row['status']:6s}] {row['recording_id']}  —  {row['title']!r}  (started {started})")
    print()

    if not args.yes:
        print("👉 Dry-run mode. Pass --yes to actually delete.")
        return

    # ── Confirm ───────────────────────────────────────────────────────────────
    answer = input(f"Delete {len(orphaned)} recording(s) from DB + Qdrant? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    # ── Delete ────────────────────────────────────────────────────────────────
    print()
    with psycopg.connect(args.dsn, row_factory=dict_row) as conn:
        for row in orphaned:
            rec_id = row["recording_id"]
            print(f"  Deleting {rec_id} ...", end=" ", flush=True)

            qdrant_ok = True
            if not args.skip_qdrant:
                qdrant_ok = delete_from_qdrant(rec_id)

            delete_from_db(conn, str(row["id"]))
            status = "✅" if qdrant_ok else "✅ (DB only, Qdrant failed)"
            print(status)

    print()
    print(f"Done. Removed {len(orphaned)} recording(s).")


if __name__ == "__main__":
    main()
