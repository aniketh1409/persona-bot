"""Story arc activation and context selection service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CharacterRelationship, StoryArc, UserArcProgress


class ArcService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_arcs_for_character(self, character_id: str) -> list[StoryArc]:
        stmt = (
            select(StoryArc)
            .where(StoryArc.character_id == character_id)
            .order_by(StoryArc.sort_order.asc(), StoryArc.id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def evaluate_arc_statuses(
        self,
        *,
        user_id: str,
        relationship: CharacterRelationship,
    ) -> list[tuple[StoryArc, str]]:
        """Return list of (arc, status) and persist status transitions."""
        arcs = await self.list_arcs_for_character(relationship.character_id)
        if not arcs:
            return []

        progress_by_arc: dict[str, UserArcProgress] = {}
        stmt = select(UserArcProgress).where(
            UserArcProgress.user_id == user_id,
            UserArcProgress.arc_id.in_([arc.id for arc in arcs]),
        )
        result = await self.db.execute(stmt)
        for row in result.scalars().all():
            progress_by_arc[row.arc_id] = row

        snapshots: list[tuple[StoryArc, str]] = []
        for arc in arcs:
            progress = progress_by_arc.get(arc.id)
            should_activate = (
                relationship.trust >= arc.trust_threshold
                and relationship.affection >= arc.affection_threshold
                and relationship.message_count >= arc.message_count_threshold
            )

            status = "active" if should_activate else "locked"
            if progress is None:
                progress = UserArcProgress(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    arc_id=arc.id,
                    status=status,
                    activated_at=datetime.now(timezone.utc) if status == "active" else None,
                )
                self.db.add(progress)
            else:
                if progress.status != status:
                    progress.status = status
                    if status == "active" and progress.activated_at is None:
                        progress.activated_at = datetime.now(timezone.utc)

            snapshots.append((arc, status))

        await self.db.flush()
        return snapshots

    async def active_arc_context(
        self,
        *,
        user_id: str,
        relationship: CharacterRelationship,
    ) -> str:
        snapshots = await self.evaluate_arc_statuses(user_id=user_id, relationship=relationship)
        active = [arc.context_injection for arc, status in snapshots if status == "active"]
        return "\n\n".join(active)
