#!/usr/bin/env python3
"""
Insert all existing VoiceCapture recordings into the recordings PostgreSQL database.
If a recording has no title (name), Ollama is used to generate one from the transcription.
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path so we can import project modules
sys.path.insert(0, str(Path(__file__).parent))

import psycopg2
from psycopg2.extras import execute_values

from recording_manager import RecordingManager, iso_duration_to_seconds
from ollama_utils import check_ollama_available, get_ollama_models, generate_title

DB_DSN = "dbname=recordings"


def parse_started_at(date_str: str) -> datetime:
    """Parse recording date string to timezone-aware datetime (local tz)."""
    dt_naive = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    return dt_naive.astimezone()


def compute_ended_at(started_at: datetime, duration_iso: str | None) -> datetime | None:
    if not duration_iso:
        return None
    seconds = iso_duration_to_seconds(duration_iso)
    if seconds <= 0:
        return None
    return started_at + timedelta(seconds=seconds)


def needs_title(name: str) -> bool:
    return not name or name.startswith("Opname ")


def resolve_title(rec: dict, ollama_model: str | None) -> str:
    """Return name from recording, or generate via Ollama if absent or generic."""
    name = (rec.get("name") or "").strip()
    if not needs_title(name):
        return name

    transcription = (rec.get("transcription") or "").strip()
    if not transcription:
        return f"Opname {rec['id']}"

    if not ollama_model:
        print(f"  [!] Geen Ollama model beschikbaar, gebruik fallback titel voor {rec['id']}")
        return f"Opname {rec['id']}"

    print(f"  [ollama] Genereer titel voor {rec['id']} ...")
    try:
        return generate_title(transcription, ollama_model)
    except Exception as e:
        print(f"  [!] Ollama fout: {e}")
        return f"Opname {rec['id']}"


def main():
    # Load recordings
    manager = RecordingManager()
    recordings = manager.recordings
    print(f"Gevonden: {len(recordings)} opnames")

    if not recordings:
        print("Niets te doen.")
        return

    # Resolve Ollama model (only needed if any recording lacks a real title)
    needs_ollama = any(needs_title((r.get("name") or "").strip()) for r in recordings)
    ollama_model = None
    if needs_ollama:
        if check_ollama_available():
            models = get_ollama_models()
            ollama_model = models[0] if models else None
            print(f"Ollama model: {ollama_model or 'geen beschikbaar'}")
        else:
            print("[!] Ollama niet bereikbaar — titels worden gegenereerd als fallback")

    # Connect to DB
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    inserted = skipped = 0

    for rec in recordings:
        recording_id = rec["id"]
        title = resolve_title(rec, ollama_model)
        started_at = parse_started_at(rec["date"])
        ended_at = compute_ended_at(started_at, rec.get("duration"))

        try:
            cur.execute(
                """
                INSERT INTO meeting (recording_id, title, started_at, ended_at, status)
                VALUES (%s, %s, %s, %s, 'ended')
                ON CONFLICT (recording_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at
                    WHERE meeting.title LIKE 'Opname %%'
                """,
                (recording_id, title, started_at, ended_at),
            )
            if cur.rowcount:
                print(f"  [+] {recording_id} — {title}")
                inserted += 1
            else:
                print(f"  [=] {recording_id} — al aanwezig, overgeslagen")
                skipped += 1
        except Exception as e:
            print(f"  [!] Fout bij {recording_id}: {e}")
            conn.rollback()
            continue

        conn.commit()

    cur.close()
    conn.close()
    print(f"\nKlaar: {inserted} ingevoegd, {skipped} overgeslagen.")


if __name__ == "__main__":
    main()
