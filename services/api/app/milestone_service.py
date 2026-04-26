"""Milestone unlock logic for character relationships."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CharacterRelationship, Milestone, UserMilestone


class MilestoneService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def unlock_eligible(
        self,
        *,
        user_id: str,
        relationship: CharacterRelationship,
    ) -> list[Milestone]:
        """Unlock any milestones that now meet requirements and return newly unlocked ones."""
        stmt = select(Milestone).where(
            and_(
                Milestone.character_id == relationship.character_id,
                Milestone.trust_threshold <= relationship.trust,
                Milestone.affection_threshold <= relationship.affection,
                Milestone.tier_threshold <= relationship.tier,
            )
        )
        result = await self.db.execute(stmt)
        eligible = list(result.scalars().all())
        if not eligible:
            return []

        existing_stmt = select(UserMilestone.milestone_id).where(
            and_(
                UserMilestone.user_id == user_id,
                UserMilestone.milestone_id.in_([m.id for m in eligible]),
            )
        )
        existing_result = await self.db.execute(existing_stmt)
        unlocked_ids = set(existing_result.scalars().all())

        newly_unlocked: list[Milestone] = []
        for milestone in eligible:
            if milestone.id in unlocked_ids:
                continue
            self.db.add(
                UserMilestone(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    milestone_id=milestone.id,
                    unlocked_at=datetime.now(timezone.utc),
                )
            )
            newly_unlocked.append(milestone)

        if newly_unlocked:
            await self.db.flush()
        return newly_unlocked

    async def list_user_milestones(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[tuple[Milestone, UserMilestone]]:
        stmt = (
            select(Milestone, UserMilestone)
            .join(UserMilestone, UserMilestone.milestone_id == Milestone.id)
            .where(UserMilestone.user_id == user_id)
            .order_by(UserMilestone.unlocked_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.all())
