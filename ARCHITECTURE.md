# PersonaBot Architecture Guide

> A detailed walkthrough of every file, technology, and design decision in the project.
> Written so that someone encountering this codebase for the first time can understand what
> each piece does, why it exists, and how it connects to everything else.

---

## Table of Contents

1. [What Is PersonaBot?](#what-is-personabot)
2. [High-Level Architecture](#high-level-architecture)
3. [Tech Stack Summary](#tech-stack-summary)
4. [Monorepo Layout](#monorepo-layout)
5. [Data Flow: What Happens When You Send a Message](#data-flow-what-happens-when-you-send-a-message)
6. [Infrastructure (Docker)](#infrastructure-docker)
7. [Backend (FastAPI)](#backend-fastapi)
   - [Entry Point & Startup](#entry-point--startup)
   - [Configuration](#configuration)
   - [Database Connections](#database-connections)
   - [ORM Models (Database Tables)](#orm-models-database-tables)
   - [Pydantic Schemas (Data Validation)](#pydantic-schemas-data-validation)
   - [Session Service](#session-service)
   - [State Engine](#state-engine)
   - [Memory Service](#memory-service)
   - [RAG Context Builder](#rag-context-builder)
   - [LLM Service](#llm-service)
   - [Persona Service](#persona-service)
   - [Database Migrations (Alembic)](#database-migrations-alembic)
8. [Frontend (Next.js)](#frontend-nextjs)
9. [Tests](#tests)
10. [Root-Level Files](#root-level-files)
11. [Environment Variables](#environment-variables)
12. [Known Gaps & Next Steps](#known-gaps--next-steps)

---

## What Is PersonaBot?

PersonaBot is a **stateful, emotionally adaptive chatbot** with long-term memory. Unlike a
typical chatbot that treats every conversation as independent, PersonaBot:

- **Tracks emotional state** (mood, trust, affection, energy) that evolves across turns.
- **Remembers past conversations** using a vector database, so it can reference things you
  said days or weeks ago.
- **Supports persona switching** between different conversational styles (Balanced, Coach,
  Warm) that control tone and temperature.
- **Streams responses** in real-time over WebSockets, token by token.

Think of it as a chatbot that actually remembers you and adapts its personality over time.

---

## High-Level Architecture

```
+---------------------+          WebSocket           +--------------------+
|                     |  <========================>  |                    |
|   Next.js Frontend  |       /ws/chat (JSON)        |   FastAPI Backend  |
|   (React, TS)       |  ========================>   |   (Python, async)  |
|   localhost:3000     |       HTTP /personas         |   localhost:8000   |
+---------------------+                              +--------------------+
                                                            |   |   |
                                                            v   v   v
                                                     +------+---+------+
                                                     | PG  | Redis| Qdrant|
                                                     | :5432| :6379| :6333|
                                                     +------+-----+------+
                                                           |
                                                           v
                                                     +----------+
                                                     |  Ollama  |
                                                     | :11434   |
                                                     +----------+
```

- **Frontend** sends chat messages over a WebSocket and displays streamed token responses.
- **Backend** orchestrates everything: resolves users/sessions, updates emotional state,
  queries long-term memory, assembles a RAG prompt, and streams LLM output.
- **PostgreSQL** stores structured data (users, sessions, conversation events, emotional
  state, personas, latency metrics).
- **Redis** caches hot emotional state for fast reads (avoids hitting Postgres every turn).
- **Qdrant** stores vectorized conversation memories for semantic retrieval.
- **Ollama** runs LLM inference and embeddings locally (free, no API key needed).

---

## Tech Stack Summary

| Layer | Technology | Why |
|---|---|---|
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript | Fast UI iteration, SSR-ready, strong React ecosystem |
| **Backend framework** | FastAPI (Python 3.11+) | Native async, WebSocket support, Pydantic integration, great for AI orchestration |
| **Relational DB** | PostgreSQL 16 | Mature, reliable, handles relational data (users, sessions, events) |
| **Cache** | Redis 7 | Sub-millisecond reads for emotional state, avoids DB round-trip on every turn |
| **Vector DB** | Qdrant | Purpose-built for semantic similarity search; stores conversation memories as embeddings |
| **LLM (default)** | Ollama (llama3.2:3b) | Runs locally, free, no API key; good enough for dev/testing |
| **LLM (optional)** | OpenAI (gpt-4.1-mini) | Higher quality, paid; used when `LLM_PROVIDER=openai` |
| **Embeddings (default)** | Ollama (nomic-embed-text) | 768-dim embeddings, local, free |
| **Embeddings (optional)** | OpenAI (text-embedding-3-small) | 1536-dim, paid; higher quality |
| **ORM** | SQLAlchemy 2.x (async) | Mature Python ORM with full async support via asyncpg |
| **Migrations** | Alembic | Schema versioning; tracks DB changes as code |
| **Validation** | Pydantic v2 | Type-safe request/response schemas, settings management |
| **HTTP client** | httpx | Async HTTP client for Ollama API calls |
| **Build/package** | hatchling (backend), npm workspaces (frontend) | Standard Python/Node packaging |
| **Testing** | pytest + pytest-asyncio | Backend test runner with async support |
| **Linting** | Ruff (Python), ESLint + next lint (TypeScript) | Fast linting for both languages |

---

## Monorepo Layout

```
persona-bot/
|
|-- apps/
|   +-- web/                          # Next.js frontend
|       |-- app/
|       |   |-- page.tsx              # Main chat UI component
|       |   |-- layout.tsx            # Root HTML layout, fonts, metadata
|       |   +-- globals.css           # All styles (CSS custom properties)
|       |-- next.config.mjs           # Next.js config (strict mode)
|       |-- next-env.d.ts             # Auto-generated Next.js types
|       |-- tsconfig.json             # TypeScript compiler settings
|       +-- package.json              # Frontend dependencies
|
|-- services/
|   +-- api/                          # FastAPI backend
|       |-- app/
|       |   |-- __init__.py           # Package marker
|       |   |-- main.py              # FastAPI app, endpoints, WebSocket handler
|       |   |-- config.py            # Pydantic Settings (all env vars)
|       |   |-- db.py                # Database engine, Redis client, Qdrant client
|       |   |-- models.py            # SQLAlchemy ORM models (DB tables)
|       |   |-- schemas.py           # Pydantic request/response schemas
|       |   |-- session_service.py   # User, session, state, event persistence
|       |   |-- state_engine.py      # Emotional state update logic
|       |   |-- memory_service.py    # Vector memory: embed, store, recall, rerank
|       |   |-- rag_context.py       # Assembles prompt context from state + history + memory
|       |   |-- llm_service.py       # LLM abstraction (Ollama + OpenAI, streaming)
|       |   +-- persona_service.py   # Persona definitions, resolution, seeding
|       |-- tests/
|       |   |-- test_state_engine.py  # Emotional state unit tests
|       |   |-- test_memory_service.py # Memory store/recall/dedupe tests
|       |   |-- test_rag_context.py   # RAG prompt assembly tests
|       |   |-- test_llm_service.py   # LLM streaming/fallback tests
|       |   +-- test_ws_stream.py     # WebSocket integration tests
|       |-- alembic/
|       |   |-- env.py               # Alembic migration runner (async)
|       |   +-- versions/
|       |       |-- 20260303_0001_initial_schema.py   # First migration: users, sessions, events, metrics
|       |       +-- 20260304_0002_personas.py         # Second migration: persona_profiles table
|       |-- alembic.ini              # Alembic config (DB URL, logging)
|       +-- pyproject.toml           # Python package config, dependencies
|
|-- docker-compose.yml               # PostgreSQL, Redis, Qdrant containers
|-- package.json                     # Root npm workspace config
|-- package-lock.json                # Locked dependency tree
|-- .env.example                     # Template for all environment variables
|-- .env                             # Actual env vars (gitignored)
|-- .gitignore                       # Ignored files/directories
|-- README.md                        # Quick-start guide
+-- AGENT.md                         # Agent context file (for AI agents working on this repo)
```

---

## Data Flow: What Happens When You Send a Message

This is the full journey of a single user message, end to end:

### 1. Frontend sends message over WebSocket

The user types in the chat box and hits send. `page.tsx` sends a JSON payload over the
WebSocket connection to `/ws/chat`:

```json
{
  "message": "I'm feeling stressed about my exam",
  "user_id": "abc-123",
  "session_id": "sess-456",
  "persona_id": "balanced"
}
```

### 2. Backend validates the payload

`main.py` receives the JSON and validates it against `ChatMessageIn` (Pydantic schema).
If validation fails (e.g., empty message), an error event is sent back.

### 3. User and session are resolved

`session_service.py` looks up or creates the user and session in PostgreSQL. If
`user_id` is null, a new UUID is generated. Sessions are linked to personas.

### 4. Emotional state is loaded

`session_service.py` first checks **Redis** for cached state (key: `state:{session_id}`).
If not cached, it falls back to the `relationship_states` table in Postgres, then caches
the result in Redis with a 6-hour TTL.

### 5. Emotional state is updated

`state_engine.py` runs simple sentiment analysis on the user message. It counts hits
against positive tokens ("thanks", "awesome") and negative tokens ("hate", "frustrated")
and adjusts trust, affection, energy, and mood accordingly.

### 6. Memory tags are extracted

`memory_service.py` scans the message for keywords matching four categories:
- **stress**: "stressed", "anxious", "exam", "deadline"...
- **preference**: "like", "love", "favorite"...
- **trigger**: "insecure", "afraid", "panic"...
- **goal**: "goal", "plan", "improve"...

### 7. The message is stored as a long-term memory (if important enough)

`memory_service.py` computes an importance score (0.0-1.0) based on tags, message length,
and personal pronouns. If the score is >= 0.50 or the message has tags or is long enough,
it gets embedded into a vector and stored in Qdrant (with deduplication via SHA-1 hash).

### 8. Relevant memories are recalled

`memory_service.py` embeds the current message, queries Qdrant for similar vectors filtered
by `user_id`, then **reranks** results using a weighted combination of:
- **Semantic similarity** (62% weight) - how close the vector match is
- **Importance** (25% weight) - how meaningful the memory was
- **Recency** (13% weight) - exponential decay with a 72-hour half-life

Duplicates are removed by normalizing text and comparing SHA-1 hashes.

### 9. RAG context is assembled

`rag_context.py` combines three sources into a single prompt block:
- **State summary**: `mood=playful, trust=0.70, affection=0.80, energy=0.60`
- **Recent history**: Last 8 conversation events from PostgreSQL
- **Long-term memory**: Top-K recalled memories from Qdrant

### 10. The LLM generates a streaming response

`llm_service.py` builds a system prompt (persona instructions) and user prompt (RAG context
+ user message), then streams the response:

- **Ollama path**: POST to `/api/chat` with `stream: true`, yields token deltas from NDJSON
- **OpenAI path**: `client.chat.completions.create(stream=True)`, yields from SSE chunks
- **Fallback**: If both fail, returns a mood-aware canned response

### 11. Tokens are streamed to the frontend

Each chunk is sent as `{"type": "token", "delta": "..."}` over the WebSocket. The frontend
appends each delta to the assistant bubble in real-time.

### 12. Final message and metrics are persisted

After streaming completes:
- The full assistant message is saved as a `ConversationEvent` in PostgreSQL
- Latency metrics (total ms, first-token ms, chunk count) are saved as a `ChatTurnMetric`
- A `{"type": "done", ...}` event with full message + state + metrics is sent to frontend

---

## Infrastructure (Docker)

### `docker-compose.yml`

Runs three containers that the backend depends on:

| Service | Image | Port | Purpose |
|---|---|---|---|
| **postgres** | `postgres:16` | 5432 | Relational data (users, sessions, events, personas, metrics) |
| **redis** | `redis:7` | 6379 | Ephemeral cache for emotional state (fast reads, 6h TTL) |
| **qdrant** | `qdrant/qdrant:latest` | 6333 (HTTP), 6334 (gRPC) | Vector storage for long-term conversation memories |

All three use named volumes for persistence across container restarts.

**Start with**: `docker compose up -d`

Ollama runs outside Docker (system-level install). Pull models with:
```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

---

## Backend (FastAPI)

All backend code lives in `services/api/app/`.

### Entry Point & Startup

**File: `services/api/app/main.py`** (301 lines)

This is the heart of the backend. It:

1. **Initializes services at module level** (lines 20-37): Creates the embedding client
   (Ollama or OpenAI based on config), MemoryService, and LlmService. These live for the
   lifetime of the process.

2. **Defines the lifespan handler** (lines 40-68): Runs on startup/shutdown:
   - Startup: auto-creates DB schema (if configured), seeds default personas, ensures the
     Qdrant collection exists.
   - Shutdown: closes Redis, Qdrant, and SQLAlchemy connections.

3. **Registers the FastAPI app** (lines 71-79): Sets title, version, and CORS middleware
   allowing the frontend origins.

4. **`GET /health`** (lines 122-124): Simple health check, returns `{"status": "ok"}`.

5. **`GET /personas`** (lines 127-142): Returns all persona profiles from the database as
   JSON. Used by the frontend to populate the persona dropdown.

6. **`WS /ws/chat`** (lines 145-301): The main WebSocket handler. This is where the entire
   message flow (steps 2-12 above) happens. It:
   - Accepts the connection and sends a system greeting
   - Loops forever, receiving JSON messages from the client
   - For each message: resolves user/session, updates state, stores/recalls memory, builds
     RAG context, streams LLM response, persists events and metrics
   - Handles disconnects gracefully

7. **Helper functions** (lines 87-119): `_remember_if_needed()` and `_recall_memories()`
   wrap memory operations with error handling so failures don't crash the chat.

### Configuration

**File: `services/api/app/config.py`** (44 lines)

Uses Pydantic Settings to load all configuration from environment variables or `.env` files.
The `Settings` class defines every configurable value with sensible defaults:

| Setting | Default | Purpose |
|---|---|---|
| `llm_provider` | `"ollama"` | Which LLM to use for chat generation |
| `embedding_provider` | `"ollama"` | Which service to use for text embeddings |
| `ollama_base_url` | `http://localhost:11434` | Ollama server address |
| `ollama_chat_model` | `llama3.2:3b` | Local LLM model name |
| `ollama_embedding_model` | `nomic-embed-text` | Local embedding model name |
| `openai_api_key` | `""` | OpenAI API key (optional, for paid fallback) |
| `postgres_dsn` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `redis_url` | `redis://localhost:6379/0` | Redis connection string |
| `qdrant_url` | `http://localhost:6333` | Qdrant server address |
| `qdrant_vector_size` | `768` | Embedding dimension (768 for nomic, 1536 for OpenAI) |
| `memory_top_k` | `5` | How many memories to recall per query |
| `memory_semantic_weight` | `0.62` | Weight of vector similarity in reranking |
| `memory_importance_weight` | `0.25` | Weight of importance score in reranking |
| `memory_recency_weight` | `0.13` | Weight of recency in reranking |
| `default_persona_id` | `"balanced"` | Fallback persona if none specified |

`get_settings()` is cached with `@lru_cache` so the settings object is created once.

### Database Connections

**File: `services/api/app/db.py`** (34 lines)

Creates all database clients at module level (created once when the backend starts):

- **`engine`**: SQLAlchemy async engine connected to PostgreSQL via `asyncpg`. Uses
  `pool_pre_ping=True` to detect stale connections.
- **`SessionLocal`**: Async session factory for creating database sessions.
- **`redis_client`**: Async Redis client with UTF-8 encoding and response decoding.
- **`qdrant_client`**: Async Qdrant client pointed at the vector DB.

**`init_db()`**: If `AUTO_CREATE_SCHEMA=true`, creates all tables from ORM models. In
production, you use Alembic migrations instead.

**`db_session()`**: Context manager that handles commit/rollback automatically. Every
database operation in the app uses this.

### ORM Models (Database Tables)

**File: `services/api/app/models.py`** (86 lines)

Defines six SQLAlchemy models mapping to PostgreSQL tables:

**`User`** - Represents a chat user.
| Column | Type | Notes |
|---|---|---|
| `id` | String(36) | UUID, primary key |
| `created_at` | DateTime | Auto-set by DB |

**`ChatSession`** - A conversation session tied to a user and persona.
| Column | Type | Notes |
|---|---|---|
| `id` | String(36) | UUID, primary key |
| `user_id` | String(36) | FK to users |
| `persona_id` | String(64) | FK to persona_profiles |
| `message_count` | Integer | Incremented each turn |
| `created_at` | DateTime | Auto-set |
| `last_active_at` | DateTime | Auto-updated on activity |

Indexed on `(user_id, last_active_at)` for efficient "recent sessions" queries.

**`RelationshipState`** - The emotional state of a session.
| Column | Type | Notes |
|---|---|---|
| `session_id` | String(36) | PK, FK to chat_sessions |
| `baseline_mood` | String(32) | Starting mood (default: "neutral") |
| `current_mood` | String(32) | Current mood (neutral/playful/guarded/calm) |
| `affection` | Float | 0.0 to 1.0 |
| `trust` | Float | 0.0 to 1.0 |
| `energy` | Float | 0.0 to 1.0 |
| `updated_at` | DateTime | Auto-updated |

**`PersonaProfile`** - A bot personality configuration.
| Column | Type | Notes |
|---|---|---|
| `id` | String(64) | e.g. "balanced", "coach", "warm" |
| `name` | String(80) | Display name |
| `description` | Text | Short description for UI |
| `system_prompt` | Text | LLM system prompt |
| `style_prompt` | Text | Additional style instructions |
| `temperature` | Float | LLM temperature (creativity level) |
| `is_default` | Boolean | Whether this is the default persona |

**`ConversationEvent`** - A single message (user or assistant) in a conversation.
| Column | Type | Notes |
|---|---|---|
| `id` | String(36) | UUID, primary key |
| `session_id` | String(36) | FK to chat_sessions |
| `user_id` | String(36) | FK to users |
| `role` | String(16) | "user" or "assistant" |
| `message` | Text | The message content |
| `sentiment_score` | Float | Computed sentiment for this message |
| `created_at` | DateTime | When the message was created |

Indexed on `(session_id, created_at)` for efficient chronological retrieval.

**`ChatTurnMetric`** - Performance metrics for each assistant response.
| Column | Type | Notes |
|---|---|---|
| `id` | String(36) | UUID |
| `session_id` | String(36) | FK |
| `user_id` | String(36) | FK |
| `assistant_event_id` | String(36) | FK to the assistant's ConversationEvent |
| `latency_ms` | Float | Total response time in ms |
| `first_token_ms` | Float | Time to first token in ms |
| `chunk_count` | Integer | Number of streamed chunks |

### Pydantic Schemas (Data Validation)

**File: `services/api/app/schemas.py`** (40 lines)

Three schemas used for data validation and serialization:

- **`EmotionalState`**: The emotional state model with `baseline_mood`, `current_mood`,
  `affection` (0-1), `trust` (0-1), `energy` (0-1). Used throughout the backend and
  sent to the frontend in every response.

- **`ChatMessageIn`**: Validates incoming WebSocket messages. Fields:
  `message` (required, 1-5000 chars), `user_id`, `session_id`, `persona_id` (all optional).

- **`ChatMessageOut`**: Structures the final response sent to the frontend after streaming
  completes. Includes message, IDs, state, and latency metrics.

- **`PersonaOut`**: Lightweight persona representation for the `GET /personas` response.

### Session Service

**File: `services/api/app/session_service.py`** (157 lines)

The persistence layer for users, sessions, emotional state, events, and metrics. Key methods:

- **`resolve_user(user_id)`**: Finds an existing user or creates a new one with a UUID.
- **`resolve_or_create_session(user_id, session_id, persona_id)`**: Finds or creates a
  session. If the session exists but has a different persona, it updates the persona.
- **`load_state(session_id)`**: Loads emotional state with a **Redis-first** strategy:
  1. Check Redis cache (`state:{session_id}`)
  2. If miss, load from PostgreSQL `relationship_states` table
  3. Cache result in Redis with 6-hour TTL
  4. If nothing exists, create default state
- **`save_state(session_id, state)`**: Writes state to both PostgreSQL and Redis.
- **`append_event(...)`**: Creates a ConversationEvent record.
- **`save_turn_metric(...)`**: Creates a ChatTurnMetric record.
- **`recent_events(session_id, limit=12)`**: Returns the last N events in chronological
  order (queries in descending order, then reverses).

### State Engine

**File: `services/api/app/state_engine.py`** (62 lines)

Pure-function emotional state machine. No database calls, no side effects.

**How sentiment analysis works:**

1. Scan the message for positive tokens ("thanks", "great", "awesome", "love", "appreciate",
   etc.) and negative tokens ("hate", "bad", "angry", "frustrated", "upset", etc.).
2. Compute a sentiment score: `(positive_hits - negative_hits) / total_hits`, range [-1, 1].
3. If no tokens match, score is 0.0 (neutral).

**How state updates work:**

- `trust` moves by `0.08 * sentiment_score` per turn
- `affection` moves by `0.10 * sentiment_score` per turn
- `energy` decreases by 0.02 per turn (natural fatigue), offset by `0.03 * sentiment`
- Extra energy drain for very long messages (>240 chars) or long conversations (>20 turns)
- All values are clamped to [0.0, 1.0]

**Mood selection:**
- sentiment > 0.25 -> "playful"
- sentiment < -0.25 -> "guarded"
- energy < 0.25 -> "calm"
- otherwise -> stays at baseline mood

### Memory Service

**File: `services/api/app/memory_service.py`** (375 lines)

The most complex module. Handles the full lifecycle of long-term conversation memory.

**Embedding Clients** (lines 22-73):

Two implementations of the `EmbeddingClient` protocol:

- **`OpenAIEmbeddingClient`**: Uses the OpenAI embeddings API. Produces 1536-dim vectors.
  Lazily imports the `openai` library.
- **`OllamaEmbeddingClient`**: Calls Ollama's `/api/embeddings` endpoint (or `/api/embed`
  for compatibility with different Ollama versions). Produces 768-dim vectors.

**MemoryChunk** (lines 76-84): A frozen dataclass representing a recalled memory with its
text, combined score, tags, creation timestamp, and individual score components.

**MemoryService** (lines 87-365): The core memory class. Constructor takes the Qdrant
client, embedding client, and all ranking weights.

Key methods:

- **`ensure_collection()`**: Creates the Qdrant collection if it doesn't exist, with the
  configured vector size and cosine distance metric.

- **`extract_tags(message)`**: Scans for keywords in four categories (stress, preference,
  trigger, goal). Returns matching tag names.

- **`should_index_memory(role, message, tags)`**: Gate that decides if a message is worth
  storing. Only indexes user messages. Accepts if: importance >= 0.50, OR has tags, OR
  message length >= 80 characters.

- **`compute_importance(message, tags)`**: Scores a message 0.0-1.0. Starting at 0.20,
  adds points for: trigger/stress tags (+0.25), goal tags (+0.20), preference tags (+0.15),
  long messages (+0.04 to +0.12), personal pronouns (+0.08), causal language (+0.04).

- **`store_memory(...)`**: Normalizes the message, hashes it (SHA-1), checks for duplicates
  in Qdrant, embeds the text, then upserts a point into Qdrant with full metadata payload.

- **`recall(user_id, query, tags, limit)`**: The retrieval pipeline:
  1. Embed the query text
  2. Query Qdrant for `limit * candidate_multiplier` candidates (over-fetch for reranking)
  3. Filter by user_id (and optionally by tags)
  4. Rerank each candidate with weighted combination of semantic, importance, and recency
  5. Deduplicate by normalized text hash
  6. Sort by combined score descending
  7. Return top `limit` results

- **`compute_recency_score(created_at, now)`**: Exponential decay:
  `score = 0.5 ^ (age_hours / half_life_hours)`. With a 72-hour half-life, a 3-day-old
  memory has score 0.5, a 6-day-old memory has score 0.25.

- **`combine_scores(...)`**: Weighted sum:
  `0.62 * semantic + 0.25 * importance + 0.13 * recency`, clamped to [0, 1].

- **`_is_duplicate_memory(user_id, text_hash)`**: Scrolls Qdrant for an existing point with
  the same user_id and text_hash. Prevents storing the same message twice.

- **`_dedupe_memories(memories)`**: After recall, removes near-identical texts by normalizing
  and hashing. Keeps the highest-scoring version.

**`format_memory_context(memories)`** (lines 368-375): Formats recalled memories as a
readable prompt block like:
```
Relevant memories:
- (0.87) [stress] user stressed about exams
- (0.72) [preference] user likes acoustic guitar
```

### RAG Context Builder

**File: `services/api/app/rag_context.py`** (56 lines)

Assembles the three context sources into a single prompt string injected before the user
message when calling the LLM.

**`RagContext`** dataclass holds:
- `state_summary`: One-line emotional state (e.g., "mood=playful, trust=0.70...")
- `recent_history`: Last 8 messages formatted as "role: message"
- `memory_context`: Formatted long-term memories from `format_memory_context()`

**`build_rag_context(...)`**: Takes the current EmotionalState, recent ConversationEvents,
and recalled MemoryChunks, formats each into a string section.

**`pick_memory_hint(memories)`**: Returns a natural language hint from the top memory (e.g.,
"I remember something related to stress: user stressed about exams"). This gets passed to
the LLM as an extra nudge to reference the memory.

### LLM Service

**File: `services/api/app/llm_service.py`** (234 lines)

Abstraction layer over multiple LLM providers. Handles both streaming and non-streaming
generation with automatic fallback.

**Constructor** (lines 14-28): Takes settings and optionally a pre-built client (for
testing). Creates an httpx async client for Ollama. Lazily creates an OpenAI client if
the API key is configured.

**`stream_reply(...)`** (lines 56-86): Main entry point for streaming. Tries the configured
provider first. If it fails or produces no output, falls back to `_fallback_reply()`.

**`generate_reply(...)`** (lines 30-54): Non-streaming wrapper that collects all chunks
from `stream_reply()` and joins them. Used when streaming produces empty output.

**`_stream_openai_reply(...)`** (lines 120-156): Calls OpenAI's chat completions API with
`stream=True`, yields content deltas from each SSE chunk.

**`_stream_ollama_reply(...)`** (lines 158-195): POSTs to Ollama's `/api/chat` endpoint
with `stream: true`, parses NDJSON lines, yields message content.

**`_build_prompts(...)`** (lines 197-216): Constructs the system prompt (persona identity +
instructions) and user prompt (RAG context + user message + generation instruction).

**`_fallback_reply(...)`** (lines 218-230): Mood-aware canned response used when both LLM
providers fail. Prefixes vary by mood ("Nice energy" for playful, "I hear you" for guarded).

**`_chunk_text(...)`** (lines 232-234): Splits fallback text into 24-char chunks to simulate
streaming behavior.

### Persona Service

**File: `services/api/app/persona_service.py`** (99 lines)

Manages bot personality profiles.

**`DEFAULT_PERSONAS`** (lines 21-53): Three built-in personas defined as frozen dataclasses:

| ID | Name | Temperature | Style |
|---|---|---|---|
| `balanced` | Balanced | 0.6 | Clear, direct, calm |
| `coach` | Coach | 0.65 | Action-oriented, accountability |
| `warm` | Warm | 0.7 | Empathetic, validating, supportive |

**`PersonaService`** methods:
- **`ensure_defaults()`**: Checks if each default persona exists in the DB; inserts any
  that are missing. Called on startup and before listing personas.
- **`list_personas()`**: Returns all personas ordered by is_default descending, then name.
- **`resolve_persona(requested_id)`**: Looks up the requested persona, falls back to the
  default, or seeds defaults and retries. Never returns None.

### Database Migrations (Alembic)

**`services/api/alembic.ini`** (37 lines): Alembic configuration. Points to the migration
scripts directory and sets the DB URL.

**`services/api/alembic/env.py`** (65 lines): Async migration runner. Uses
`async_engine_from_config` to connect to PostgreSQL. Reads the DB URL from the Settings
object so it stays in sync with the app.

**Migration 1: `20260303_0001_initial_schema.py`** (108 lines):
Creates the initial five tables: `users`, `chat_sessions`, `relationship_states`,
`conversation_events`, `chat_turn_metrics`. Includes all indexes and foreign keys.

**Migration 2: `20260304_0002_personas.py`** (100 lines):
Creates the `persona_profiles` table and seeds three default personas. Adds `persona_id`
column to `chat_sessions` with a foreign key constraint (backfills existing rows with
"balanced").

---

## Frontend (Next.js)

All frontend code is in `apps/web/`.

### `apps/web/app/page.tsx` (495 lines)

The entire chat UI in a single client component. Key sections:

**Types** (lines 6-47): TypeScript types for UI messages, server events, and persona options.
Server events are discriminated unions on the `type` field ("system", "meta", "token",
"done", "error").

**State management** (lines 85-107): Uses React `useState` for:
- `messages`: Array of chat bubbles
- `input`: Current text input
- `connected`: WebSocket connection status
- `isAwaitingReply`: Whether we're waiting for the LLM
- `userId`, `sessionId`: Persisted in localStorage
- `personas`: Loaded from `GET /personas`
- `selectedPersonaId`: Current persona choice
- `state`: Current emotional state from backend

**WebSocket lifecycle** (lines 170-345): A `useEffect` that:
1. Opens a WebSocket to `ws://localhost:8000/ws/chat`
2. On `onopen`: resets reconnect counter, shows "connected" status
3. On `onmessage`: parses server events and updates UI accordingly:
   - `meta`: Stores user/session IDs and emotional state
   - `token`: Appends delta text to the active assistant bubble (streaming)
   - `done`: Finalizes the assistant message with latency metrics
   - `error`: Shows error in chat timeline
4. On `onclose`: Attempts exponential backoff reconnection (max 8 attempts, 1s to 10s delay)
5. After max attempts, pauses and shows a manual "reconnect" button

**Persona loading** (lines 131-164): Fetches personas from `GET /personas` on mount, saves
selection to localStorage.

**Message sending** (lines 360-396): On form submit, adds user bubble + empty assistant
bubble to timeline, sends JSON payload over WebSocket.

**Rendering** (lines 402-494): Clean layout with:
- Top bar: title + connection status + reconnect button
- Persona selector bar: dropdown + description
- Meta bar: user ID, session ID, mood, persona name
- Timeline: chat bubbles with streaming support and latency stats
- Composer: textarea + send button

### `apps/web/app/layout.tsx` (32 lines)

Root layout component. Loads two Google Fonts:
- **Space Grotesk** (`--font-body`): Body text
- **IBM Plex Mono** (`--font-mono`): Monospace elements (status, metrics, system messages)

Sets metadata title and description.

### `apps/web/app/globals.css` (313 lines)

All styles in a single CSS file using custom properties. Key design decisions:
- Light color scheme with soft blue gradient background
- Glassmorphic card design (frosted glass effect via `backdrop-filter: blur`)
- Chat bubbles: user messages right-aligned (dark blue), assistant left-aligned (light blue),
  system messages centered (yellow dashed border)
- Responsive: collapses to single-column layout below 840px
- Reveal animation on new messages (fade-in + slight upward slide)

### `apps/web/next.config.mjs` (6 lines)
Minimal config. Just enables React strict mode.

### `apps/web/tsconfig.json` (35 lines)
TypeScript config targeting ES2022, using bundler module resolution, with the Next.js plugin.

### `apps/web/package.json` (24 lines)
Dependencies: Next.js 14, React 18. Dev dependencies: TypeScript 5.5, ESLint, type
definitions.

---

## Tests

All tests are in `services/api/tests/`. Run with:
```bash
cd services/api
.venv\Scripts\python -m pytest tests/ -q
```

### `test_state_engine.py` (20 lines)
Two tests verifying that positive messages increase trust/affection and negative messages
decrease them. Tests the pure function `update_emotional_state()`.

### `test_memory_service.py` (292 lines)
The most thorough test file. Uses `FakeQdrant` and `FakeEmbedder` stubs to test:
- Tag extraction from messages
- Memory indexing gate (`should_index_memory`)
- Full store + recall round-trip
- Duplicate detection via text hash
- Deduplication of near-identical recalled memories
- Reranking with importance and recency weighting
- Memory context formatting

### `test_rag_context.py` (28 lines)
Tests that `build_rag_context()` includes state, history, and memory in the prompt text.
Tests that `pick_memory_hint()` uses the top memory's tags.

### `test_llm_service.py` (167 lines)
Tests LLM streaming and fallback using fake clients:
- Falls back to mood-aware canned response when no OpenAI client is configured
- Streams tokens correctly from a mock OpenAI client
- Streams tokens correctly from a mock Ollama HTTP response

### `test_ws_stream.py` (333 lines)
Integration tests using FastAPI's `TestClient` with monkeypatched services:
- Verifies WebSocket event ordering (system -> meta -> tokens -> done)
- Verifies user and session ID persistence across turns
- Verifies persona switching mid-conversation
- Verifies the `GET /personas` endpoint returns all three defaults

---

## Root-Level Files

### `package.json` (13 lines)
Root workspace config. Defines npm workspaces pointing to `apps/*`. Three scripts:
- `dev:web`: Runs Next.js dev server
- `build:web`: Production build
- `lint:web`: ESLint check

### `docker-compose.yml` (34 lines)
Described in [Infrastructure](#infrastructure-docker) section.

### `.env.example` (31 lines)
Template for all environment variables. Copy to `.env` and customize. See
[Environment Variables](#environment-variables) for the full list.

### `.gitignore` (35 lines)
Ignores: node_modules, Python bytecode/caches, .env files, IDE configs, build output, and
a `data/` directory.

### `README.md` (109 lines)
Quick-start guide with stack decision rationale, monorepo layout, setup instructions, and
next build steps.

### `AGENT.md` (128 lines)
Context file for AI agents working on this repo. Contains project state, stack details,
architecture overview, important files, runbook, environment expectations, testing commands,
change rules, and known gaps.

---

## Environment Variables

Full reference from `.env.example`:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `openai` |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` or `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_CHAT_MODEL` | `llama3.2:3b` | Chat model name |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name |
| `OPENAI_API_KEY` | (empty) | OpenAI key for paid provider |
| `OPENAI_MODEL` | `gpt-4.1-mini` | OpenAI chat model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `API_HOST` | `0.0.0.0` | Backend bind address |
| `API_PORT` | `8000` | Backend port |
| `AUTO_CREATE_SCHEMA` | `false` | Create tables on startup (use Alembic instead) |
| `POSTGRES_DSN` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server |
| `QDRANT_COLLECTION` | `persona_memories` | Qdrant collection name |
| `QDRANT_VECTOR_SIZE` | `768` | Embedding dimensions (768 for nomic, 1536 for OpenAI) |
| `MEMORY_TOP_K` | `5` | Memories to recall per query |
| `MEMORY_CANDIDATE_MULTIPLIER` | `4` | Over-fetch ratio for reranking |
| `MEMORY_SEMANTIC_WEIGHT` | `0.62` | Semantic similarity weight |
| `MEMORY_IMPORTANCE_WEIGHT` | `0.25` | Importance score weight |
| `MEMORY_RECENCY_WEIGHT` | `0.13` | Recency score weight |
| `MEMORY_RECENCY_HALF_LIFE_HOURS` | `72` | Recency decay half-life |
| `DEFAULT_PERSONA_ID` | `balanced` | Default persona |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins |
| `NEXT_PUBLIC_API_WS_URL` | `ws://localhost:8000/ws/chat` | Frontend WebSocket URL |
| `NEXT_PUBLIC_API_HTTP_URL` | `http://localhost:8000` | Frontend HTTP API URL |

---

## Known Gaps & Next Steps

These are areas where the project needs further work:

1. **Persona prompts are too assistant-like** - The system/style prompts need tuning to
   sound more natural and less like a customer service bot.
2. **No CI/CD** - No GitHub Actions, no deployment pipeline.
3. **No structured logging** - No observability layer (should add structured JSON logging
   with correlation IDs).
4. **No frontend tests** - The React component has no automated tests.
5. **No analytics dashboard** - Turn metrics and state data are collected but not visualized.
6. **No user authentication** - User IDs are self-asserted strings from localStorage. No
   login, no OAuth, no session tokens.
7. **Sentiment analysis is keyword-based** - The state engine uses simple token matching.
   A model-based sentiment classifier would be more accurate.
8. **Single-page frontend** - The entire UI is one component. As features grow, it should
   be split into smaller components.
