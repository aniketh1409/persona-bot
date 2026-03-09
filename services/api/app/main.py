from contextlib import asynccontextmanager
from datetime import datetime, timezone
import inspect
from time import perf_counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.db import db_session, engine, init_db, qdrant_client, redis_client
from app.llm_service import LlmService
from app.memory_service import MemoryChunk, MemoryService, OllamaEmbeddingClient, OpenAIEmbeddingClient
from app.persona_service import PersonaService
from app.rag_context import build_rag_context, pick_memory_hint
from app.schemas import ChatMessageIn, ChatMessageOut, HistoryEventOut, PersonaOut, SessionOut
from app.session_service import SessionService
from app.state_engine import update_emotional_state

settings = get_settings()
if settings.embedding_provider.lower() == "ollama":
    memory_embedder = OllamaEmbeddingClient(settings)
else:
    memory_embedder = OpenAIEmbeddingClient(settings)

memory_service = MemoryService(
    qdrant=qdrant_client,
    embedder=memory_embedder,
    collection_name=settings.qdrant_collection,
    vector_size=settings.qdrant_vector_size,
    candidate_multiplier=settings.memory_candidate_multiplier,
    semantic_weight=settings.memory_semantic_weight,
    importance_weight=settings.memory_importance_weight,
    recency_weight=settings.memory_recency_weight,
    recency_half_life_hours=settings.memory_recency_half_life_hours,
)
llm_service = LlmService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    try:
        async with db_session() as db:
            persona_service = PersonaService(db)
            await persona_service.ensure_defaults()
    except Exception:
        # Persona seed can be skipped in environments without DB.
        pass
    try:
        await memory_service.ensure_collection()
    except Exception:
        # Qdrant or embedding service may be unavailable in local dev.
        pass
    yield
    await redis_client.aclose()
    close_coro = getattr(qdrant_client, "aclose", None)
    if callable(close_coro):
        maybe_awaitable = close_coro()
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    else:
        close_sync = getattr(qdrant_client, "close", None)
        if callable(close_sync):
            maybe_awaitable = close_sync()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
    await engine.dispose()


app = FastAPI(title="PersonaBot API", version="0.1.0", lifespan=lifespan)
allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    service: str


async def _remember_if_needed(
    *,
    user_id: str,
    session_id: str,
    role: str,
    message: str,
    tags: list[str],
) -> None:
    if not memory_service.should_index_memory(role, message, tags):
        return

    try:
        await memory_service.store_memory(
            user_id=user_id,
            session_id=session_id,
            role=role,
            message=message,
            tags=tags,
        )
    except Exception:
        return


async def _recall_memories(user_id: str, message: str, tags: list[str]) -> list[MemoryChunk]:
    try:
        return await memory_service.recall(
            user_id=user_id,
            query=message,
            tags=tags or None,
            limit=settings.memory_top_k,
        )
    except Exception:
        return []


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="personabot-api")


@app.get("/personas", response_model=list[PersonaOut])
async def personas() -> list[PersonaOut]:
    async with db_session() as db:
        persona_service = PersonaService(db)
        await persona_service.ensure_defaults()
        rows = await persona_service.list_personas()
        return [
            PersonaOut(
                id=row.id,
                name=row.name,
                description=row.description,
                is_default=row.is_default,
                temperature=row.temperature,
            )
            for row in rows
        ]


@app.get("/sessions/{user_id}", response_model=list[SessionOut])
async def sessions(user_id: str) -> list[SessionOut]:
    async with db_session() as db:
        service = SessionService(db)
        rows = await service.list_sessions(user_id)
        result: list[SessionOut] = []
        for row in rows:
            preview = await service.session_preview(row.id)
            result.append(
                SessionOut(
                    id=row.id,
                    persona_id=row.persona_id,
                    message_count=row.message_count,
                    created_at=row.created_at,
                    last_active_at=row.last_active_at,
                    preview=preview,
                )
            )
        return result


