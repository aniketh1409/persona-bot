import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
from typing import TYPE_CHECKING, Any, Protocol

import httpx

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


class OllamaEmbeddingClient:
    def __init__(self, settings: "Settings", http_client: httpx.AsyncClient | None = None) -> None:
        self.model = settings.ollama_embedding_model
        self.base_url = settings.ollama_base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(base_url=self.base_url, timeout=60.0)

    async def embed(self, text: str) -> list[float]:
        # Preferred endpoint for recent Ollama versions.
        response = await self._client.post(
            "/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        if response.status_code == 404:
            # Compatibility with older/newer variants using /api/embed.
            response = await self._client.post(
                "/api/embed",
                json={"model": self.model, "input": [text]},
            )
        response.raise_for_status()
        payload = response.json()

        embedding = payload.get("embedding")
        if isinstance(embedding, list):
            return [float(value) for value in embedding]

        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            first = embeddings[0]
            if isinstance(first, list):
                return [float(value) for value in first]

        raise RuntimeError(f"Unexpected embedding payload: {json.dumps(payload)[:200]}")


@dataclass(frozen=True)
class MemoryChunk:
    text: str
    score: float
    tags: list[str]
    created_at: str
    semantic_score: float = 0.0
    importance: float = 0.0
    recency_score: float = 0.0


class MemoryService:
    def __init__(
        self,
        *,
        qdrant: Any,
        embedder: EmbeddingClient,
        collection_name: str,
        vector_size: int,
        candidate_multiplier: int = 4,
        semantic_weight: float = 0.62,
        importance_weight: float = 0.25,
        recency_weight: float = 0.13,
        recency_half_life_hours: float = 72.0,
    ) -> None:
        self.qdrant = qdrant
        self.embedder = embedder
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.candidate_multiplier = max(2, candidate_multiplier)
        self.semantic_weight = semantic_weight
        self.importance_weight = importance_weight
        self.recency_weight = recency_weight
        self.recency_half_life_hours = max(1.0, recency_half_life_hours)

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
        importance = self.compute_importance(message=message, tags=tags)
        if importance >= 0.50:
            return True
        if tags:
            return True
        return len(message) >= 80

    def compute_importance(self, *, message: str, tags: list[str]) -> float:
        lowered = message.lower()
        score = 0.20

        if "trigger" in tags or "stress" in tags:
            score += 0.25
        if "goal" in tags:
            score += 0.20
        if "preference" in tags:
            score += 0.15

        if len(message) > 220:
            score += 0.12
        elif len(message) > 120:
            score += 0.08
        elif len(message) > 80:
            score += 0.04

        if any(token in lowered for token in {" i ", " i'm ", " ive ", " my ", " me "}):
            score += 0.08
        if "because" in lowered or "since" in lowered:
            score += 0.04

        return self._clamp(score)

    async def store_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        message: str,
        tags: list[str],
        created_at: datetime | None = None,
    ) -> bool:
        normalized = self.normalize_message(message)
        text_hash = self.message_hash(normalized)
        if await self._is_duplicate_memory(user_id=user_id, text_hash=text_hash):
            return False

        embedding = await self.embedder.embed(message)
        timestamp = created_at or datetime.now(timezone.utc)
        importance = self.compute_importance(message=message, tags=tags)

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "message": message,
            "tags": tags,
            "created_at": timestamp.isoformat(),
            "importance": importance,
            "text_hash": text_hash,
        }
        try:
            from qdrant_client.http.models import PointStruct

            point: Any = PointStruct(id=str(uuid.uuid4()), vector=embedding, payload=payload)
        except ModuleNotFoundError:
            point = {"id": str(uuid.uuid4()), "vector": embedding, "payload": payload}

        await self.qdrant.upsert(collection_name=self.collection_name, points=[point], wait=False)
        return True

    async def recall(
        self,
        *,
        user_id: str,
        query: str,
        tags: list[str] | None = None,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[MemoryChunk]:
        embedding = await self.embedder.embed(query)
        target_time = now or datetime.now(timezone.utc)

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
            limit=max(limit * self.candidate_multiplier, limit),
            with_payload=True,
            with_vectors=False,
        )

        reranked: list[MemoryChunk] = []
        for point in results.points:
            payload = point.payload or {}
            text = str(payload.get("message", ""))
            payload_tags = [str(tag) for tag in payload.get("tags", [])]
            created_at = str(payload.get("created_at", ""))
            semantic_score = float(point.score or 0.0)
            importance = float(payload.get("importance") or self.compute_importance(message=text, tags=payload_tags))
            recency_score = self.compute_recency_score(created_at=created_at, now=target_time)
            score = self.combine_scores(
                semantic_score=semantic_score,
                importance=importance,
                recency_score=recency_score,
            )

            reranked.append(
                MemoryChunk(
                    text=text,
                    score=score,
                    tags=payload_tags,
                    created_at=created_at,
                    semantic_score=semantic_score,
                    importance=importance,
                    recency_score=recency_score,
                )
            )

        deduped = self._dedupe_memories(reranked)
        deduped.sort(key=lambda item: item.score, reverse=True)
        return deduped[:limit]

    def normalize_message(self, message: str) -> str:
        collapsed = re.sub(r"\s+", " ", message.lower().strip())
        alnum = re.sub(r"[^a-z0-9 ]+", "", collapsed)
        return alnum.strip()

    @staticmethod
    def message_hash(normalized_message: str) -> str:
        import hashlib

        return hashlib.sha1(normalized_message.encode("utf-8")).hexdigest()

    def compute_recency_score(self, *, created_at: str, now: datetime) -> float:
        parsed = self.parse_datetime(created_at)
        if parsed is None:
            return 0.5

        age_hours = max((now - parsed).total_seconds() / 3600.0, 0.0)
        return self._clamp(0.5 ** (age_hours / self.recency_half_life_hours))

    def combine_scores(self, *, semantic_score: float, importance: float, recency_score: float) -> float:
        combined = (
            semantic_score * self.semantic_weight
            + importance * self.importance_weight
            + recency_score * self.recency_weight
        )
        return self._clamp(combined)

    @staticmethod
    def parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    async def _is_duplicate_memory(self, *, user_id: str, text_hash: str) -> bool:
        if not hasattr(self.qdrant, "scroll"):
            return False

        try:
            try:
                from qdrant_client.http.models import FieldCondition, Filter, MatchValue

                scroll_filter: Any = Filter(
                    must=[
                        FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                        FieldCondition(key="text_hash", match=MatchValue(value=text_hash)),
                    ]
                )
            except ModuleNotFoundError:
                scroll_filter = {
                    "must": [
                        {"key": "user_id", "match": {"value": user_id}},
                        {"key": "text_hash", "match": {"value": text_hash}},
                    ]
                }

            scrolled = await self.qdrant.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
            if isinstance(scrolled, tuple):
                points = scrolled[0]
            else:
                points = getattr(scrolled, "points", [])
            return bool(points)
        except Exception:
            return False

    def _dedupe_memories(self, memories: list[MemoryChunk]) -> list[MemoryChunk]:
        by_key: dict[str, MemoryChunk] = {}
        for memory in sorted(memories, key=lambda item: item.score, reverse=True):
            normalized = self.normalize_message(memory.text)
            dedupe_key = self.message_hash(normalized)
            if dedupe_key not in by_key:
                by_key[dedupe_key] = memory
        return list(by_key.values())

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        if math.isnan(value):
            return low
        return max(low, min(high, value))


def format_memory_context(memories: list[MemoryChunk]) -> str:
    if not memories:
        return "No relevant long-term memory."

    lines = ["Relevant memories:"]
    for memory in memories:
        lines.append(f"- ({memory.score:.2f}) [{', '.join(memory.tags) or 'general'}] {memory.text}")
    return "\n".join(lines)
