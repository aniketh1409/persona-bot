# PersonaBot Agent Guide

> Last updated: 2026-03-08
> Last change: Session sidebar with switching, multi-bubble assistant messages, dark mode, UI redesign.

## Project State

PersonaBot is a working vertical slice of a stateful, emotionally adaptive chatbot:

- Next.js chat UI with WebSocket streaming, reconnect logic, and persona switching
- FastAPI backend with session/state handling and streaming LLM responses
- PostgreSQL persistence for users, sessions, events, personas, and turn metrics
- Redis cache for hot emotional state (6h TTL, read-through strategy)
- Qdrant vector memory with weighted reranking (semantic + importance + recency), deduplication, and SHA-1 hash-based duplicate prevention
- Three personas (`balanced`, `coach`, `warm`) stored in DB with system/style prompts
- Ollama-first local inference and embeddings (OpenAI as paid fallback)
- Alembic migrations (2 revisions)
- Backend test coverage for state engine, memory service, RAG context, LLM streaming, and WebSocket contract

## Documentation

- `ARCHITECTURE.md`: Comprehensive file-by-file walkthrough of the entire codebase, tech stack explanations, data flow diagrams, and table schemas. Read this first if you are new to the project.
- `README.md`: Quick-start setup guide.
- `AGENT.md` (this file): Concise reference for AI agents. Change rules, runbook, known gaps.

## Agent Coordination

- Codex and Claude are expected to work alongside each other on this repository.
- When `AGENT.md` is updated, the editor should record who made the change in the "Last change" line and in the changelog if the update is material.
- This update to `AGENT.md` was made by Codex.

## Stack

- Frontend: Next.js 14 (App Router), React 18, TypeScript 5.5
- Backend: FastAPI, async SQLAlchemy 2.x, Pydantic v2, httpx
- Data: PostgreSQL 16, Redis 7, Qdrant (latest)
- Local model runtime: Ollama
- Default local models:
  - chat: `llama3.2:3b`
  - embeddings: `nomic-embed-text` (768-dim)
- Build: hatchling (Python), npm workspaces (Node)
- Testing: pytest + pytest-asyncio
- Linting: ruff (Python), ESLint + next lint (TypeScript)

## Current Architecture

Message flow:

1. Frontend sends `message`, `user_id`, `session_id`, and `persona_id` over `/ws/chat`.
2. Backend validates payload against `ChatMessageIn` schema.
3. Backend resolves user/session and current persona via `session_service.py` and `persona_service.py`.
4. Emotional state is loaded from Redis (fallback: Postgres) and updated via `state_engine.py`.
5. Memory tags are extracted and user message is stored in Qdrant if importance threshold is met.
6. Relevant long-term memories are recalled from Qdrant with weighted reranking through `memory_service.py`.
7. RAG prompt context is assembled in `rag_context.py` (state + recent history + memories).
8. Reply is streamed from `llm_service.py` via Ollama (or OpenAI) with persona-specific system prompt and temperature.
9. Tokens are streamed to frontend as `{"type": "token", "delta": "..."}` events.
10. Assistant event and latency metrics (total ms, first-token ms, chunk count) are persisted in Postgres.

## Important Files

| File | Purpose |
|---|---|
| `apps/web/app/page.tsx` | Chat UI, WebSocket lifecycle, session sidebar, persona selector, multi-bubble rendering, dark mode toggle |
| `apps/web/app/layout.tsx` | Root layout, Google Fonts (Inter + JetBrains Mono) |
| `apps/web/app/globals.css` | All styles, light/dark theme via `data-theme` attribute, sidebar, responsive |
| `services/api/app/main.py` | FastAPI entrypoint: `/health`, `/personas`, `/sessions/{user_id}`, `/history/{session_id}`, `/ws/chat` |
| `services/api/app/config.py` | Pydantic Settings, all env vars with defaults |
| `services/api/app/db.py` | SQLAlchemy engine, Redis client, Qdrant client, `db_session()` context manager |
| `services/api/app/models.py` | 6 SQLAlchemy ORM models: User, ChatSession, RelationshipState, PersonaProfile, ConversationEvent, ChatTurnMetric |
| `services/api/app/schemas.py` | Pydantic schemas: EmotionalState, ChatMessageIn, ChatMessageOut, HistoryEventOut, PersonaOut |
| `services/api/app/session_service.py` | User/session resolution, Redis-first state loading, event/metric persistence |
| `services/api/app/state_engine.py` | Pure-function emotional state machine (keyword sentiment -> mood/trust/affection/energy) |
| `services/api/app/memory_service.py` | Embedding clients (Ollama + OpenAI), memory store/recall, reranking, deduplication |
| `services/api/app/rag_context.py` | Assembles prompt context from state + recent events + recalled memories |
| `services/api/app/llm_service.py` | LLM abstraction (Ollama + OpenAI streaming), prompt building, fallback replies |
| `services/api/app/persona_service.py` | 3 default personas, DB seeding, resolution logic |
| `services/api/alembic/versions/` | 2 migrations: initial schema (0001), persona profiles (0002) |
| `services/api/tests/` | 5 test files covering state, memory, RAG, LLM, and WebSocket contract |

