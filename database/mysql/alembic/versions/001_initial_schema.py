"""Initial MySQL 8 InnoDB Schema

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-10-13 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. import_batches
    op.create_table(
        "import_batches",
        sa.Column("batch_id", sa.String(64), primary_key=True),
        sa.Column("source_name", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_import_batches_status"),
    )

    # 2. users
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("role IN ('patient', 'doctor', 'admin_operator')", name="ck_users_role"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # 3. patient_profiles
    op.create_table(
        "patient_profiles",
        sa.Column("patient_id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(64), nullable=False),
        sa.Column("last_name", sa.String(64), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=True),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("emergency_contact", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", name="uq_patient_user"),
        sa.CheckConstraint("gender IS NULL OR gender IN ('male', 'female', 'other', 'unknown')", name="ck_patient_gender"),
        sa.CheckConstraint("height_cm IS NULL OR height_cm > 0", name="ck_patient_height_positive"),
        sa.CheckConstraint("weight_kg IS NULL OR weight_kg > 0", name="ck_patient_weight_positive"),
    )
    op.create_index("idx_patient_user_id", "patient_profiles", ["user_id"])

    # 4. doctor_profiles
    op.create_table(
        "doctor_profiles",
        sa.Column("doctor_id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(64), nullable=False),
        sa.Column("last_name", sa.String(64), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=False, server_default="General Practice"),
        sa.Column("license_number", sa.String(64), nullable=False),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", name="uq_doctor_user"),
        sa.UniqueConstraint("license_number", name="uq_doctor_license"),
    )
    op.create_index("idx_doctor_user_id", "doctor_profiles", ["user_id"])

    # 5. doctor_patient_assignments
    op.create_table(
        "doctor_patient_assignments",
        sa.Column("doctor_id", sa.String(32), sa.ForeignKey("doctor_profiles.doctor_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("idx_assignments_patient", "doctor_patient_assignments", ["patient_id"])
    op.create_index("idx_assignments_doctor_active", "doctor_patient_assignments", ["doctor_id", "is_active"])

    # 6. ingestion_events
    op.create_table(
        "ingestion_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("batch_id", sa.String(64), sa.ForeignKey("import_batches.batch_id", ondelete="SET NULL"), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("mirror_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("source", "source_event_id", name="uq_events_source_source_event_id"),
        sa.CheckConstraint("mirror_status IN ('pending', 'mirrored', 'failed')", name="ck_events_mirror_status"),
    )
    op.create_index("idx_events_patient_measured", "ingestion_events", ["patient_id", "measured_at"])
    op.create_index("idx_events_mirror_status", "ingestion_events", ["mirror_status"])

    # 7. vitals_readings
    op.create_table(
        "vitals_readings",
        sa.Column("reading_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), sa.ForeignKey("ingestion_events.event_id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(8, 2), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("raw_value", sa.Numeric(8, 2), nullable=False),
        sa.Column("raw_unit", sa.String(16), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False, server_default="valid"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("event_id", "metric_code", name="uq_vitals_event_metric"),
        sa.CheckConstraint("metric_code IN ('heart_rate', 'spo2', 'temperature', 'respiratory_rate', 'bp_systolic', 'bp_diastolic')", name="ck_vitals_metric_code"),
        sa.CheckConstraint("quality_status IN ('valid', 'out_of_range', 'stale', 'suspect')", name="ck_vitals_quality_status"),
    )
    op.create_index("idx_vitals_patient_metric_time", "vitals_readings", ["patient_id", "metric_code", "measured_at"])
    op.create_index("idx_vitals_measured_at", "vitals_readings", ["measured_at"])

    # 8. alert_rules
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(32), primary_key=True),
        sa.Column("metric_code", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(8), nullable=False),
        sa.Column("configured_value", sa.Numeric(8, 2), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_demo_only", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("operator IN ('<', '>', '<=', '>=', '==', '!=')", name="ck_alert_rules_operator"),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_alert_rules_severity"),
    )

    # 9. patient_baselines
    op.create_table(
        "patient_baselines",
        sa.Column("baseline_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(32), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("median_value", sa.Numeric(8, 2), nullable=False),
        sa.Column("mad_value", sa.Numeric(8, 2), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("patient_id", "metric_code", "window_hours", name="uq_patient_metric_window"),
    )
    op.create_index("idx_baselines_patient", "patient_baselines", ["patient_id"])

    # 10. model_assessments
    op.create_table(
        "model_assessments",
        sa.Column("assessment_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(64), sa.ForeignKey("ingestion_events.event_id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("score", sa.Numeric(6, 4), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=True),
        sa.Column("time_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("result IN ('normal', 'anomaly', 'inconclusive')", name="ck_assessments_result"),
    )
    op.create_index("idx_assessments_patient_time", "model_assessments", ["patient_id", "created_at"])

    # 11. alerts
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(64), sa.ForeignKey("ingestion_events.event_id", ondelete="SET NULL"), nullable=True),
        sa.Column("assessment_id", sa.String(64), sa.ForeignKey("model_assessments.assessment_id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_id", sa.String(32), sa.ForeignKey("alert_rules.rule_id", ondelete="SET NULL"), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="NEW"),
        sa.Column("acknowledged_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_alerts_severity"),
        sa.CheckConstraint("category IN ('vital_threshold', 'ml_anomaly', 'composite', 'stale_data')", name="ck_alerts_category"),
        sa.CheckConstraint("status IN ('NEW', 'ACKNOWLEDGED', 'RESOLVED')", name="ck_alerts_status"),
    )
    op.create_index("idx_alerts_patient_status_time", "alerts", ["patient_id", "status", "created_at"])
    op.create_index("idx_alerts_status_created", "alerts", ["status", "created_at"])

    # 12. alert_status_history
    op.create_table(
        "alert_status_history",
        sa.Column("history_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("alert_id", sa.String(64), sa.ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_alert_history_alert_time", "alert_status_history", ["alert_id", "changed_at"])

    # 13. notification_deliveries
    op.create_table(
        "notification_deliveries",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("alert_id", sa.String(64), sa.ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("channel IN ('in_app', 'websocket', 'email', 'sms')", name="ck_deliveries_channel"),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name="ck_deliveries_status"),
    )
    op.create_index("idx_deliveries_recipient_status", "notification_deliveries", ["recipient_id", "status"])

    # 14. messages
    op.create_table(
        "messages",
        sa.Column("message_id", sa.String(64), primary_key=True),
        sa.Column("sender_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("receiver_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_context_id", sa.String(32), sa.ForeignKey("patient_profiles.patient_id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_messages_receiver_read_time", "messages", ["receiver_id", "is_read", "created_at"])
    op.create_index("idx_messages_sender_time", "messages", ["sender_id", "created_at"])

    # 15. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String(64), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_audit_actor_time", "audit_logs", ["actor_id", "timestamp"])
    op.create_index("idx_audit_target", "audit_logs", ["target_type", "target_id"])
    op.create_index("idx_audit_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    # Drop in exact reverse order of foreign key dependencies
    op.drop_table("audit_logs")
    op.drop_table("messages")
    op.drop_table("notification_deliveries")
    op.drop_table("alert_status_history")
    op.drop_table("alerts")
    op.drop_table("model_assessments")
    op.drop_table("patient_baselines")
    op.drop_table("alert_rules")
    op.drop_table("vitals_readings")
    op.drop_table("ingestion_events")
    op.drop_table("doctor_patient_assignments")
    op.drop_table("doctor_profiles")
    op.drop_table("patient_profiles")
    op.drop_table("users")
    op.drop_table("import_batches")
