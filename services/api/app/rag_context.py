from dataclasses import dataclass
from typing import Any

from app.memory_service import MemoryChunk, format_memory_context
from app.schemas import EmotionalState


@dataclass(frozen=True)
class RagContext:
    state_summary: str
    recent_history: str
    memory_context: str

    def to_prompt_text(self) -> str:
        return "\n\n".join(
            [
                f"State:\n{self.state_summary}",
                f"Recent conversation:\n{self.recent_history}",
                f"Long-term memory:\n{self.memory_context}",
            ]
        )


def build_rag_context(
    *,
    state: EmotionalState,
    recent_events: list[Any],
    memories: list[MemoryChunk],
) -> RagContext:
    state_summary = (
        f"mood={state.current_mood}, trust={state.trust:.2f}, "
        f"affection={state.affection:.2f}, energy={state.energy:.2f}"
    )

    if not recent_events:
        history_summary = "No recent events."
    else:
        history_lines = []
        for event in recent_events[-12:]:
            role = getattr(event, "role", "unknown")
            message = str(getattr(event, "message", "")).strip().replace("\n", " ")
            history_lines.append(f"{role}: {message}")
        history_summary = "\n".join(history_lines)

    memory_context = format_memory_context(memories)
    return RagContext(state_summary=state_summary, recent_history=history_summary, memory_context=memory_context)


def pick_memory_hint(memories: list[MemoryChunk]) -> str | None:
    if not memories:
        return None

    top = memories[0]
    if top.tags:
        return f"I remember something related to {top.tags[0]}: {top.text}"
    return f"I remember: {top.text}"
