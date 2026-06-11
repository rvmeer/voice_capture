# Validation & Improvement Report — Live Meeting Intelligence Dashboard

**Date:** 2026-06-11 · **Scope:** commits `49dc56b` + `1bc8a04` (8,667 insertions, 76 files) validated against the requirements and `plans/PLAN_LIVE_MEETING_DASHBOARD.md`.

**How validated:** full code review of backend (`dashboard/`), migrations, Voice Capture integration (`dashboard_client.py`, `main.py` wiring), frontend (`dashboard/frontend/src`), plus dynamic checks: `pytest dashboard/tests` (32 passed), import smoke test of all modules (OK), `tsc --noEmit` (clean), and a live psycopg3 adapter probe confirming the jsonb bug. No PostgreSQL was available in the validation sandbox, so migrations were verified by inspection only — flagged below where that matters.

---

## 1. Verdict at a glance

The implementation follows the plan closely and the architecture is sound: dumb synchronous ingest fully decoupled from an AI worker queue (`ai_status` + `FOR UPDATE SKIP LOCKED`), solid idempotency (dedup hashes, ON CONFLICT merges, goal latch), a clean provider abstraction with Claude tool-use + Ollama fallback, one-table-per-migration, and a typed React/Zustand frontend with WS reconnect + snapshot refetch.

However, **5 critical defects currently break user-visible functionality**, including the entire a-priori setup flow and the speaking-time/tone panel. None are architectural — all are fixable in hours.

| Area | Status |
|---|---|
| Segment ingest & persistence (REQ-REC) | ✅ works, 2 caveats |
| A-priori setup (REQ-PRE) | ❌ broken end-to-end (C2) |
| AI pipeline & idempotency (REQ-AI, REQ-FLY) | ✅ good, robustness gaps |
| Participants & speaking time (REQ-PAR) | ⚠️ DB ok; live UI update broken (C3) |
| Topics & hierarchy (REQ-TOP) | ✅ |
| Goals / Agenda / Decisions / Actions / Key moments | ✅ minor issues |
| Cross-recording context (REQ-CTX) | ⚠️ likely fails at runtime (C5) |
| Dashboard panels 12.1–12.8 | ⚠️ 12.8 broken (C3+C4), rest ✅ |
| Resilience (REQ-NFR-03) | ⚠️ half-implemented (M1, M2) |
| Migrations (REQ-NFR-02/04) | ⚠️ fresh-DB bootstrap broken (C1) |

---

## 2. Critical bugs (P0 — fix before first real use)

### C1 — Migration 001 fails on a fresh database
`dashboard/migrations/sql/001_recording.sql` declares `status meeting_status DEFAULT 'planned'`, but the enum type `meeting_status` is **never created in any migration**. On a fresh DB (`CREATE TABLE IF NOT EXISTS` actually executing), migration 001 errors out and the whole chain halts. It only works today because the live DB already has the table+type, so the statement is skipped.

Two follow-on risks even on the live DB: (a) if the existing enum lacks the values `'live'`/`'ended'`, every ingest INSERT/UPDATE fails at runtime; (b) default `'planned'` and the frontend type `'live' | 'ended' | 'planned'` quietly deviate from REQ-REC-03 (`live`/`ended` only).

**Fix:** add a guarded `DO $$ ... CREATE TYPE meeting_status AS ENUM ('planned','live','ended') ... $$` (or migrate the column to `text` + CHECK), and `ALTER TYPE ... ADD VALUE IF NOT EXISTS 'live'/'ended'` for the live DB. Then verify with `python -m dashboard.migrations.runner` against a scratch DB — the plan's Phase 1 acceptance test (fresh-DB run) was evidently never executed.

