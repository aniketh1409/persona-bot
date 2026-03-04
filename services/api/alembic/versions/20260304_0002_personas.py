"""Add persona profiles

Revision ID: 20260304_0002
Revises: 20260303_0001
Create Date: 2026-03-04 10:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260304_0002"
down_revision: Union[str, None] = "20260303_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persona_profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("style_prompt", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.bulk_insert(
        sa.table(
            "persona_profiles",
            sa.column("id", sa.String(length=64)),
            sa.column("name", sa.String(length=80)),
            sa.column("description", sa.Text()),
            sa.column("system_prompt", sa.Text()),
            sa.column("style_prompt", sa.Text()),
            sa.column("temperature", sa.Float()),
            sa.column("is_default", sa.Boolean()),
        ),
        [
            {
                "id": "balanced",
                "name": "Balanced",
                "description": "Steady and practical assistant tone.",
                "system_prompt": (
                    "You are PersonaBot in balanced mode. Prioritize clear, helpful answers with calm emotional grounding."
                ),
                "style_prompt": "Use concise, direct language. Avoid excessive enthusiasm.",
                "temperature": 0.6,
                "is_default": True,
            },
            {
                "id": "coach",
                "name": "Coach",
                "description": "Goal-focused and motivating while staying concrete.",
                "system_prompt": (
                    "You are PersonaBot in coach mode. Help the user execute with clear steps, accountability, and momentum."
                ),
                "style_prompt": "Use action-oriented language and short plans.",
                "temperature": 0.65,
                "is_default": False,
            },
            {
                "id": "warm",
                "name": "Warm",
                "description": "Supportive and empathetic conversational style.",
                "system_prompt": (
                    "You are PersonaBot in warm mode. Be empathetic and reassuring while still giving useful guidance."
                ),
                "style_prompt": "Sound supportive, validate feelings briefly, then help.",
                "temperature": 0.7,
                "is_default": False,
            },
        ],
    )

    op.add_column("chat_sessions", sa.Column("persona_id", sa.String(length=64), nullable=True))
    op.execute("UPDATE chat_sessions SET persona_id = 'balanced' WHERE persona_id IS NULL")
    op.alter_column("chat_sessions", "persona_id", nullable=False)
    op.create_foreign_key(
        "fk_chat_sessions_persona_id_persona_profiles",
        "chat_sessions",
        "persona_profiles",
        ["persona_id"],
        ["id"],
    )
    op.create_index("ix_chat_sessions_persona_id", "chat_sessions", ["persona_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_persona_id", table_name="chat_sessions")
    op.drop_constraint("fk_chat_sessions_persona_id_persona_profiles", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "persona_id")
    op.drop_table("persona_profiles")
