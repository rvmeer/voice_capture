# Implementation Plan — Live Meeting Intelligence Dashboard

> **Audience:** Claude Code (Sonnet). Execute phases in order. Each phase ends with explicit acceptance criteria — verify them before moving on. Do not skip the verification steps.
>
> **Scope:** Extend the existing Voice Capture application with a real-time meeting intelligence system: segment ingestion, relational data model in PostgreSQL, an AI analysis pipeline (Claude with Ollama fallback), and a live React dashboard updated over WebSocket.

---

## 1. Current state of the codebase (read this first)

The repo root contains a flat Python application (no `src/` layout):

| Component | File(s) | Relevant facts |
|---|---|---|
| Tray app (PyQt6) | `main.py` (~1900 lines) | `VoiceCaptureApp` class. Signal `segment_transcribed = pyqtSignal(str, int)` → handler `on_segment_transcribed(self, text, segment_num)`. This handler already pushes live segments to Qdrant best-effort (`qdrant_indexer.index_live_segment(...)`) — **mirror that exact pattern** for the dashboard push. `self.segment_duration = 10` (seconds, configurable). `self.current_recording_id` holds the active Voice Capture recording id (format `YYYYMMDD_HHMMSS`). |
| Recording storage | `recording_manager.py`, `~/Documents/VoiceCapture/recording_<id>/` | JSON metadata + segment WAVs + `transcription_<n>.txt` per segment. |
| Existing REST API | `openapi_server.py` | FastAPI on **port 8000** (`/recordings`, `/transcription`, `/health`). Do not modify; the new service is separate. |
| MCP server | `mcp_server.py` | Exposes `search_recordings` (semantic search via Qdrant), `get_transcription`, `start_recording`, `stop_recording`, etc. |
| Qdrant | `qdrant.py` | `QdrantIndexer` class: `index_live_segment(...)`, `search(query, limit, recording_id)`. Reuse this class directly from the new service for "dig deeper". |
| Ollama | `ollama_utils.py` | `check_ollama_available()`, `get_ollama_models()`, `generate_title(...)` against `http://localhost:11434`. |
| Diarization | `diarization.py` | **Post-hoc only.** Live segments have NO speaker id. Treat speaker as optional on ingest (REQ-REC-02 says "where detectable"); the AI may infer speakers from text cues ("Jan, kun jij…"). |
| Existing Postgres | DSN `dbname=recordings` | Already contains tables `recording (recording_id UNIQUE, title, started_at, ended_at, status, …)`, `participant (name UNIQUE)`, `recording_participant (recording_id, participant_id, role)` — populated by `insert_recordings.py` / `insert_participants.py`. **Migrations must adopt these tables, not recreate them blindly** (see §4.1). |

## 2. Architecture decisions (already made — do not revisit)

1. **New backend service in this repo**: Python package `dashboard/` with its own FastAPI app, run as a separate process (`python -m dashboard`), default port **8100**. Voice Capture pushes segments to it over localhost HTTP.
2. **Frontend**: React + Vite + Tailwind in `dashboard/frontend/`. Production build served as static files by the dashboard FastAPI app; dev mode uses Vite dev server with proxy.
3. **AI**: Anthropic API primary (`ANTHROPIC_API_KEY`, default model `claude-haiku-4-5` for per-segment analysis — cheap and fast; configurable to Sonnet). Ollama as automatic fallback when the Anthropic API is unreachable/unconfigured. One provider interface, two implementations.
4. **Live updates**: WebSocket (`/ws/{recording_id}`), JSON events, one channel per recording.
5. **Database**: PostgreSQL (`dbname=recordings`), raw SQL via `psycopg` (v3) — no ORM. Migrations are plain numbered `.sql` files executed by a small runner (no Alembic), per REQ-NFR-02/04.
6. **Decoupling**: segment persistence is synchronous and dumb (REQ-REC-04); AI analysis is an asynchronous worker polling a queue table (REQ-AI-03, REQ-NFR-03). The dashboard reads DB state; the WS layer only signals "something changed".

```
┌─────────────┐  POST /ingest/*   ┌──────────────────────────────┐
│ Voice        │ ────────────────► │ dashboard service (:8100)    │
│ Capture      │                   │  FastAPI                     │
│ (main.py)    │                   │  ├─ ingest API   ──► Postgres│
└─────────────┘                   │  ├─ AI worker (async loop)   │
                                   │  │    Claude ⇄ Ollama        │
       Qdrant ◄────────────────────│  ├─ context worker (Qdrant)  │
                                   │  ├─ REST read API            │
   React dashboard ◄── WebSocket ──│  └─ WS hub                   │
└──────────────────────────────────┴──────────────────────────────┘
```

## 3. New directory layout

