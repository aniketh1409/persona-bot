from collections.abc import AsyncIterator
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
        persona_name: str = "Balanced",
        persona_system_prompt: str = "",
        persona_style_prompt: str = "",
        persona_temperature: float | None = None,
        memory_hint: str | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.stream_reply(
            user_message=user_message,
            state=state,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
            persona_temperature=persona_temperature,
            memory_hint=memory_hint,
        ):
            chunks.append(chunk)
        return "".join(chunks).strip()

    async def stream_reply(
        self,
        *,
        user_message: str,
        state: EmotionalState,
        rag_context: str,
        persona_name: str = "Balanced",
        persona_system_prompt: str = "",
        persona_style_prompt: str = "",
        persona_temperature: float | None = None,
        memory_hint: str | None = None,
    ) -> AsyncIterator[str]:
        fallback = self._fallback_reply(user_message=user_message, mood=state.current_mood, memory_hint=memory_hint)
        if self.client is None:
            for chunk in self._chunk_text(fallback):
                yield chunk
            return

        system_prompt = (
            f"You are PersonaBot in {persona_name} persona mode. "
            "Keep replies concise, emotionally adaptive, and consistent with state and memory context. "
            f"{persona_system_prompt} {persona_style_prompt}"
        )
        user_prompt = (
            f"{rag_context}\n\n"
            f"Latest user message:\n{user_message}\n\n"
            "Generate a direct assistant reply."
        )

        try:
            stream = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=persona_temperature if persona_temperature is not None else 0.6,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            produced = False
            async for part in stream:
                if not getattr(part, "choices", None):
                    continue
                delta = getattr(part.choices[0].delta, "content", None)
                if not delta:
                    continue
                produced = True
                yield str(delta)
            if not produced:
                for chunk in self._chunk_text(fallback):
                    yield chunk
        except Exception:
            for chunk in self._chunk_text(fallback):
                yield chunk

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

    @staticmethod
    def _chunk_text(text: str, size: int = 24) -> list[str]:
        return [text[i : i + size] for i in range(0, len(text), size)] or [""]
