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
    async def create(self, model: str, temperature: float, messages: list[dict[str, str]], stream: bool = False):
        if stream:
            return FakeStream(["Here ", "is ", "a model-driven reply."])
        return FakeResponse("Here is a model-driven reply.")


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


class FakeDelta:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeStreamChoice:
    def __init__(self, content: str) -> None:
        self.delta = FakeDelta(content)


class FakeStreamChunk:
    def __init__(self, content: str) -> None:
        self.choices = [FakeStreamChoice(content)]


class FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        value = self._chunks[self._index]
        self._index += 1
        return FakeStreamChunk(value)


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


def test_stream_reply_yields_multiple_chunks() -> None:
    async def run_stream() -> list[str]:
        service = LlmService(FakeSettings(), client=FakeClient())
        chunks: list[str] = []
        async for chunk in service.stream_reply(
            user_message="Hello",
            state=EmotionalState(),
            rag_context="state and memory context",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run_stream())
    assert chunks == ["Here ", "is ", "a model-driven reply."]
