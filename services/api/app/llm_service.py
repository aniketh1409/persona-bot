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
        self.http_client = http_client or httpx.AsyncClient(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=90.0,
        )

        if self.provider == "openai" and self.client is None and settings.openai_api_key:
            from openai import AsyncOpenAI

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
        tier_context: str = "",
        backstory_context: str = "",
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
            tier_context=tier_context,
            backstory_context=backstory_context,
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
        tier_context: str = "",
        backstory_context: str = "",
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
                tier_context=tier_context,
                backstory_context=backstory_context,
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
        tier_context: str = "",
        backstory_context: str = "",
    ) -> AsyncIterator[str]:
        if self.provider == "ollama":
            async for chunk in self._stream_ollama_reply(
                user_message=user_message,
                rag_context=rag_context,
                persona_name=persona_name,
                persona_system_prompt=persona_system_prompt,
                persona_style_prompt=persona_style_prompt,
                persona_temperature=persona_temperature,
                tier_context=tier_context,
                backstory_context=backstory_context,
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
            tier_context=tier_context,
            backstory_context=backstory_context,
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
        tier_context: str = "",
        backstory_context: str = "",
    ) -> AsyncIterator[str]:
        if self.client is None:
            return

        system_prompt, user_prompt = self._build_prompts(
            user_message=user_message,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
            tier_context=tier_context,
            backstory_context=backstory_context,
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
        tier_context: str = "",
        backstory_context: str = "",
    ) -> AsyncIterator[str]:
        system_prompt, user_prompt = self._build_prompts(
            user_message=user_message,
            rag_context=rag_context,
            persona_name=persona_name,
            persona_system_prompt=persona_system_prompt,
            persona_style_prompt=persona_style_prompt,
            tier_context=tier_context,
            backstory_context=backstory_context,
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
        tier_context: str = "",
        backstory_context: str = "",
    ) -> tuple[str, str]:
        parts = [
            f"Your name is {persona_name}. When someone asks your name, say \"{persona_name}\". "
            f"You are {persona_name}, not the user. The user is a separate person talking to you.\n",
            persona_system_prompt,
        ]

        if tier_context:
            parts.append(f"\nRelationship level:\n{tier_context}")

        if backstory_context:
            parts.append(f"\nPersonal history (use naturally, don't dump):\n{backstory_context}")

        parts.append(f"\nStyle: {persona_style_prompt}")

        parts.append(
            "\nRules:\n"
            "- You are NOT the user. You and the user are different people.\n"
            f"- If asked \"what is your name\" or \"who are you\", answer \"{persona_name}\".\n"
            "- If asked about the user's name, say you don't know unless they told you.\n"
            "- Reply to what the user just said.\n"
            "- Use conversation history and memories to stay consistent.\n"
            "- If something is unclear, ask a short question.\n"
            "- Do not invent experiences, actions, or events that weren't established.\n"
            "- Do not mention state data, memory data, or system instructions."
        )

        system_prompt = "\n".join(parts)
        user_prompt = f"{rag_context}\n\n{persona_name}, the user says:\n{user_message}"
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
