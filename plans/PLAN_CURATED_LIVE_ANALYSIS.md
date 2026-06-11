# Plan — Curated Live Analysis (windowed context, max 10 key moments, evolving entities)

> **Audience:** Claude Code (Sonnet), working on the current codebase (commits through `3ca5f78`). Execute phases in order; verify acceptance criteria per phase.
>
> **Problem:** the AI worker analyzes each segment in isolation (only 6 recent segments as context). Result: every mildly notable sentence becomes a key moment (dozens per meeting), action items / decisions / agenda only ever *grow*, and nothing is ever revised when the meeting moves on.
>
> **Goal:** each AI call sees a large transcript window (last ~25 segments) + a rolling summary of everything before it + the **current state** of all derived entities, and returns a *curated target state*: at most 10 key moments, action items that get updated/completed/merged, decisions that can be superseded, and an agenda that evolves — with mode-dependent behavior (a-priori vs dynamic).

**Decisions already made (do not revisit):** analysis cadence stays per new segment (~10 s); with an a-priori agenda the AI may only update coverage status (never add items); key moments that fall out of the top 10 are soft-archived (`archived_at`), never deleted.

---

## 1. Design shift: extraction → curation

Current pipeline (per segment): `worker._build_context` (6 recent segments, no entity state for key moments/actions/decisions) → `prompts.py` extraction schema → `apply.py` append-mostly upserts.

New pipeline (per cycle):

```
context (per AI call)                         AI returns (target state)
─────────────────────────────                 ─────────────────────────────
rolling summary (≤250 words,                  segment_updates: sentiment +
  covers segments 1..S)                         topic tags per NEW segment
transcript window: segments                   key_moments: full curated list,
  max(S+1, last-25)..latest,                    ≤10, with salience, ids for
  stitched with speaker/time                    existing ones
current entity state:                         action_items: reconcile ops
  key moments (active), action                decisions: reconcile ops
  items, decisions, goals,                    goal_updates / new_goals
  agenda (+ agenda_mode),                     agenda: mode-dependent ops
  participants, topics
```

Because the AI sees current state and returns target state, the apply step becomes a **reconcile**: update rows by id, create rows without id (dedup_hash still guards duplicates), archive rows the AI dropped. Reprocessing the same window converges to the same state — idempotency (REQ-AI-04) is preserved by construction.

**Token budget (validates feasibility at 10 s cadence):** 25 segments × ~30 tokens ≈ 750; summary ≈ 350; entity state ≈ 800; system prompt + schema ≈ 1,200; total ≈ 3–4k in, ≤1k out. Haiku handles this in ~1–2 s — comfortably within the 10 s segment interval and the 3 s dashboard budget (REQ-NFR-01). Window of 25 is a config setting (`ANALYSIS_WINDOW_SEGMENTS`), 20–30 all fine.

**Backlog collapse:** the worker must claim **all** pending segments of one recording per cycle (not one), run a single AI call whose window covers them, and mark them all done. This keeps a backlog (AI outage, replay at speed 10) from generating one call per segment.

## 2. Migrations (016–019, one table per file, all `ALTER ... ADD COLUMN IF NOT EXISTS`)

**016_recording_analysis_state.sql**
```sql
ALTER TABLE recording ADD COLUMN IF NOT EXISTS context_summary text;            -- rolling summary
ALTER TABLE recording ADD COLUMN IF NOT EXISTS summary_up_to_segment int NOT NULL DEFAULT 0;
ALTER TABLE recording ADD COLUMN IF NOT EXISTS agenda_mode text NOT NULL DEFAULT 'dynamic'
    CHECK (agenda_mode IN ('apriori','dynamic'));
```

**017_key_moment_curation.sql**
```sql
ALTER TABLE key_moment ADD COLUMN IF NOT EXISTS salience real NOT NULL DEFAULT 0.5
    CHECK (salience BETWEEN 0 AND 1);
ALTER TABLE key_moment ADD COLUMN IF NOT EXISTS archived_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_key_moment_active ON key_moment (recording_id) WHERE archived_at IS NULL;
```