### C2 — A-priori setup (REQ-PRE-01..03) is broken twice over
1. **Payload shape:** `HomePage.tsx` POSTs `{recording_title_hint, participants, agenda, goals, topics}` flat, but `PrecreateRequest` requires `{recording_title_hint, payload: {...}}` → FastAPI returns **422** for every pre-configure submission. The form shows "✅ saved" anyway because the fetch result is never checked.
2. **jsonb adaptation:** even with the correct shape, `INSERT INTO apriori_setup ... VALUES (%s, %s)` passes a Python dict; **verified dynamically**: psycopg3 raises `ProgrammingError: cannot adapt type 'dict'`. The dict must be wrapped in `psycopg.types.json.Jsonb(payload)`.

**Fix:** wrap with `Jsonb(...)` in `precreate_recording`; nest the frontend body under `payload` (or accept both shapes in the model); make `submitSetup` check `res.ok` and surface errors. Add one integration test that precreates → starts a recording → asserts linked entities.

### C3 — `participant.stats` WS event crashes the live page
Backend (`apply.py`) broadcasts a **bare list** with fields `participant_id`/`ratio`; the frontend store reads `(payload as {participants}).participants` → `undefined`, and stores it. `SpeakingTonePanel` then calls `.sort()` on `undefined` → unhandled TypeError → **blank dashboard** the first time the AI attributes a speaker. Field names also disagree (`participant_id`/`ratio` vs `id`/`speaking_time_ratio`).

**Fix:** broadcast `{"participants": [...]}` reusing the exact snapshot query/field names; defensively guard the store (`payload?.participants ?? []`). This also restores REQ-PAR-03's "updated continuously" on the UI.

### C4 — Tone indicator can never show anything but "Neutral"
`stats.tone_window()` emits labels `positive | neutral | negative` (thresholds ±0.25); the frontend `ToneInfo` type and `TONE_CONFIG` expect `constructive | neutral | tense` and fall back to Neutral for unknown labels. Panel 12.8's tone indicator is effectively dead. Notably, `test_unit.py` contains a `_tone_label` replica with the *correct* labels and ±0.15 thresholds — the test documents the intended behavior but tests a copy, so the divergence went unnoticed (see M6).

**Fix:** change `tone_window` to return `constructive`/`tense` (and decide on thresholds once); also replace the fixed "last 6 segments" window with the spec's time window (last ~3 minutes) — at 10s segments, 6 segments is only 1 minute.

### C5 — Embedded Qdrant access from the dashboard process will fail or block
`context/past_refs._qdrant_snippets()` instantiates `QdrantIndexer()` **inside the dashboard service**. The tray app already holds the embedded Qdrant storage lock — commit `3ead9b1` added the internal HTTP proxy in `main.py` precisely because two processes cannot share embedded storage. So while Voice Capture runs (i.e., always during a live meeting), Qdrant enrichment of past references throws and is swallowed by the `except` → REQ-CTX context loses its semantic-search half, and dig-deeper (12.6) returns nothing. Additionally the call is synchronous inside the async event loop and re-instantiates the indexer (embedding-model load) per call — when it *does* work, it freezes every WS broadcast and HTTP request for seconds, busting REQ-NFR-01.

**Fix:** call the tray app's internal proxy (`/qdrant/search`, same API the MCP server uses) via `httpx` instead of importing `QdrantIndexer`; or if direct access is kept for tray-app-off scenarios, wrap in `asyncio.to_thread(...)` and cache one indexer instance with a server-mode Qdrant.

---

## 3. Major gaps (P1 — needed for the requirements to hold under real conditions)

**M1 — Spool file is written but never replayed.** `dashboard_client._spool()` saves failed deliveries to `~/.voice_capture_dashboard_spool.jsonl`, but no code ever reads it. If the dashboard service is down during a recording, those segments are lost forever — REQ-NFR-03/REC-04 only half-met. *Fix:* on `DashboardClient` startup (and periodically), drain the spool before processing the live queue.

