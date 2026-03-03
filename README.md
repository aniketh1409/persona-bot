# PersonaBot

Stateful, emotionally adaptive conversational AI system with long-term memory and real-time chat streaming.

## Core Stack Decision

- Frontend: Next.js (React + TypeScript)
- Backend: FastAPI (Python async + WebSockets)
- Data: PostgreSQL, Redis, Qdrant (vector memory)

Why this split:
- Next.js gives fast UI iteration and production-ready React routing.
- FastAPI is a strong fit for async AI orchestration, state engines, and streaming.
- PostgreSQL + Redis + vector DB maps directly to profile/state/memory requirements.

## Monorepo Layout

```text
apps/
  web/          # Next.js frontend
services/
  api/          # FastAPI backend
docker-compose.yml
.env.example
```

## Quick Start

1. Start infra:

```bash
docker compose up -d
```

2. Frontend install + run:

```bash
npm install
npm run dev:web
```

3. Backend install + run:

```bash
cd services/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open:
- Frontend: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- Chat socket: `ws://localhost:8000/ws/chat`

## Core Dependencies Added

Frontend:
- `next`, `react`, `react-dom`, `typescript`, `eslint`, `eslint-config-next`

Backend:
- `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
- `sqlalchemy`, `asyncpg` (PostgreSQL)
- `redis` (ephemeral/session state)
- `qdrant-client` (vector memory)
- `openai`, `httpx`

## Next Build Steps

1. Implement session/user profile tables in PostgreSQL.
2. Add `state-engine` module (trust/affection/energy update rules).
3. Add memory ingestion + retrieval against Qdrant.
4. Stream model tokens over `/ws/chat`.
