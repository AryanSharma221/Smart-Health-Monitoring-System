"""Add Analytics Outbox Table and Alert Event-Rule Unique Constraint

Revision ID: 002_analytics_outbox
Revises: 001_initial_schema
Create Date: 2026-10-13 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_analytics_outbox"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create analytics_outbox table
    op.create_table(
        "analytics_outbox",
        sa.Column("outbox_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_outbox_status"),
        sa.CheckConstraint("event_type IN ('telemetry_event', 'alert_event')", name="ck_outbox_event_type"),
    )
    op.create_index("idx_outbox_status_created", "analytics_outbox", ["status", "created_at"])
    op.create_index("idx_outbox_aggregate", "analytics_outbox", ["event_type", "aggregate_id"])

    # 2. Add Unique Constraint on alerts (event_id, rule_id)
    try:
        op.create_unique_constraint("uq_alerts_event_rule", "alerts", ["event_id", "rule_id"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_constraint("uq_alerts_event_rule", "alerts", type_="unique")
    except Exception:
        pass
    op.drop_index("idx_outbox_aggregate", table_name="analytics_outbox")
    op.drop_index("idx_outbox_status_created", table_name="analytics_outbox")
    op.drop_table("analytics_outbox")
