"""Service layer for characters and per-user character relationships."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import redis_client
from app.models import Character, CharacterRelationship
from app.schemas import EmotionalState


# ---------------------------------------------------------------------------
# Tier thresholds — trust value determines the tier
# ---------------------------------------------------------------------------

TIER_THRESHOLDS: list[tuple[float, int, str]] = [
    (0.85, 5, "Bonded"),
    (0.70, 4, "Confidant"),
    (0.50, 3, "Companion"),
    (0.30, 2, "Acquaintance"),
    (0.00, 1, "Stranger"),
]


def compute_tier(trust: float) -> tuple[int, str]:
    """Return (tier_number, tier_label) for a given trust value."""
    for threshold, tier, label in TIER_THRESHOLDS:
        if trust >= threshold:
            return tier, label
    return 1, "Stranger"


TIER_CONTEXT: dict[int, str] = {
    1: (
        "Your relationship with this person is brand new — they're a stranger. "
        "Be guarded. Keep things surface-level. You don't owe them anything personal. "
        "Be yourself, but don't open up."
    ),
    2: (
        "You're getting to know this person. They're an acquaintance. "
        "You can share opinions and ask about them, but keep personal history to yourself. "
        "You're warming up, but you're not there yet."
    ),
    3: (
        "This person is becoming a real companion. You trust them enough to reference "
        "past conversations and show some vulnerability. You can be more yourself around them. "
        "But your deeper secrets stay locked."
    ),
    4: (
        "This person has earned your trust. They're a confidant. "
        "You can share things from your past, reveal vulnerabilities, and let them see "
        "the real you. If you have backstory or secrets, you can start hinting at them "
        "or sharing them when it feels natural."
    ),
    5: (
        "This person is bonded to you. You trust them completely. "
        "Nothing is off-limits. You can share your deepest thoughts, fears, and memories. "
        "Reference your history together. Be fully authentic — no walls."
    ),
}


class CharacterService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- Character CRUD ---------------------------------------------------

    async def list_characters(self) -> list[Character]:
        stmt = select(Character).order_by(Character.is_default.desc(), Character.name.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_character(self, character_id: str) -> Character | None:
        return await self.db.get(Character, character_id)

    async def resolve_character(self, character_id: str | None) -> Character:
        if character_id:
            char = await self.db.get(Character, character_id)
            if char is not None:
                return char

        # Fall back to default
        stmt = select(Character).where(Character.is_default.is_(True)).limit(1)
        result = await self.db.execute(stmt)
        default = result.scalars().first()
        if default is not None:
            return default

        # Last resort: first character
        stmt = select(Character).order_by(Character.name.asc()).limit(1)
        result = await self.db.execute(stmt)
        first = result.scalars().first()
        if first is None:
            raise RuntimeError("No characters found in database.")
        return first

    # -- Relationship management ------------------------------------------

    async def load_relationship(
        self,
        user_id: str,
        character_id: str,
    ) -> CharacterRelationship:
        """Load or create a relationship for a user+character pair."""
        # Try Redis cache first
        cache_key = self._rel_cache_key(user_id, character_id)
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            # Still need the DB row for writes, but we can construct a detached snapshot
            rel = await self._get_or_create_relationship(user_id, character_id)
            rel.trust = data["trust"]
            rel.affection = data["affection"]
            rel.energy = data["energy"]
            rel.current_mood = data["current_mood"]
            rel.baseline_mood = data["baseline_mood"]
            rel.tier = data["tier"]
            rel.message_count = data["message_count"]
            return rel

        rel = await self._get_or_create_relationship(user_id, character_id)
        await self._cache_relationship(rel)
        return rel

    async def save_relationship(self, rel: CharacterRelationship) -> None:
        """Persist relationship to DB and cache."""
        rel.tier = compute_tier(rel.trust)[0]
        rel.last_active_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self._cache_relationship(rel)

    async def increment_message_count(self, rel: CharacterRelationship) -> None:
        rel.message_count += 1
        rel.last_active_at = datetime.now(timezone.utc)
        await self.db.flush()

    def to_emotional_state(self, rel: CharacterRelationship) -> EmotionalState:
        """Convert a relationship into the EmotionalState schema used by state engine."""
        return EmotionalState(
            baseline_mood=rel.baseline_mood,
            current_mood=rel.current_mood,
            affection=rel.affection,
            trust=rel.trust,
            energy=rel.energy,
        )

    def apply_state_update(self, rel: CharacterRelationship, state: EmotionalState) -> None:
        """Write state engine output back into the relationship row."""
        rel.trust = state.trust
        rel.affection = state.affection
        rel.energy = state.energy
        rel.current_mood = state.current_mood
        rel.tier = compute_tier(state.trust)[0]

    def get_tier_context(self, tier: int) -> str:
        """Return the tier-specific context string for the LLM prompt."""
        return TIER_CONTEXT.get(tier, TIER_CONTEXT[1])

    # -- Relationship listing for frontend --------------------------------

    async def list_relationships(self, user_id: str) -> list[CharacterRelationship]:
        stmt = (
            select(CharacterRelationship)
            .where(CharacterRelationship.user_id == user_id)
            .order_by(CharacterRelationship.last_active_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # -- Private helpers --------------------------------------------------

    async def _get_or_create_relationship(
        self,
        user_id: str,
        character_id: str,
    ) -> CharacterRelationship:
        stmt = select(CharacterRelationship).where(
            CharacterRelationship.user_id == user_id,
            CharacterRelationship.character_id == character_id,
        )
        result = await self.db.execute(stmt)
        rel = result.scalars().first()
        if rel is not None:
            return rel

        # Create with character's starting values
        char = await self.db.get(Character, character_id)
        if char is None:
            raise RuntimeError(f"Character {character_id!r} not found.")

        rel = CharacterRelationship(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_id=character_id,
            trust=char.starting_trust,
            affection=char.starting_affection,
            energy=char.starting_energy,
            current_mood=char.baseline_mood,
            baseline_mood=char.baseline_mood,
            tier=compute_tier(char.starting_trust)[0],
            message_count=0,
        )
        self.db.add(rel)
        await self.db.flush()
        return rel

    async def _cache_relationship(self, rel: CharacterRelationship) -> None:
        cache_key = self._rel_cache_key(rel.user_id, rel.character_id)
        data = {
            "trust": rel.trust,
            "affection": rel.affection,
            "energy": rel.energy,
            "current_mood": rel.current_mood,
            "baseline_mood": rel.baseline_mood,
            "tier": rel.tier,
            "message_count": rel.message_count,
        }
        await redis_client.set(cache_key, json.dumps(data), ex=60 * 60 * 6)

    @staticmethod
    def _rel_cache_key(user_id: str, character_id: str) -> str:
        return f"rel:{user_id}:{character_id}"
