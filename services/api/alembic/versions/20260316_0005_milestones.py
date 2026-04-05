"""Add milestone tracking tables and seed baseline milestones."""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


MILESTONES = [
    {
        "id": "kael_confidant",
        "character_id": "kael",
        "title": "Kael Opens Up",
        "description": "Reached Confidant tier with Kael.",
        "icon": "🗝️",
        "trust_threshold": 0.70,
        "affection_threshold": 0.30,
        "tier_threshold": 4,
    },
    {
        "id": "lyra_confidant",
        "character_id": "lyra",
        "title": "Lyra Gets Real",
        "description": "Reached Confidant tier with Lyra.",
        "icon": "💫",
        "trust_threshold": 0.65,
        "affection_threshold": 0.70,
        "tier_threshold": 4,
    },
    {
        "id": "vex_confidant",
        "character_id": "vex",
        "title": "Vex Slows Down",
        "description": "Reached Confidant tier with Vex.",
        "icon": "⚡",
        "trust_threshold": 0.70,
        "affection_threshold": 0.45,
        "tier_threshold": 4,
    },
]


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("icon", sa.String(16), server_default="*"),
        sa.Column("trust_threshold", sa.Float, server_default="0.0"),
        sa.Column("affection_threshold", sa.Float, server_default="0.0"),
        sa.Column("tier_threshold", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_milestones_character", "milestones", ["character_id"])

    op.create_table(
        "user_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("milestone_id", sa.String(64), sa.ForeignKey("milestones.id"), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "milestone_id", name="uq_user_milestone"),
    )
    op.create_index("ix_user_milestones_user", "user_milestones", ["user_id"])

    milestones = sa.table(
        "milestones",
        sa.column("id", sa.String),
        sa.column("character_id", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("icon", sa.String),
        sa.column("trust_threshold", sa.Float),
        sa.column("affection_threshold", sa.Float),
        sa.column("tier_threshold", sa.Integer),
    )
    op.bulk_insert(milestones, MILESTONES)


def downgrade() -> None:
    op.drop_index("ix_user_milestones_user", table_name="user_milestones")
    op.drop_table("user_milestones")
    op.drop_index("ix_milestones_character", table_name="milestones")
    op.drop_table("milestones")
