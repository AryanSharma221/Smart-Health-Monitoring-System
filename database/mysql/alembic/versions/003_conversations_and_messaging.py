"""Add Conversations Table and Extend Messages with Conversation & Idempotency Keys

Revision ID: 003_conversations_and_messaging
Revises: 002_analytics_outbox
Create Date: 2026-10-13 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_conversations_and_messaging"
down_revision: Union[str, None] = "002_analytics_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create conversations table
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(64), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(32),
            sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            sa.String(32),
            sa.ForeignKey("doctor_profiles.doctor_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("patient_id", "doctor_id", name="uq_conversations_patient_doctor"),
    )
    op.create_index("idx_conversations_patient", "conversations", ["patient_id"])
    op.create_index("idx_conversations_doctor", "conversations", ["doctor_id"])
    op.create_index("idx_conversations_updated", "conversations", ["updated_at"])

    # 2. Add conversation_id and idempotency_key to messages table
    op.add_column(
        "messages",
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
    )
    op.create_index(
        "idx_messages_conversation_time",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "idx_messages_conversation_unread",
        "messages",
        ["conversation_id", "is_read", "receiver_id"],
    )
    op.create_index(
        "uq_messages_sender_idempotency",
        "messages",
        ["sender_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_messages_sender_idempotency", table_name="messages")
    op.drop_index("idx_messages_conversation_unread", table_name="messages")
    op.drop_index("idx_messages_conversation_time", table_name="messages")
    op.drop_column("messages", "idempotency_key")
    op.drop_column("messages", "conversation_id")
    op.drop_index("idx_conversations_updated", table_name="conversations")
    op.drop_index("idx_conversations_doctor", table_name="conversations")
    op.drop_index("idx_conversations_patient", table_name="conversations")
    op.drop_table("conversations")
