#!/usr/bin/env python3
"""
Parse participant front matter from Obsidian meeting notes and insert into PostgreSQL.

Matching strategy (in order):
  1. explicit `recording_id` in front matter → direct
  2. single recording that day → direct
  3. multiple recordings that day → Ollama-assisted title matching:
       a. generate a short title for each markdown via Ollama
       b. ask Ollama to match those temp titles to the DB recording titles
       c. use the match result to link markdown → recording
  4. no match found → skip
"""

import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg2
import yaml

VAULT_DIR = Path.home() / "Documents/ObsidianVaults/FirstVault/Meetings"
DB_DSN = "dbname=recordings"
OLLAMA_BASE_URL = "http://localhost:11434"

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
DATE_FROM_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


# ---------- Ollama helpers ----------

def ollama_call(model: str, prompt: str, timeout: int = 120) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode()).get("response", "").strip()


def generate_temp_title(content: str, model: str) -> str:
    prompt = (
        "Geef een korte beschrijvende titel (max 8 woorden) voor de volgende meeting-samenvatting. "
        "Gebruik dezelfde taal als de tekst. Geef alleen de titel, zonder aanhalingstekens of uitleg.\n\n"
        f"{content[:3000]}\n\nTitel:"
    )
    return ollama_call(model, prompt).strip("\"'")


def match_titles(md_titles: list[str], rec_titles: list[str], model: str) -> dict[int, int]:
    """
    Ask Ollama to match markdown titles (0-based index) to recording titles (0-based index).
    Returns {md_index: rec_index} for confident matches.
    """
    md_list = "\n".join(f"{i}: {t}" for i, t in enumerate(md_titles))
    rec_list = "\n".join(f"{i}: {t}" for i, t in enumerate(rec_titles))
    prompt = (
        "Je krijgt twee lijsten met meeting-titels. Koppel elke markdown-titel aan de meest passende "
        "opname-titel op basis van inhoud. Gebruik alleen zekere koppelingen. "
        "Antwoord uitsluitend als JSON-object: {\"matches\": [[md_index, rec_index], ...]}, "
        "waarbij md_index en rec_index 0-gebaseerde indices zijn. "
        "Laat onzekere koppelingen weg.\n\n"
        f"Markdown-titels:\n{md_list}\n\n"
        f"Opname-titels:\n{rec_list}\n\n"
        "JSON:"
    )
    response = ollama_call(model, prompt, timeout=60)
    # Extract JSON from response (model may add prose around it)
    json_match = re.search(r'\{.*"matches".*\}', response, re.DOTALL)
    if not json_match:
        return {}
    try:
        data = json.loads(json_match.group())
        result = {}
        for pair in data.get("matches", []):
            if isinstance(pair, list) and len(pair) == 2:
                mi, ri = int(pair[0]), int(pair[1])
                if 0 <= mi < len(md_titles) and 0 <= ri < len(rec_titles):
                    result[mi] = ri
        return result
    except Exception:
        return {}


# ---------- Front matter parsing ----------

def parse_front_matter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        m = FRONT_MATTER_RE.match(text)
        return yaml.safe_load(m.group(1)) or {} if m else {}
    except Exception:
        return {}


def normalize_name(raw: str) -> str | None:
    name = re.sub(r"\s*\(.*?\)", "", raw).strip()
    return name if len(name) >= 2 else None


def extract_participants(fm: dict) -> list[tuple[str, str]]:
    results = []

    organizer = fm.get("organizer")
    if isinstance(organizer, str) and organizer.strip():
        name = normalize_name(organizer)
        if name:
            results.append((name, "organizer"))

    for entry in fm.get("attendees") or []:
        if isinstance(entry, str):
            name = normalize_name(entry)
            if name:
                results.append((name, "attendee"))

    participants = fm.get("participants")
    if isinstance(participants, str) and participants.strip():
        for part in re.split(r"[|,]", participants):
            name = normalize_name(part)
            if name:
                results.append((name, "attendee"))
    elif isinstance(participants, list):
        for entry in participants:
            if isinstance(entry, str):
                name = normalize_name(entry)
                if name:
                    results.append((name, "attendee"))

    seen: dict[str, str] = {}
    for name, role in results:
        if name not in seen or role == "organizer":
            seen[name] = role
    return list(seen.items())


# ---------- DB helpers ----------

