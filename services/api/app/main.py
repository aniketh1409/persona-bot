from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.db import db_session, engine, init_db, redis_client
from app.schemas import ChatMessageIn, ChatMessageOut
from app.session_service import SessionService
from app.state_engine import update_emotional_state


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="PersonaBot API", version="0.1.0", lifespan=lifespan)


class HealthResponse(BaseModel):
    status: str
    service: str


def _compose_assistant_message(user_message: str, mood: str) -> str:
    if mood == "playful":
        prefix = "Nice energy. "
    elif mood == "guarded":
        prefix = "I hear you. "
    elif mood == "calm":
        prefix = "Got it, keeping this steady. "
    else:
        prefix = "Understood. "
    return f"{prefix}You said: {user_message}"


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

                assistant_message = _compose_assistant_message(incoming.message, state_update.state.current_mood)
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
