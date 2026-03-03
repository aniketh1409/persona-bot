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


class ChatMessageOut(BaseModel):
    type: Literal["assistant"] = "assistant"
    message: str
    user_id: str
    session_id: str
    state: EmotionalState
    created_at: datetime
