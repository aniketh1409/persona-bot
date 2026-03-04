import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.config import Settings

MEMORY_TAG_RULES: dict[str, set[str]] = {
    "stress": {"stressed", "stress", "anxious", "overwhelmed", "midterm", "exam", "deadline"},
    "preference": {"like", "love", "prefer", "favorite", "enjoy"},
    "trigger": {"insecure", "worried", "afraid", "panic", "embarrassed"},
    "goal": {"goal", "plan", "trying to", "improve", "learn", "build"},
}


class EmbeddingClient(Protocol):
    async def embed(self, text: str) -> list[float]:
        """Return embedding vector for input text."""


class OpenAIEmbeddingClient:
    def __init__(self, settings: "Settings") -> None:
        from openai import AsyncOpenAI  # Lazy import keeps tests independent of optional local installs.

        self.model = settings.openai_embedding_model
        self._client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        response = await self._client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding


@dataclass(frozen=True)
class MemoryChunk:
    text: str
    score: float
    tags: list[str]
    created_at: str


class MemoryService:
    def __init__(
        self,
        *,
        qdrant: Any,
        embedder: EmbeddingClient,
        collection_name: str,
        vector_size: int,
    ) -> None:
        self.qdrant = qdrant
        self.embedder = embedder
        self.collection_name = collection_name
        self.vector_size = vector_size

    async def ensure_collection(self) -> None:
        exists = await self.qdrant.collection_exists(collection_name=self.collection_name)
        if exists:
            return

        try:
            from qdrant_client.http.models import Distance, VectorParams

            vectors_config: Any = VectorParams(size=self.vector_size, distance=Distance.COSINE)
        except ModuleNotFoundError:
            vectors_config = {"size": self.vector_size, "distance": "Cosine"}

        await self.qdrant.create_collection(
            collection_name=self.collection_name,
            vectors_config=vectors_config,
        )

    def extract_tags(self, message: str) -> list[str]:
        lowered = message.lower()
        tags: list[str] = []
        for tag, keywords in MEMORY_TAG_RULES.items():
            if any(keyword in lowered for keyword in keywords):
                tags.append(tag)
        return tags

    def should_index_memory(self, role: str, message: str, tags: list[str]) -> bool:
        if role != "user":
            return False
        if tags:
            return True
        return len(message) >= 80

    async def store_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        message: str,
        tags: list[str],
        created_at: datetime | None = None,
    ) -> None:
        embedding = await self.embedder.embed(message)
        timestamp = created_at or datetime.now(timezone.utc)

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "message": message,
            "tags": tags,
            "created_at": timestamp.isoformat(),
        }
        try:
            from qdrant_client.http.models import PointStruct

            point: Any = PointStruct(id=str(uuid.uuid4()), vector=embedding, payload=payload)
        except ModuleNotFoundError:
            point = {"id": str(uuid.uuid4()), "vector": embedding, "payload": payload}

        await self.qdrant.upsert(collection_name=self.collection_name, points=[point], wait=False)

    async def recall(
        self,
        *,
        user_id: str,
        query: str,
        tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[MemoryChunk]:
        embedding = await self.embedder.embed(query)

        try:
            from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue

            must_filters: list[Any] = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            if tags:
                must_filters.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
            query_filter: Any = Filter(must=must_filters)
        except ModuleNotFoundError:
            must_filters = [{"key": "user_id", "match": {"value": user_id}}]
            if tags:
                must_filters.append({"key": "tags", "match": {"any": tags}})
            query_filter = {"must": must_filters}

        results = await self.qdrant.query_points(
            collection_name=self.collection_name,
            query=embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        chunks: list[MemoryChunk] = []
        for point in results.points:
            payload = point.payload or {}
            chunks.append(
                MemoryChunk(
                    text=str(payload.get("message", "")),
                    score=float(point.score or 0.0),
                    tags=[str(tag) for tag in payload.get("tags", [])],
                    created_at=str(payload.get("created_at", "")),
                )
            )
        return chunks


def format_memory_context(memories: list[MemoryChunk]) -> str:
    if not memories:
        return "No relevant long-term memory."

    lines = ["Relevant memories:"]
    for memory in memories:
        lines.append(f"- ({memory.score:.2f}) [{', '.join(memory.tags) or 'general'}] {memory.text}")
    return "\n".join(lines)