```
dashboard/
  __init__.py
  __main__.py            # uvicorn entrypoint: python -m dashboard
  config.py              # env-based settings (DB DSN, port, API keys, models)
  db.py                  # psycopg connection pool + helpers
  migrations/
    runner.py            # applies migrations/sql/*.sql in order, tracks schema_migrations
    sql/                 # 001_...sql … 0NN_...sql (one table per file, REQ-NFR-04)
  api/
    ingest.py            # POST endpoints called by Voice Capture
    setup.py             # a-priori CRUD (participants, agenda, goals, topics)
    read.py              # dashboard snapshot + panel reads
    ws.py                # WebSocket hub
  analyzer/
    worker.py            # async polling loop over unprocessed segments
    provider.py          # AIProvider protocol; ClaudeProvider, OllamaProvider, with fallback chain
    prompts.py           # system prompt + JSON schema (see §7)
    apply.py             # transactionally applies AI results to the DB (idempotent)
    sentiment.py         # sentiment extraction (part of the same AI call)
  context/
    past_refs.py         # cross-recording context builder (Postgres + QdrantIndexer)
  stats.py               # speaking ratio, header stats, tone window
  frontend/              # Vite + React + Tailwind app (see §9)
  tests/
scripts/
  replay_recording.py    # dev tool: replays an existing recording's segments through the ingest API
dashboard_client.py      # repo root: thin client used by main.py to push to the service
```

## 4. Database schema & migrations

### 4.1 Migration mechanics

