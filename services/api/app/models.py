from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_user_last_active", "user_id", "last_active_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    persona_id: Mapped[str] = mapped_column(String(64), ForeignKey("persona_profiles.id"), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RelationshipState(Base):
    __tablename__ = "relationship_states"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), primary_key=True)
    baseline_mood: Mapped[str] = mapped_column(String(32), default="neutral")
    current_mood: Mapped[str] = mapped_column(String(32), default="neutral")
    affection: Mapped[float] = mapped_column(Float, default=0.5)
    trust: Mapped[float] = mapped_column(Float, default=0.5)
    energy: Mapped[float] = mapped_column(Float, default=0.6)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PersonaProfile(Base):
    __tablename__ = "persona_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    style_prompt: Mapped[str] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, default=0.6)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationEvent(Base):
    __tablename__ = "conversation_events"
    __table_args__ = (Index("ix_events_session_created_at", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatTurnMetric(Base):
    __tablename__ = "chat_turn_metrics"
    __table_args__ = (Index("ix_metrics_session_created_at", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    assistant_event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversation_events.id"))
    latency_ms: Mapped[float] = mapped_column(Float)
    first_token_ms: Mapped[float | None] = mapped_column(Float)
    chunk_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