@app.get("/history/{session_id}", response_model=list[HistoryEventOut])
async def history(session_id: str, limit: int = 50) -> list[HistoryEventOut]:
    async with db_session() as db:
        service = SessionService(db)
        events = await service.recent_events(session_id, limit=limit)
        return [
            HistoryEventOut(
                role=event.role,
                message=event.message,
                created_at=event.created_at,
            )
            for event in events
        ]


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "system", "message": "Connected to PersonaBot session service."})

    try:
        while True:
            payload = await websocket.receive_json()
            try:
                incoming = ChatMessageIn.model_validate(payload)
            except ValidationError as exc:
                await websocket.send_json({"type": "error", "message": exc.errors()})
                continue

            async with db_session() as db:
                service = SessionService(db)
                persona_service = PersonaService(db)
                await persona_service.ensure_defaults()
                persona = await persona_service.resolve_persona(incoming.persona_id)
                user = await service.resolve_user(incoming.user_id)
                session = await service.resolve_or_create_session(
                    user_id=user.id,
                    session_id=incoming.session_id,
                    persona_id=persona.id,
                )
                previous_state = await service.load_state(session.id)

                await service.append_event(
                    session_id=session.id,
                    user_id=user.id,
                    role="user",
                    message=incoming.message,
                    sentiment_score=0.0,
                )
                session = await service.increment_message_count(session)

                state_update = update_emotional_state(previous_state, incoming.message, session.message_count)
                await service.save_state(session.id, state_update.state)

                memory_tags = memory_service.extract_tags(incoming.message)
                recent_events = await service.recent_events(session.id, limit=12)

                user_id = user.id
                session_id = session.id
                persona_id = persona.id
                state = state_update.state
                sentiment_score = state_update.sentiment_score
                persona_name = persona.name
                persona_system_prompt = persona.system_prompt
                persona_style_prompt = persona.style_prompt
                persona_temperature = persona.temperature

            await _remember_if_needed(
                user_id=user_id,
                session_id=session_id,
                role="user",
                message=incoming.message,
                tags=memory_tags,
            )

            memories = await _recall_memories(user_id, incoming.message, memory_tags)
            rag_context = build_rag_context(
                state=state,
                recent_events=recent_events,
                memories=memories,
            )
            memory_hint = pick_memory_hint(memories)

            await websocket.send_json(
                {
                    "type": "meta",
                    "user_id": user_id,
                    "session_id": session_id,
                    "persona_id": persona_id,
                    "state": state.model_dump(mode="json"),
                }
            )

            started_at = perf_counter()
            first_token_ms: float | None = None
            chunk_count = 0
            chunks: list[str] = []
            try:
                async for chunk in llm_service.stream_reply(
                    user_message=incoming.message,
                    state=state,
                    rag_context=rag_context.to_prompt_text(),
                    persona_name=persona_name,
                    persona_system_prompt=persona_system_prompt,
                    persona_style_prompt=persona_style_prompt,
                    persona_temperature=persona_temperature,
                    memory_hint=memory_hint,
                ):
                    if not chunk:
                        continue
                    chunk_count += 1
                    chunks.append(chunk)
                    if first_token_ms is None:
                        first_token_ms = (perf_counter() - started_at) * 1000
                    await websocket.send_json({"type": "token", "delta": chunk})
            except Exception:
                await websocket.send_json({"type": "error", "message": "reply streaming failed"})
                continue

            assistant_message = "".join(chunks).strip()
            if not assistant_message:
                assistant_message = await llm_service.generate_reply(
                    user_message=incoming.message,
                    state=state,
                    rag_context=rag_context.to_prompt_text(),
                    persona_name=persona_name,
                    persona_system_prompt=persona_system_prompt,
                    persona_style_prompt=persona_style_prompt,
                    persona_temperature=persona_temperature,
                    memory_hint=memory_hint,
                )
                chunk_count = 1
                first_token_ms = first_token_ms or (perf_counter() - started_at) * 1000
            latency_ms = (perf_counter() - started_at) * 1000

            async with db_session() as db:
                service = SessionService(db)
                session = await service.resolve_session(user_id, session_id)

                assistant_event = await service.append_event(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    message=assistant_message,
                    sentiment_score=sentiment_score,
                )
                await service.increment_message_count(session)
                await service.save_turn_metric(
                    session_id=session_id,
                    user_id=user_id,
                    assistant_event_id=assistant_event.id,
                    latency_ms=latency_ms,
                    first_token_ms=first_token_ms,
                    chunk_count=chunk_count,
                )

            outgoing = ChatMessageOut(
                message=assistant_message,
                user_id=user_id,
                session_id=session_id,
                persona_id=persona_id,
                state=state,
                created_at=datetime.now(timezone.utc),
                latency_ms=latency_ms,
                first_token_ms=first_token_ms,
                chunk_count=chunk_count,
            )
            payload = outgoing.model_dump(mode="json")
            payload["type"] = "done"
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        return
