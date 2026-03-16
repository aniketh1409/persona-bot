from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

settings = get_settings()

engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
redis_client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)


class LazyQdrantClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self._client: AsyncQdrantClient | None = None

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(url=self.url)
        return self._client

    async def collection_exists(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_client().collection_exists(*args, **kwargs)

    async def create_collection(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_client().create_collection(*args, **kwargs)

    async def upsert(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_client().upsert(*args, **kwargs)

    async def query_points(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_client().query_points(*args, **kwargs)

    async def scroll(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_client().scroll(*args, **kwargs)

    async def aclose(self) -> None:
        if self._client is None:
            return
        close_coro = getattr(self._client, "aclose", None)
        if callable(close_coro):
            await close_coro()
            return
        close_sync = getattr(self._client, "close", None)
        if callable(close_sync):
            close_sync()


qdrant_client = LazyQdrantClient(url=settings.qdrant_url)


async def init_db() -> None:
    if not settings.auto_create_schema:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
