from app.memory_service import MemoryChunk
from app.rag_context import build_rag_context, pick_memory_hint
from app.schemas import EmotionalState


class FakeEvent:
    def __init__(self, role: str, message: str) -> None:
        self.role = role
        self.message = message


def test_build_rag_context_contains_state_history_and_memory() -> None:
    state = EmotionalState(current_mood="playful", trust=0.7, affection=0.8, energy=0.6)
    events = [FakeEvent("user", "I am stressed"), FakeEvent("assistant", "We can plan this out")]
    memories = [MemoryChunk(text="user has midterm stress", score=0.9, tags=["stress"], created_at="x")]

    context = build_rag_context(state=state, recent_events=events, memories=memories)
    prompt_text = context.to_prompt_text()

    assert "mood=playful" in prompt_text
    assert "user: I am stressed" in prompt_text
    assert "midterm stress" in prompt_text


def test_pick_memory_hint_uses_top_memory() -> None:
    hint = pick_memory_hint([MemoryChunk(text="user likes guitar", score=0.6, tags=["preference"], created_at="x")])
    assert hint is not None
    assert "preference" in hint
