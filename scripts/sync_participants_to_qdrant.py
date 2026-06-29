#!/usr/bin/env python3
"""
Retroactively copy participants from recording JSON files to Qdrant final_chunk points.

Usage:
  python scripts/sync_participants_to_qdrant.py              # all recordings
  python scripts/sync_participants_to_qdrant.py 202606       # only June 2026
  python scripts/sync_participants_to_qdrant.py 20260629     # only one day

Run from the project root with the project virtualenv active.
"""

import sys
from pathlib import Path

# Make sure project modules are on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from logging_config import setup_logging, get_logger
from qdrant import QdrantIndexer, QdrantUnavailableError

setup_logging()
logger = get_logger(__name__)


def main():
    month_prefix = sys.argv[1] if len(sys.argv) > 1 else None

    if month_prefix:
        print(f"Syncing participants to Qdrant for recordings matching '{month_prefix}*' ...")
    else:
        print("Syncing participants to Qdrant for ALL recordings ...")

    try:
        indexer = QdrantIndexer()
        indexer.init_collection(force_recreate=False)
    except QdrantUnavailableError as e:
        print(f"ERROR: Qdrant is not available: {e}")
        sys.exit(1)

    result = indexer.sync_participants_from_json(month_prefix=month_prefix)

    print(f"\nDone.")
    print(f"  Updated: {result['updated']} recording(s)")
    print(f"  Skipped: {result['skipped']} (no participants or no final_chunk points)")

    if result["recordings"]:
        print("\nUpdated recordings:")
        for r in result["recordings"]:
            print(f"  {r['recording_id']}  participants={r['participants']}  ({r['chunks_updated']} chunks)")


if __name__ == "__main__":
    main()
