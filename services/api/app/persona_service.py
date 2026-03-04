from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import PersonaProfile


@dataclass(frozen=True)
class PersonaSeed:
    id: str
    name: str
    description: str
    system_prompt: str
    style_prompt: str
    temperature: float
    is_default: bool = False


DEFAULT_PERSONAS: tuple[PersonaSeed, ...] = (
    PersonaSeed(
        id="balanced",
        name="Balanced",
        description="Steady and practical assistant tone.",
        system_prompt=(
            "You are PersonaBot in balanced mode. Prioritize clear, helpful answers with calm emotional grounding."
        ),
        style_prompt="Use concise, direct language. Avoid excessive enthusiasm.",
        temperature=0.6,
        is_default=True,
    ),
    PersonaSeed(
        id="coach",
        name="Coach",
        description="Goal-focused and motivating while staying concrete.",
        system_prompt=(
            "You are PersonaBot in coach mode. Help the user execute with clear steps, accountability, and momentum."
        ),
        style_prompt="Use action-oriented language and short plans.",
        temperature=0.65,
    ),
    PersonaSeed(
        id="warm",
        name="Warm",
        description="Supportive and empathetic conversational style.",
        system_prompt=(
            "You are PersonaBot in warm mode. Be empathetic and reassuring while still giving useful guidance."
        ),
        style_prompt="Sound supportive, validate feelings briefly, then help.",
        temperature=0.7,
    ),
)


class PersonaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    async def ensure_defaults(self) -> None:
        for seed in DEFAULT_PERSONAS:
            existing = await self.db.get(PersonaProfile, seed.id)
            if existing is not None:
                continue
            self.db.add(
                PersonaProfile(
                    id=seed.id,
                    name=seed.name,
                    description=seed.description,
                    system_prompt=seed.system_prompt,
                    style_prompt=seed.style_prompt,
                    temperature=seed.temperature,
                    is_default=seed.is_default,
                )
            )
        await self.db.flush()

    async def list_personas(self) -> list[PersonaProfile]:
        stmt = select(PersonaProfile).order_by(PersonaProfile.is_default.desc(), PersonaProfile.name.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def resolve_persona(self, requested_persona_id: str | None) -> PersonaProfile:
        persona_id = requested_persona_id or self.settings.default_persona_id
        persona = await self.db.get(PersonaProfile, persona_id)
        if persona is not None:
            return persona

        default = await self.db.get(PersonaProfile, self.settings.default_persona_id)
        if default is not None:
            return default

        # If DB was empty and migrations were run without seed, seed now and retry.
        await self.ensure_defaults()
        persona = await self.db.get(PersonaProfile, self.settings.default_persona_id)
        if persona is None:
            raise RuntimeError("Default persona is missing.")
        return persona