- Table `schema_migrations(version int primary key, applied_at timestamptz)`. `runner.py` scans `dashboard/migrations/sql/`, applies files with version > max applied, each inside a transaction. Run automatically on service startup and manually via `python -m dashboard.migrations.runner`.
- **Adopting existing tables:** migrations 001–003 cover `recording`, `participant`, `recording_participant`, which already exist in the live DB. Write them as `CREATE TABLE IF NOT EXISTS` (matching the live shape) followed by `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for new columns. Before writing 001–003, **introspect the live DB** (`pg_dump --schema-only -d recordings` or `\d` via psql) and match the existing columns exactly so the migrations are no-ops on existing structure and full creates on a fresh DB.
- One table per migration file (REQ-NFR-04). Indexes/triggers for a table live in its migration file.

### 4.2 Tables (target shape)

All PKs are `id BIGINT GENERATED ALWAYS AS IDENTITY` unless stated. All timestamps `timestamptz`.

**001_recording.sql** — adopt + extend
```sql
recording (
  id PK,
  recording_id text UNIQUE NOT NULL,          -- Voice Capture id (REQ-REC-05)
  title text,
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  status text NOT NULL DEFAULT 'live'         -- live | ended  (REQ-REC-03)
    CHECK (status IN ('live','ended'))
)
```

**002_participant.sql** — adopt + extend
```sql
participant (
  id PK,
  name text UNIQUE NOT NULL,
  initials text,                               -- ADD COLUMN IF NOT EXISTS
  is_user boolean NOT NULL DEFAULT false       -- marks Ralf for REQ-ACT-03
)
```

**003_recording_participant.sql** — adopt + extend
```sql
recording_participant (
  recording_id bigint REFERENCES recording(id) ON DELETE CASCADE,
  participant_id bigint REFERENCES participant(id),
  role text,
  speaking_time_ratio real NOT NULL DEFAULT 0, -- REQ-PAR-02
  speaking_seconds real NOT NULL DEFAULT 0,    -- raw accumulator for live ratio updates
  source text NOT NULL DEFAULT 'apriori',      -- apriori | ai
  PRIMARY KEY (recording_id, participant_id)
)
```
> NOTE: the live DB's `recording_participant.recording_id` may reference `recording.id` or the text id — introspect first and keep whatever FK shape exists; add the new columns either way.

**004_topic.sql**
```sql
topic (
  id PK,
  label text UNIQUE NOT NULL,
  synonyms text[] NOT NULL DEFAULT '{}',       -- REQ-FLY-03
  parent_topic_id bigint REFERENCES topic(id), -- REQ-TOP-02
  occurrence_count int NOT NULL DEFAULT 0,     -- REQ-TOP-03
  created_at timestamptz NOT NULL DEFAULT now()
)
-- index: GIN on synonyms; functional unique index on lower(label)
```

**005_segment.sql**
```sql
segment (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
  segment_num int NOT NULL,
  text text NOT NULL,
  speaker_label text,                          -- nullable (REQ-REC-02 "where detectable")
  participant_id bigint REFERENCES participant(id),
  ts timestamptz NOT NULL,                     -- arrival timestamp
  duration_seconds real,
  sentiment real CHECK (sentiment BETWEEN -1.0 AND 1.0),  -- REQ-FLY-05
  ai_status text NOT NULL DEFAULT 'pending'    -- pending|processing|done|failed (REQ-AI-03/04, REQ-NFR-03)
    CHECK (ai_status IN ('pending','processing','done','failed')),
  ai_processed_at timestamptz,
  ai_attempts int NOT NULL DEFAULT 0,
  UNIQUE (recording_id, segment_num)           -- idempotent ingest
)
-- index on (ai_status, id) for the worker queue; (recording_id, ts)
```

**006_segment_topic.sql**
```sql
segment_topic (
  segment_id bigint REFERENCES segment(id) ON DELETE CASCADE,
  topic_id bigint REFERENCES topic(id),
  confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),  -- REQ-FLY-04
  PRIMARY KEY (segment_id, topic_id)
)
```

**007_recording_topic.sql** — materialized link for fast cross-recording queries + occurrence_count maintenance
```sql
recording_topic (
  recording_id bigint REFERENCES recording(id) ON DELETE CASCADE,
  topic_id bigint REFERENCES topic(id),
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (recording_id, topic_id)
)
-- AFTER INSERT/DELETE trigger maintains topic.occurrence_count (REQ-TOP-03)
```

**008_goal.sql**
```sql
goal (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,  -- REQ-GOA-01
  description text NOT NULL,
  coaching_tip text,                           -- REQ-GOA-03
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','achieved','at_risk')),  -- REQ-GOA-02
  topic_id bigint REFERENCES topic(id),        -- REQ-GOA-05
  source text NOT NULL DEFAULT 'apriori',      -- apriori | ai
  achieved_at timestamptz,                     -- REQ-GOA-04
  achieved_segment_id bigint REFERENCES segment(id),
  created_at timestamptz NOT NULL DEFAULT now()
)
```

**009_agenda_item.sql**
```sql
agenda_item (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
  title text NOT NULL,
  position int NOT NULL,                       -- REQ-AGE-01 order
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','done')),  -- REQ-AGE-02
  topic_id bigint REFERENCES topic(id),        -- REQ-AGE-05
  source text NOT NULL DEFAULT 'apriori',      -- apriori | ai (REQ-AGE-04)
  started_at timestamptz,
  ended_at timestamptz,
  duration_seconds real GENERATED ALWAYS AS
    (EXTRACT(EPOCH FROM (ended_at - started_at))) STORED,  -- REQ-AGE-03
  UNIQUE (recording_id, position)
)
```

**010_decision.sql**
```sql
decision (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
  description text NOT NULL,
  status text NOT NULL DEFAULT 'concept' CHECK (status IN ('agreed','concept','rejected')),  -- REQ-DEC-01
  segment_id bigint REFERENCES segment(id),    -- REQ-DEC-02
  decided_at timestamptz NOT NULL,             -- REQ-DEC-02
  topic_id bigint REFERENCES topic(id),        -- REQ-DEC-03
  dedup_hash text NOT NULL,                    -- REQ-AI-04, see §7.3
  UNIQUE (recording_id, dedup_hash)
)
```

**011_action_item.sql**
```sql
action_item (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,  -- REQ-ACT-01
  description text NOT NULL,
  owner_participant_id bigint REFERENCES participant(id),  -- optional (REQ-ACT-02)
  due_date date,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','overdue')),
  topic_id bigint REFERENCES topic(id),
  segment_id bigint REFERENCES segment(id),
  dedup_hash text NOT NULL,
  UNIQUE (recording_id, dedup_hash)
)
```

**012_key_moment.sql**
```sql
key_moment (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
  segment_id bigint REFERENCES segment(id),
  type text NOT NULL CHECK (type IN ('commitment','decision','tension','insight')),  -- REQ-KEY-01
  quote text NOT NULL,                         -- REQ-KEY-02
  speaker_participant_id bigint REFERENCES participant(id),
  speaker_label text,
  flagged_by text NOT NULL DEFAULT 'ai' CHECK (flagged_by IN ('ai','user')),
  ts timestamptz NOT NULL DEFAULT now(),
  dedup_hash text NOT NULL,
  UNIQUE (recording_id, dedup_hash)
)
```

**013_past_reference.sql**
```sql
past_reference (
  id PK,
  recording_id bigint NOT NULL REFERENCES recording(id) ON DELETE CASCADE,  -- current recording
  topic_id bigint NOT NULL REFERENCES topic(id),
  source_recording_id bigint NOT NULL REFERENCES recording(id),
  signal text NOT NULL CHECK (signal IN ('repeated','resolved','new_context')),  -- REQ-CTX-02
  summary text NOT NULL,                       -- what was said/decided
  source text NOT NULL DEFAULT 'auto',         -- auto | dig_deeper
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (recording_id, topic_id, source_recording_id, source)  -- REQ-CTX-03 + idempotency
)
```

**014_goal_topic_history view (optional)** — a SQL VIEW joining goal → topic → past recordings for REQ-GOA-05 panel data. Views may share a migration file with related indexes if needed; tables may not.

---

## 5. Build phases

Execute in order. Each phase is independently shippable and testable.

### Phase 0 — Scaffolding
- Create `dashboard/` package: `config.py` (pydantic-settings or plain env: `DASHBOARD_PORT=8100`, `DATABASE_DSN=dbname=recordings`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL=claude-haiku-4-5`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `AI_PROVIDER=auto|claude|ollama`), `db.py` (psycopg3 `AsyncConnectionPool`), `__main__.py` (uvicorn, runs migrations on startup), `api/` FastAPI app with `/health`.
- Add deps to `requirements.txt` / `pyproject.toml`: `psycopg[binary,pool]`, `anthropic`, `httpx`. Keep dashboard deps optional for the tray app (the tray app must run without them).
- **Accept:** `python -m dashboard` starts, `GET :8100/health` returns DB connectivity status.

