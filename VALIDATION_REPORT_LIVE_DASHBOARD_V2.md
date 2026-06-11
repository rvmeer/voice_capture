# Validation & Improvement Report v2 — Live Meeting Intelligence Dashboard

**Date:** 2026-06-11 · **Scope:** commits `5eaa9ed` → `3ca5f78` (fix round following `plans/VALIDATION_REPORT_LIVE_DASHBOARD.md` v1), validated against the requirements and the v1 findings.

**How validated:** line-by-line review of every diff since `1bc8a04`, cross-checked against the v1 issue list; verification of the new Qdrant proxy contract against `main.py`'s internal API (port 5151, `POST /qdrant/search`, `{"results": [...]}` shape) and `QdrantIndexer.search()` field names; dynamic re-checks: `pytest dashboard/tests` (32 passed), import smoke test (OK), `tsc --noEmit` (clean). Still no PostgreSQL in the validation sandbox — migration 001 verified by inspection.

---

## 1. Verdict at a glance

**All 5 critical bugs (C1–C5) are properly fixed, plus 6 of 7 major gaps (M1–M5, M7) and 3 of the P2 items (P2-1, P2-4, P2-6).** The fixes are correct, not cosmetic — e.g. the Qdrant fix switched to the tray app's internal proxy exactly as recommended (avoiding the embedded-storage lock *and* the event-loop blocking), and the `participant.stats` fix corrected both the payload wrapper and the field names. The system is now functionally ready for real use.

What remains: one major gap (M6 — tests still verify inline replicas instead of the real code), a handful of v1 minor items, and **4 small new issues introduced by the fix round** (§4). Nothing remaining is release-blocking.

| Area | v1 | v2 |
|---|---|---|
| Fresh-DB migrations (C1) | ❌ | ✅ guarded `DO $$` enum creation + value backfill |
| A-priori setup (C2, REQ-PRE) | ❌ | ✅ `Jsonb()` wrap + accepts flat & nested payload |
| `participant.stats` crash (C3) | ❌ | ✅ `{participants: [...]}` + snapshot field names + store guard |
| Tone labels (C4) | ❌ | ✅ `constructive/tense`, ±0.15, window 18 segments (~3 min) |
| Qdrant lock/blocking (C5) | ❌ | ✅ async httpx → tray proxy `:5151/qdrant/search` |
| Spool replay (M1) | ❌ | ✅ drained on tray-app start |
| Stuck `processing` segments (M2) | ❌ | ✅ reaper at startup + ~5 min interval |
| Segment-ingest 404 (M3) | ❌ | ✅ auto-creates recording row |
| Fallback coverage (M4) | ❌ | ✅ timeout/5xx/overloaded/`APIError` included |
| AI-value poisoning (M5) | ❌ | ✅ per-entity try/except in `apply_result` |
| Tests test replicas (M6) | ❌ | ❌ **unchanged** |
| Unbounded topic context (M7) | ❌ | ✅ CTE: linked topics ∪ top-20 (incl. its own UNION/ORDER BY bugfix `9fab68c`) |

## 2. Fix-by-fix verification notes

**C1 (migrations):** the three `DO $$` blocks are idempotent and correct for both fresh and live DBs. One caveat: `ALTER TYPE ... ADD VALUE` inside a transaction requires PostgreSQL ≥ 12 (the migration runner wraps each file in a transaction). On a fresh DB the type is created with all three values so the ALTER branches never run; on a live PG ≥ 12 DB they run fine. Document PG 12+ as a hard requirement. The fresh-DB acceptance run is still outstanding — execute `python -m dashboard.migrations.runner` once against `createdb recordings_scratch` to close this for good.

**C2 (precreate):** `Jsonb(body.get_payload())` fixes the adaptation error (the exact failure verified dynamically in v1), and `PrecreateRequest` now accepts the UI's flat shape as well as the nested one. Leftover: `HomePage.submitSetup` still doesn't check `res.ok` — a future failure would again silently show "✅ saved" (carried forward as R3).

**C3/C4 (panel 12.8):** payload now `{"participants": [...]}` with `id`/`speaking_time_ratio`/`role`/`source` matching the snapshot query; store guards with `?? []`. Tone labels and thresholds now match the frontend's `ToneInfo` type, and the live tone window grew to 18 segments (~3 min at 10 s). New inconsistency introduced: the **snapshot** tone in `read.py` still uses `LIMIT 6` — initial page load and live updates compute tone over different windows (R1).

