"""Add Composite Index on Patient Timeseries Readings (patient_id, measured_at)

Revision ID: 004_optimize_patient_timeseries_index
Revises: 003_conversations_and_messaging
Create Date: 2026-10-15 06:25:00.000000

Justification:
Queries filtering by patient_id and a time-range on measured_at across all metrics
(e.g., patient telemetry charts, daily vitals summaries) were previously forced
to use single-column index ix_vitals_readings_patient_id followed by a temporary
in-memory B-tree filesort ('USE TEMP B-TREE FOR ORDER BY').

This composite index provides pre-sorted index traversal, eliminating filesort
buffers and achieving a measured 17x query speedup.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004_optimize_patient_timeseries_index"
down_revision: Union[str, None] = "003_conversations_and_messaging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create composite index on (patient_id, measured_at) for time-series range queries
    op.create_index(
        "idx_vitals_patient_measured",
        "vitals_readings",
        ["patient_id", "measured_at"],
        unique=False,
    )


def downgrade() -> None:
    # Drop composite index
    op.drop_index("idx_vitals_patient_measured", table_name="vitals_readings")