### Phase 1 — Migrations
- Introspect live DB schema first (`pg_dump --schema-only -d recordings`); write `runner.py` + migrations 001–013(+014) per §4.
- **Accept:** runner is idempotent (second run = no-op); applying against a *fresh* scratch DB (`createdb recordings_test`) produces the full schema; applying against the live DB preserves existing rows in `recording`/`participant`/`recording_participant`. Trigger test: insert/delete `recording_topic` row → `topic.occurrence_count` changes.

### Phase 2 — Ingestion API + Voice Capture hook
Backend (`api/ingest.py`):
- `POST /ingest/recordings` `{recording_id, title?, started_at}` → upsert recording with status `live` (REQ-REC-03). Returns DB id.
- `POST /ingest/recordings/{recording_id}/segments` `{segment_num, text, ts, speaker_label?, duration_seconds?}` → insert with `ON CONFLICT (recording_id, segment_num) DO NOTHING` (REQ-REC-04, idempotent). Pure DB write — **no AI call in this path**. Broadcast `segment.created` on WS.
- `POST /ingest/recordings/{recording_id}/end` `{ended_at}` → status `ended`, set `ended_at`; close out the active agenda item if any.

Voice Capture side:
- New repo-root module `dashboard_client.py`: tiny class with an internal `queue.Queue` + daemon worker thread; methods `recording_started(id, title, started_at)`, `segment(id, num, text, ts)`, `recording_ended(id, ended_at)`. HTTP via `urllib.request` or `requests`, timeout 2s, retries with backoff, drops to a local JSONL spool file on persistent failure (never blocks or crashes the tray app).
- Wire into `main.py`: instantiate alongside Qdrant init; call from the recording start path, from `on_segment_transcribed` (after the Qdrant block, same best-effort style), and from the stop/finalize path. Guard every call with try/except + `logger.warning`, exactly like the existing Qdrant pattern.
- **Accept:** start a recording (or use the replayer, Phase 3) → `recording` row appears with status `live`; segments appear within 1s of transcription; stopping sets `ended` + `ended_at`. Kill the dashboard service mid-recording → tray app keeps working, segments spool, and are deliverable after restart.

### Phase 3 — Replayer (dev tool, build early)
- `scripts/replay_recording.py --recording-id <vc_id> [--speed 10] [--port 8100]`: reads an existing recording dir (`segments/transcription_*.txt` + metadata via `RecordingManager`), then replays it through the ingest API as if live (start → segments at `segment_duration/speed` intervals → end). Use a synthetic `recording_id` suffix (e.g. `<id>_replay01`) to avoid colliding with the real row.
- **Accept:** replaying any old recording populates the DB end-to-end. This becomes the standard test harness for Phases 4–9.