**C5 (Qdrant):** contract verified end-to-end: `past_refs` POSTs `{query, limit}` to `http://127.0.0.1:5151/qdrant/search` (configurable via `VC_INTERNAL_API_URL`), reads `data["results"]`, and uses `recording_id`/`text` keys — all matching `main.py`'s `RecordingAPIHandler` and `QdrantIndexer.search()` exactly. Graceful degradation (debug-log + empty list) when the tray app is off. Correct fix.

**M1 (spool):** drained in a background thread on `DashboardClient` construction, failed lines re-spooled. Two limitations: drain happens only at tray-app start (if the dashboard service recovers mid-session, spooled events wait until the next restart), and the drain thread posts concurrently with the live queue, so ordering across the two isn't guaranteed — harmless today because every ingest endpoint is an upsert, worth a comment in the code.

**M2 (reaper):** correct for the current single-serial-worker design. Two latent weaknesses, see R2.

**M3 (auto-create):** works; the auto-created row uses `title = recording_id` and `started_at = first segment ts`. Note that this path does **not** call `consume_apriori_setup`, so if the `recording_started` event is lost, a pending pre-configuration is not applied (R4).

**M4/M5/M7, P2-1/4/6:** verified correct as implemented. P2-1's guard (`AND status <> 'done'`) now enforces done-is-terminal for agenda items.

## 3. Remaining from v1 (not addressed — carried forward)