## Runbook

Infra:

```powershell
docker compose up -d
```

Ollama:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Backend:

```powershell
cd services/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```powershell
npm install
npm run dev:web
```

## Expected Env

The backend expects Ollama by default. Key values:

```env
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
QDRANT_VECTOR_SIZE=768
```

If a previous setup used `QDRANT_VECTOR_SIZE=1536`, the `persona_memories` collection should be recreated once.

See `.env.example` for the full list of all environment variables.

## Testing

Backend:

```powershell
cd services/api
.venv\Scripts\python -m pytest tests/test_state_engine.py tests/test_memory_service.py tests/test_rag_context.py tests/test_llm_service.py tests/test_ws_stream.py -q
```

Frontend:

- `npm run build:web`
- `npm run lint:web`

## Change Rules

- If you change schema, add an Alembic migration.
- If you change WebSocket payloads, update both frontend event handling and `test_ws_stream.py`.
- If you change memory vector size or embedding provider output dimension, recreate the Qdrant collection or add a migration path.
- Keep Ollama as the default local path unless there is a clear reason to change it.
- Prefer extending personas through `persona_service.py` and the migration layer, not hardcoded frontend-only changes.
- After making changes, update this file (AGENT.md) with a new "Last updated" date and a brief description of what changed.
- Keep ARCHITECTURE.md in sync if you add new files, change the data flow, or modify the tech stack.

## Known Gaps

- There is no CI/CD or deployment pipeline yet.
- There is no structured logging / observability layer yet.
- Frontend has no automated tests.
- No analytics dashboard exists yet for state/memory trends.
- No user authentication (user IDs are self-asserted strings from localStorage).
- Sentiment analysis is keyword-based; a model-based classifier would be more accurate.
- The entire frontend UI is a single component (`page.tsx`); should be decomposed as features grow.
- `ensure_defaults()` now overwrites persona DB rows on every startup; if a user customizes a persona via DB, it will be reset. Consider a migration-based approach for persona updates instead.

## Changelog

| Date | Change |
|---|---|
| 2026-03-08 | Added session sidebar with session switching (retains old chats). Multi-bubble assistant messages (splits on paragraph breaks). Dark mode toggle with `data-theme` attribute. `GET /sessions/{user_id}` endpoint + `SessionOut` schema. `SessionService.list_sessions()` and `session_preview()` methods. Full UI redesign: cleaner layout, removed system socket messages from timeline, compact controls row. |
| 2026-03-08 | Codex updated `AGENT.md` to document Codex/Claude collaboration and require agent attribution when this file changes. |
| 2026-03-08 | Added multi-line text style instructions to all persona prompts. Changed fonts to Inter (body) + JetBrains Mono (code/status). Added "+ new chat" button that clears session and starts fresh conversation. |
| 2026-03-08 | Rewrote all 3 persona prompts (balanced/coach/warm) to sound natural and human-like. Updated `_build_prompts()` to stop saying "You are PersonaBot". Added `GET /history/{session_id}` endpoint + `HistoryEventOut` schema. Frontend loads chat history on page refresh. Added Enter-to-send (Shift+Enter for newline). `ensure_defaults()` now updates existing persona rows on startup. Added history endpoint test. |
| 2026-03-08 | Added `ARCHITECTURE.md` with full codebase documentation. Updated `AGENT.md` with file table, changelog, and expanded known gaps. |
| 2026-03-04 | Migration 0002: Added persona_profiles table, persona switching, 3 default personas. |
| 2026-03-03 | Initial working vertical slice: WebSocket chat, state engine, memory service, Ollama integration. |