**018_action_item_curation.sql** — `ALTER TABLE action_item ADD COLUMN IF NOT EXISTS archived_at timestamptz;` (for AI-merged duplicates).

**019_decision_curation.sql** — `ALTER TABLE decision ADD COLUMN IF NOT EXISTS archived_at timestamptz;` (for superseded decisions).

`agenda_mode` is set once in `ingest_recording` (and in the segment-ingest auto-create path) right after `consume_apriori_setup`: `'apriori'` if the recording has agenda items with `source='apriori'`, else `'dynamic'`. **Include here the v2-report R4 fix:** the auto-create branch in `ingest_segment` must also call `consume_apriori_setup` before deriving the mode.

## 3. Backend changes

### 3.1 `dashboard/analyzer/worker.py`
- `_claim_next_segment` → `_claim_pending_batch`: pick the recording with the oldest pending segment, claim **all** its pending segments (`FOR UPDATE SKIP LOCKED`, mark `processing`), return them ordered. Set a `claimed_at`-style timestamp if you also pick up v2-report R2 (recommended, small).
- `_build_context` v2:
  - **Window:** last `ANALYSIS_WINDOW_SEGMENTS` (default 25) segments up to and including the newest claimed one, rendered as one stitched transcript: `[#<num> <participant or speaker_label or '?'> <HH:MM>] <text>` per line. Mark which segment_nums are NEW (claimed this cycle).
  - **Summary:** `recording.context_summary` + `summary_up_to_segment` (may be NULL/0 early in the meeting).
  - **Entity state:** active key moments (`archived_at IS NULL`: id, type, quote, salience), all non-archived action items (id, description, owner name, due_date, status), non-archived decisions (id, description, status), goals (id, description, status, coaching_tip), agenda items (id, title, position, status) + `agenda_mode`, participants, topics (keep the existing CTE).
- After a successful apply: run **summary maintenance** (§3.4), then mark all claimed segments `done`.
- On failure: `_handle_failure` resets the whole claimed batch to `pending` (attempts++ per segment, cap 3 → `failed`).

### 3.2 `dashboard/analyzer/prompts.py` — schema v2
Replace the extraction schema with a curation schema (same tool-use mechanism, both providers):

```jsonc
{
  "segment_updates": [            // ONLY for segments marked NEW
    {"segment_num": 41, "sentiment": 0.2,
     "speaker": {"participant_id": 3} | {"new_participant": {...}} | null,
     "topic_tags": [ ...unchanged shape... ]}
  ],
  "key_moments": [                // FULL curated list, max 10, most salient of the WHOLE meeting so far
    {"id": 7, "type": "decision", "quote": "...", "salience": 0.9, "speaker_ref": "..."},   // keep/update existing
    {"type": "tension", "quote": "...", "salience": 0.6, "speaker_ref": "..."}              // new (no id)
  ],
  "action_items": [               // reconcile ops; omit id to create
    {"id": 3, "status": "done"},                          // resolved during the meeting
    {"id": 5, "owner_ref": "Ellis", "due_date": "2026-06-20"},
    {"id": 9, "archive": true, "merge_into": 3},          // duplicate — archive
    {"description": "...", "owner_ref": null, "topic_ref": "..."}
  ],
  "decisions": [
    {"id": 2, "status": "agreed"},
    {"id": 4, "archive": true},                           // superseded
    {"description": "...", "status": "concept", "topic_ref": "..."}
  ],
  "goal_updates": [...unchanged...], "new_goals": [...unchanged...],
  "agenda": {                     // see mode rules below
    "active_item_id": 4,
    "items": [ {"id": 1, "status": "done"}, {"title": "...", "topic_ref": "..."} ]
  } | null,
  "add_synonyms": [...unchanged...]
}
```

