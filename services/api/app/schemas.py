from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmotionalState(BaseModel):
    baseline_mood: str = "neutral"
    current_mood: str = "neutral"
    affection: float = Field(default=0.5, ge=0.0, le=1.0)
    trust: float = Field(default=0.5, ge=0.0, le=1.0)
    energy: float = Field(default=0.6, ge=0.0, le=1.0)


class ChatMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    user_id: str | None = None
    session_id: str | None = None
    persona_id: str | None = None


class ChatMessageOut(BaseModel):
    type: Literal["assistant"] = "assistant"
    message: str
    user_id: str
    session_id: str
    persona_id: str
    state: EmotionalState
    created_at: datetime
    latency_ms: float | None = None
    first_token_ms: float | None = None
    chunk_count: int | None = None


class HistoryEventOut(BaseModel):
    role: str
    message: str
    created_at: datetime


class SessionOut(BaseModel):
    id: str
    persona_id: str
    message_count: int
    created_at: datetime
    last_active_at: datetime
    preview: str


class PersonaOut(BaseModel):
    id: str
    name: str
    description: str
    is_default: bool
    temperature: float
