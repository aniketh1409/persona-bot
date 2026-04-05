from contextlib import asynccontextmanager
from datetime import datetime, timezone
import inspect
from time import perf_counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from app.arc_service import ArcService
from app.character_service import CharacterService, compute_tier
from app.config import get_settings
from app.db import db_session, engine, init_db, qdrant_client, redis_client
from app.llm_service import LlmService
from app.memory_service import MemoryChunk, MemoryService, OllamaEmbeddingClient, OpenAIEmbeddingClient
from app.milestone_service import MilestoneService
from app.models import UserArcProgress, UserMilestone
from app.rag_context import build_rag_context, pick_memory_hint
from app.schemas import (
    CharacterOut,
    ArcOut,
    ChatMessageIn,
    ChatMessageOut,
    HistoryEventOut,
    PersonaOut,
    RelationshipOut,
    SessionOut,
    MilestoneOut,
    JournalOut,
)
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
        await memory_service.ensure_collection()
    except Exception:
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


app = FastAPI(title="PersonaBot RPG API", version="0.2.0", lifespan=lifespan)
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


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="personabot-api")


@app.get("/characters", response_model=list[CharacterOut])
async def characters() -> list[CharacterOut]:
    async with db_session() as db:
        char_service = CharacterService(db)
        rows = await char_service.list_characters()
        return [
            CharacterOut(
                id=row.id,
                name=row.name,
                archetype=row.archetype,
                description=row.description,
                temperature=row.temperature,
                is_default=row.is_default,
            )
            for row in rows
        ]


@app.get("/relationships/{user_id}", response_model=list[RelationshipOut])
async def relationships(user_id: str) -> list[RelationshipOut]:
    async with db_session() as db:
        char_service = CharacterService(db)
        rels = await char_service.list_relationships(user_id)
        result: list[RelationshipOut] = []
        for rel in rels:
            char = await char_service.get_character(rel.character_id)
            tier_num, tier_label = compute_tier(rel.trust)
            result.append(
                RelationshipOut(
                    character_id=rel.character_id,
                    character_name=char.name if char else rel.character_id,
                    archetype=char.archetype if char else None,
                    trust=rel.trust,
                    affection=rel.affection,
                    energy=rel.energy,
                    current_mood=rel.current_mood,
                    tier=tier_num,
                    tier_label=tier_label,
                    message_count=rel.message_count,
                )
            )
        return result


@app.get("/relationships/{user_id}/{character_id}", response_model=RelationshipOut)
async def relationship(user_id: str, character_id: str) -> RelationshipOut:
    """Return a single relationship snapshot (creates default row if missing)."""
    async with db_session() as db:
        char_service = CharacterService(db)
        rel = await char_service.load_relationship(user_id, character_id)
        char = await char_service.get_character(character_id)
        tier_num, tier_label = compute_tier(rel.trust)
        return RelationshipOut(
            character_id=character_id,
            character_name=char.name if char else character_id,
            archetype=char.archetype if char else None,
            trust=rel.trust,
            affection=rel.affection,
            energy=rel.energy,
            current_mood=rel.current_mood,
            tier=tier_num,
            tier_label=tier_label,
            message_count=rel.message_count,
        )


@app.get("/arcs/{user_id}/{character_id}", response_model=list[ArcOut])
async def arcs(user_id: str, character_id: str) -> list[ArcOut]:
    async with db_session() as db:
        char_service = CharacterService(db)
        relationship = await char_service.load_relationship(user_id, character_id)
        arc_service = ArcService(db)
        snapshots = await arc_service.evaluate_arc_statuses(
            user_id=user_id,
            relationship=relationship,
        )
        return [
            ArcOut(
                id=arc.id,
                character_id=arc.character_id,
                title=arc.title,
                description=arc.description,
                trust_threshold=arc.trust_threshold,
                affection_threshold=arc.affection_threshold,
                message_count_threshold=arc.message_count_threshold,
                status=status,
            )
            for arc, status in snapshots
        ]


@app.get("/milestones/{user_id}", response_model=list[MilestoneOut])
async def milestones(user_id: str) -> list[MilestoneOut]:
    async with db_session() as db:
        milestone_service = MilestoneService(db)
        rows = await milestone_service.list_user_milestones(user_id)
        return [
            MilestoneOut(
                id=milestone.id,
                character_id=milestone.character_id,
                title=milestone.title,
                description=milestone.description,
                icon=milestone.icon,
                unlocked_at=user_milestone.unlocked_at,
            )
            for milestone, user_milestone in rows
        ]