| # | Item | Severity |
|---|---|---|
| M6 | `test_unit.py` still tests inline *copies* of the logic; this exact pattern hid bug C4 in v1. The fixed code (e.g. `stats.tone_window` now matching the test replica's thresholds) makes converting to real imports trivial. Still no integration test / MockProvider replay. | Major (quality) |
| P2-2 | `overdue` computed at snapshot read only; never persisted or broadcast mid-meeting | Minor |
| P2-3 | Past-reference `signal` heuristic unchanged (any decision → `repeated`; a done action item → `resolved`); REQ-CTX-02 intent only loosely met | Minor |
| P2-5 | Empty segments still never pushed (gaps in `segment_num`) | Cosmetic |
| P2-7 | No DELETE endpoints for AI mis-extractions | Minor |
| P2-8 | `OLLAMA_MODEL` default still `qwen3.6:latest` — verify it exists locally or change default | Minor |
| — | `goal_topic_history` view (migration 014) remains entirely unused — REQ-GOA-05's cross-recording goal comparison is stored but never surfaced in API or UI | Minor |

## 4. New issues introduced by the fix round (R-series)

**R1 — Tone window inconsistency (snapshot vs live).** `apply.py:_tone_payload` uses `LIMIT 18`; `read.py` snapshot still `LIMIT 6`. On page load the tone gauge can differ from the next WS update. Fix: extract one shared `tone_for_recording(conn, recording_uuid)` helper.

**R2 — Segment reaper is correct only by accident of seriality.** `_reap_stuck_segments` resets *every* `processing` row because the 3-minute clause compares `ai_processed_at`, which is always NULL while processing (it's only set on completion). Today that's safe — the single worker never has a segment in flight when the reaper runs — but it breaks the moment a second worker or concurrent processing is added. Also, reaped attempts are capped at `LEAST(ai_attempts+1, 2)`, so a segment that repeatedly hangs (rather than errors) can cycle forever instead of reaching `failed`. Fix: set a `claimed_at` timestamp on claim and reap on that; let reaped attempts count toward the 3-attempt cap.

**R3 — Pre-configure form still reports success unconditionally** (`submitSetup` ignores `res.ok`). The v1 root cause (422) is fixed, but the masking behavior that hid it is still there.

**R4 — Auto-created recordings skip a-priori consumption** (see M3 note). If the start event is lost but a pre-configuration is pending, participants/agenda/goals are silently never attached. Fix: call `consume_apriori_setup` in the auto-create branch too.

Also noted: the new 4-hour live-recording reaper (§6.3) would force-end a genuinely long recording (e.g. an all-day workshop) if the service restarts mid-session — consider making the threshold configurable.

## 5. Requirements traceability (v2 verdicts)

| Requirement | v1 | v2 | Notes |
|---|---|---|---|
| REQ-REC-01/02/05 | ✅ | ✅ | |
| REQ-REC-03 | ⚠️ | ✅ | enum guaranteed; `planned` extra value tolerated |
| REQ-REC-04 | ⚠️ | ✅ | spool drained, ingest self-healing (R4 edge remains) |
| REQ-PRE-01..03 | ❌ | ✅ | end-to-end functional (R3 cosmetic) |
| REQ-FLY-01..05 | ✅/⚠️ | ✅ | tone UI now live |
| REQ-PAR-01..03 | ⚠️ | ✅ | live ratio updates reach the panel |
| REQ-TOP-01..04 | ✅/⚠️ | ✅ | Qdrant half now works via proxy |
| REQ-GOA-01..04 | ✅ | ✅ | |
| REQ-GOA-05 | ✅ | ⚠️ | topic link stored; cross-recording comparison still not surfaced (unused view) |
| REQ-AGE-01..05 | ✅ | ✅ | done-is-terminal now enforced |
| REQ-DEC-01..03 / ACT-01..03 / KEY-01..02 | ✅ | ✅ | |
| REQ-CTX-01..03 | ⚠️ | ✅ | functional; signal heuristic still crude (P2-3) |
| Dashboard 12.1–12.8 | 12.8 ❌ | ✅ all | |
| REQ-AI-01..04 | ✅/⚠️ | ✅ | bounded topic context |
| REQ-NFR-01 | ⚠️ | ✅ | blocking Qdrant call removed from event loop |
| REQ-NFR-02/04 | ⚠️ | ✅ | PG ≥ 12 required; fresh-DB run still to be executed once |
| REQ-NFR-03 | ⚠️ | ✅ | spool + segment reaper + backlog drain |

## 6. Features beyond the requirements

The implementation now contains functionality that was **not** in the original requirements document. None of it conflicts with the requirements; items 6.1–6.4 are new in this fix round, 6.5–6.9 came with the original implementation.

1. **Per-recording AI (re)analysis tool** — `scripts/analyze_recording.py` re-queues all segments of any recording for AI processing (`--reset` to redo `done` segments). Effectively enables *retro-analysis of historical recordings* through the live pipeline — a useful capability the requirements never asked for (they only required live processing and backlog recovery).
2. **Recording-list auto-refresh** — the home page polls `/recordings` every 5 s, so newly started recordings appear without manual refresh. The requirements specify only the per-recording live dashboard, not a self-updating overview.
3. **Stale live-recording reaper** — at service startup, recordings stuck in `live` for > 4 h are auto-ended (`cfe7265`). Pure housekeeping, not required; note the long-meeting caveat in §4.
4. **Tray-app remote control endpoints** — the internal API's `/start` and `/stop` routes let other processes start/stop a Voice Capture recording over HTTP (used by MCP, but accessible to the dashboard ecosystem too).
5. **Recording overview page with live/ended grouping** — a navigable index of all recordings (live first), beyond the required single-recording dashboard.
6. **Replay/simulation harness** — `scripts/replay_recording.py` replays any historical recording through the ingest API at configurable speed with a synthetic id; this was a development tool in the plan, not a requirement, and doubles as a demo mode.
7. **Pre-configuration staging with title-hint matching** — `apriori_setup` lets a meeting be configured *before any recording exists*, matched later by title hint or applied to the next recording. The requirements only said a-priori data "is linked at creation time"; the staging/matching workflow is extra.
8. **Automatic `is_user` bootstrapping** — migration 002 marks the participant `'ralf van meer'` as the user automatically (REQ-ACT-03 requires distinguishing the user, but not auto-detection in a migration). Side note: this hardcodes a name in a migration — fine for a personal tool, worth knowing it's there.
9. **Health endpoint & `planned` recording status** — `/health` with DB connectivity state; and a third `planned` status value (inherited from the pre-existing DB) tolerated throughout the stack, which could later support scheduled meetings.

## 7. Recommended next steps (priority order)

1. Run the **fresh-DB migration acceptance test** once (only unexecuted verification left from the plan).
2. **M6**: convert `test_unit.py` to import the real functions (now trivial), and add the MockProvider replay integration test — this is the single highest-leverage quality item left; it would have caught C2–C4 and would catch R1 today.
3. Fix the four R-items (all small: shared tone helper, `claimed_at`-based reaper, `res.ok` check, apriori-consumption in auto-create).
4. Surface REQ-GOA-05 (use or drop the `goal_topic_history` view) and revisit the past-reference signal heuristic (P2-3) — optionally with the originally planned AI classification call.
5. P2 leftovers opportunistically (DELETE endpoints, Ollama model default, mid-meeting overdue broadcast).
