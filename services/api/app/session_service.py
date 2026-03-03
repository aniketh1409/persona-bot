import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import redis_client
from app.models import ChatSession, ConversationEvent, RelationshipState, User
from app.schemas import EmotionalState


class SessionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_user(self, user_id: str | None) -> User:
        resolved_id = user_id or str(uuid.uuid4())
        user = await self.db.get(User, resolved_id)
        if user is None:
            user = User(id=resolved_id)
            self.db.add(user)
            await self.db.flush()
        return user

    async def resolve_session(self, user_id: str, session_id: str | None) -> ChatSession:
        resolved_id = session_id or str(uuid.uuid4())
        session = await self.db.get(ChatSession, resolved_id)
        if session is None:
            session = ChatSession(id=resolved_id, user_id=user_id, message_count=0)
            self.db.add(session)
            await self.db.flush()
        return session

    async def load_state(self, session_id: str) -> EmotionalState:
        cache_key = self._state_cache_key(session_id)
        cached = await redis_client.get(cache_key)
        if cached:
            return EmotionalState.model_validate_json(cached)

        state_row = await self.db.get(RelationshipState, session_id)
        if state_row is None:
            default_state = EmotionalState()
            await self.save_state(session_id, default_state)
            return default_state

        state = EmotionalState(
            baseline_mood=state_row.baseline_mood,
            current_mood=state_row.current_mood,
            affection=state_row.affection,
            trust=state_row.trust,
            energy=state_row.energy,
        )
        await redis_client.set(cache_key, state.model_dump_json(), ex=60 * 60 * 6)
        return state

    async def save_state(self, session_id: str, state: EmotionalState) -> None:
        row = await self.db.get(RelationshipState, session_id)
        if row is None:
            row = RelationshipState(
                session_id=session_id,
                baseline_mood=state.baseline_mood,
                current_mood=state.current_mood,
                affection=state.affection,
                trust=state.trust,
                energy=state.energy,
            )
            self.db.add(row)
        else:
            row.baseline_mood = state.baseline_mood
            row.current_mood = state.current_mood
            row.affection = state.affection
            row.trust = state.trust
            row.energy = state.energy

        await redis_client.set(self._state_cache_key(session_id), state.model_dump_json(), ex=60 * 60 * 6)

    async def append_event(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        message: str,
        sentiment_score: float,
    ) -> None:
        event = ConversationEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            role=role,
            message=message,
            sentiment_score=sentiment_score,
        )
        self.db.add(event)

    async def increment_message_count(self, session: ChatSession) -> ChatSession:
        session.message_count += 1
        session.last_active_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def recent_events(self, session_id: str, limit: int = 12) -> list[ConversationEvent]:
        stmt = (
            select(ConversationEvent)
            .where(ConversationEvent.session_id == session_id)
            .order_by(ConversationEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()
        events.reverse()
        return events

    @staticmethod
    def _state_cache_key(session_id: str) -> str:
        return f"state:{session_id}"