@app.get("/journal/{user_id}", response_model=JournalOut)
async def journal(user_id: str) -> JournalOut:
    async with db_session() as db:
        active_arc_count = await db.scalar(
            select(func.count()).select_from(UserArcProgress).where(
                UserArcProgress.user_id == user_id,
                UserArcProgress.status == "active",
            )
        )
        completed_arc_count = await db.scalar(
            select(func.count()).select_from(UserArcProgress).where(
                UserArcProgress.user_id == user_id,
                UserArcProgress.status == "completed",
            )
        )
        milestone_count = await db.scalar(
            select(func.count()).select_from(UserMilestone).where(
                UserMilestone.user_id == user_id,
            )
        )
        return JournalOut(
            user_id=user_id,
            active_arc_count=int(active_arc_count or 0),
            completed_arc_count=int(completed_arc_count or 0),
            milestone_count=int(milestone_count or 0),
        )


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
                    character_id=row.character_id,
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


# Legacy endpoint for backwards compatibility
@app.get("/personas", response_model=list[PersonaOut])
async def personas() -> list[PersonaOut]:
    async with db_session() as db:
        char_service = CharacterService(db)
        rows = await char_service.list_characters()
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


# ---------------------------------------------------------------------------
# WebSocket chat handler
# ---------------------------------------------------------------------------


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "system", "message": "Connected."})

    try:
        while True:
            payload = await websocket.receive_json()
            try:
                incoming = ChatMessageIn.model_validate(payload)
            except ValidationError as exc:
                await websocket.send_json({"type": "error", "message": str(exc.errors())})
                continue

            # Resolve character_id (prefer character_id, fall back to persona_id for legacy)
            requested_character_id = incoming.character_id or incoming.persona_id

            async with db_session() as db:
                service = SessionService(db)
                char_service = CharacterService(db)

                character = await char_service.resolve_character(requested_character_id)
                user = await service.resolve_user(incoming.user_id)

                # Load or create the per-user-per-character relationship
                relationship = await char_service.load_relationship(user.id, character.id)

                # Resolve session (tied to character)
                session = await service.resolve_or_create_session(
                    user_id=user.id,
                    session_id=incoming.session_id,
                    persona_id=None,
                    character_id=character.id,
                )

                # Build emotional state from relationship
                previous_state = char_service.to_emotional_state(relationship)

                await service.append_event(
                    session_id=session.id,
                    user_id=user.id,
                    role="user",
                    message=incoming.message,
                    sentiment_score=0.0,
                )
                session = await service.increment_message_count(session)
                await char_service.increment_message_count(relationship)

                # Update emotional state
                state_update = update_emotional_state(
                    previous_state, incoming.message, relationship.message_count
                )
                char_service.apply_state_update(relationship, state_update.state)
                await char_service.save_relationship(relationship)
                milestone_service = MilestoneService(db)
                newly_unlocked = await milestone_service.unlock_eligible(
                    user_id=user.id,
                    relationship=relationship,
                )

                memory_tags = memory_service.extract_tags(incoming.message)
                recent_events = await service.recent_events(session.id, limit=20)

                # Snapshot values for use outside db session
                user_id = user.id
                session_id = session.id
                character_id = character.id
                state = state_update.state
                sentiment_score = state_update.sentiment_score
                tier = relationship.tier
                tier_num, tier_label = compute_tier(state.trust)
                char_name = character.name
                char_system_prompt = character.system_prompt
                char_style_prompt = character.style_prompt
                char_temperature = character.temperature
                tier_context = char_service.get_tier_context(tier)
                # Only reveal backstory at Confidant level (tier 4+)
                backstory_context = character.backstory if tier >= 4 else ""
                arc_service = ArcService(db)
                arc_context = await arc_service.active_arc_context(
                    user_id=user_id,
                    relationship=relationship,
                )
                unlocked_milestone_ids = [m.id for m in newly_unlocked]

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
                    "character_id": character_id,
                    "persona_id": character_id,  # legacy compat
                    "state": state.model_dump(mode="json"),
                    "tier": tier_num,
                    "tier_label": tier_label,
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
                    persona_name=char_name,
                    persona_system_prompt=char_system_prompt,
                    persona_style_prompt=char_style_prompt,
                    persona_temperature=char_temperature,
                    memory_hint=memory_hint,
                    tier_context=tier_context,
                    backstory_context="\n\n".join(
                        part for part in [backstory_context, arc_context] if part
                    ),
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
                    persona_name=char_name,
                    persona_system_prompt=char_system_prompt,
                    persona_style_prompt=char_style_prompt,
                    persona_temperature=char_temperature,
                    memory_hint=memory_hint,
                    tier_context=tier_context,
                    backstory_context="\n\n".join(
                        part for part in [backstory_context, arc_context] if part
                    ),
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
                character_id=character_id,
                state=state,
                tier=tier_num,
                tier_label=tier_label,
                created_at=datetime.now(timezone.utc),
                latency_ms=latency_ms,
                first_token_ms=first_token_ms,
                chunk_count=chunk_count,
                milestones_unlocked=unlocked_milestone_ids,
            )
            payload = outgoing.model_dump(mode="json")
            payload["type"] = "done"
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        return