def upsert_participants(cur, recording_id: str, participants: list[tuple[str, str]]) -> int:
    count = 0
    for name, role in participants:
        cur.execute(
            "INSERT INTO participant (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        cur.execute("SELECT id FROM participant WHERE name = %s", (name,))
        pid = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO recording_participant (recording_id, participant_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (recording_id, participant_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (recording_id, pid, role),
        )
        count += 1
    return count


# ---------- Main ----------

def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # Load all recording titles keyed by date
    cur.execute("SELECT recording_id, title FROM recording")
    date_index: dict[str, list[tuple[str, str]]] = {}
    for rid, title in cur.fetchall():
        date_key = f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}"
        date_index.setdefault(date_key, []).append((rid, title or ""))

    files = sorted(VAULT_DIR.glob("*.md"))
    print(f"Gevonden: {len(files)} markdown bestanden")

    # Get Ollama model
    try:
        resp = urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m["name"] for m in json.loads(resp.read()).get("models", [])]
        ollama_model = models[0] if models else None
    except Exception:
        ollama_model = None

    if not ollama_model:
        print("[!] Ollama niet beschikbaar — alleen directe koppelingen mogelijk")

    # Group markdown files by date
    date_md_index: dict[str, list[Path]] = {}
    explicit_map: dict[Path, str] = {}  # path → recording_id (explicit front matter)

    for path in files:
        fm = parse_front_matter(path)
        rid = fm.get("recording_id")
        if rid:
            explicit_map[path] = str(rid).strip()
            continue
        m = DATE_FROM_FILENAME_RE.match(path.name)
        if m:
            date_md_index.setdefault(m.group(1), []).append(path)

    # Resolve ambiguous dates via Ollama title matching
    ollama_map: dict[Path, str] = {}

    if ollama_model:
        ambiguous_dates = {
            date: (mds, recs)
            for date, recs in date_index.items()
            if len(recs) > 1 and (mds := date_md_index.get(date, []))
        }
        print(f"Ollama titel-matching voor {len(ambiguous_dates)} dagen met meerdere opnames...")

        for date, (mds, recs) in sorted(ambiguous_dates.items()):
            print(f"  {date}: {len(mds)} markdown(s), {len(recs)} opname(s)")

            # Generate temp titles for each markdown
            temp_titles = []
            for md in mds:
                text = md.read_text(encoding="utf-8")
                body = FRONT_MATTER_RE.sub("", text).strip()
                title = generate_temp_title(body or md.stem, ollama_model)
                temp_titles.append(title)
                print(f"    → {md.name[:60]}: \"{title}\"")

            rec_titles = [title for _, title in recs]
            rec_ids = [rid for rid, _ in recs]

            matches = match_titles(temp_titles, rec_titles, ollama_model)
            for mi, ri in matches.items():
                ollama_map[mds[mi]] = rec_ids[ri]
                print(f"    ✓ \"{temp_titles[mi]}\" → \"{rec_titles[ri]}\"")

    # Process all files
    linked = skipped = total_links = 0

    for path in files:
        fm = parse_front_matter(path)
        if not fm:
            continue

        # Determine recording_id
        if path in explicit_map:
            recording_id = explicit_map[path]
            method = "explicit"
        else:
            m = DATE_FROM_FILENAME_RE.match(path.name)
            if not m:
                skipped += 1
                continue
            date_key = m.group(1)
            candidates = date_index.get(date_key, [])
            if len(candidates) == 1:
                recording_id = candidates[0][0]
                method = "date"
            elif path in ollama_map:
                recording_id = ollama_map[path]
                method = "ollama"
            else:
                skipped += 1
                continue

        # Verify recording exists
        cur.execute("SELECT 1 FROM recording WHERE recording_id = %s", (recording_id,))
        if not cur.fetchone():
            skipped += 1
            continue

        participants = extract_participants(fm)
        if not participants:
            skipped += 1
            continue

        n = upsert_participants(cur, recording_id, participants)
        conn.commit()
        total_links += n
        linked += 1
        print(f"  [+] {recording_id} ({method}) — {n} deelnemer(s) ({path.name})")

    cur.execute("SELECT COUNT(*) FROM participant")
    total_p = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM recording_participant")
    total_rp = cur.fetchone()[0]

    cur.close()
    conn.close()
    print(f"\nKlaar: {linked} bestanden gekoppeld, {skipped} overgeslagen")
    print(f"Totaal in DB: {total_p} unieke deelnemers, {total_rp} koppelingen")


if __name__ == "__main__":
    main()
