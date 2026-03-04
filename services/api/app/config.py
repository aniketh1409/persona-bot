from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    auto_create_schema: bool = False

    postgres_dsn: str = "postgresql+asyncpg://personabot:personabot@localhost:5432/personabot"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "persona_memories"
    qdrant_vector_size: int = 1536
    memory_top_k: int = 5
    memory_candidate_multiplier: int = 4
    memory_semantic_weight: float = 0.62
    memory_importance_weight: float = 0.25
    memory_recency_weight: float = 0.13
    memory_recency_half_life_hours: float = 72.0
    default_persona_id: str = "balanced"

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"


@lru_cache
def get_settings() -> Settings:
    return Settings()
