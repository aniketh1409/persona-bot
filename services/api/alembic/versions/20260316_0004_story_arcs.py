"""Add story_arcs and user_arc_progress tables with initial character arcs."""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


INITIAL_ARCS = [
    {
        "id": "kael_past_failure",
        "character_id": "kael",
        "title": "The One He Couldn't Help",
        "description": "Kael starts opening up about someone he failed to mentor.",
        "context_injection": (
            "Kael is beginning to trust the user enough to hint at a painful memory about a past mentee. "
            "He should reveal this gradually, starting with subtle references, then specifics if the user asks sincerely."
        ),
        "trust_threshold": 0.75,
        "affection_threshold": 0.30,
        "message_count_threshold": 24,
        "sort_order": 10,
    },
    {
        "id": "lyra_hidden_anxiety",
        "character_id": "lyra",
        "title": "Behind the Warmth",
        "description": "Lyra reveals the anxiety she hides behind optimism.",
        "context_injection": (
            "Lyra is ready to admit that her optimism is partly a coping strategy. "
            "She can acknowledge uncertainty and anxiety if the user creates emotional safety."
        ),
        "trust_threshold": 0.65,
        "affection_threshold": 0.80,
        "message_count_threshold": 20,
        "sort_order": 20,
    },
    {
        "id": "vex_mask_of_chaos",
        "character_id": "vex",
        "title": "The Mask of Noise",
        "description": "Vex drops the chaotic act and talks honestly about fear of being ordinary.",
        "context_injection": (
            "Vex can occasionally pause the chaos and share a grounded, vulnerable line about feeling replaceable. "
            "The reveal should feel surprising but emotionally real."
        ),
        "trust_threshold": 0.70,
        "affection_threshold": 0.45,
        "message_count_threshold": 18,
        "sort_order": 30,
    },
]


def upgrade() -> None:
    op.create_table(
        "story_arcs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("context_injection", sa.Text, nullable=False),
        sa.Column("trust_threshold", sa.Float, server_default="0.0"),
        sa.Column("affection_threshold", sa.Float, server_default="0.0"),
        sa.Column("message_count_threshold", sa.Integer, server_default="0"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_story_arcs_character", "story_arcs", ["character_id"])

    op.create_table(
        "user_arc_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("arc_id", sa.String(64), sa.ForeignKey("story_arcs.id"), nullable=False),
        sa.Column("status", sa.String(16), server_default="locked"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "arc_id", name="uq_user_arc"),
    )
    op.create_index("ix_user_arc_progress_user", "user_arc_progress", ["user_id"])

    arcs = sa.table(
        "story_arcs",
        sa.column("id", sa.String),
        sa.column("character_id", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("context_injection", sa.Text),
        sa.column("trust_threshold", sa.Float),
        sa.column("affection_threshold", sa.Float),
        sa.column("message_count_threshold", sa.Integer),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(arcs, INITIAL_ARCS)


def downgrade() -> None:
    op.drop_index("ix_user_arc_progress_user", table_name="user_arc_progress")
    op.drop_table("user_arc_progress")
    op.drop_index("ix_story_arcs_character", table_name="story_arcs")
    op.drop_table("story_arcs")
