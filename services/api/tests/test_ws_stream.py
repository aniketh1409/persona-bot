from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.schemas import EmotionalState
from app import main as main_module


@dataclass
class FakeUser:
    id: str


@dataclass
class FakeSession:
    id: str
    user_id: str
    message_count: int = 0


@dataclass
class FakeEvent:
    id: str


class FakeSessionService:
    sessions: dict[str, FakeSession] = {}
    users: dict[str, FakeUser] = {}
    session_creations: int = 0
    last_session_id: int = 0
    last_user_id: int = 0

    def __init__(self, _db) -> None:
        pass

    async def resolve_user(self, user_id: str | None) -> FakeUser:
        if user_id and user_id in self.users:
            return self.users[user_id]
        if user_id:
            user = FakeUser(id=user_id)
            self.users[user.id] = user
            return user

        self.__class__.last_user_id += 1
        user = FakeUser(id=f"user-{self.last_user_id}")
        self.users[user.id] = user
        return user

    async def resolve_session(self, user_id: str, session_id: str | None) -> FakeSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        if session_id:
            session = FakeSession(id=session_id, user_id=user_id)
            self.sessions[session.id] = session
            self.__class__.session_creations += 1
            return session

        self.__class__.last_session_id += 1
        session = FakeSession(id=f"session-{self.last_session_id}", user_id=user_id)
        self.sessions[session.id] = session
        self.__class__.session_creations += 1
        return session

    async def load_state(self, _session_id: str) -> EmotionalState:
        return EmotionalState()

    async def append_event(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        message: str,
        sentiment_score: float,
    ) -> FakeEvent:
        return FakeEvent(id=f"evt-{session_id}-{role}")

    async def increment_message_count(self, session: FakeSession) -> FakeSession:
        session.message_count += 1
        return session

    async def save_state(self, session_id: str, state: EmotionalState) -> None:
        _ = (session_id, state)

    async def recent_events(self, session_id: str, limit: int = 12) -> list[object]:
        _ = (session_id, limit)
        return []

    async def save_turn_metric(
        self,
        *,
        session_id: str,
        user_id: str,
        assistant_event_id: str | None,
        latency_ms: float,
        first_token_ms: float | None,
        chunk_count: int,
    ) -> None:
        _ = (session_id, user_id, assistant_event_id, latency_ms, first_token_ms, chunk_count)


class FakeMemoryService:
    def extract_tags(self, message: str) -> list[str]:
        _ = message
        return []

    def should_index_memory(self, role: str, message: str, tags: list[str]) -> bool:
        _ = (role, message, tags)
        return False

    async def store_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        message: str,
        tags: list[str],
    ) -> None:
        _ = (user_id, session_id, role, message, tags)

    async def recall(self, *, user_id: str, query: str, tags: list[str] | None = None, limit: int = 5) -> list:
        _ = (user_id, query, tags, limit)
        return []


class FakeLlmService:
    async def stream_reply(
        self,
        *,
        user_message: str,
        state: EmotionalState,
        rag_context: str,
        memory_hint: str | None = None,
    ):
        _ = (user_message, state, rag_context, memory_hint)
        yield "token-one "
        yield "token-two"

    async def generate_reply(
        self,
        *,
        user_message: str,
        state: EmotionalState,
        rag_context: str,
        memory_hint: str | None = None,
    ) -> str:
        _ = (user_message, state, rag_context, memory_hint)
        return "token-one token-two"


@asynccontextmanager
async def fake_db_session():
    yield object()


def _read_until_done(ws) -> list[dict]:
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == "done":
            return events


def _patch_runtime(monkeypatch) -> None:
    FakeSessionService.sessions = {}
    FakeSessionService.users = {}
    FakeSessionService.session_creations = 0
    FakeSessionService.last_session_id = 0
    FakeSessionService.last_user_id = 0

    monkeypatch.setattr(main_module, "db_session", fake_db_session)
    monkeypatch.setattr(main_module, "SessionService", FakeSessionService)
    monkeypatch.setattr(main_module, "memory_service", FakeMemoryService())
    monkeypatch.setattr(main_module, "llm_service", FakeLlmService())


def test_websocket_stream_event_order(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            system_event = ws.receive_json()
            assert system_event["type"] == "system"

            ws.send_json({"message": "hello there"})
            events = _read_until_done(ws)

    event_types = [event["type"] for event in events]
    assert event_types[0] == "meta"
    assert event_types[-1] == "done"
    assert event_types.count("token") >= 1
    assert events[-1]["chunk_count"] == 2


def test_websocket_preserves_user_and_session_ids(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()

            ws.send_json({"message": "first turn"})
            first_events = _read_until_done(ws)
            first_done = first_events[-1]

            ws.send_json(
                {
                    "message": "second turn",
                    "user_id": first_done["user_id"],
                    "session_id": first_done["session_id"],
                }
            )
            second_events = _read_until_done(ws)
            second_done = second_events[-1]

    assert first_done["user_id"] == second_done["user_id"]
    assert first_done["session_id"] == second_done["session_id"]
    assert FakeSessionService.session_creations == 1
