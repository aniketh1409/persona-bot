import asyncio

from app.llm_service import LlmService
from app.schemas import EmotionalState


class FakeSettings:
    llm_provider = "openai"
    openai_api_key = ""
    openai_model = "fake-model"
    ollama_base_url = "http://localhost:11434"
    ollama_chat_model = "llama3.2:3b"


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


class FakeOllamaResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeOllamaHttpClient:
    def stream(self, method: str, path: str, json: dict):
        _ = (method, path, json)
        return FakeOllamaResponse(
            [
                '{"message":{"role":"assistant","content":"hey "},"done":false}',
                '{"message":{"role":"assistant","content":"there"},"done":false}',
                '{"done":true}',
            ]
        )


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


def test_ollama_stream_reply_yields_chunks() -> None:
    class OllamaSettings(FakeSettings):
        llm_provider = "ollama"

    async def run_stream() -> list[str]:
        service = LlmService(OllamaSettings(), http_client=FakeOllamaHttpClient())
        chunks: list[str] = []
        async for chunk in service.stream_reply(
            user_message="Hello",
            state=EmotionalState(),
            rag_context="state and memory context",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run_stream())
    assert chunks == ["hey ", "there"]


def test_build_prompts_adds_grounding_rules() -> None:
    system_prompt, user_prompt = LlmService._build_prompts(
        user_message="im tired and unloveable",
        rag_context="Recent conversation:\nuser: im tired",
        persona_name="Balanced",
        persona_system_prompt="stay casual",
        persona_style_prompt="keep it short",
    )

    assert "Do not invent experiences" in system_prompt
    assert "Your name is Balanced" in system_prompt
    assert "You are NOT the user" in system_prompt
    assert "im tired and unloveable" in user_prompt
    assert "Balanced, the user says:" in user_prompt


def test_build_prompts_includes_tier_and_backstory() -> None:
    system_prompt, _ = LlmService._build_prompts(
        user_message="hey",
        rag_context="context",
        persona_name="Kael",
        persona_system_prompt="You are Kael.",
        persona_style_prompt="short sentences",
        tier_context="This person is a confidant.",
        backstory_context="You once failed a student.",
    )

    assert "Relationship level:" in system_prompt
    assert "This person is a confidant." in system_prompt
    assert "Personal history" in system_prompt
    assert "You once failed a student." in system_prompt
