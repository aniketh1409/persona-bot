import asyncio
from datetime import datetime, timezone

from app.memory_service import MemoryChunk, MemoryService, format_memory_context


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), 0.5, 0.25]


class FakeQdrant:
    def __init__(self, *, query_items: list[dict] | None = None) -> None:
        self.exists = False
        self.created = False
        self.last_upsert = None
        self.query_items = query_items or []
        self._stored_hashes: set[tuple[str, str]] = set()

    async def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    async def create_collection(self, collection_name: str, vectors_config) -> None:
        self.created = True
        self.exists = True

    async def upsert(self, collection_name: str, points, wait: bool) -> None:
        self.last_upsert = {"collection_name": collection_name, "points": points, "wait": wait}
        for point in points:
            payload = self._extract_payload(point)
            self._stored_hashes.add((str(payload.get("user_id", "")), str(payload.get("text_hash", ""))))

    async def scroll(
        self,
        collection_name: str,
        scroll_filter,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ):
        _ = (collection_name, limit, with_payload, with_vectors)
        user_id = self._extract_filter_value(scroll_filter, "user_id")
        text_hash = self._extract_filter_value(scroll_filter, "text_hash")
        if (user_id, text_hash) in self._stored_hashes:
            return ([{"id": "existing"}], None)
        return ([], None)

    async def query_points(
        self,
        collection_name: str,
        query,
        query_filter,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ):
        _ = (collection_name, query, query_filter, limit, with_payload, with_vectors)
        points = [self._build_point(item) for item in self.query_items]

        class Result:
            def __init__(self, points) -> None:
                self.points = points

        return Result(points)

    @staticmethod
    def _extract_payload(point) -> dict:
        if hasattr(point, "payload"):
            return point.payload
        if isinstance(point, dict):
            return point.get("payload", {})
        return {}

    @staticmethod
    def _extract_filter_value(scroll_filter, key: str) -> str:
        if isinstance(scroll_filter, dict):
            for condition in scroll_filter.get("must", []):
                if condition.get("key") == key:
                    return str(condition.get("match", {}).get("value", ""))
            return ""

        for condition in getattr(scroll_filter, "must", []) or []:
            if getattr(condition, "key", None) == key:
                match = getattr(condition, "match", None)
                return str(getattr(match, "value", ""))
        return ""

    @staticmethod
    def _build_point(item: dict):
        class Point:
            def __init__(self, score: float, payload: dict) -> None:
                self.score = score
                self.payload = payload

        return Point(score=float(item.get("score", 0.0)), payload=dict(item.get("payload", {})))


def test_extract_tags_finds_multiple_categories() -> None:
    service = MemoryService(
        qdrant=FakeQdrant(),
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )

    tags = service.extract_tags("I am stressed about my exam but I love practicing guitar")
    assert "stress" in tags
    assert "preference" in tags


def test_should_index_memory_only_for_user() -> None:
    service = MemoryService(
        qdrant=FakeQdrant(),
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )

    assert service.should_index_memory("assistant", "anything", ["goal"]) is False
    assert service.should_index_memory("user", "short", []) is False
    assert service.should_index_memory("user", "this sentence has meaningful detail", ["goal"]) is True


def test_store_and_recall_memory() -> None:
    qdrant = FakeQdrant(
        query_items=[
            {
                "score": 0.91,
                "payload": {
                    "message": "user likes acoustic guitar",
                    "tags": ["preference"],
                    "created_at": "2026-03-03T00:00:00+00:00",
                    "importance": 0.8,
                },
            }
        ]
    )
    service = MemoryService(
        qdrant=qdrant,
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )
    asyncio.run(service.ensure_collection())

    assert qdrant.created is True

    stored = asyncio.run(
        service.store_memory(
            user_id="u1",
            session_id="s1",
            role="user",
            message="I enjoy acoustic guitar at night",
            tags=["preference"],
            created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
        )
    )
    assert stored is True
    assert qdrant.last_upsert is not None

    chunks = asyncio.run(service.recall(user_id="u1", query="music", limit=3))
    assert len(chunks) == 1
    assert chunks[0].text == "user likes acoustic guitar"
    assert chunks[0].tags == ["preference"]
    assert 0.0 <= chunks[0].score <= 1.0


def test_store_memory_skips_duplicate_hash() -> None:
    qdrant = FakeQdrant()
    service = MemoryService(
        qdrant=qdrant,
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )

    first = asyncio.run(
        service.store_memory(
            user_id="u1",
            session_id="s1",
            role="user",
            message="I am stressed about my exam",
            tags=["stress"],
            created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
        )
    )
    second = asyncio.run(
        service.store_memory(
            user_id="u1",
            session_id="s1",
            role="user",
            message="I am stressed about my exam!!!",
            tags=["stress"],
            created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
        )
    )

    assert first is True
    assert second is False


def test_recall_dedupes_near_identical_text() -> None:
    qdrant = FakeQdrant(
        query_items=[
            {
                "score": 0.89,
                "payload": {
                    "message": "user likes acoustic guitar",
                    "tags": ["preference"],
                    "created_at": "2026-03-03T09:00:00+00:00",
                    "importance": 0.72,
                },
            },
            {
                "score": 0.88,
                "payload": {
                    "message": "User likes acoustic guitar!!!",
                    "tags": ["preference"],
                    "created_at": "2026-03-03T09:05:00+00:00",
                    "importance": 0.72,
                },
            },
        ]
    )
    service = MemoryService(
        qdrant=qdrant,
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )

    chunks = asyncio.run(
        service.recall(
            user_id="u1",
            query="tell me about guitar",
            limit=5,
            now=datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc),
        )
    )
    assert len(chunks) == 1
    assert "acoustic guitar" in chunks[0].text.lower()


def test_recall_reranks_with_importance_and_recency() -> None:
    qdrant = FakeQdrant(
        query_items=[
            {
                "score": 0.90,
                "payload": {
                    "message": "old generic memory",
                    "tags": [],
                    "created_at": "2026-02-20T08:00:00+00:00",
                    "importance": 0.20,
                },
            },
            {
                "score": 0.82,
                "payload": {
                    "message": "user insecure about hyperpigmentation",
                    "tags": ["trigger"],
                    "created_at": "2026-03-03T07:30:00+00:00",
                    "importance": 0.90,
                },
            },
        ]
    )
    service = MemoryService(
        qdrant=qdrant,
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )

    chunks = asyncio.run(
        service.recall(
            user_id="u1",
            query="skin insecurity",
            limit=2,
            now=datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc),
        )
    )
    assert len(chunks) == 2
    assert chunks[0].text == "user insecure about hyperpigmentation"
    assert chunks[0].importance > chunks[1].importance


def test_format_memory_context() -> None:
    text = format_memory_context(
        [MemoryChunk(text="user stressed about exams", score=0.87, tags=["stress"], created_at="x")]
    )
    assert "Relevant memories:" in text
    assert "stressed about exams" in text