**M2 — Segments can get stuck in `processing` forever.** Two paths: (a) service crash/restart between claim and apply; (b) an exception in `_build_context` is caught by the worker's outer handler, which logs but never resets the status. The queue only picks up `pending`. *Fix:* on worker startup and every few minutes, reset `processing` rows older than ~2 minutes back to `pending` (bump `ai_attempts`).

**M3 — Segment ingest 404s if the recording row is missing.** `ingest_segment` calls `get_recording_row` → HTTPException 404. If the `recording_started` POST was lost (spooled — see M1), every subsequent segment fails 3 retries and spools too. *Fix:* auto-create a minimal `live` recording row on first segment (upsert), making ingest self-healing.

**M4 — No Ollama fallback for the most common Claude failures.** `_should_fallback` matches only `APIConnectionError/AuthenticationError/PermissionDeniedError/RateLimitError`. `APITimeoutError`, `InternalServerError`, and overloaded-529 errors raise through → 3 retries → segment `failed`, no fallback. *Fix:* include `APITimeoutError`, `APIStatusError` (5xx), and `OverloadedError`; consider falling back on *any* exception after the first retry.

**M5 — Unvalidated AI field values can poison a whole segment.** `date.fromisoformat(due_date)` in `apply.py` throws on any malformed AI date ("next week"), failing the entire segment transaction 3 times. Same class of risk for unexpected enum values reaching CHECK constraints. *Fix:* per-entity try/except inside apply — skip the bad entity, keep the rest; log it.

**M6 — Tests verify replicas, not the code.** Every helper in `test_unit.py` is re-implemented inline ("same logic as in apply.py / stats.py") — and at least one (tone label/thresholds) has already drifted from the real implementation, which is exactly how C4 escaped. There is no integration test, no `MockProvider`, and the plan's replay-based E2E (Phase 10) is absent. *Fix:* import the real functions; add one DB-backed integration test (scratch Postgres + canned AI responses via a `MockProvider`) that replays a fixture recording and asserts idempotency by reprocessing.

**M7 — Full `topic` table sent to the AI on every segment.** `_build_context` selects **all** topics. With months of recordings this grows unbounded — token cost, latency, and degraded matching. *Fix:* recording-linked topics + top ~20 global by `occurrence_count` (as planned).

---

## 4. Minor issues (P2)

1. **Done agenda items can be reactivated** by `active_item_id` (plan: done is terminal). Add `AND status <> 'done'` to the activation UPDATE.
2. **`overdue` is display-time only** (`apply_overdue` in snapshot) — fine in practice, but a `status='overdue'` is never persisted nor broadcast mid-meeting; a due date passing during a live recording won't update the panel until refetch.
3. **Past-reference `signal` heuristic is crude:** any past decision → `repeated`; one `done` action item → `resolved` (overriding `repeated`). REQ-CTX-02 intends `agreed` decisions → `resolved` and *unresolved/recurring* items → `repeated`. The planned AI classification call was skipped entirely — acceptable simplification, but the signals will often mislabel.
4. **WS URL hardcodes port 8100** (`ws://${hostname}:8100/...`) — the Vite `/ws` proxy is configured but unused; breaks behind HTTPS or a changed port. Use relative `ws(s)://${location.host}/ws/...`.
5. **Empty segments are never sent to the dashboard** (filtered in `on_segment_transcribed` before the push) — defensible, but yields gaps in `segment_num` and slightly under-counts speaking time.
6. **`ClaudeProvider` creates a new `AsyncAnthropic` client per segment** — reuse one instance.
7. **No DELETE endpoints** for goals/agenda/participants (plan listed them); mis-extracted AI entities can't be removed from the UI.
8. **`config.py` default `OLLAMA_MODEL="qwen3.6:latest"`** — likely not present locally; document/verify (plan suggested confirming with the user).
9. **Tone/window:** snapshot and apply both hardcode 6 segments; centralize in one place when fixing C4.
10. **`recording.title NOT NULL`** with COALESCE-to-id in ingest works, but `insert_recordings.py` rows predate this — verify no NULL titles exist before relying on it.