### Phase 4 — A-priori setup API (REQ-PRE-*)
`api/setup.py`, all plain CRUD:
- `POST /recordings/precreate` `{title, participants:[{name,initials}], agenda:[{title,position,topic_label?}], goals:[{description,coaching_tip?,topic_label?}], topics:[{label,parent_label?,synonyms?}]}`. Design: since the Voice Capture `recording_id` doesn't exist until the user presses record, the payload is stored in a staging table `apriori_setup(recording_title_hint, payload jsonb, created_at, consumed boolean)` (migration `015_apriori_setup.sql`). When `POST /ingest/recordings` fires, the most recent unconsumed setup (or one matched by title hint) is consumed and applied: participants upserted + linked, agenda/goals/topics created and linked — so everything is attached at recording creation time and instantly visible (REQ-PRE-02).
- Individual CRUD for live edits: `POST/PATCH/DELETE` for `participants`, `agenda_items`, `goals`, `topics` under `/recordings/{id}/…` (used by the dashboard's setup screen and manual corrections).
- Participant upsert rule: match on exact `name` (case-insensitive) → reuse (REQ-PAR-01, REQ-FLY-02).
- Topic upsert rule: match `lower(label)` against `lower(topic.label)` AND each element of `synonyms` → reuse; else create (REQ-FLY-03).
- **Accept:** precreate + start recording → all a-priori entities linked to the new recording and returned by the snapshot endpoint (Phase 7). Starting with no setup works identically (REQ-PRE-03).

### Phase 5 — AI pipeline (the core)
`analyzer/worker.py`:
- Async loop (started in FastAPI lifespan): every 1s, `SELECT … FROM segment WHERE ai_status='pending' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED` → mark `processing` → build context → call provider → `apply` → mark `done` (or `failed` after 3 attempts, with backoff). Because it polls the DB, a backlog accumulated while the worker/AI was down is processed automatically on recovery (REQ-NFR-03). Process segments of `ended` recordings too.
- Context window passed to the model (REQ-AI-01): recording title; participants (id, name, initials); topics linked to this recording (id, label, synonyms) + top-20 global topics by occurrence_count; goals (id, description, status); agenda (id, title, status, position); last 6 segments of transcript; the new segment (num, text, speaker_label).

`analyzer/provider.py`:
- `class AIProvider(Protocol): async def analyze(self, context: AnalysisContext) -> AnalysisResult`.
- `ClaudeProvider`: `anthropic.AsyncAnthropic`, single message, **tool-use with `input_schema` = the JSON schema in §7.2** (forces valid structure), `max_tokens≈2000`.
- `OllamaProvider`: `httpx` POST to `/api/chat` with `format: json` and the same schema embedded in the prompt; tolerate/repair minor JSON issues.
- `FallbackProvider`: try Claude; on `APIConnectionError`/auth/missing-key, fall through to Ollama; if both fail raise → segment retried later. Log which provider served each segment.

`analyzer/apply.py` — one DB transaction per segment result (details in §7.3). After commit, broadcast fine-grained WS events for everything that changed.

Sentiment (REQ-FLY-05) is a field in the same AI response — no second call.

- **Accept:** replay a real meeting at speed 10 → topics/goals/decisions/actions/key moments populate; `segment.sentiment` set; **re-run the worker over the same segments (reset `ai_status` to `pending`) → zero duplicate rows** (REQ-AI-04). Stop the worker, ingest 20 segments, restart → backlog drains.

### Phase 6 — Derived live state
In `stats.py` + extensions to `apply.py`:
- **Speaking ratio (REQ-PAR-03):** when a segment is attributed to a participant (speaker_label→participant mapping decided by the AI result), add `segment.duration_seconds` (fallback: the configured segment duration) to `recording_participant.speaking_seconds`; recompute `speaking_time_ratio = speaking_seconds / SUM(speaking_seconds)` for all rows of the recording in the same transaction. Broadcast `participant.stats`.
- **Goal transitions (REQ-GOA-02/04):** AI result may set goal status; on `achieved`, also write `achieved_at = segment.ts`, `achieved_segment_id`. Never auto-downgrade `achieved` → anything (one-way latch); `open ⇄ at_risk` may flip freely.
- **Agenda state machine (REQ-AGE-02/03):** AI result may nominate the currently-active agenda item id (or a new on-the-fly item, REQ-AGE-04). Apply: previous active item → `done` + `ended_at = segment.ts`; nominated item → `active` + `started_at` (only if not already set). Items are never reverted from `done`.
- **Tone window:** rolling sentiment = AVG over segments in the last 3 minutes; classify `constructive (>0.15) / neutral / tense (<-0.15)`; broadcast `sentiment.updated`.
- **Action item overdue check:** small periodic task flips `open` → `overdue` when `due_date < today`.
- **Accept:** replay shows ratios summing to ~1.0 and updating live; agenda items walk pending→active→done with sane durations; an achieved goal never reopens.

### Phase 7 — Read API + WebSocket hub
`api/read.py`:
- `GET /recordings/{id}/snapshot` → one JSON document with everything the dashboard needs (recording + header stats, participants+ratios, goals sorted at_risk→open→achieved, agenda ordered, decisions by time, action items, key moments, past references grouped by topic, tone). The frontend renders entirely from this; WS events trigger targeted refetch or in-place patch.
- `GET /recordings?status=live|ended`, `GET /recordings/{id}/segments?after=<n>`.
- `POST /recordings/{id}/key_moments` (manual flag, `flagged_by='user'`, REQ-KEY-01) and `POST /recordings/{id}/topics/{topic_id}/dig_deeper` (see Phase 8).

`api/ws.py`:
- `WS /ws/{recording_id}`. In-process hub: `dict[recording_db_id, set[WebSocket]]`. Every event: `{"type": "<event>", "recording_id": …, "payload": {…}}`. Event types: `segment.created`, `segment.analyzed`, `topic.tagged`, `goal.updated`, `agenda.updated`, `decision.upserted`, `action_item.upserted`, `key_moment.created`, `participant.stats`, `sentiment.updated`, `past_reference.created`, `recording.status`, `header.stats`.
- Latency budget (REQ-NFR-01): ingest→WS broadcast is in-request (<100ms); AI-derived events arrive when the worker finishes (typically 1–3s with Haiku). Header stats (`goals achieved/total`, counts) are recomputed and broadcast on every applying event.
- **Accept:** `websocat ws://localhost:8100/ws/<id>` during a replay shows the full event stream; snapshot endpoint returns in <200ms for a 2-hour recording (add indexes if not).

### Phase 8 — Cross-recording context (REQ-CTX-*, REQ-TOP-04)
`context/past_refs.py`:
- **Auto path:** when `apply.py` links a topic to the recording for the first time (insert into `recording_topic`), enqueue a context job (simple asyncio task or a `context_pending` flag). The job: (1) query Postgres for the last 5 other recordings with that topic, pulling their decisions, key moments, and open action items on the topic; (2) call `QdrantIndexer.search(topic.label, limit=5)` for verbatim quotes; (3) one AI call (`prompts.py`: classification prompt) summarizing into ≤3 `past_reference` rows, each classified `repeated|resolved|new_context` (REQ-CTX-02) — classification heuristics in the prompt: open/unresolved action items or conflicting decisions across recordings → `repeated`; an `agreed` decision settled it → `resolved`; else `new_context`. Persist (REQ-CTX-03) and broadcast.
- **Dig deeper (12.6):** `POST /recordings/{id}/topics/{topic_id}/dig_deeper` runs `QdrantIndexer.search` with a wider limit (use the topic label + synonyms as query), AI-summarizes additional findings, appends `past_reference` rows with `source='dig_deeper'`, broadcasts. (Import `QdrantIndexer` from the repo root `qdrant.py` directly — same repo.)
- **Accept:** replay a recording whose topics overlap with existing DB recordings → past_reference rows appear with sensible signals; second replay does not duplicate them (unique constraint); dig-deeper appends and persists.

### Phase 9 — Frontend dashboard
See §9 for the full panel spec. Build order: scaffold → WS/store plumbing → header → goals → agenda → actions/decisions → key moments → speaking/tone → past recordings → setup screen → polish.
- **Accept:** with a `--speed 5` replay running, every panel updates live without page refresh; panel content readable at a glance (large text, color-coded badges); header never scrolls away; a panel reflects a new segment within 3s of ingest (REQ-NFR-01).

### Phase 10 — Hardening, tests, docs
- `dashboard/tests/`: pytest + `pytest-asyncio`; unit tests for topic synonym matching, dedup hashing, agenda state machine, goal latch, ratio math; integration test that replays a fixture recording against a scratch DB with a `MockProvider` (canned AI responses — deterministic, no API key needed in CI).
- Resilience drills (manual or scripted): kill AI mid-replay (segments keep persisting, backlog drains on restart — REQ-NFR-03); kill dashboard service mid-recording (spool file catches segments).
- `DASHBOARD_README.md`: setup, env vars, how to run service + frontend + replayer, architecture summary.
- **Accept:** full test suite green on a scratch DB without network access.

---

## 6. Configuration & runbook

Environment (`.env` or shell), all with defaults:

```
DASHBOARD_PORT=8100
DATABASE_DSN=dbname=recordings
ANTHROPIC_API_KEY=            # empty → Claude skipped, Ollama used
ANTHROPIC_MODEL=claude-haiku-4-5
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b      # any local model that handles JSON well
AI_PROVIDER=auto              # auto | claude | ollama
VOICE_CAPTURE_DASHBOARD_URL=http://localhost:8100   # read by dashboard_client.py in the tray app
```

Run: `python -m dashboard` (service, applies migrations) · `cd dashboard/frontend && npm run dev` (dev UI, proxies `/api` + `/ws` to :8100) · `python scripts/replay_recording.py --recording-id … --speed 10` (simulation). Production UI: `npm run build` → FastAPI serves `dashboard/frontend/dist` at `/`.

## 7. AI pipeline details

### 7.1 System prompt (per-segment analysis — `analyzer/prompts.py`)

Single prompt, both providers. Core instructions (write it in English; transcripts are mostly Dutch — tell the model to keep entity text in the transcript's language):

- You analyze one new transcript segment of a live meeting, given current meeting state (participants, topics, goals, agenda, recent transcript).
- Return ONLY operations justified by this segment. Most segments yield few or no operations — that is the expected output. Never invent entities.
- Reuse existing entities by id whenever possible. For topics, match against labels AND synonyms before creating; if the segment uses a new phrasing of an existing topic, return an `add_synonym` op instead of a new topic.
- Decisions: only when the group clearly converges ("dan doen we…", "afgesproken"). Distinguish `agreed` vs `concept`.
- Action items: require an actionable commitment; owner only if named or strongly implied.
- Goals: mark `achieved` only on clear evidence; `at_risk` when the conversation moves against the goal or time runs short. Optionally update `coaching_tip` with one concrete sentence the user can say next.
- Key moments: only genuinely notable (commitment/decision/tension/insight); `quote` = most salient verbatim phrase, ≤15 words.
- Always include `sentiment` (−1.0..1.0) and `topic_tags` (existing or new topics with confidence) for the segment.
- If the speaker is identifiable from context/address forms, attribute the segment to a participant.

### 7.2 Response JSON schema — REQ-AI-02 (Claude tool `input_schema`; embedded in prompt for Ollama)

```jsonc
{
  "sentiment": -1.0,
  "speaker": {"participant_id": 3} | {"new_participant": {"name": "...", "initials": "..."}} | null,
  "topic_tags": [{"topic_id": 7, "confidence": 0.9} | {"new_topic": {"label": "...", "parent_topic_id": null, "synonyms": []}, "confidence": 0.8}],
  "add_synonyms": [{"topic_id": 7, "synonym": "BtD-planner"}],
  "goal_updates": [{"goal_id": 2, "status": "achieved|at_risk|open", "coaching_tip": "..."}],
  "new_goals": [{"description": "...", "coaching_tip": "...", "topic_ref": "..."}],
  "agenda": {"active_item_id": 4} | {"new_item": {"title": "...", "topic_ref": "..."}} | null,
  "decisions": [{"description": "...", "status": "agreed|concept|rejected", "topic_ref": "..."}],
  "action_items": [{"description": "...", "owner_ref": "name-or-id|null", "due_date": "YYYY-MM-DD|null", "topic_ref": "..."}],
  "key_moments": [{"type": "commitment|decision|tension|insight", "quote": "...", "speaker_ref": "..."}]
}
```
`*_ref` fields accept an existing id or a label/name string; `apply.py` resolves strings through the same upsert rules as the setup API (REQ-FLY-02/03).

### 7.3 Idempotent apply (`analyzer/apply.py`) — REQ-AI-04

One transaction per segment result:

1. Resolve refs (participant by name ci-match; topic by label/synonym match) — reuse before create.
2. `dedup_hash` for decisions/action_items/key_moments = `sha256(lower(normalized_description))[:16]`; insert with `ON CONFLICT (recording_id, dedup_hash) DO UPDATE` (update may upgrade decision status concept→agreed, fill owner/due_date — never blank out existing values).
3. `segment_topic`: `ON CONFLICT DO UPDATE SET confidence = GREATEST(...)`. New `recording_topic` links fire the occurrence trigger + enqueue the past-reference job.
4. Goal latch + agenda state machine per Phase 6 rules.
5. Set `segment.sentiment`, `ai_status='done'`, `ai_processed_at=now()`.
6. Collect changed-entity list during the transaction; broadcast WS events after commit only.

Reprocessing a segment (any path that resets `ai_status`) therefore converges to the same DB state.

## 8. WS event ↔ panel map (frontend contract)

| Event | Payload core | Panels affected |
|---|---|---|
| `segment.created` | segment row | header timer/liveness |
| `segment.analyzed` | segment id, sentiment | tone |
| `topic.tagged` | segment_topic rows | past recordings (topic activation) |
| `goal.updated` | full goal row | goals, header (n/total) |
| `agenda.updated` | all agenda rows for recording | agenda |
| `decision.upserted` | decision row | decisions, header |
| `action_item.upserted` | action item row (+owner name) | action items, header |
| `key_moment.created` | key moment row | key moments |
| `participant.stats` | `[ {participant_id, name, ratio} ]` | speaking time, header |
| `sentiment.updated` | `{window_avg, label}` | tone |
| `past_reference.created` | past_reference + source recording meta | past recordings |
| `recording.status` | `{status, ended_at}` | header |
| `header.stats` | `{participants, goals_achieved, goals_total, action_items, decisions}` | header |

## 9. Frontend spec (`dashboard/frontend/`)

Stack: Vite + React 18 + TypeScript + Tailwind. State: a single `useRecordingStore` (Zustand) hydrated from `GET /recordings/{id}/snapshot`, patched by WS events; reconnect with exponential backoff + snapshot refetch on reconnect (covers missed events — keeps the WS protocol simple). Optimize every panel for ≤5s comprehension: large type, color-semantic badges, minimal chrome.

Routes: `/` recording picker (live recordings first) + a-priori setup form (creates the precreate payload, REQ-PRE-01); `/live/:recordingId` the dashboard.

Dashboard layout (CSS grid, 3 columns desktop):

- **HeaderBar** (sticky top, never scrolls — 12.1): title · live timer `HH:MM:SS` ticking client-side from `started_at` (stops at `ended_at`) · 👥 n · 🎯 2/4 · ✅ actions · ⚖ decisions.
- **GoalsPanel** (12.2): cards, big description text, badge `Achieved`/green, `Open`/amber, `At risk`/red; coaching tip in an accented quote block; sort at_risk → open → achieved; subtle flash animation on status change.
- **AgendaPanel** (12.3): vertical list, colored dot (done=green, active=pulsing blue, pending=gray), title, elapsed `mm:ss` for done items (from `duration_seconds`), active row highlighted.
- **ActionItemsPanel** (12.4): owner avatar/initials chip, description, due date; items where `owner.is_user` get a distinct "You" badge + highlighted border (REQ-ACT-03); ownerless items get an "Unassigned" warning chip.
- **DecisionsPanel** (12.5): time-ordered; `agreed` solid, `concept` dashed-border + muted with "Concept" chip; timestamp `HH:MM`.
- **PastRecordingsPanel** (12.6): grouped per active topic; each card: date + participants of source recording, summary, signal chip (`repeated`=red "Komt terug", `resolved`=green "Opgelost", `new_context`=gray "Context"); "Dig deeper" button → `POST …/dig_deeper`, spinner, appended cards.
- **KeyMomentsPanel** (12.7): quote card with type chip (commitment 🟦, decision 🟩, tension 🟥, insight 🟨), speaker + timestamp; newest on top; manual "flag moment" affordance posting to the manual endpoint.
- **SpeakingTonePanel** (12.8): horizontal stacked/parallel bars per participant (name, %, animated width); below, tone gauge: `constructive / neutral / tense` from `sentiment.updated`.

## 10. Requirements traceability

| Requirement | Where |
|---|---|
| REQ-REC-01/02 | Phase 2 ingest API + `dashboard_client.py` hook in `on_segment_transcribed` |
| REQ-REC-03 | Phase 2 start/end endpoints; `recording.status` |
| REQ-REC-04 | Phase 2: dumb synchronous persist, AI fully decoupled |
| REQ-REC-05 | `recording.recording_id` UNIQUE (migration 001) |
| REQ-PRE-01..03 | Phase 4 setup API + setup form (§9 routes) |
| REQ-FLY-01..05 | Phase 5 pipeline; §7.2 schema; `segment_topic`; `segment.sentiment` |
| REQ-PAR-01..03 | Migrations 002/003; Phase 6 speaking ratio |
| REQ-TOP-01..04 | Migration 004/007 + trigger; Phase 8 |
| REQ-GOA-01..05 | Migration 008; Phase 5/6 goal latch; `goal.topic_id` |
| REQ-AGE-01..05 | Migration 009 (generated duration); Phase 6 state machine |
| REQ-DEC-01..03 | Migration 010; §7.3 |
| REQ-ACT-01..03 | Migration 011; `participant.is_user`; ActionItemsPanel |
| REQ-KEY-01..02 | Migration 012; manual flag endpoint |
| REQ-CTX-01..03 | Migration 013; Phase 8 |
| 12.1–12.8 | §9 panels |
| REQ-AI-01..04 | Phase 5; §7 |
| REQ-NFR-01 | WS push pipeline (Phase 7), verified in Phase 9 accept |
| REQ-NFR-02/04 | §4 migrations, one table per file |
| REQ-NFR-03 | ai_status queue + spool file (Phases 2/5/10) |

## 11. Execution guidance for Claude Code

1. Work phase by phase; commit per phase (`feat(dashboard): phase N — …`). Don't start a phase before the previous one's acceptance criteria pass.
2. **Before migrations 001–003, introspect the live DB** — never guess existing column shapes. If the live DB is unreachable, ask the user rather than assuming.
3. Touch `main.py` minimally: only the `dashboard_client.py` wiring (3 call sites), wrapped in try/except, mirroring the existing Qdrant best-effort pattern. The tray app must never fail because the dashboard service is down or deps are missing.
4. Use the replayer (Phase 3) + `MockProvider` for all development; only smoke-test against the real Anthropic API at the end of Phase 5.
5. Open questions to resolve with the user when first relevant: which `participant` row is the user (set `is_user` — likely "Ralf"); preferred Ollama model for fallback; whether the segment interval stays at 10s or moves to ~5s (`self.segment_duration` in `main.py` — requirement says ~5s; changing it raises transcription load, so confirm first).

