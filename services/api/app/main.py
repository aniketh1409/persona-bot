from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.db import db_session, engine, init_db, qdrant_client, redis_client
from app.llm_service import LlmService
from app.memory_service import MemoryChunk, MemoryService, OpenAIEmbeddingClient
from app.rag_context import build_rag_context, pick_memory_hint
from app.schemas import ChatMessageIn, ChatMessageOut
from app.session_service import SessionService
from app.state_engine import update_emotional_state

settings = get_settings()
memory_service = MemoryService(
    qdrant=qdrant_client,
    embedder=OpenAIEmbeddingClient(settings),
    collection_name=settings.qdrant_collection,
    vector_size=settings.qdrant_vector_size,
)
llm_service = LlmService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    try:
        await memory_service.ensure_collection()
    except Exception:
        # Qdrant or embedding service may be unavailable in local dev.
        pass
    yield
    await redis_client.aclose()
    await qdrant_client.aclose()
    await engine.dispose()


app = FastAPI(title="PersonaBot API", version="0.1.0", lifespan=lifespan)


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
                user = await service.resolve_user(incoming.user_id)
                session = await service.resolve_session(user.id, incoming.session_id)
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
                await _remember_if_needed(
                    user_id=user.id,
                    session_id=session.id,
                    role="user",
                    message=incoming.message,
                    tags=memory_tags,
                )

                recent_events = await service.recent_events(session.id, limit=12)
                memories = await _recall_memories(user.id, incoming.message, memory_tags)
                rag_context = build_rag_context(
                    state=state_update.state,
                    recent_events=recent_events,
                    memories=memories,
                )
                memory_hint = pick_memory_hint(memories)
                assistant_message = await llm_service.generate_reply(
                    user_message=incoming.message,
                    state=state_update.state,
                    rag_context=rag_context.to_prompt_text(),
                    memory_hint=memory_hint,
                )

                await service.append_event(
                    session_id=session.id,
                    user_id=user.id,
                    role="assistant",
                    message=assistant_message,
                    sentiment_score=state_update.sentiment_score,
                )
                await service.increment_message_count(session)

                outgoing = ChatMessageOut(
                    message=assistant_message,
                    user_id=user.id,
                    session_id=session.id,
                    state=state_update.state,
                    created_at=datetime.now(timezone.utc),
                )
            await websocket.send_json(outgoing.model_dump(mode="json"))
    except WebSocketDisconnect:
        return