---

## 5. Requirements traceability (verdicts)

| Requirement | Verdict | Notes |
|---|---|---|
| REQ-REC-01/02 | ✅ | push from `on_segment_transcribed`, speaker optional |
| REQ-REC-03 | ⚠️ | works on live DB *if* enum has values; see C1 |
| REQ-REC-04 | ⚠️ | persist-first ✅; spool never drained (M1), 404 edge (M3) |
| REQ-REC-05 | ✅ | `recording.recording_id UNIQUE` |
| REQ-PRE-01..03 | ❌ | C2 — broken end-to-end (on-the-fly mode unaffected) |
| REQ-FLY-01..04 | ✅ | reuse-before-create, synonyms, segment_topic+confidence |
| REQ-FLY-05 | ⚠️ | stored ✅; UI tone dead (C4) |
| REQ-PAR-01/02 | ✅ | global participants, join table with ratio |
| REQ-PAR-03 | ⚠️ | recomputed only on AI speaker attribution; UI event broken (C3) |
| REQ-TOP-01..03 | ✅ | hierarchy, occurrence trigger verified by inspection |
| REQ-TOP-04 | ⚠️ | Postgres half ✅; Qdrant half fails at runtime (C5) |
| REQ-GOA-01..05 | ✅ | latch, achieved_at + trigger segment, topic link |
| REQ-AGE-01..05 | ✅ | generated duration column; minor: done-reactivation (P2-1) |
| REQ-DEC-01..03 | ✅ | incl. smart status-upgrade on conflict |
| REQ-ACT-01..03 | ✅ | overdue display-time only (P2-2) |
| REQ-KEY-01..02 | ✅ | AI + manual endpoint with user-flag upgrade |
| REQ-CTX-01..03 | ⚠️ | persisted+idempotent ✅; C5 + crude signals (P2-3) |
| Dashboard 12.1–12.7 | ✅ | all panels present and wired |
| Dashboard 12.8 | ❌ | C3 + C4 |
| REQ-AI-01 | ⚠️ | context complete but unbounded topics (M7) |
| REQ-AI-02 | ✅ | forced tool-use with JSON schema |
| REQ-AI-03 | ✅ | async queue, never blocks ingest |
| REQ-AI-04 | ✅ | dedup hashes + ON CONFLICT; reprocessing converges |
| REQ-NFR-01 | ⚠️ | fine with Haiku; C5 blocking calls threaten it |
| REQ-NFR-02/04 | ⚠️ | structure ✅; fresh-DB bootstrap broken (C1) |
| REQ-NFR-03 | ⚠️ | pending-backlog ✅; M1 + M2 |

---

## 6. Recommended fix order

1. **C2** (a-priori flow) + **C3** (page crash) + **C4** (tone) — small, user-visible, ~1–2 h total.
2. **C1** — write the enum-safe migration and *actually run* the fresh-DB acceptance test from the plan.
3. **C5** — switch past_refs to the tray app's `/qdrant/search` proxy via async httpx.
4. **M1–M5** — resilience set: spool drain, processing-reaper, ingest auto-create, broader fallback, per-entity apply guards.
5. **M6** — make tests import real code; add the MockProvider replay integration test (this would have caught C2–C4).
6. P2 list opportunistically.

## 7. What was done well

Worth keeping as-is: the ingest/AI decoupling with `FOR UPDATE SKIP LOCKED` and attempt-capped retries; the idempotency design (verified logic paths converge on reprocess); decision status upgrade rules (`concept→agreed`, never downgrade); the goal achieved-latch with trigger-segment provenance; `apriori_setup` staging with `SKIP LOCKED` consumption (elegant solution to the "recording id doesn't exist yet" problem); strict separation of VC `recording_id` vs internal UUID; and the frontend's snapshot-hydrate + WS-patch + refetch-on-reconnect pattern. The structure makes all P0 fixes local and low-risk.
