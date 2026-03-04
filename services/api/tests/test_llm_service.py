import asyncio

from app.llm_service import LlmService
from app.schemas import EmotionalState


class FakeSettings:
    openai_api_key = ""
    openai_model = "fake-model"


class FakeResponseMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeResponseMessage(content)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    async def create(self, model: str, temperature: float, messages: list[dict[str, str]]) -> FakeResponse:
        return FakeResponse("Here is a model-driven reply.")


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


def test_generate_reply_uses_fallback_without_openai_client() -> None:
    service = LlmService(FakeSettings())
    reply = asyncio.run(
        service.generate_reply(
            user_message="I feel stressed",
            state=EmotionalState(current_mood="calm"),
            rag_context="x",
        )
    )
    assert "keeping this steady" in reply


def test_generate_reply_uses_model_client_when_available() -> None:
    service = LlmService(FakeSettings(), client=FakeClient())
    reply = asyncio.run(
        service.generate_reply(
            user_message="Hello",
            state=EmotionalState(),
            rag_context="state and memory context",
        )
    )
    assert reply == "Here is a model-driven reply."
