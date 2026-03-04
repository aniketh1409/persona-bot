"""Initial schema

Revision ID: 20260303_0001
Revises:
Create Date: 2026-03-03 22:36:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260303_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)
    op.create_index("ix_chat_sessions_user_last_active", "chat_sessions", ["user_id", "last_active_at"], unique=False)

    op.create_table(
        "relationship_states",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_mood", sa.String(length=32), nullable=False),
        sa.Column("current_mood", sa.String(length=32), nullable=False),
        sa.Column("affection", sa.Float(), nullable=False),
        sa.Column("trust", sa.Float(), nullable=False),
        sa.Column("energy", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.PrimaryKeyConstraint("session_id"),
    )

    op.create_table(
        "conversation_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_events_session_id", "conversation_events", ["session_id"], unique=False)
    op.create_index("ix_conversation_events_user_id", "conversation_events", ["user_id"], unique=False)
    op.create_index("ix_events_session_created_at", "conversation_events", ["session_id", "created_at"], unique=False)

    op.create_table(
        "chat_turn_metrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("assistant_event_id", sa.String(length=36), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("first_token_ms", sa.Float(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assistant_event_id"], ["conversation_events.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_turn_metrics_session_id", "chat_turn_metrics", ["session_id"], unique=False)
    op.create_index("ix_chat_turn_metrics_user_id", "chat_turn_metrics", ["user_id"], unique=False)
    op.create_index("ix_metrics_session_created_at", "chat_turn_metrics", ["session_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_metrics_session_created_at", table_name="chat_turn_metrics")
    op.drop_index("ix_chat_turn_metrics_user_id", table_name="chat_turn_metrics")
    op.drop_index("ix_chat_turn_metrics_session_id", table_name="chat_turn_metrics")
    op.drop_table("chat_turn_metrics")

    op.drop_index("ix_events_session_created_at", table_name="conversation_events")
    op.drop_index("ix_conversation_events_user_id", table_name="conversation_events")
    op.drop_index("ix_conversation_events_session_id", table_name="conversation_events")
    op.drop_table("conversation_events")

    op.drop_table("relationship_states")

    op.drop_index("ix_chat_sessions_user_last_active", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_table("users")
