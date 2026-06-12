# Plan — Peripheral Decoupling & Retrospective Backfill

> **Audience:** Claude Code (Sonnet), current codebase. Three independent workstreams; execute in order, commit per phase.
>
> **Principle:** the core (tray app → WAV + transcription + JSON in the VoiceCapture folder) must run without Qdrant and PostgreSQL; both peripherals must be addable later and fillable in retrospect from the files.
>
> **Explicitly out of scope (user decision):** NO changes to the recording core. In particular: do not add per-segment timestamp logging to the recording folder. Backfill timestamps are therefore approximated as `started_at + (n−1) × segment_duration` — document this in the script's docstring and README. `main.py` may only be touched for the 3-line env-flag guard in Phase 2.

---

## Phase 1 — One unified psql backfill: `scripts/backfill_dashboard.py`

Replaces the fragmented trio (`insert_recordings.py` / `replay_recording.py` / `analyze_recording.py`) with a single idempotent command. It feeds the **ingest API** (not the DB directly), so backfilled recordings flow through exactly the same path as live ones: apriori consumption, `agenda_mode` derivation, AI worker, WS events.

**CLI:**
```
python scripts/backfill_dashboard.py --all [--since 2026-01-01] [--port 8100] [--no-ai]
python scripts/backfill_dashboard.py --recording-id 20260609_140126
```

**Behavior:**
1. Scan `~/Documents/VoiceCapture/recording_*/` (reuse `RecordingManager`), **oldest first** — so `topic.occurrence_count` and cross-recording past-references build up chronologically.
2. Per recording: `POST /ingest/recordings` with the **real** `recording_id` (no suffix — that stays a `replay_recording.py` dev-tool feature), title from metadata (`name`), `started_at` from metadata date.
3. All segments via `POST .../segments`, no sleep, `ts` reconstructed per the approximation above, `duration_seconds = segment_duration`.
4. `POST .../end` with `ended_at = started_at + duration` from metadata (skip if no duration).
5. `--no-ai`: after ingest, set the segments' `ai_status='done'` directly (one UPDATE via psycopg, optional dep for this flag only) so the worker skips them — for users who want searchable/relational data without AI cost. Default: leave `pending`, the worker churns through the backlog (REQ-NFR-03 behavior).
6. Idempotent by construction: recording upsert + `ON CONFLICT (recording_id, segment_num) DO NOTHING`. Re-running is safe; already-ingested recordings report "skipped (n segments exist)".
7. Skip recordings with zero transcription files; print a summary table (ingested / skipped / failed).

**Cleanup:** mark `insert_recordings.py` as superseded (docstring note pointing to the new script; do not delete). `analyze_recording.py` stays — it is the re-analysis tool; the backfill script may print its invocation as a hint.

**Accept:** with a running service and ≥3 historical recordings: first run ingests all (visible in dashboard, AI entities appear as the worker drains); second run is a no-op; `--no-ai` run leaves no pending segments; Qdrant remains untouched by this script.

## Phase 2 — `dashboard_client.py` hardening (circuit breaker, spool cap, kill switch)

Current pain: with no dashboard service, every message burns ~7.5 s in retries before spooling, logs 3 warnings per segment, and the spool grows unbounded forever.

1. **Kill switch:** env `VOICE_CAPTURE_DASHBOARD_ENABLED` (default `"true"`). When false, `_init_dashboard_client` in `main.py` skips construction entirely (the only permitted `main.py` change, mirror the existing guard style).
2. **Circuit breaker** in the client: after a connection failure, open the circuit for 60 s (`_circuit_open_until`); while open, messages go **straight to the spool** (no retries, no timeouts). After 60 s the next message acts as the probe. On any successful POST: close the circuit **and trigger a spool drain** — this also fixes the known limitation that the spool only drains at tray-app start.
3. **Spool cap:** before appending, if the spool exceeds 20 MB, rotate: keep the newest half, log one warning. Never let it grow unbounded.
4. **Log hygiene:** one warning when the circuit opens, one info when it closes/drains; per-message failures at debug level.

**Accept (manual drill):** start a recording with the service down → no retry storms in the log, segments spool instantly; start the service mid-recording → within ~60 s the circuit closes, the spool drains, and the dashboard catches up with the full recording. With `VOICE_CAPTURE_DASHBOARD_ENABLED=false` no HTTP attempts occur at all. The tray app keeps recording flawlessly in all scenarios.

## Phase 3 — Dependency split

1. `requirements.txt` → core only: remove `psycopg[binary,pool]`, `anthropic`, `httpx`, `pydantic-settings`, `websockets`.
2. New `requirements-dashboard.txt` containing exactly those five, with a header comment ("only needed for `python -m dashboard`").
3. Recommended (separate commit, easy to revert): move `qdrant-client` + `sentence-transformers` to the existing `requirements-optional.txt` — `qdrant.py` already lazy-imports behind `_require_qdrant`, and the tray app degrades cleanly without them.
4. Guard check: `dashboard_client.py` must remain stdlib-only (add a comment at the top stating this invariant); verify `main.py` has no direct or transitive import of any dashboard-only package.
5. Update `README.md` + `DASHBOARD_README.md`: three install profiles — core, core+qdrant, core+dashboard — and the backfill story ("install peripherals later, then run `backfill_dashboard.py --all` and `/qdrant/build`").

**Accept:** in a fresh venv with only the new core `requirements.txt`: `python -c "import dashboard_client"` works and the tray app starts (PyQt available); `python -m dashboard` fails with a clear missing-dependency message until `requirements-dashboard.txt` is installed.

---

## Explicitly documented limitation (no code)

Add one paragraph to `DASHBOARD_README.md`: data that originates only in psql (a-priori goals/participants, manual key-moment flags, curation history) is not reconstructable from the VoiceCapture folder; AI-derived entities are re-derivable via backfill + re-analysis, but curation is not bit-for-bit reproducible. The files are the source of truth for the core data only.
