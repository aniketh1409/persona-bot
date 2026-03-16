from contextlib import asynccontextmanager
from dataclasses import dataclass, field

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
    persona_id: str = "kael"
    character_id: str | None = "kael"
    message_count: int = 0


@dataclass
class FakeEvent:
    id: str


@dataclass
class FakeCharacter:
    id: str
    name: str
    archetype: str = ""
    description: str = ""
    backstory: str = ""
    system_prompt: str = ""
    style_prompt: str = ""
    temperature: float = 0.7
    starting_trust: float = 0.5
    starting_affection: float = 0.5
    starting_energy: float = 0.6
    baseline_mood: str = "neutral"
    is_default: bool = False


@dataclass
class FakeRelationship:
    id: str = "rel-1"
    user_id: str = ""
    character_id: str = ""
    trust: float = 0.5
    affection: float = 0.5
    energy: float = 0.6
    current_mood: str = "neutral"
    baseline_mood: str = "neutral"
    tier: int = 2
    message_count: int = 0


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

    async def resolve_or_create_session(
        self,
        *,
        user_id: str,
        session_id: str | None,
        persona_id: str,
        character_id: str | None = None,
    ) -> FakeSession:
        session = await self.resolve_session(user_id=user_id, session_id=session_id)
        session.persona_id = persona_id
        session.character_id = character_id
        return session

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


class FakeCharacterService:
    characters = {
        "kael": FakeCharacter("kael", "Kael", is_default=True, system_prompt="system::Kael", style_prompt="style::Kael"),
        "lyra": FakeCharacter("lyra", "Lyra", system_prompt="system::Lyra", style_prompt="style::Lyra"),
        "vex": FakeCharacter("vex", "Vex", system_prompt="system::Vex", style_prompt="style::Vex"),
    }

    def __init__(self, _db) -> None:
        pass

    async def list_characters(self) -> list[FakeCharacter]:
        return [self.characters["kael"], self.characters["lyra"], self.characters["vex"]]

    async def get_character(self, character_id: str) -> FakeCharacter | None:
        return self.characters.get(character_id)

    async def resolve_character(self, character_id: str | None) -> FakeCharacter:
        if character_id and character_id in self.characters:
            return self.characters[character_id]
        return self.characters["kael"]

    async def load_relationship(self, user_id: str, character_id: str) -> FakeRelationship:
        return FakeRelationship(user_id=user_id, character_id=character_id)

    async def save_relationship(self, rel: FakeRelationship) -> None:
        pass

    async def increment_message_count(self, rel: FakeRelationship) -> None:
        rel.message_count += 1

    def to_emotional_state(self, rel: FakeRelationship) -> EmotionalState:
        return EmotionalState(
            baseline_mood=rel.baseline_mood,
            current_mood=rel.current_mood,
            trust=rel.trust,
            affection=rel.affection,
            energy=rel.energy,
        )

    def apply_state_update(self, rel: FakeRelationship, state: EmotionalState) -> None:
        rel.trust = state.trust
        rel.affection = state.affection
        rel.energy = state.energy
        rel.current_mood = state.current_mood

    def get_tier_context(self, tier: int) -> str:
        return f"tier {tier} context"

    async def list_relationships(self, user_id: str) -> list[FakeRelationship]:
        return []


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
        persona_name: str = "Kael",
        persona_system_prompt: str = "",
        persona_style_prompt: str = "",
        persona_temperature: float | None = None,
        memory_hint: str | None = None,
        tier_context: str = "",
        backstory_context: str = "",
    ):
        _ = (
            user_message, state, rag_context, persona_name,
            persona_system_prompt, persona_style_prompt, persona_temperature,
            memory_hint, tier_context, backstory_context,
        )
        yield "token-one "
        yield "token-two"

    async def generate_reply(
        self,
        *,
        user_message: str,
        state: EmotionalState,
        rag_context: str,
        persona_name: str = "Kael",
        persona_system_prompt: str = "",
        persona_style_prompt: str = "",
        persona_temperature: float | None = None,
        memory_hint: str | None = None,
        tier_context: str = "",
        backstory_context: str = "",
    ) -> str:
        _ = (
            user_message, state, rag_context, persona_name,
            persona_system_prompt, persona_style_prompt, persona_temperature,
            memory_hint, tier_context, backstory_context,
        )
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
    monkeypatch.setattr(main_module, "CharacterService", FakeCharacterService)
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
    # character_id should be kael (default)
    assert events[0]["character_id"] == "kael"
    assert events[-1]["character_id"] == "kael"


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


def test_websocket_supports_character_switching(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()

            ws.send_json({"message": "first turn", "character_id": "kael"})
            first_events = _read_until_done(ws)
            first_done = first_events[-1]

            ws.send_json(
                {
                    "message": "second turn",
                    "user_id": first_done["user_id"],
                    "character_id": "lyra",
                }
            )
            second_events = _read_until_done(ws)
            second_done = second_events[-1]

    assert first_done["character_id"] == "kael"
    assert second_done["character_id"] == "lyra"


def test_done_event_includes_tier(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()

            ws.send_json({"message": "hello"})
            events = _read_until_done(ws)

    done = events[-1]
    assert "tier" in done
    assert "tier_label" in done
    assert isinstance(done["tier"], int)


def test_characters_endpoint(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        response = client.get("/characters")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert payload[0]["id"] == "kael"


def test_personas_endpoint_legacy_compat(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        response = client.get("/personas")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3


def test_history_endpoint_returns_events(monkeypatch) -> None:
    _patch_runtime(monkeypatch)

    with TestClient(main_module.app) as client:
        response = client.get("/history/some-session-id?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
