# Live Meeting Intelligence Dashboard

A real-time meeting intelligence system that extends Voice Capture with live AI analysis, a WebSocket-driven dashboard, and cross-recording context.

---

## Architecture

```
Voice Capture (main.py)
  └─ dashboard_client.py  ──POST /ingest/*──►  dashboard/ (FastAPI :8100)
                                               ├─ ingest API  ──► PostgreSQL
                                               ├─ AI worker (async)
                                               │    Claude Haiku ⇄ Ollama fallback
                                               ├─ REST read API
                                               └─ WebSocket hub ◄── React dashboard
```

## Prerequisites

- Python 3.10+ with virtual environment
- PostgreSQL (`dbname=recordings`)
- Node.js 18+ (for frontend dev/build)
- Ollama running locally (`http://localhost:11434`) with `qwen3.6:latest`
- (Optional) `ANTHROPIC_API_KEY` for Claude primary provider

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
pip install psycopg[binary,pool] anthropic httpx pydantic-settings
```

### 2. Configure environment

Create a `.env` file (or set environment variables):

```env
DASHBOARD_PORT=8100
DATABASE_DSN=dbname=recordings
ANTHROPIC_API_KEY=            # leave empty to use Ollama only
ANTHROPIC_MODEL=claude-haiku-4-5
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.6:latest
AI_PROVIDER=auto              # auto | claude | ollama
VOICE_CAPTURE_DASHBOARD_URL=http://localhost:8100
```

### 3. Run the dashboard service

```bash
python -m dashboard
```

On first start, this automatically applies all database migrations (idempotent).  
To run migrations manually: `python -m dashboard.migrations.runner`

### 4. Build / run the frontend

**Development** (Vite dev server with proxy to :8100):
```bash
cd dashboard/frontend
npm install
npm run dev          # → http://localhost:5173
```

**Production** (static files served by FastAPI at `/`):
```bash
cd dashboard/frontend
npm run build        # outputs to dashboard/frontend/dist/
# FastAPI serves dist/ automatically
```

---

## Usage

### Starting a meeting

1. Open `http://localhost:8100` (or :5173 in dev mode)
2. Optionally click **Pre-configure meeting** to set participants, agenda, goals, topics before recording starts
3. Press record in the Voice Capture tray app
4. Navigate to the live recording in the dashboard — all panels update in real time

### Replayer (dev/testing)

Replay any existing recording through the ingest API as if it's happening live:

```bash
python scripts/replay_recording.py --recording-id 20251219_140030 --speed 10
```

Options:
- `--speed N` — replay N× faster than real time (default: 10)
- `--port 8100` — dashboard port
- `--suffix _replay01` — appended to the synthetic recording ID to avoid conflicts

---

## Dashboard panels

| Panel | Description |
|---|---|
| **Header** | Sticky: title, live timer, participant count, goals achieved/total, action items, decisions |
| **Goals** | Status cards (At risk / Open / Achieved) with coaching tips, colour-coded |
| **Agenda** | Ordered list with active item pulsing, elapsed time for completed items |
| **Action Items** | Owner initials chip, "You" badge for your items, overdue highlight |
| **Decisions** | Time-ordered, agreed (solid) vs concept (dashed) |
| **Key Moments** | Quotes with type chips (commitment/decision/tension/insight), manual flag button |
| **Speaking & Tone** | Animated speaking bars per participant + 3-min rolling tone gauge |
| **Past Recordings** | Cross-recording context grouped by topic, Dig Deeper button |

---

## AI pipeline

- **Per-segment analysis**: runs asynchronously after each segment is ingested
- **Primary**: Claude Haiku (`claude-haiku-4-5`) via Anthropic API
- **Fallback**: Ollama (`qwen3.6:latest`) when Anthropic is unreachable or unconfigured
- **Retry**: up to 3 attempts with exponential backoff; `ai_status` tracks state per segment
- **Idempotent**: reprocessing a segment converges to the same DB state (dedup hashes)
- **Cross-recording context**: when a new topic is first seen, past recordings are queried for related decisions, key moments, and open actions

---

## Database migrations

Migrations live in `dashboard/migrations/sql/` as numbered `.sql` files.  
Applied in order, tracked in `schema_migrations(version, applied_at)`.

| File | Table |
|---|---|
| 001 | `recording` (adopt existing) |
| 002 | `participant` (adopt + add `initials`, `is_user`) |
| 003 | `recording_participant` (adopt + add speaking stats) |
| 004 | `topic` |
| 005 | `segment` |
| 006 | `segment_topic` |
| 007 | `recording_topic` (+ occurrence_count trigger) |
| 008 | `goal` |
| 009 | `agenda_item` |
| 010 | `decision` |
| 011 | `action_item` |
| 012 | `key_moment` |
| 013 | `past_reference` |
| 014 | `goal_topic_history` (view) |
| 015 | `apriori_setup` |

---

## Running tests

```bash
pip install pytest
python -m pytest dashboard/tests/ -v
```

Tests cover: dedup hashing, sentiment clamping, tone window, topic synonym matching, agenda state machine, goal latch, speaking ratio math.

---

## Key environment variables

| Variable | Default | Description |
|---|---|---|
| `DASHBOARD_PORT` | `8100` | Port for the FastAPI service |
| `DATABASE_DSN` | `dbname=recordings` | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | _(empty)_ | Leave empty to use Ollama only |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | Claude model for segment analysis |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `qwen3.6:latest` | Ollama model (fallback) |
| `AI_PROVIDER` | `auto` | `auto` \| `claude` \| `ollama` |
| `VOICE_CAPTURE_DASHBOARD_URL` | `http://localhost:8100` | Read by `dashboard_client.py` in tray app |