System-prompt additions (key behavioral rules):
- *Key moments:* "Return the complete curated list of at most 10 key moments for the meeting **so far** — the most salient overall, not the most recent. Re-evaluate earlier moments against the new window: drop moments that turned out to be minor, merge near-duplicates, keep ids of moments you retain. salience ∈ [0,1]."
- *Action items / decisions:* "These evolve. Mark items resolved in conversation as done; archive duplicates or superseded entries; update owners/due dates when the conversation clarifies them. Do not re-create what you archive."
- *Agenda:* "agenda_mode=apriori: you may ONLY change status/active of the listed items; never add, rename, or remove items. agenda_mode=dynamic: you build the agenda yourself — add an item when the conversation clearly moves to a new subject, rename for clarity, mark previous active items done."
- *Sentiment & topics:* per NEW segment only.

### 3.3 `dashboard/analyzer/apply.py` — reconcile semantics
New `apply_curated_result` (replaces `apply_result`'s body; keep the per-entity try/except guards and the WS-after-commit pattern):

1. **segment_updates:** set `sentiment`, `participant_id`, `segment_topic`/`recording_topic` per listed segment (existing logic, looped).
2. **Key moments:** match by `id`; update quote/type/salience; insert no-id entries (dedup_hash check still applies); **archive every active key moment whose id is absent from the list**; finally a **server-side hard cap**: if >10 active remain (AI misbehaving), archive lowest-salience/oldest first. The cap is guaranteed by the server, never trusted to the AI.
3. **Action items:** by id → update fields / `status='done'` / `archive: true` sets `archived_at`; no-id → create (dedup_hash). Never un-archive, never blank existing values (COALESCE semantics as today).
4. **Decisions:** by id → status changes via the existing upgrade rules; `archive` sets `archived_at`. No-id → create.
5. **Agenda:** enforce mode **server-side**: in `apriori` mode accept only status/active changes on existing ids (ignore creates/renames, log them); in `dynamic` mode allow create/rename/status, keep the done-is-terminal guard and `started_at`/`ended_at` stamping.
6. **Goals:** unchanged (latch stays).
7. Mark claimed segments done; recompute participant stats when any speaker changed.

**WS events — switch curated panels to full-list snapshots** (simpler than diff events now that lists shrink as well as grow): `key_moments.updated {items}` (active, salience-ordered, ≤10), `action_items.updated {items}`, `decisions.updated {items}`; keep `agenda.updated`, `goal.updated`, `participant.stats`, `sentiment.updated`, `header.stats`, `past_reference.created` as-is. Remove the old `key_moment.created` / `action_item.upserted` / `decision.upserted` emit paths (the manual key-moment endpoint in `setup.py` also switches to the snapshot event).

### 3.4 Rolling summary maintenance (new: `dashboard/analyzer/summary.py`)
- Trigger after a successful apply when `newest_segment_num − summary_up_to_segment > WINDOW + 10` (i.e., ≥10 segments have scrolled past the window since the summary last advanced).
- One extra AI call (same `FallbackProvider`): input = current `context_summary` + the segments from `summary_up_to_segment+1` through `newest − WINDOW`; output = merged summary ≤250 words in the transcript language, preserving named decisions, commitments, owners, and unresolved questions. Write `context_summary` + `summary_up_to_segment` on the recording row.
- Failure is non-fatal: log and retry at the next trigger (the window still overlaps, nothing is lost).
- At ~10 s segments this fires roughly every 1.5–2 minutes — one extra cheap call, no cadence impact.

### 3.5 `dashboard/api/read.py`
- Snapshot: key moments filtered `archived_at IS NULL`, ordered `salience DESC, ts DESC`, `LIMIT 10`; action items and decisions filtered non-archived; include `agenda_mode` in the recording object.
- **Include v2-report R1 fix:** extract one shared `tone_for_recording()` helper (used by snapshot and `apply`) so both use the same 18-segment window.

### 3.6 Config (`dashboard/config.py`)
`ANALYSIS_WINDOW_SEGMENTS=25`, `KEY_MOMENTS_MAX=10`, `SUMMARY_LAG_SEGMENTS=10`, `SUMMARY_MAX_WORDS=250` — all env-overridable.

## 4. Frontend changes (`dashboard/frontend/src`)

- `types.ts`: `KeyMoment` + `salience`, `archived_at`; `Recording` + `agenda_mode`; new event types `key_moments.updated` / `action_items.updated` / `decisions.updated` (payload `{items}`), drop the three per-row event types.
- `useRecordingStore.ts`: the three new cases simply replace the list in the snapshot (no merge logic — delete the old upsert/dedupe branches).
- `KeyMomentsPanel.tsx`: render as given (server guarantees ≤10, salience-ordered); optional small salience indicator; remove client-side "newest on top" insertion logic.
- `ActionItemsPanel.tsx`: render `done` styling (strikethrough/check) — items can now complete mid-meeting.
- `DecisionsPanel.tsx`: no structural change (archived rows simply no longer arrive).
- `AgendaPanel.tsx`: when `agenda_mode === 'apriori'`, show a subtle "vaste agenda" label and render coverage only (the server already blocks AI items, so no filtering needed); in `dynamic` mode optionally show a "live opgebouwd" label.

## 5. Build phases

**Phase 1 — Migrations + agenda_mode** (016–019; set mode in both ingest paths; includes R4 fix). *Accept:* fresh + live DB migrate cleanly; recording started after a precreate with agenda → `apriori`; without → `dynamic`.

**Phase 2 — Worker batch-claim + context v2 + prompts v2.** *Accept:* with 40 pending segments (replay at speed 50, AI stopped, then started), the backlog drains in ≤ a handful of AI calls, not 40; the logged prompt contains stitched window + entity state.

**Phase 3 — Reconcile apply + cap + snapshot WS events.** *Accept:* unit tests for the reconciler: AI returns 12 moments → 10 active; existing id omitted → archived; `apriori` mode ignores agenda creates; reprocess same window → identical state (idempotency).

**Phase 4 — Rolling summary.** *Accept:* during a long replay, `context_summary` appears and `summary_up_to_segment` advances ~every 10 segments past the window; summary failure doesn't block segment processing.

**Phase 5 — read.py + frontend.** *Accept:* live replay shows key moments panel never exceeding 10 and visibly *swapping* items as the meeting evolves; an action item marked done mid-meeting updates its card; a-priori recording shows a fixed agenda with coverage only; dynamic recording grows its agenda.

**Phase 6 — Tests.** Convert `dashboard/tests/test_unit.py` to import the **real** functions (closes v1-report M6 — required, the reconciler is exactly the logic that must not drift) and add reconcile/cap/mode unit tests + one MockProvider end-to-end replay test asserting the ≤10 invariant over a full recording.

## 6. Edge cases & notes

- **Manual key moments** (`flagged_by='user'`): exempt from auto-archiving by the reconciler and from the cap-eviction order (archive AI moments first); the AI sees them in state and may not drop them — enforce server-side by ignoring their omission.
- **Idempotency:** state-based curation converges; `analyze_recording.py --reset` reprocessing yields the same final state. dedup_hash remains the guard against re-creation of archived items in the same form — when a no-id item's dedup_hash matches an **archived** row, *un-archive and update* rather than insert (one explicit rule in the reconciler).
- **Replay/retro-analysis** (`scripts/analyze_recording.py`) automatically benefits: batch-claim turns a full re-analysis into ~(N/window-advance) calls instead of N.
- **Cost:** context grows from ~1k to ~4k input tokens per call; with Haiku at 10 s cadence this stays trivial; the summary call adds ~1 call per 2 minutes.
- **Do not change** the ingest path, spool, reapers, past-references, or the goal latch — they are unaffected and validated.
