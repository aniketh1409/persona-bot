import asyncio

from app.memory_service import MemoryChunk, MemoryService, format_memory_context


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), 0.5, 0.25]


class FakeQdrant:
    def __init__(self) -> None:
        self.exists = False
        self.created = False
        self.last_upsert = None

    async def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    async def create_collection(self, collection_name: str, vectors_config) -> None:
        self.created = True
        self.exists = True

    async def upsert(self, collection_name: str, points, wait: bool) -> None:
        self.last_upsert = {"collection_name": collection_name, "points": points, "wait": wait}

    async def query_points(
        self,
        collection_name: str,
        query,
        query_filter,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ):
        class Point:
            score = 0.91
            payload = {
                "message": "user likes acoustic guitar",
                "tags": ["preference"],
                "created_at": "2026-03-03T00:00:00+00:00",
            }

        class Result:
            points = [Point()]

        return Result()


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
    qdrant = FakeQdrant()
    service = MemoryService(
        qdrant=qdrant,
        embedder=FakeEmbedder(),
        collection_name="test",
        vector_size=3,
    )
    asyncio.run(service.ensure_collection())

    assert qdrant.created is True

    asyncio.run(
        service.store_memory(
            user_id="u1",
            session_id="s1",
            role="user",
            message="I enjoy acoustic guitar at night",
            tags=["preference"],
        )
    )
    assert qdrant.last_upsert is not None

    chunks = asyncio.run(service.recall(user_id="u1", query="music", limit=3))
    assert len(chunks) == 1
    assert chunks[0].text == "user likes acoustic guitar"
    assert chunks[0].tags == ["preference"]


def test_format_memory_context() -> None:
    text = format_memory_context(
        [MemoryChunk(text="user stressed about exams", score=0.87, tags=["stress"], created_at="x")]
    )
    assert "Relevant memories:" in text
    assert "stressed about exams" in text
