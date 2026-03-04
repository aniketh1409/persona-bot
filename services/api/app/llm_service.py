from typing import TYPE_CHECKING, Any

from app.schemas import EmotionalState

if TYPE_CHECKING:
    from app.config import Settings


class LlmService:
    def __init__(self, settings: "Settings", client: Any | None = None) -> None:
        self.settings = settings
        if client is not None:
            self.client = client
            return

        if settings.openai_api_key:
            from openai import AsyncOpenAI  # Lazy import for local test environments.

            self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            self.client = None

    async def generate_reply(
        self,
        *,
        user_message: str,
        state: EmotionalState,
        rag_context: str,
        memory_hint: str | None = None,
    ) -> str:
        if self.client is None:
            return self._fallback_reply(user_message=user_message, mood=state.current_mood, memory_hint=memory_hint)

        system_prompt = (
            "You are PersonaBot, an emotionally adaptive assistant. "
            "Keep replies concise, empathetic, and consistent with the provided state and memory context."
        )
        user_prompt = (
            f"{rag_context}\n\n"
            f"Latest user message:\n{user_message}\n\n"
            "Generate a direct assistant reply."
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=0.6,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception:
            return self._fallback_reply(user_message=user_message, mood=state.current_mood, memory_hint=memory_hint)

        content = response.choices[0].message.content if response.choices else None
        if not content:
            return self._fallback_reply(user_message=user_message, mood=state.current_mood, memory_hint=memory_hint)
        return str(content).strip()

    @staticmethod
    def _fallback_reply(*, user_message: str, mood: str, memory_hint: str | None) -> str:
        if mood == "playful":
            prefix = "Nice energy. "
        elif mood == "guarded":
            prefix = "I hear you. "
        elif mood == "calm":
            prefix = "Got it, keeping this steady. "
        else:
            prefix = "Understood. "

        hint = f" {memory_hint}" if memory_hint else ""
        return f"{prefix}You said: {user_message}.{hint}"
