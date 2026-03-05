from collections.abc import AsyncIterator
import json
from typing import TYPE_CHECKING, Any

import httpx

from app.schemas import EmotionalState

if TYPE_CHECKING:
    from app.config import Settings


class LlmService:
    def __init__(
        self,
        settings: "Settings",
        client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.provider = settings.llm_provider.lower()
        self.client = client
        self.http_client = http_client or httpx.AsyncClient(base_url=settings.ollama_base_url.rstrip("/"), timeout=90.0)

        if self.provider == "openai" and self.client is None and settings.openai_api_key:
            from openai import AsyncOpenAI  # Lazy import for local test environments.

            self.client = AsyncOpenAI(api_key=settings.openai_api_key)

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
        produced = False
        try:
            async for chunk in self._stream_provider_reply(
                user_message=user_message,
                rag_context=rag_context,
                persona_name=persona_name,
                persona_system_prompt=persona_system_prompt,
                persona_style_prompt=persona_style_prompt,
                persona_temperature=persona_temperature,
            ):
                produced = True
                yield chunk
        except Exception:
            produced = False

        if not produced:
            for chunk in self._chunk_text(fallback):
                yield chunk

    async def _stream_provider_reply(
        self,
        *,
        user_message: str,
        rag_context: str,
        persona_name: str,
        persona_system_prompt: str,
        persona_style_prompt: str,
        persona_temperature: float | None,
    ) -> AsyncIterator[str]:
        if self.provider == "ollama":
            async for chunk in self._stream_ollama_reply(
                user_message=user_message,
                rag_context=rag_context,
                persona_name=persona_name,
                persona_system_prompt=persona_system_prompt,
                persona_style_prompt=persona_style_prompt,
                persona_temperature=persona_temperature,
            ):
                yield chunk
            return

        async for chunk in self._stream_openai_reply(
            user_message=user_message,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
            persona_temperature=persona_temperature,
        ):
            yield chunk

    async def _stream_openai_reply(
        self,
        *,
        user_message: str,
        rag_context: str,
        persona_name: str,
        persona_system_prompt: str,
        persona_style_prompt: str,
        persona_temperature: float | None,
    ) -> AsyncIterator[str]:
        if self.client is None:
            return

        system_prompt, user_prompt = self._build_prompts(
            user_message=user_message,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
        )

        stream = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=persona_temperature if persona_temperature is not None else 0.6,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
        async for part in stream:
            if not getattr(part, "choices", None):
                continue
            delta = getattr(part.choices[0].delta, "content", None)
            if not delta:
                continue
            yield str(delta)

    async def _stream_ollama_reply(
        self,
        *,
        user_message: str,
        rag_context: str,
        persona_name: str,
        persona_system_prompt: str,
        persona_style_prompt: str,
        persona_temperature: float | None,
    ) -> AsyncIterator[str]:
        system_prompt, user_prompt = self._build_prompts(
            user_message=user_message,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
        )

        payload = {
            "model": self.settings.ollama_chat_model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": persona_temperature if persona_temperature is not None else 0.6},
        }

        async with self.http_client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                message = data.get("message") or {}
                delta = message.get("content")
                if delta:
                    yield str(delta)

    @staticmethod
    def _build_prompts(
        *,
        user_message: str,
        rag_context: str,
        persona_name: str,
        persona_system_prompt: str,
        persona_style_prompt: str,
    ) -> tuple[str, str]:
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
        return system_prompt, user_prompt

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
